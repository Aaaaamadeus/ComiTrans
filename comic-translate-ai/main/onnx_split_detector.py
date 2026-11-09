"""Comic text regions, PP-OCR manga lines and midpoint box refinement."""

from pathlib import Path

import cv2
import numpy as np
import pyclipper
from PIL import Image

from comic_translate_core.inference_control import run_inference
from comic_translate_core.onnx_session import create_onnx_session
from comic_translate_core.detector_paths import LINE_FILE
from comic_text_detector.utils.textblock import TextBlock, sort_textblk_list


def line_polygons(session, bgr):
    h, w = bgr.shape[:2]
    scale = 1024 / max(h, w)  # same long-side budget as current detector
    rw, rh = [max(32, round(k * scale / 32) * 32) for k in (w, h)]
    pixels = cv2.resize(bgr, (rw, rh)).astype(np.float32) / 255
    pixels -= np.array([0.485, 0.456, 0.406], np.float32)
    pixels /= np.array([0.229, 0.224, 0.225], np.float32)
    prob = run_inference(
        session, None, {session.get_inputs()[0].name: pixels.transpose(2, 0, 1)[None]}
    )[0][0, 0]
    contours, _ = cv2.findContours(
        (prob > 0.15).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
    )
    polygons = []
    for contour in contours:
        if len(contour) < 4 or cv2.contourArea(contour) <= 0:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        mask = np.zeros((bh, bw), np.uint8)
        cv2.fillPoly(mask, [(contour - [x, y]).astype(np.int32)], 1)
        if cv2.mean(prob[y : y + bh, x : x + bw], mask)[0] < 0.25:
            continue
        offset = pyclipper.PyclipperOffset()
        offset.AddPath(contour[:, 0].tolist(), pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        expanded = offset.Execute(1.4 * cv2.contourArea(contour) / cv2.arcLength(contour, True))
        if len(expanded) != 1:
            continue
        rect = cv2.minAreaRect(np.asarray(expanded[0], np.float32))
        if min(rect[1]) >= 3:
            polygons.append(
                np.rint(cv2.boxPoints(rect) * [w / prob.shape[1], h / prob.shape[0]]).astype(
                    np.int32
                )
            )
    return polygons


def text_regions(session, bgr):
    h, w = bgr.shape[:2]
    rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).resize(
        (640, 640), Image.Resampling.BILINEAR
    )
    x = np.asarray(rgb, dtype=np.float32).transpose(2, 0, 1)[None] / 255
    labels, boxes, scores = run_inference(
        session,
        ["labels", "boxes", "scores"],
        {"images": x, "orig_target_sizes": np.array([[w, h]], np.int64)},
    )
    return [
        (np.clip(np.rint(b), 0, [w, h, w, h]).astype(int).tolist(), int(l))
        for l, b, s in zip(labels[0], boxes[0], scores[0])
        if l in (1, 2) and s >= 0.5
    ]


def assign_lines(regions, polygons):
    groups = [[] for _ in regions]
    for polygon in polygons:
        cx, cy = polygon.mean(axis=0)
        containing = [
            i for i, ((l, t, r, b), _) in enumerate(regions) if l <= cx < r and t <= cy < b
        ]
        if containing:

            def area(index):
                l, t, r, b = regions[index][0]
                return (r - l) * (b - t)

            groups[min(containing, key=area)].append(polygon)
    return groups


def midpoint_box(box, lines, width, height):
    if not lines:
        return box
    points = np.concatenate(lines)
    limits = [width, height, width, height]
    extent = np.clip([*points.min(axis=0), *points.max(axis=0)], 0, limits)
    return np.rint((extent + box) / 2).astype(int).tolist()


def ordered_corners(polygon):
    # PP-OCR rectification expects top-left, top-right, bottom-right, bottom-left.
    left, right = np.split(polygon[np.argsort(polygon[:, 0], kind="stable")], 2)
    tl, bl = sorted(left, key=lambda point: point[1])
    tr, br = sorted(right, key=lambda point: point[1])
    return np.array([tl, tr, br, bl], dtype=np.int32)


def seed_strokes(gray, seed, box, lines):
    l, t, r, b = box
    crop = gray[t:b, l:r]
    for polygon in lines:
        local = np.zeros(crop.shape, np.uint8)
        cv2.fillPoly(local, [polygon - [l, t]], 1)
        inside = local.astype(bool)
        if inside.any():
            paper = np.median(crop[inside])
            seed[t:b, l:r][inside & (np.abs(crop - paper) > 36)] = 255


class SplitTextDetector:
    def __init__(self, model_path, device, language):
        self.session = create_onnx_session(model_path, device)
        self.line_session = create_onnx_session(Path(model_path).with_name(LINE_FILE), device)
        self.right_to_left = language == "ja"

    def __call__(self, image):
        height, width = image.shape[:2]
        regions = [
            (box, label)
            for box, label in text_regions(self.session, image)
            if box[2] > box[0] and box[3] > box[1]
        ]
        lines = line_polygons(self.line_session, image)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        seed = np.zeros((height, width), np.uint8)
        blocks = []
        for (box, label), polygons in zip(regions, assign_lines(regions, lines)):
            fitted = midpoint_box(box, polygons, width, height)
            if fitted[2] <= fitted[0] or fitted[3] <= fitted[1]:
                continue
            corners = [ordered_corners(poly) for poly in polygons]
            seed_strokes(gray, seed, fitted, corners)
            thickness = [min(cv2.minAreaRect(poly)[1]) for poly in corners]
            size = max(6, round(np.median(thickness))) if thickness else 16
            blocks.append(
                TextBlock(
                    fitted,
                    [q.tolist() for q in corners],
                    font_size=size,
                    vertical=fitted[3] - fitted[1] > fitted[2] - fitted[0],
                    language="unknown",
                    label=2 if label == 2 else 0,
                )
            )
        return (
            seed,
            seed,
            sort_textblk_list(blocks, width, height, right_to_left=self.right_to_left),
        )
