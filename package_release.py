import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist", "ComiTrans")
RELEASE = os.path.join(ROOT, "release")
MODELS_SRC = os.path.join(ROOT, "comic-translate-ai", "models")

APP_ZIP = os.path.join(RELEASE, "ComiTrans-v2.0.0-app.zip")
MODEL_ZIP = os.path.join(RELEASE, "ComiTrans-v2.0.0-models.zip")

MODEL_FILES = [
    "text_detector/comic-text-detector.onnx",
    "manga-lama/lama-manga-dynamic.onnx",
]
MODEL_DIRS = [
    "manga-ocr-onnx",
]

SKIP_DIRS = {"models", "Log"}


def clean_old():
    for name in os.listdir(RELEASE):
        if name.endswith((".zip", ".001", ".002", ".003")):
            os.remove(os.path.join(RELEASE, name))


def zip_app():
    with zipfile.ZipFile(APP_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for root, dirs, files in os.walk(DIST):
            rel_root = os.path.relpath(root, DIST)
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, DIST)
                zf.write(full, os.path.join("ComiTrans", rel))
    print("app zip:", APP_ZIP, round(os.path.getsize(APP_ZIP) / 1e6, 1), "MB")


def zip_models():
    with zipfile.ZipFile(MODEL_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for rel in MODEL_FILES:
            src = os.path.join(MODELS_SRC, rel)
            dst = os.path.join("ComiTrans", "comic-translate-ai", "models", rel)
            zf.write(src, dst)
        for rel_dir in MODEL_DIRS:
            src_dir = os.path.join(MODELS_SRC, rel_dir)
            for root, dirs, files in os.walk(src_dir):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, MODELS_SRC)
                    zf.write(full, os.path.join("ComiTrans", "comic-translate-ai", "models", rel))
    print("model zip:", MODEL_ZIP, round(os.path.getsize(MODEL_ZIP) / 1e6, 1), "MB")


if __name__ == "__main__":
    clean_old()
    zip_app()
    zip_models()
