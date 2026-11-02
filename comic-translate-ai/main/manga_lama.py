import numpy as np
from comic_translate_core.inference_control import run_inference
from PIL import Image
import os
from pathlib import Path
from threading import Lock
from weakref import WeakValueDictionary


class _SharedSession:
    def __init__(self, session):
        self.session = session
        self.lock = Lock()


_sessions = WeakValueDictionary()
_sessions_lock = Lock()


class MangaLama:
    def __init__(self, model_path, device=None, cancel_callback=None):
        self.device = device or "cpu"
        self.cancel_callback = cancel_callback
        self._tile_size = 768

        print(f"正在加载漫画专用 LaMa 模型: {model_path} ...")
        self.onnx_session = None
        self.input_image_name = None
        self.input_mask_name = None
        self.output_name = None

        if str(model_path).lower().endswith(".onnx"):
            self._load_onnx(model_path)
        else:
            raise ValueError("LaMa 仅支持 ONNX 模型: " + str(model_path))

    def _load_onnx(self, model_path):
        from comic_translate_core.onnx_session import create_onnx_session

        path = Path(model_path).resolve()
        stamp = path.stat()
        key = (os.path.normcase(str(path)), stamp.st_mtime_ns, stamp.st_size, str(self.device))
        # Share weights, but keep each caller's cancellation and tiling state separate.
        # Weak references release sessions after both pipeline and editor let go.
        with _sessions_lock:
            resource = _sessions.get(key)
            if resource is None:
                session = create_onnx_session(path, self.device)
                resource = _SharedSession(session)
                _sessions[key] = resource
            self._session_resource = resource
        self.onnx_session = resource.session

        self.input_image_name = self.onnx_session.get_inputs()[0].name
        self.input_mask_name = self.onnx_session.get_inputs()[1].name
        self.output_name = self.onnx_session.get_outputs()[0].name
        print("ONNX LaMa 模型加载成功！")

    def __call__(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        if image.size != mask.size:
            raise ValueError('LaMa 图片与蒙版尺寸必须一致')
        image = image.convert('RGB')
        mask = mask.convert('L').point(lambda value: 255 if value > 127 else 0)
        if mask.getbbox() is None:
            return image.copy()
        while True:
            try:
                return self._repair_tiles(image, mask, self._tile_size)
            except Exception as exc:
                message = str(exc).lower()
                out_of_memory = isinstance(exc, MemoryError) or any(text in message for text in (
                    'failed to allocate memory', 'out of memory', 'out_of_memory', 'bad_alloc',
                    'cudaerrormemoryallocation', 'cudnn_status_alloc_failed'))
                if not out_of_memory:
                    raise
                if self._tile_size <= 256:
                    raise RuntimeError('LaMa 最小分块仍内存不足，请重启客户端释放占用，'
                                       '关闭其他占显存程序，或关闭 GPU 后使用断点续传重试。') from exc
                self._tile_size = {768: 512, 512: 384, 384: 256}[self._tile_size]
                print(f'[LaMa] 内存不足，改用 {self._tile_size} 像素分块重试当前页')

    def _check_cancelled(self):
        if self.cancel_callback is not None:
            self.cancel_callback()

    @staticmethod
    def _blend_axis(length, overlap, before, after):
        weights = np.ones(length, dtype=np.float32)
        ramp = np.arange(1, overlap + 1, dtype=np.float32) / (overlap + 1)
        if before:
            weights[:min(length, overlap)] *= ramp[:min(length, overlap)]
        if after:
            weights[-min(length, overlap):] *= ramp[::-1][-min(length, overlap):]
        return weights

    def _repair_tiles(self, image, mask, tile_size):
        # Inference uses original pixels: no page/crop downscaling. The model
        # sees context around each output tile; adjacent outputs also overlap.
        context = tile_size // 8
        overlap = max(16, tile_size // 12 // 8 * 8)
        span = tile_size - context * 2
        stride = span - overlap
        width, height = image.size
        x1, y1, x2, y2 = mask.getbbox()
        bounds = (max(0, x1 - context), max(0, y1 - context),
                  min(width, x2 + context), min(height, y2 + context))
        if bounds[2] - bounds[0] <= tile_size and bounds[3] - bounds[1] <= tile_size:
            self._check_cancelled()
            crop_mask = mask.crop(bounds)
            repaired = self._infer(image.crop(bounds), crop_mask)
            result = image.copy()
            result.paste(repaired, bounds[:2], crop_mask)
            return result

        print(f'[LaMa] 原图 {width}×{height}，按最大 {tile_size}×{tile_size} 分块修复')
        result = image.copy()
        tail_pixels = tail_weights = None
        # Keep only one horizontal band of floating-point blending buffers.
        # A full-page RGB accumulation buffer would defeat memory reduction.
        for top in range(0, height, stride):
            self._check_cancelled()
            bottom = min(height, top + span)
            if mask.crop((0, top, width, bottom)).getbbox() is None:
                tail_pixels = tail_weights = None
                continue
            pixels = np.zeros((bottom - top, width, 3), dtype=np.float32)
            weights = np.zeros((bottom - top, width), dtype=np.float32)
            if tail_pixels is not None:
                count = len(tail_pixels)
                pixels[:count] = tail_pixels
                weights[:count] = tail_weights
            tail_pixels = tail_weights = None
            wy = self._blend_axis(bottom - top, overlap, top > 0, bottom < height)
            for left in range(0, width, stride):
                self._check_cancelled()
                right = min(width, left + span)
                target = (left, top, right, bottom)
                target_mask = mask.crop(target)
                if target_mask.getbbox() is None:
                    continue
                bounds = (max(0, left - context), max(0, top - context),
                          min(width, right + context), min(height, bottom + context))
                repaired = self._infer(image.crop(bounds), mask.crop(bounds))
                repaired = repaired.crop((left - bounds[0], top - bounds[1],
                                          right - bounds[0], bottom - bounds[1]))
                wx = self._blend_axis(right - left, overlap, left > 0, right < width)
                contribution = wy[:, None] * wx[None, :] * (np.asarray(target_mask) > 0)
                pixels[:, left:right] += np.asarray(repaired, dtype=np.float32) * contribution[:, :, None]
                weights[:, left:right] += contribution
            count = min(stride, height - top)
            valid = weights[:count] > 0
            blended = pixels[:count] / np.maximum(weights[:count, :, None], 1e-8)
            result.paste(Image.fromarray(np.clip(np.rint(blended), 0, 255).astype(np.uint8)),
                         (0, top), Image.fromarray(valid.astype(np.uint8) * 255))
            if count < bottom - top:
                tail_pixels = pixels[count:].copy()
                tail_weights = weights[count:].copy()
            del pixels, weights, blended
        return result

    def _infer(self, image, mask):
        img_tensor, mask_tensor, original_size = self._preprocess(image, mask)

        # Serialize inference on shared weights to avoid simultaneous GPU workspaces.
        while not self._session_resource.lock.acquire(timeout=0.1):
            self._check_cancelled()
        try:
            self._check_cancelled()
            outputs = run_inference(self.onnx_session,
                [self.output_name],
                {self.input_image_name: img_tensor, self.input_mask_name: mask_tensor},
                check_cancelled=self._check_cancelled,
            )
        finally:
            self._session_resource.lock.release()
        output_tensor = outputs[0]

        result_image = self._postprocess(output_tensor, original_size)
        return result_image

    def _preprocess(self, image, mask):
        original_size = image.size

        img_np = np.array(image).astype(np.float32) / 255.0
        mask_np = np.array(mask.convert("L")).astype(np.float32) / 255.0
        mask_np = (mask_np > 0.5).astype(np.float32)

        h, w = img_np.shape[:2]
        pad_h = (8 - h % 8) % 8
        pad_w = (8 - w % 8) % 8

        if pad_h > 0 or pad_w > 0:
            img_np = np.pad(img_np, ((0, pad_h), (0, pad_w), (0, 0)), mode="reflect")
            mask_np = np.pad(mask_np, ((0, pad_h), (0, pad_w)), mode="reflect")

        img_tensor = np.transpose(img_np, (2, 0, 1))[None]
        mask_tensor = mask_np[None, None]
        return img_tensor, mask_tensor, original_size

    def _postprocess(self, output_tensor, original_size):
        out_np = output_tensor[0].transpose(1, 2, 0)

        w_orig, h_orig = original_size
        out_np = out_np[:h_orig, :w_orig, :]

        out_np = np.clip(out_np * 255, 0, 255).astype(np.uint8)
        return Image.fromarray(out_np)
