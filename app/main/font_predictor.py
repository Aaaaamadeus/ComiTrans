import torch
import torch.nn as nn
from torchvision import models, transforms
import cv2
from PIL import Image
import traceback

class FontPredictor:
    def __init__(self, model_path, device):
        self.device = torch.device(device if torch.cuda.is_available() else 'cpu')
        # 对应训练代码中的 label_map
        self.class_names = ["radiating", "dialogue", "handwriting","serious"]

        # 重建模型结构 (MobileNetV2 Small)
        self.model = models.mobilenet_v2(weights=None)
        # 修改全连接层以匹配 3 个分类
        in_features = self.model.classifier[1].in_features
        self.model.classifier[1] = nn.Linear(in_features, 4)

        try:
            state_dict = torch.load(model_path, map_location=self.device)
            self.model.load_state_dict(state_dict)
        except Exception as e:
            print(f"字体模型加载失败: {e}")
            traceback.print_exc()

        self.model.to(self.device).eval()

        # 预处理
        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])

    def predict(self, img_bgr):
        try:
            # OpenCV BGR -> PIL RGB
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(img_rgb)
            img_tensor = self.transform(pil_img).unsqueeze(0).to(self.device)

            with torch.no_grad():
                outputs = self.model(img_tensor)
                _, preds = torch.max(outputs, 1)
            return self.class_names[preds.item()]
        except:
            return "dialogue"  # 出错默认回退