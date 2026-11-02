"""Repeatable synthetic page-project benchmark; no models, API calls or downsampling."""
import argparse
import ctypes
import json
import os
import shutil
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings, QTimer, QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from comic_translate_desktop import config
from comic_translate_desktop.pdf_project import write_project_metadata
from comic_translate_desktop.ui.editor_page import EditorPage


def memory_mb():
    if sys.platform == 'win32':
        class Counters(ctypes.Structure):
            _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [
                (name, ctypes.c_size_t) for name in ('peak', 'rss', 'peak_paged', 'paged',
                                                    'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile')]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError()
        return round(counters.rss / 1048576, 1)
    import resource
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def wait_until(condition):
    if condition():
        return
    loop = QEventLoop()
    poll, deadline = QTimer(), QTimer()
    poll.timeout.connect(lambda: loop.quit() if condition() else None)
    poll.start(5)
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(60000)
    # A real Qt event loop releases the GIL; repeated QTest.qWait calls can starve Python I/O workers.
    loop.exec()
    poll.stop()
    deadline.stop()
    if not condition():
        raise RuntimeError('Benchmark operation timed out')


def run(count):
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix='comitrans-benchmark-') as raw:
        root = Path(raw)
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, raw)
        native_size = (3000, 4500)
        source = Image.effect_noise((750, 1125), 35).convert('RGB').resize(native_size, Image.Resampling.BICUBIC)
        draw = ImageDraw.Draw(source)
        draw.rectangle((200, 200, 1100, 1500), fill='#e8ddc8')
        source.save(root / 'sample.png')
        source.close()
        item = dict(text='性能测试文字', box=[300, 300, 900, 1400], mask_box=[300, 300, 900, 1400],
                    font_size=60, rendered_font_size=60, direction=1, style='dialogue')
        for folder in ('translated', 'translated_cleaned', 'translated_layout'):
            (root / folder).mkdir()
        for index in range(1, count + 1):
            stem = f'page_{index:04d}'
            seed = root / f'seed_{index // 400}.png'
            if not seed.exists():
                shutil.copyfile(root / 'sample.png', seed)
            os.link(seed, root / 'translated' / f'{stem}.png')
            os.link(seed, root / 'translated_cleaned' / f'{stem}_cleaned.png')
            (root / 'translated_layout' / f'{stem}_layout.json').write_text(json.dumps([item]), encoding='utf-8')
        write_project_metadata(root, 'synthetic.pdf', [(720, 1080)] * count)
        with patch.object(config, 'CONFIG_PATH', root / 'config.yaml'):
            config.save_ai_config({'watermark_enabled': True})
            editor = EditorPage()
            editor.resize(1440, 900)
            editor.show()
            QTest.qWait(20)
            before = memory_mb()
            gaps, last = [], [time.perf_counter()]
            timer = QTimer()
            def tick():
                now = time.perf_counter()
                gaps.append((now-last[0])*1000)
                last[0] = now
            timer.timeout.connect(tick)
            timer.start(10)
            start = time.perf_counter()
            editor.request_page(root / 'project.json')
            wait_until(lambda: not editor.page_io_busy)
            opening = (time.perf_counter()-start)*1000
            editor._strip_toggle.setChecked(True)
            QTest.qWait(50)
            switches, canvas_counts = [], []
            for fraction in (1, .5, .1, .75, 0):
                page = max(1, round((count-1)*fraction)+1)
                start = time.perf_counter()
                editor.request_page(root / 'translated' / f'page_{page:04d}.png')
                wait_until(lambda: not editor._page_jobs.busy)
                switches.append((time.perf_counter()-start)*1000)
                canvas_counts.append(len(editor.preview._canvas_keys)+len(editor.preview._spares))
            editor.apply_changes()
            edits, ratios = [], []
            for n in range(5):
                start = time.perf_counter()
                editor._text_input.setPlainText(f'修改后的文字{n}')
                editor.apply_changes()
                edits.append((time.perf_counter()-start)*1000)
                ratios.append(sum((r[2]-r[0])*(r[3]-r[1]) for r in editor._last_render_regions)/(3000*4500))
                QTest.qWait(10)
            start = time.perf_counter()
            editor.request_save()
            wait_until(lambda: not editor._save_jobs.busy)
            saving = (time.perf_counter()-start)*1000
            timer.stop()
            result = dict(pages=count, native_pixels=list(native_size), open_ms=round(opening),
                          switch_median_ms=round(statistics.median(switches)),
                          edit_median_ms=round(statistics.median(edits)), save_ms=round(saving),
                          max_gui_timer_gap_ms=round(max(gaps)), rss_before_mb=before,
                          rss_after_mb=memory_mb(), max_canvas_widgets=max(canvas_counts),
                          sidebar_thumbnail_count=len(editor._thumbnail_lru),
                          median_redrawn_fraction=round(statistics.median(ratios), 4))
            editor.close()
            wait_until(lambda: editor._thumbnail_loader._active is None and editor.preview._thumbnail_loader._active is None)
            return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.pages)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
