# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


hidden_imports = [
    "comic_translator_pipeline",
    "manga_lama",
    "vertical_typesetter",
]
hidden_imports += collect_submodules("comic_text_detector")

datas = [
    ("comic-translate-ai/font_file", "comic-translate-ai/font_file"),
    ("comic-translate-ai/models/manga-ocr-base", "comic-translate-ai/models/manga-ocr-base"),
    (
        "comic-translate-ai/models/manga-lama/lama-manga-dynamic.onnx",
        "comic-translate-ai/models/manga-lama",
    ),
    (
        "comic-translate-ai/models/text_detector/comictextdetector.pt",
        "comic-translate-ai/models/text_detector",
    ),
    ("comic-translate-ai/main/comic_text_detector", "comic-translate-ai/main/comic_text_detector"),
]

a = Analysis(
    ["run.py"],
    pathex=["D:\\ComiTrans", "D:\\ComiTrans\\comic-translate-ai\\main"],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
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
