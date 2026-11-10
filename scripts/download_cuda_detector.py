"""Install the audited CUDA detector without overwriting a custom model."""
import argparse
from pathlib import Path
import sys
from uuid import uuid4

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from comic_translate_core.detector_paths import LEGACY_PATH
from package_release import legacy_detector_entry
from scripts.model_package import digest, verify


def install(models_root):
    entry = legacy_detector_entry()
    manifest = {"files": [entry]}
    target = models_root / LEGACY_PATH
    if target.exists():
        verify(models_root, manifest)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    # Create the download beside its destination so it inherits the model
    # library's permissions when the verified file is moved into place.
    temporary = target.with_name(f".{target.name}-{uuid4().hex}.part")
    try:
        with requests.get(entry["source_url"], stream=True, timeout=(15, 90)) as response:
            response.raise_for_status()
            with temporary.open("wb") as stream:
                size = 0
                for chunk in response.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > entry["bytes"]:
                        raise ValueError("Detector download exceeds the audited size")
                    stream.write(chunk)
        if size != entry["bytes"] or digest(temporary) != entry["sha256"]:
            raise ValueError("Detector download failed verification")
        if target.exists():
            verify(models_root, manifest)
            return target
        temporary.rename(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", type=Path, default=ROOT / "comic-translate-ai/models")
    print(install(parser.parse_args().models_root))
