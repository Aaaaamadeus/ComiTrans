# -*- mode: python ; coding: utf-8 -*-

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules
import unidic_lite

UNIDIC_DATA = os.path.join(os.path.dirname(unidic_lite.__file__), "dicdir")


hidden_imports = [
    "comic_translator_pipeline",
    "manga_lama",
    "vertical_typesetter",
]
hidden_imports += collect_submodules("comic_text_detector")
hidden_imports += [
    "pyclipper",
    "shapely",
    "tqdm",
]

datas = [
    ("comic-translate-ai/font_file", "comic-translate-ai/font_file"),
    ("comic-translate-ai/main/comic_text_detector", "comic-translate-ai/main/comic_text_detector"),
    (UNIDIC_DATA, "unidic_lite/dicdir"),
]
datas += collect_data_files("manga_ocr")

a = Analysis(
    ["run.py"],
    pathex=["D:\\ComiTrans", "D:\\ComiTrans\\comic-translate-ai\\main"],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
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
