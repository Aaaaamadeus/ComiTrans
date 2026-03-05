import os
import yaml
import multiprocessing
import platform
import numpy as np
import signal


from concurrent.futures import ProcessPoolExecutor
import sys
import threading
import time
from comic_translator_pipeline import ComicTranslatorPipeline

# 优雅关闭标志
is_running = True

def signal_handler(signum, frame):
    global is_running
    print(f"\n[INFO] 接收到信号 {signum}，准备停止...")
    is_running = False

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

PAGE_INPUT_DIR = get_path('page_input_dir', 'page/test_page')
PAGE_OUTPUT_DIR = get_path('page_output_dir', 'page/test_page_output')

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

# API 配置（仅从 config.yaml 读取）
API_KEY = CONFIG.get('api_key', '')
API_BASE_URL = CONFIG.get('api_base_url', '')
TRANSLATION_MODEL = CONFIG.get('translation_model', 'gemini-2.5-flash')

if not API_KEY or not API_BASE_URL:
    print("[WARNING] 未检测到有效的 API 配置，请在 config.yaml 中填写 api_key 和 api_base_url")

USE_GPU = bool(CONFIG.get('use_gpu', False))

MAX_WORKERS = CONFIG.get('max_workers')

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


def get_test_indices(count):
    return tuple(range(1, count + 1))

def init_worker(det_path, font_map, font_size, lama_path, use_gpu, output_dir, trans_model, api_key, api_base_url):
    global worker_pipeline, worker_output_dir
    worker_output_dir = output_dir
    
    print(f"[WORKER {multiprocessing.current_process().name}] 加载模型...")
    try:
        worker_pipeline = ComicTranslatorPipeline(
            det_model_path=det_path,
            font_map=font_map,
            font_size=font_size,
            lama_path=lama_path,
            use_gpu=use_gpu,
            translation_model=trans_model,
            api_key=api_key,
            api_base_url=api_base_url
        )
    except Exception as e:
        print(f"[ERROR] 模型加载失败: {e}")
        import traceback
        traceback.print_exc()
        raise  # 让异常传播到主进程，避免静默失败

def run_worker_process(user_input, output_name):
    if worker_pipeline is None:
        return f"错误: 进程 {multiprocessing.current_process().name} 未初始化管道"
    try:
        output_path = os.path.join(worker_output_dir, output_name)
        worker_pipeline.process_comic_page(user_input, output_path)
        return f"处理完成: {user_input}"
    except Exception as e:
        import traceback
        return f"失败 {user_input}: {e}\n{traceback.format_exc()}"

worker_pipeline = None
global_pipeline = None
worker_output_dir = None

def get_pending_images(input_dir, output_dir, suffix="_translated"):
    if not os.path.exists(input_dir):
        return []
    
    pending = []
    for f in os.listdir(input_dir):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            input_path = os.path.join(input_dir, f)
            base_name = os.path.splitext(f)[0]
            ext = os.path.splitext(f)[1]
            
            output_name = f"{base_name}{suffix}{ext}"
            output_path = os.path.join(output_dir, output_name)
            
            if not os.path.exists(output_path):
                pending.append((input_path, output_name))
    
    return pending

if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    current_os = platform.system()
    print(f"[INFO] 检测到操作系统: {current_os}")
    
    os.makedirs(PAGE_OUTPUT_DIR, exist_ok=True)
    
    executor_cls = ProcessPoolExecutor
    init_func = None
    init_args = ()
    worker_func = None
    max_workers = MAX_WORKERS if MAX_WORKERS else 1

    if current_os == 'Linux':
        print("[INFO] Linux 高效模式 (Fork + CPU)")
        try:
            multiprocessing.set_start_method('fork', force=True)
        except RuntimeError:
            pass

        global_pipeline = ComicTranslatorPipeline(
            det_model_path=DET_PATH,
            font_map=FONT_MAP,
            font_size=FONT_SIZE,
            use_gpu=USE_GPU,
            lama_path=LAMA_PATH,
            translation_model=TRANSLATION_MODEL,
            api_key=API_KEY,
            api_base_url=API_BASE_URL
        )

        print("[INFO] 预热检测模型...")
        global_pipeline.detector(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False)
        worker_func = run_worker_process
        if MAX_WORKERS is None:
            max_workers = os.cpu_count()

    else:
        print("[INFO] Windows/兼容模式")
        global_pipeline = None

        init_func = init_worker
        init_args = (DET_PATH, FONT_MAP, FONT_SIZE, LAMA_PATH, USE_GPU, PAGE_OUTPUT_DIR, TRANSLATION_MODEL, API_KEY, API_BASE_URL)
        worker_func = run_worker_process

    print(f"[INFO] 最大并发数: {max_workers}")
    print(f"[INFO] 输入目录: {PAGE_INPUT_DIR}")
    print(f"[INFO] 输出目录: {PAGE_OUTPUT_DIR}")
    print("等待新图片...")
    
    processed_count = 0
    failed_images = set()  # 记录处理失败的图片，避免反复重试
    
    with executor_cls(max_workers=max_workers, initializer=init_func, initargs=init_args) as executor:
        while is_running:
            pending = get_pending_images(PAGE_INPUT_DIR, PAGE_OUTPUT_DIR)
            # 过滤掉已知失败的图片
            pending = [(p, n) for p, n in pending if p not in failed_images]
            
            if pending:
                print(f"\n[INFO] 发现 {len(pending)} 张待处理图片")
                futures = []
                
                for input_path, output_name in pending:
                    if not is_running: break
                    print(f"[TASK] 处理: {os.path.basename(input_path)}")
                    future = executor.submit(worker_func, input_path, output_name)
                    futures.append((future, input_path))

                for f, input_path in futures:
                    try:
                        result = f.result()
                        if result.startswith("错误") or result.startswith("失败"):
                            print(f"[FAIL] {result}")
                            failed_images.add(input_path)
                        else:
                            print(f"[DONE] {result}")
                            processed_count += 1
                    except Exception as e:
                        print(f"[ERROR] 任务执行异常: {e}")
                        failed_images.add(input_path)
                
                if failed_images:
                    print(f"[INFO] 累计 {len(failed_images)} 张图片处理失败，已跳过")
                print(f"[INFO] 本轮完成，累计成功处理 {processed_count} 张")
                print("等待新图片...")
            else:
                for _ in range(20): # sleep 2s in 0.1s intervals to respond to signal faster
                    if not is_running: break
                    time.sleep(0.1)
    
    print("[INFO] 正在关闭资源...")
    if global_pipeline is not None:
        global_pipeline.clear_name_cache()
    print("程序结束")
