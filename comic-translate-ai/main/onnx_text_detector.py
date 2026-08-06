from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort


def _find_detector_utils_dir() -> str:
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        candidates.append(os.path.join(meipass, "comic-translate-ai", "main", "comic_text_detector"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "comic-translate-ai", "main", "comic_text_detector"))
    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(current_dir, "comic_text_detector"))
    for cand in candidates:
        if os.path.isdir(cand):
            return cand
    return candidates[-1]


DETECTOR_UTILS_DIR = _find_detector_utils_dir()
if DETECTOR_UTILS_DIR not in sys.path:
    sys.path.append(DETECTOR_UTILS_DIR)

from utils.db_utils import SegDetectorRepresenter  # noqa: E402
from utils.imgproc_utils import letterbox  # noqa: E402
from utils.textblock import group_output  # noqa: E402
from utils.textmask import REFINEMASK_INPAINT, refine_mask  # noqa: E402


def _xywh2xyxy(x: np.ndarray) -> np.ndarray:
    y = np.copy(x)
    y[:, 0] = x[:, 0] - x[:, 2] / 2
    y[:, 1] = x[:, 1] - x[:, 3] / 2
    y[:, 2] = x[:, 0] + x[:, 2] / 2
    y[:, 3] = x[:, 1] + x[:, 3] / 2
    return y


def _bbox_iou(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    x1 = np.maximum(boxes_a[:, None, 0], boxes_b[None, :, 0])
    y1 = np.maximum(boxes_a[:, None, 1], boxes_b[None, :, 1])
    x2 = np.minimum(boxes_a[:, None, 2], boxes_b[None, :, 2])
    y2 = np.minimum(boxes_a[:, None, 3], boxes_b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (boxes_a[:, 2] - boxes_a[:, 0]) * (boxes_a[:, 3] - boxes_a[:, 1])
    area_b = (boxes_b[:, 2] - boxes_b[:, 0]) * (boxes_b[:, 3] - boxes_b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return inter / np.maximum(union, 1e-9)


def non_max_suppression_np(prediction: np.ndarray, conf_thres: float = 0.4, iou_thres: float = 0.35, max_det: int = 300) -> np.ndarray:
    prediction = prediction[0]
    if prediction.size == 0:
        return np.zeros((0, 6), dtype=np.float32)

    box = prediction[:, :4]
    obj_conf = prediction[:, 4:5]
    cls_conf = prediction[:, 5:]
    conf = obj_conf * cls_conf
    conf_max = conf.max(axis=1)
    cls_id = conf.argmax(axis=1)

    keep_mask = conf_max >= conf_thres
    box = box[keep_mask]
    conf_max = conf_max[keep_mask]
    cls_id = cls_id[keep_mask]
    if box.shape[0] == 0:
        return np.zeros((0, 6), dtype=np.float32)

    box = _xywh2xyxy(box)
    keep = []
    for c in np.unique(cls_id):
        idx = np.where(cls_id == c)[0]
        boxes_c = box[idx]
        scores_c = conf_max[idx]
        order = scores_c.argsort()[::-1]
        while order.size > 0:
            i = order[0]
            keep.append(idx[i])
            if order.size == 1:
                break
            iou = _bbox_iou(boxes_c[i][None], boxes_c[order[1:]])[0]
            order = order[1:][iou < iou_thres]

    if not keep:
        return np.zeros((0, 6), dtype=np.float32)

    keep = np.asarray(keep, dtype=np.int64)
    keep = keep[conf_max[keep].argsort()[::-1]][:max_det]
    out = np.zeros((len(keep), 6), dtype=np.float32)
    out[:, :4] = box[keep]
    out[:, 4] = conf_max[keep]
    out[:, 5] = cls_id[keep].astype(np.float32)
    return out


def _postprocess_yolo_np(det: np.ndarray, conf_thresh: float, nms_thresh: float, resize_ratio) -> tuple:
    det = non_max_suppression_np(det, conf_thresh, nms_thresh)
    det[..., [0, 2]] = det[..., [0, 2]] * resize_ratio[0]
    det[..., [1, 3]] = det[..., [1, 3]] * resize_ratio[1]
    blines = det[..., 0:4].astype(np.int32)
    confs = np.round(det[..., 4], 3)
    cls = det[..., 5].astype(np.int32)
    return blines, cls, confs


def _preprocess_img_np(img: np.ndarray, input_size=(1024, 1024)):
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_in, ratio, (dw, dh) = letterbox(img, new_shape=input_size, auto=False, stride=64)
    img_in = img_in.transpose((2, 0, 1))[::-1]
    img_in = np.ascontiguousarray(img_in, dtype=np.float32)
    img_in = np.expand_dims(img_in, 0) / 255.0
    return img_in, ratio, int(dw), int(dh)


def _postprocess_mask_np(img: np.ndarray) -> np.ndarray:
    img = np.squeeze(img)
    img = img * 255
    return img.astype(np.uint8)


class OnnxTextDetector:
    def __init__(self, model_path: str, input_size: int = 1024, device: str = "cpu", conf_thresh: float = 0.4, nms_thresh: float = 0.35, mask_thresh: float = 0.3):
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
        try:
            self.session = ort.InferenceSession(str(model_path), providers=providers)
        except Exception:
            self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_size = input_size if isinstance(input_size, tuple) else (input_size, input_size)
        self.conf_thresh = conf_thresh
        self.nms_thresh = nms_thresh
        self.seg_rep = SegDetectorRepresenter(thresh=mask_thresh)

    def __call__(self, img):
        if isinstance(img, str):
            img = cv2.imdecode(np.fromfile(img, dtype=np.uint8), -1)
        if img is None:
            return [], [], []

        img_in, ratio, dw, dh = _preprocess_img_np(img, self.input_size)
        im_h, im_w = img.shape[:2]
        blks, mask, lines_map = self.session.run(None, {"images": img_in})
        resize_ratio = (im_w / (self.input_size[0] - dw), im_h / (self.input_size[1] - dh))

        blks = _postprocess_yolo_np(blks, self.conf_thresh, self.nms_thresh, resize_ratio)
        mask = _postprocess_mask_np(mask)

        lines, scores = self.seg_rep(self.input_size, lines_map)
        box_thresh = 0.6
        idx = np.where(scores[0] > box_thresh)
        lines, scores = lines[0][idx], scores[0][idx]

        mask = mask[: mask.shape[0] - dh, : mask.shape[1] - dw]
        mask = cv2.resize(mask, (im_w, im_h), interpolation=cv2.INTER_LINEAR)
        if lines.size == 0:
            lines = []
        else:
            lines = lines.astype(np.float64)
            lines[..., 0] *= resize_ratio[0]
            lines[..., 1] *= resize_ratio[1]
            lines = lines.astype(np.int32)

        blk_list = group_output(blks, lines, im_w, im_h, mask)
        mask_refined = refine_mask(img, mask, blk_list, refine_mode=REFINEMASK_INPAINT)
        return mask, mask_refined, blk_list