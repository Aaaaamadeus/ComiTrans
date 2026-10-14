"""Generate a verified file-level patch from a baseline and a new app ZIP."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comic_translate_core.release_patch import create_patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True, help='Previous app ZIP or baseline JSON')
    parser.add_argument('--target', type=Path, required=True, help='New app ZIP with a baseline')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-version', help='Required only for older ZIPs without a baseline')
    args = parser.parse_args()
    patch = create_patch(args.base, args.target, args.output, base_version=args.base_version)
    print(f'{args.output.name}: {args.output.stat().st_size / 1e6:.2f} MB; '
          f'{len(patch["changed"])} updated, {len(patch["deleted"])} removed')


if __name__ == '__main__':
    main()
