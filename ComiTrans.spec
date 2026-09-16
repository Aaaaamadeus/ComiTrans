# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

import PySide6
import shiboken6

# Resolve DLLs from this Python/Qt installation and Windows, not unrelated
# tools on PATH (e.g. Poppler's ICU exports do not match Qt's Windows ICU ABI).
if sys.platform == "win32":
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    os.environ["PATH"] = os.pathsep.join(map(str, (
        Path(PySide6.__file__).parent,
        Path(shiboken6.__file__).parent,
        Path(sys.base_prefix),
        Path(sys.base_prefix) / "DLLs",
        Path(sys.executable).parent,
        windows / "System32",
        windows,
    )))

hidden_imports = [
    "comic_translator_pipeline",
    "manga_lama",
    "vertical_typesetter",
    "onnx_text_detector",
    "onnx_manga_ocr",
    "onnx_baberu_ocr",
    "comic_translate_core.ocr",
    "comic_translate_core.onnx_ppocr",
    "text_style",
    "punctuation_layout",
    "pyclipper",
    "shapely",
    "tqdm",
    "jaconv",
    "tokenizers",
    "PySide6.QtPdf",
    "PySide6.QtSvg",
]

datas = [
    ("comic-translate-ai/font_file", "comic-translate-ai/font_file"),
    ("comic-translate-ai/main/comic_text_detector", "comic-translate-ai/main/comic_text_detector"),
    ("assets/ComiTrans.ico", "assets"),
    ("assets/ui", "assets/ui"),
]

a = Analysis(
    ["run.py"],
    pathex=[SPECPATH, os.path.join(SPECPATH, "comic-translate-ai", "main")],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchvision",
        "transformers",
        "manga_ocr",
        "unidic_lite",
        "fugashi",
        "optimum",
        "accelerate",
        "matplotlib",
        "pandas",
        "wandb",
        "torchsummary",
        "tkinter",
        "pytest",
        "test",
        "pydoc_data",
        "setuptools.command",
        "IPython",
        "jupyter",
        "notebook",
        "numpy.testing",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ComiTrans",
    icon="assets/ComiTrans.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="ComiTrans",
)
