"""Install the noncommercial CharSpot Small ONNX package (CC BY-NC-SA 4.0)."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.model_package import install_package

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", type=Path, default=ROOT / "comic-translate-ai/models")
    parser.add_argument("--from-directory", type=Path, help="Install from a downloaded official checkout")
    args = parser.parse_args()
    print(install_package(ROOT / "docs/models/charspot-small.json", args.models_root, args.from_directory))
