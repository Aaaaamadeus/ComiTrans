import os
import io
import threading
import uuid
import yaml
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import uuid

# 复用原本 main.py 中的核心检测逻辑库
from comic_translator_pipeline import ComicTranslatorPipeline

app = FastAPI(title="Comic Translate API", description="AI 漫画内嵌机器翻译接口")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(BASE_DIR)
CONFIG_PATH = os.path.join(BASE_DIR, 'config.yaml')

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except:
        return {}

CONFIG = load_config()

def get_path(key, default_relative_path):
    val = CONFIG.get(key)
    if val and isinstance(val, str) and val.strip():
        if os.path.isabs(val):
            return val
        return os.path.join(APP_DIR, val)
    return os.path.join(APP_DIR, default_relative_path)

FONT_SIZE = CONFIG.get('font_size', 16) or 16
font_dialogue = get_path('font_dialogue', 'font_file/CN/SourceHanSerifCN-Regular-1.otf')
font_radiating = get_path('font_radiating', 'font_file/CN/SourceHanSansSC-Heavy-2.otf')
font_handwriting = get_path('font_handwriting', 'font_file/CN/setofont.ttf')
font_serious = get_path('font_serious', 'font_file/CN/SourceHanSansSC-Medium-2.otf')

FONT_MAP = {
    "dialogue": font_dialogue,
    "radiating": font_radiating,
    "handwriting": font_handwriting,
    "serious": font_serious
}

LAMA_PATH = get_path('lama_model', 'models/manga-lama/manga-lama.pt')
DET_PATH = get_path('detector_model', 'models/text_detector/comictextdetector.pt')

API_KEY = CONFIG.get('api_key', '')
API_BASE_URL = CONFIG.get('api_base_url', '')
TRANSLATION_MODEL = CONFIG.get('translation_model', 'gemini-2.5-flash')
USE_GPU = bool(CONFIG.get('use_gpu', False))
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

# 全局模型实例
pipeline_instance = None
pipeline_lock = threading.Lock()

@app.on_event("startup")
def startup_event():
    global pipeline_instance
    print("[API] 正在初始化 AI 模型...")
    pipeline_instance = ComicTranslatorPipeline(
        det_model_path=DET_PATH,
        font_map=FONT_MAP,
        font_size=FONT_SIZE,
        lama_path=LAMA_PATH,
        use_gpu=USE_GPU,
        translation_model=TRANSLATION_MODEL,
        api_key=API_KEY,
        api_base_url=API_BASE_URL
    )
    print("[API] AI 模型初始化完成！")

@app.post("/process-image")
async def process_image(file: UploadFile = File(...)):
    """
    接收上传的图片文件，利用 AI pipeline 处理并返回渲染后的图像。
    """
    global pipeline_instance
    if not pipeline_instance:
        raise HTTPException(status_code=500, detail="模型未完成初始化，请稍后重试")

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="必须上传图片文件")

    # 创建一个临时目录供读写
    temp_dir = os.path.join(APP_DIR, "page", "temp_api")
    os.makedirs(temp_dir, exist_ok=True)
    
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1] or ".png"
    input_path = os.path.join(temp_dir, f"{file_id}_input{ext}")
    output_path = os.path.join(temp_dir, f"{file_id}_output{ext}")

    try:
        # 保存上传的图片
        file_bytes = await file.read()
        with open(input_path, "wb") as f:
            f.write(file_bytes)

        # 锁保证显存与模型推断安全（简易实现，适合单卡/单实例）
        with pipeline_lock:
            pipeline_instance.process_comic_page(input_path, output_path)
            
        if not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="图片处理失败，未生成输出图片")

        return FileResponse(output_path, media_type=file.content_type, filename=f"translated_{file.filename}")
        
    except Exception as e:
        import traceback
        print(f"[API ERROR] {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # 为了供 Docker 使用，监听在 0.0.0.0
    uvicorn.run(app, host="0.0.0.0", port=8000)
