import os
import numpy as np
from PIL import Image


class MangaLama:
    def __init__(self, model_path, device=None):
        self.device = device or "cpu"

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
        import onnxruntime as ort

        if str(self.device).startswith("cuda"):
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        try:
            self.onnx_session = ort.InferenceSession(model_path, providers=providers)
        except Exception:
            self.onnx_session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])

        self.input_image_name = self.onnx_session.get_inputs()[0].name
        self.input_mask_name = self.onnx_session.get_inputs()[1].name
        self.output_name = self.onnx_session.get_outputs()[0].name
        print("ONNX LaMa 模型加载成功！")

    def __call__(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        img_tensor, mask_tensor, original_size = self._preprocess(image, mask)

        outputs = self.onnx_session.run(
            [self.output_name],
            {
                self.input_image_name: img_tensor,
                self.input_mask_name: mask_tensor,
            },
        )
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
