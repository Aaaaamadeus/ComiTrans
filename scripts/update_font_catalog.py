"""Build the offline Google Fonts catalog without downloading font binaries."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
from urllib.request import Request, urlopen


def get_json(url):
    request = Request(url, headers={'User-Agent': 'ComiTrans-Font-Catalog', 'Accept': 'application/json'})
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def normalized(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def build_catalog(tree, metadata, revision):
    if tree.get('truncated'):
        raise ValueError('GitHub returned a truncated tree; refusing an incomplete catalog')
    names = {normalized(font['family']): font for font in metadata if font.get('type') == 'google'}
    groups = {}
    for entry in tree['tree']:
        parts = entry['path'].split('/')
        if entry['type'] != 'blob' or len(parts) < 3 or parts[0] not in ('ofl', 'apache', 'ufl'):
            continue
        group = groups.setdefault('/'.join(parts[:2]), {'faces': [], 'licenses': []})
        path = Path(entry['path'])
        asset = dict(path=entry['path'], sha1=entry['sha'], size=entry['size'])
        if path.suffix.lower() in ('.ttf', '.otf', '.ttc', '.otc'):
            group['faces'].append(dict(asset, name=path.stem))
        elif len(parts) == 3 and path.name.lower() in ('ofl.txt', 'license.txt', 'licence.txt', 'ufl.txt', 'apache.txt'):
            group['licenses'].append(asset)
    families = []
    for identifier, group in groups.items():
        if not group['faces']:
            continue
        info = names.get(identifier.split('/')[-1], {})
        guessed = re.split(r'[-\[]', group['faces'][0]['name'])[0]
        guessed = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', guessed)
        faces = sorted(group['faces'], key=lambda face: (
            'italic' in face['name'].lower(),
            'regular' not in face['name'].lower(),
            '[' not in face['name'],
            len(face['path'].split('/')), face['name']))
        families.append(dict(id=identifier, name=info.get('family', guessed),
                             category=info.get('category', 'other'), subsets=info.get('subsets', []),
                             license={'ofl': 'OFL-1.1', 'apache': 'Apache-2.0', 'ufl': 'UFL-1.0'}[identifier.split('/')[0]],
                             licenses=group['licenses'], faces=faces))
    return dict(schema=1, repository='google/fonts', revision=revision,
                generated_at=datetime.now(timezone.utc).isoformat(),
                metadata_source='https://api.fontsource.org/v1/fonts',
                families=sorted(families, key=lambda family: family['name'].casefold()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('assets/font_catalog.json'))
    parser.add_argument('--source-repo', type=Path, help='Use a blob-filtered local clone when the public API is rate limited')
    args = parser.parse_args()
    if args.source_repo:
        revision = subprocess.check_output(['git', '-C', str(args.source_repo), 'rev-parse', 'HEAD'], text=True).strip()
        entries = subprocess.check_output(['git', '-C', str(args.source_repo), 'ls-tree', '-rz', 'HEAD']).decode('utf-8')
        blobs = []
        for entry in entries.split('\0'):
            if not entry:
                continue
            header, path = entry.split('\t', 1)
            _, kind, sha = header.split()
            # Asking Git for blob sizes would download all blobs in a partial clone.
            blobs.append(dict(type=kind, path=path, sha=sha, size=0))
        tree = dict(tree=blobs, truncated=False)
    else:
        commit = get_json('https://api.github.com/repos/google/fonts/commits/main')
        revision = commit['sha']
        tree = get_json(f'https://api.github.com/repos/google/fonts/git/trees/{revision}?recursive=1')
    metadata = get_json('https://api.fontsource.org/v1/fonts')
    catalog = build_catalog(tree, metadata, revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    faces = [face for family in catalog['families'] for face in family['faces']]
    print(json.dumps(dict(families=len(catalog['families']), faces=len(faces),
                          downloadable_families=sum(bool(family['licenses']) for family in catalog['families']),
                          catalog_bytes=args.output.stat().st_size,
                          all_font_bytes=sum(face['size'] for face in faces) or None,
                          revision=revision), indent=2))


if __name__ == '__main__':
    main()
