"""Create versioned app/model archives and checksums; keep older releases."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile

from comic_translate_desktop import __version__

ROOT = Path(__file__).resolve().parent
MODELS_SRC = ROOT / "comic-translate-ai" / "models"
MODEL_FILES = [
    "text_detector/comic-text-detector.onnx",
    "manga-lama/lama-manga-dynamic.onnx",
    "ppocr/korean_PP-OCRv5_rec_mobile.onnx",
    "ppocr/en_PP-OCRv5_rec_mobile.onnx",
]
MODEL_DIRS = ["baberu-ocr", "manga-ocr-onnx"]
SKIP_DIRS = {"models", "Log", "logs", "__pycache__", ".cache"}


def collect_app(dist: Path):
    required = ["ComiTrans.exe", "_internal/assets/ui/fonts/Skribble.ttf",
                "_internal/assets/ui/fonts/AaJinRiHuaQing-ChunLanMaoKun.ttf",
                "_internal/assets/ui/icons/chevron-down.svg"]
    for name in required:
        if not (dist / name).is_file():
            raise FileNotFoundError(f"Build is incomplete: {dist / name}")
    files = []
    for path in sorted(dist.rglob("*")):
        rel = path.relative_to(dist)
        if not path.is_file() or any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.name in {"config.yaml", ".env"} or path.suffix == ".log":
            continue
        files.append((path, "ComiTrans/" + rel.as_posix()))
    return files


def collect_models():
    files = [(MODELS_SRC / rel, rel) for rel in MODEL_FILES]
    for directory in MODEL_DIRS:
        folder = MODELS_SRC / directory
        if not folder.is_dir() or not list(folder.rglob("*.onnx")):
            raise FileNotFoundError(f"Model directory is incomplete: {folder}")
        files.extend((path, path.relative_to(MODELS_SRC).as_posix())
                     for path in sorted(folder.rglob("*"))
                     if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(folder).parts))
    for path, _ in files:
        if not path.is_file():
            raise FileNotFoundError(f"Missing model: {path}")
    return [(path, "ComiTrans/comic-translate-ai/models/" + rel) for path, rel in files]


def write_archive(target: Path, files):
    temporary = target.with_suffix(".zip.partial")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path, name in files:
            archive.write(path, name)
    temporary.replace(target)
    print(f"{target.name}: {target.stat().st_size / 1e6:.1f} MB", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "ComiTrans")
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    # Validate all inputs before creating either archive.
    app_files, model_files = collect_app(args.dist), collect_models()
    args.output.mkdir(parents=True, exist_ok=True)
    archives = []
    for kind, files in (("app", app_files), ("models", model_files)):
        target = args.output / f"ComiTrans-v{__version__}-{kind}.zip"
        write_archive(target, files)
        archives.append(target)
    checksums = []
    for path in archives:
        with path.open("rb") as handle:
            checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        checksums.append(f"{checksum}  {path.name}")
    (args.output / f"ComiTrans-v{__version__}-SHA256SUMS.txt").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
