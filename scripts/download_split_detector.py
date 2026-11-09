"""Install both ONNX graphs and the Apache license from pinned sources."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.model_package import install_package

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", type=Path, default=ROOT / "comic-translate-ai/models")
    parser.add_argument("--from-directory", type=Path, help="Verified local files with manifest basenames")
    args = parser.parse_args()
    print(install_package(ROOT / "docs/models/split-detector.json", args.models_root, args.from_directory))
