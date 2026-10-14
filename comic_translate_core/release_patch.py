"""Content-addressed release baselines and file-level Windows patches."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import zipfile


MANIFEST_NAME = 'release-manifest.json'
ROOT_FILES = {'ComiTrans.exe', 'README-release.md', 'CHANGELOG.md',
              'Apply-Update.ps1', 'Update-ComiTrans.bat'}
PROTECTED = {'models', 'user_fonts', 'page', 'log', 'logs', '__pycache__', '.cache', '.comitrans-update'}


def managed_path(name: str) -> str:
    if not isinstance(name, str) or not name or re.search(r'[\\:\x00-\x1f<>"|?*]', name):
        raise ValueError(f'Invalid release path: {name!r}')
    parts = name.split('/')
    if any(part in ('', '.', '..') or part.endswith((' ', '.')) or
           re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', part) for part in parts):
        raise ValueError(f'Invalid release path: {name!r}')
    if any(part.casefold() in PROTECTED or part.casefold() == 'config.yaml'
           or part.casefold().startswith('.env') for part in parts):
        raise ValueError(f'User data is excluded from patches: {name}')
    if name not in ROOT_FILES and (len(parts) < 2 or parts[0] != '_internal'):
        raise ValueError(f'Unmanaged release path: {name}')
    return name


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def build_id(manifest) -> str:
    content = {key: manifest[key] for key in ('schema', 'product', 'version', 'target', 'files')}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode('utf-8')).hexdigest()


def validate_manifest(manifest):
    if (manifest.get('schema') != 1 or manifest.get('product') != 'ComiTrans'
            or manifest.get('target') != 'windows-x64'
            or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', manifest.get('version', ''))):
        raise ValueError('Unsupported release manifest')
    seen = set()
    for name, record in manifest['files'].items():
        managed_path(name)
        if name.casefold() in seen:
            raise ValueError(f'Conflicting Windows paths: {name}')
        seen.add(name.casefold())
        if (not re.fullmatch(r'[0-9a-f]{64}', record.get('sha256', ''))
                or type(record.get('size')) is not int or record['size'] < 0):
            raise ValueError(f'Invalid file record: {name}')
    if 'ComiTrans.exe' not in manifest['files'] or build_id(manifest) != manifest.get('build_id'):
        raise ValueError('Release build fingerprint does not match')
    return manifest


def make_manifest(version, files):
    manifest = dict(schema=1, product='ComiTrans', version=version,
                    target='windows-x64', files=dict(sorted(files.items())))
    manifest['build_id'] = build_id(manifest)
    return validate_manifest(manifest)


def file_record(handle):
    digest, size = hashlib.sha256(), 0
    while chunk := handle.read(1024 * 1024):
        digest.update(chunk)
        size += len(chunk)
    return dict(size=size, sha256=digest.hexdigest())


def manifest_for_files(version, files):
    records = {}
    for path, archive_name in files:
        if not archive_name.startswith('ComiTrans/'):
            raise ValueError('App archive requires a ComiTrans root folder')
        name = managed_path(archive_name.removeprefix('ComiTrans/'))
        if name in records:
            raise ValueError(f'Duplicate app file: {name}')
        with Path(path).open('rb') as handle:
            records[name] = file_record(handle)
    return make_manifest(version, records)


def read_release(path, legacy_version=None):
    """Verify all archive files, or read a standalone baseline for patch generation."""
    path = Path(path)
    if path.suffix.lower() == '.json':
        return validate_manifest(json.loads(path.read_text(encoding='utf-8-sig'))), True
    with zipfile.ZipFile(path) as archive:
        records, seen = {}, set()
        embedded = None
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            if entry.filename in seen:
                raise ValueError(f'Duplicate archive entry: {entry.filename}')
            seen.add(entry.filename)
            if entry.filename == 'ComiTrans/' + MANIFEST_NAME:
                embedded = json.loads(archive.read(entry))
                continue
            if not entry.filename.startswith('ComiTrans/'):
                raise ValueError('Invalid app archive root')
            name = managed_path(entry.filename.removeprefix('ComiTrans/'))
            with archive.open(entry) as handle:
                records[name] = file_record(handle)
        if embedded is not None:
            validate_manifest(embedded)
            if embedded['files'] != records:
                raise ValueError('App archive does not match its release baseline')
            return embedded, True
        if legacy_version is None:
            raise ValueError('Legacy archive requires an explicit --base-version')
        return make_manifest(legacy_version, records), False


def create_patch(base_path, target_path, output, *, base_version=None):
    if Path(output).resolve() in (Path(base_path).resolve(), Path(target_path).resolve()):
        raise ValueError('Patch output must not overwrite its input baseline or app archive')
    base, requires_manifest = read_release(base_path, base_version)
    target, has_manifest = read_release(target_path)
    if not has_manifest or Path(target_path).suffix.lower() != '.zip':
        raise ValueError('Target must be a complete app ZIP with a release baseline')
    if base['build_id'] == target['build_id']:
        raise ValueError('Both releases have the same build fingerprint')
    old_case = {name.casefold(): name for name in base['files']}
    if any(name.casefold() in old_case and name != old_case[name.casefold()]
           for name in target['files']):
        raise ValueError('Case-only file renames are not supported on Windows')
    changed = sorted(name for name, record in target['files'].items()
                     if base['files'].get(name) != record)
    deleted = sorted(set(base['files']) - set(target['files']))
    patch = dict(schema=1, product='ComiTrans', base=base, target=target,
                 requires_manifest=requires_manifest, changed=changed, deleted=deleted)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.partial')
    try:
        with zipfile.ZipFile(target_path) as source, zipfile.ZipFile(
                temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr('patch.json', json_bytes(patch))
            for name in changed:
                with source.open('ComiTrans/' + name) as input_file, archive.open('files/' + name, 'w') as destination:
                    while chunk := input_file.read(1024 * 1024):
                        destination.write(chunk)
            for name in ('Apply-Update.ps1', 'Update-ComiTrans.bat'):
                archive.writestr(name, source.read('ComiTrans/' + name))
            archive.writestr('README-patch.txt', (
                'ComiTrans 补丁 / Patch\n\n'
                '关闭 ComiTrans。已有基线版可在程序目录双击 Update-ComiTrans.bat，选择此 ZIP。\n'
                '旧版也可先解压此补丁，双击其中 Update-ComiTrans.bat，选择安装目录。\n'
                '补丁验证所有原始程序文件并保留配置、字体、模型和漫画；不匹配会停止。\n'
                '更新前备份修改文件，失败自动恢复；备份保存在安装目录 .comitrans-update。\n\n'
                'Close ComiTrans. Run Update-ComiTrans.bat in the app folder and select this ZIP.\n'
                'Or extract the patch, run its launcher and select the installed app folder.\n'
                f'From: {base["version"]} / {base["build_id"]}\n'
                f'To: {target["version"]} / {target["build_id"]}\n'
            ).encode('utf-8-sig'))
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return patch
