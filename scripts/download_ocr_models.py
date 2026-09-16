"""Download pinned RapidOCR PP-OCRv5 models without installing Paddle/PyTorch."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import requests

BASE_URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/"
MODELS = {
    "ko": ("korean_PP-OCRv5_rec_mobile.onnx", "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b"),
    "en": ("en_PP-OCRv5_rec_mobile.onnx", "c3461add59bb4323ecba96a492ab75e06dda42467c9e3d0c18db5d1d21924be8"),
}


def download(language: str, output: Path) -> Path:
    filename, expected = MODELS[language]
    output.mkdir(parents=True, exist_ok=True)
    target = output / filename
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        print(f"已校验: {target}", flush=True)
        return target
    temporary = target.with_suffix(".onnx.part")
    try:
        print(f"下载 {language}: {filename}", flush=True)
        digest = hashlib.sha256()
        with requests.get(BASE_URL + filename, stream=True, timeout=(15, 90)) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    handle.write(chunk)
                    digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"{filename} SHA256 校验失败，未替换原模型。")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"已下载并校验: {target}", flush=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languages", nargs="+", choices=MODELS, default=list(MODELS))
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "comic-translate-ai/models/ppocr")
    args = parser.parse_args()
    for language in args.languages:
        download(language, args.output)
