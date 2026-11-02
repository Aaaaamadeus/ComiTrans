"""Stage page assets on disk and roll back failed publication, without Qt."""
import json
import os
from pathlib import Path
import shutil
import tempfile


class PageWriteTransaction:
    def __init__(self, output_path):
        self.parent = Path(output_path).parent
        self.files = {}

    def __enter__(self):
        self.parent.mkdir(parents=True, exist_ok=True)
        self._directory = tempfile.TemporaryDirectory(prefix='.page-save-', dir=self.parent)
        self.directory = Path(self._directory.name)
        return self

    def stage(self, target):
        target = Path(target)
        if target not in self.files:
            self.files[target] = self.directory / f'new-{len(self.files)}{target.suffix}'
        return self.files[target]

    def commit(self):
        backups = {}
        for index, (target, staged) in enumerate(self.files.items()):
            if not staged.is_file():
                raise FileNotFoundError(f'页面文件尚未写入：{target}')
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = self.directory / f'old-{index}'
            if target.exists():
                shutil.copy2(target, backup)
                backups[target] = backup
            else:
                backups[target] = None
        committed = []
        try:
            for target, staged in self.files.items():
                os.replace(staged, target)
                committed.append(target)
        except Exception:
            for target in reversed(committed):
                if backups[target] is None:
                    target.unlink(missing_ok=True)
                else:
                    shutil.copy2(backups[target], target)
            raise

    def __exit__(self, *_exc):
        self._directory.cleanup()


def save_page_files(rendered, output_path, items, layout_path, cleaned=None, cleaned_path=None,
                    original=None, original_path=None):
    with PageWriteTransaction(output_path) as store:
        rendered.save(store.stage(output_path))
        store.stage(layout_path).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')
        if cleaned is not None:
            cleaned.save(store.stage(cleaned_path))
        if original is not None:
            original.save(store.stage(original_path), format='PNG')
        store.commit()
