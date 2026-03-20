import os
import io
import threading
import uuid
import yaml
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
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


# ---- 配置管理 ----

def mask_key(key: str) -> str:
    """对 API Key 进行脱敏处理"""
    if not key or len(key) <= 8:
        return "***"
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"

@app.get("/config")
def get_config():
    """获取当前翻译 API 配置（API Key 脱敏显示）"""
    current = load_config()
    return JSONResponse(content={
        "api_key": mask_key(current.get("api_key", "")),
        "api_base_url": current.get("api_base_url", ""),
        "translation_model": current.get("translation_model", ""),
        "raw_api_key_length": len(current.get("api_key", ""))
    })

@app.post("/config")
async def update_config(request: Request):
    """更新翻译 API 配置，写入 config.yaml 并热更新 pipeline"""
    global pipeline_instance
    try:
        body = await request.json()
        print(f"[API] 收到配置更新请求: {list(body.keys())}")
    except Exception as e:
        print(f"[API ERROR] 解析请求体失败: {e}")
        raise HTTPException(status_code=400, detail=f"请求体解析失败: {e}")

    current = load_config()

    # 只更新用户提交的字段
    if body.get("api_key") is not None:
        current["api_key"] = body["api_key"]
    if body.get("api_base_url") is not None:
        current["api_base_url"] = body["api_base_url"]
    if body.get("translation_model") is not None:
        current["translation_model"] = body["translation_model"]

    # 写入 config.yaml
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            yaml.dump(current, f, allow_unicode=True, default_flow_style=False)
        print(f"[API] 配置已写入: {CONFIG_PATH}")
    except Exception as e:
        import traceback
        print(f"[API ERROR] 写入配置文件失败: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"写入配置文件失败: {e}")

    # 热更新 pipeline 实例的翻译配置
    if pipeline_instance:
        with pipeline_lock:
            pipeline_instance.api_key = current.get("api_key", "")
            pipeline_instance.api_base_url = current.get("api_base_url", "")
            pipeline_instance.translation_model = current.get("translation_model", "")
        print(f"[API] 配置已热更新: model={current.get('translation_model')}, url={current.get('api_base_url')}")

    return JSONResponse(content={"message": "配置更新成功"})

if __name__ == "__main__":
    import uvicorn
    # 为了供 Docker 使用，监听在 0.0.0.0
    uvicorn.run(app, host="0.0.0.0", port=8000)
