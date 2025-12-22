import os
import multiprocessing
import platform
import numpy as np
from dotenv import load_dotenv
from concurrent.futures import ProcessPoolExecutor
from comic_translator_pipeline import ComicTranslatorPipeline
load_dotenv()
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

def init_worker(det_path, font_map, font_size, cls_path, lama_path, use_gpu):
    """每个子进程启动时执行一次，加载独立模型"""
    global worker_pipeline
    print(f"[{multiprocessing.current_process().name}] 正在加载模型...")
    try:
        worker_pipeline = ComicTranslatorPipeline(
            det_model_path=det_path,
            font_map=font_map,
            font_size=font_size,
            cls_model_path=cls_path,
            lama_path=lama_path,
            use_gpu=use_gpu
        )
    except Exception as e:
        print(f"模型加载失败: {e}")
def run_worker_process_fork(user_input, output_name):
    if global_pipeline is None:
        return f"[Fork] 错误: 管道未在主进程初始化"

    try:
        # 直接调用
        global_pipeline.process_comic_page(user_input, f"../page/test_page_output/{output_name}")
        return f"完成: {os.path.basename(user_input)}"
    except Exception as e:
        import traceback
        return f"[Fork] 失败: {e}"
def run_worker_process(user_input, output_name):
    if worker_pipeline is None:
        return f"错误: 进程 {multiprocessing.current_process().name} 未初始化管道"
    try:
        # 直接调用全局变量
        worker_pipeline.process_comic_page(user_input, f"../page/test_page_output/{output_name}")
        return f"处理完成: {user_input}"
    except Exception as e:
        import traceback
        return f"失败 {user_input}: {e}\n{traceback.format_exc()}"

worker_pipeline = None
global_pipeline = None

if __name__ == "__main__":
    multiprocessing.freeze_support()
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    FONT_MAP = {
        "dialogue": "../font_file/CN/SourceHanSerifCN-Regular-1.otf",
        "radiating": "../font_file/CN/SourceHanSansSC-Heavy-2.otf",
        "handwriting": "../font_file/CN/setofont.ttf",
        "serious": "./font_file/CN/SourceHanSansSC-Medium-2.otf"
    }
    lama_path = os.path.join(BASE_DIR,'..' ,'models' ,'manga-lama', 'manga-lama.pt')
    det_path  = os.path.join(BASE_DIR,'..' ,'models' ,'ogkalucomic-speech-bubble-detector-yolov8m','comic-speech-bubble-detector.pt')
    cls_model = os.path.join(BASE_DIR,'..' ,'models' ,'manga-font-mobilnet', 'manga_font_mobilnet.pth')
    current_os = platform.system()
    print(f"检测到操作系统: {current_os}")
    executor_cls = ProcessPoolExecutor
    init_func = None
    init_args = ()
    worker_func = None

    if current_os == 'Linux':
        print(">>> 启用 Linux 高效模式 (Fork + CPU)")
        try:
            multiprocessing.set_start_method('fork', force=True)
        except RuntimeError:
            pass

        global_pipeline = ComicTranslatorPipeline(
            det_model_path=det_path,
            font_map=FONT_MAP,
            font_size=16,
            cls_model_path=cls_model,
            use_gpu=False,
            lama_path=lama_path
        )

        print("正在预热 YOLO...")
        global_pipeline.detector(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False)
        worker_func = run_worker_process_fork
        max_workers = os.cpu_count()

    else:
        print(">>> 启用 Windows/兼容模式")
        global_pipeline = None

        init_func = init_worker
        init_args = (det_path, FONT_MAP, 16, cls_model, lama_path, True)
        worker_func = run_worker_process
        max_workers = 1
    print(f"最大并发数: {max_workers}")
    with executor_cls(max_workers=max_workers, initializer=init_func, initargs=init_args) as executor:
        while True:
            # 交互式循环
            user_cmd = input("是否有新任务 (y/n)? ")
            if user_cmd.lower() == 'n': break
            print("等待任务...")
            futures = []
            target_indices = [7]
            for i in target_indices:
                user_input = f"../page/test_page/test{i}.jpg"

                if not os.path.exists(user_input):
                    print(f"文件不存在: {user_input}")
                    continue

                output_name = f"translated_{os.path.basename(user_input)}"
                print(f"提交任务: {user_input}")

                future = executor.submit(worker_func, user_input, output_name)
                futures.append(future)

            for f in futures:
                try:
                    print(f.result())
                except Exception as e:
                    print(f"任务执行异常: {e}")