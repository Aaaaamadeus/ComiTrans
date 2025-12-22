import torch
import numpy as np
from PIL import Image

class MangaLama:
    def __init__(self, model_path, device=None):
        if device is None:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        else:
            self.device = device

        print(f"正在加载漫画专用 LaMa 模型: {model_path} ...")
        # 加载 TorchScript 模型
        try:
            self.model = torch.jit.load(model_path, map_location=self.device)
            self.model.eval()
            print("模型加载成功！")
        except Exception as e:
            print(f"模型加载失败，请检查路径: {e}")
            raise e

    def __call__(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        # 1. 预处理：转换为 Tensor 并调整尺寸 (LaMa 需要宽高能被8整除)
        img_tensor, mask_tensor, original_size = self._preprocess(image, mask)

        # 2. 推理
        with torch.no_grad():
            img_tensor = img_tensor.to(self.device)
            mask_tensor = mask_tensor.to(self.device)
            # LaMa JIT 的标准输入通常是 (img, mask)
            output_tensor = self.model(img_tensor, mask_tensor)

            # 兼容性处理：有些 JIT 输出是 list，有些是 tensor
            if isinstance(output_tensor, list) or isinstance(output_tensor, tuple):
                output_tensor = output_tensor[0]

        # 3. 后处理：转回 PIL 并恢复原始尺寸
        result_image = self._postprocess(output_tensor, original_size)
        return result_image

    def _preprocess(self, image, mask):
        original_size = image.size  # (W, H)

        # 转换为 numpy
        img_np = np.array(image).astype(np.float32) / 255.0
        mask_np = np.array(mask.convert('L')).astype(np.float32) / 255.0

        # 调整 mask 值范围：LaMa 通常预期 mask 1=mask, 0=image
        # 但有些实现是反的，通常 simple-lama 传入的是 (mask=255)，这里归一化后是 1.0
        mask_np = (mask_np > 0.5).astype(np.float32)

        # 补齐 Padding 到 8 的倍数 (LaMa 核心要求)
        h, w = img_np.shape[:2]
        pad_h = (8 - h % 8) % 8
        pad_w = (8 - w % 8) % 8

        if pad_h > 0 or pad_w > 0:
            img_np = np.pad(img_np, ((0, pad_h), (0, pad_w), (0, 0)), mode='reflect')
            mask_np = np.pad(mask_np, ((0, pad_h), (0, pad_w)), mode='reflect')

        # HWC -> NCHW
        img_tensor = torch.from_numpy(img_np).permute(2, 0, 1).unsqueeze(0)
        mask_tensor = torch.from_numpy(mask_np).unsqueeze(0).unsqueeze(0)

        return img_tensor, mask_tensor, original_size
    def _postprocess(self, output_tensor, original_size):
        # NCHW -> HWC
        out_np = output_tensor[0].cpu().permute(1, 2, 0).numpy()

        # 裁剪掉 Padding
        w_orig, h_orig = original_size
        out_np = out_np[:h_orig, :w_orig, :]

        # 反归一化
        out_np = np.clip(out_np * 255, 0, 255).astype(np.uint8)
        return Image.fromarray(out_np)