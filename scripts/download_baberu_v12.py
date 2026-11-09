"""Install the pinned optional Baberu v1.2 package beside existing models.

Never changes config or overwrites an existing model directory. No torch required.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.model_package import install_package

MANIFEST = ROOT / "docs/models/baberu-v1.2.json"


def install(models_root: Path, source: Path | None = None):
    return install_package(MANIFEST, models_root, source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", type=Path, default=ROOT / "comic-translate-ai/models")
    parser.add_argument("--from-directory", type=Path, help="Verify and install an already downloaded candidate")
    args = parser.parse_args()
    print(install(args.models_root, args.from_directory))
    print("Optional model installed; set baberu_ocr_model to this directory and ocr_backend to baberu in config.yaml.")
