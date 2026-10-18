"""Create app/model archives and versioned repository metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from comic_translate_desktop import __version__
from comic_translate_core.release_patch import MANIFEST_NAME, json_bytes, manifest_for_files

ROOT = Path(__file__).resolve().parent
MODELS_SRC = ROOT / "comic-translate-ai" / "models"
MODEL_FILES = [
    "text_detector/comic-text-detector.onnx",
    "manga-lama/lama-manga-dynamic.onnx",
    "ppocr/korean_PP-OCRv5_rec_mobile.onnx",
    "ppocr/en_PP-OCRv5_rec_mobile.onnx",
]
MODEL_DIRS = ["baberu-ocr", "manga-ocr-onnx"]
SKIP_DIRS = {"models", "user_fonts", "Log", "logs", "__pycache__", ".cache"}


def collect_app(dist: Path):
    required = ["ComiTrans.exe", "_internal/assets/ui/fonts/Skribble.ttf",
                "_internal/assets/ui/fonts/AaJinRiHuaQing-ChunLanMaoKun.ttf",
                "_internal/assets/ui/icons/chevron-down.svg",
                "_internal/assets/font_catalog.json",
                "_internal/assets/i18n/en.json",
                "_internal/assets/i18n/ja.json",
                "_internal/PySide6/translations/qtbase_ja.qm",
                "_internal/PySide6/translations/qtbase_zh_CN.qm",
                "_internal/assets/ui/illustrations/studio-import-v1.png",
                "_internal/assets/ui/illustrations/studio-editor-v1.png",
                "_internal/licenses/comic-text-detector/LICENSE",
                "_internal/opencc/config/s2t.json",
                "_internal/opencc/config/t2s.json",
                "_internal/opencc/dictionary/STCharacters.txt",
                "_internal/opencc/dictionary/STPhrases.txt",
                "_internal/opencc/dictionary/TSCharacters.txt",
                "_internal/opencc/dictionary/TSPhrases.txt",
                "_internal/opencc/NOTICE.txt",
                "_internal/opencc_python_reimplemented-0.1.7.dist-info/LICENSE.txt",
                "_internal/comic-translate-ai/font_file/TC/manifest.json"]
    for folder in ('TC', 'Manga'):
        prefix = '_internal/comic-translate-ai/font_file/' + folder + '/'
        required.append(prefix + 'manifest.json')
        font_manifest = dist / (prefix + 'manifest.json')
        if font_manifest.is_file():
            bundled = json.loads(font_manifest.read_text(encoding='utf-8'))
            required.extend(prefix + asset['file'] for asset in bundled['assets'])
    for name in required:
        if not (dist / name).is_file():
            raise FileNotFoundError(f"Build is incomplete: {dist / name}")
    files = []
    for path in sorted(dist.rglob("*")):
        rel = path.relative_to(dist)
        if not path.is_file() or any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.name in {"config.yaml", MANIFEST_NAME, "Apply-Update.ps1", "Update-ComiTrans.bat"} or path.name.startswith('.env') or path.suffix == ".log":
            continue
        files.append((path, "ComiTrans/" + rel.as_posix()))
    for path, name in ((ROOT / f"docs/RELEASE-v{__version__}.md", "README-release.md"),
                       (ROOT / "CHANGELOG.md", "CHANGELOG.md"),
                       (ROOT / "scripts/apply_patch.ps1", "Apply-Update.ps1"),
                       (ROOT / "scripts/apply_patch.bat", "Update-ComiTrans.bat")):
        if not path.is_file():
            raise FileNotFoundError(f"Missing release documentation: {path}")
        files.append((path, "ComiTrans/" + name))
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


def write_checksums(output: Path, paths):
    checksums = []
    for path in paths:
        with path.open('rb') as handle:
            checksum = hashlib.file_digest(handle, 'sha256').hexdigest()
        checksums.append(f'{checksum}  {path.name}')
    (output / 'SHA256SUMS.txt').write_text(
        '\n'.join(checksums) + '\n', encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "ComiTrans")
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    parser.add_argument('--app-only', action='store_true', help='Reuse an existing model archive')
    parser.add_argument('--metadata-dir', type=Path,
                        default=ROOT / 'docs' / 'releases' / f'v{__version__}',
                        help='Repository directory for the baseline and checksums')
    args = parser.parse_args()
    # Validate all inputs before creating either archive.
    app_files = collect_app(args.dist)
    model_target = args.output / f'ComiTrans-v{__version__}-models.zip'
    if args.app_only and not model_target.is_file():
        raise FileNotFoundError(f'--app-only requires an existing model archive: {model_target}')
    model_files = None if args.app_only else collect_models()
    baseline = manifest_for_files(__version__, app_files)
    args.output.mkdir(parents=True, exist_ok=True)
    args.metadata_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = args.metadata_dir / 'baseline.json'
    baseline_path.write_bytes(json_bytes(baseline))
    app_files.append((baseline_path, 'ComiTrans/' + MANIFEST_NAME))
    archives = []
    for kind, files in (("app", app_files), ("models", model_files)):
        target = args.output / f"ComiTrans-v{__version__}-{kind}.zip"
        if files is not None:
            write_archive(target, files)
        archives.append(target)
    write_checksums(args.metadata_dir, [*archives, baseline_path])
    print(f'Release baseline: {baseline["build_id"]}', flush=True)
    print(f'Repository metadata: {args.metadata_dir}', flush=True)


if __name__ == "__main__":
    main()
