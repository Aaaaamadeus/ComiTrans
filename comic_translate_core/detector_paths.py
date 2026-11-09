"""File names shared by the desktop preflight and detector loader."""
from pathlib import Path

REGION_FILE = "detector-v4-s_int8.onnx"
LINE_FILE = "manga_det_v0.2.onnx"
SPLIT_PATH = Path("split-detector") / REGION_FILE
LEGACY_PATH = Path("text_detector/comic-text-detector.onnx")
