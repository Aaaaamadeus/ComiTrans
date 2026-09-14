# -*- mode: python ; coding: utf-8 -*-

hidden_imports = [
    "comic_translator_pipeline",
    "manga_lama",
    "vertical_typesetter",
    "onnx_text_detector",
    "onnx_manga_ocr",
    "onnx_baberu_ocr",
    "text_style",
    "punctuation_layout",
    "pyclipper",
    "shapely",
    "tqdm",
    "jaconv",
    "tokenizers",
    "PySide6.QtPdf",
]

datas = [
    ("comic-translate-ai/font_file", "comic-translate-ai/font_file"),
    ("comic-translate-ai/main/comic_text_detector", "comic-translate-ai/main/comic_text_detector"),
    ("assets/ComiTrans.ico", "assets"),
]

a = Analysis(
    ["run.py"],
    pathex=["D:\\ComiTrans", "D:\\ComiTrans\\comic-translate-ai\\main"],
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
