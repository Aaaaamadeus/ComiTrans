"""Opt-in release verification using a real Qt window and isolated preferences."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QFontInfo, QRawFont
from PySide6.QtSvg import QSvgRenderer

from . import __version__, config
from .ui.main_window import MainWindow
from .worker import BatchWorker
from .font_library import font_directory
from .font_catalog import load_catalog
from .ui.font_library_dialog import FontLibraryDialog
from .i18n import install_qt_language, load_ui_catalog, set_ui_language, tr
from .ui.language_dialog import InterfaceLanguageDialog
from .ui.star_prompt import STAR_PROMPT_PROBABILITY, STAR_PROMPT_IDLE_MS
from .ui.theme import install_ui_font
from comic_translate_core.chinese import convert_chinese


def run_smoke_test(app, output_dir):
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # Exercise default local models without loading the user's API credentials.
    config.CONFIG_PATH = output / "smoke-defaults.yaml"
    config.PROJECT_ROOT = output
    config.DEFAULT_OUTPUT_DIR = output / "pages"
    app.setApplicationName("ComiTrans-Smoke-Test")
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(output / "settings"))
    window = MainWindow()
    window.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.show()
    result = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False))}

    def finish():
        if window.warmup_worker is not None:
            QTimer.singleShot(200, finish)
            return
        try:
            window._log_panel.flush_all()
            result["pipeline_ready"] = window.pipeline is not None
            result["brand_font"] = QFontInfo(window._brand_title.font()).family()
            result["log_font"] = QFontInfo(window._log_panel.view.font()).family()
            raw = QRawFont.fromFont(window._log_panel.view.font())
            result["missing_glyphs"] = [c for c in "日志翻译日本語かなカナABC0123" if not raw.supportsCharacter(ord(c))]
            result["svg_valid"] = QSvgRenderer(str(config.ICON_PATH.parent / "ui/icons/chevron-down.svg")).isValid()
            result["window_visible"] = window.isVisible()
            pipeline = window.pipeline
            result['translation_preferences_collapsed'] = not window._font_picker.isVisible() and not window._translation_alignment.isVisible()
            window._pref_toggle.click()
            app.processEvents()
            result['translation_preferences_expand'] = window._font_picker.isVisible() and window._translation_alignment.isVisible()
            window._translation_alignment.setCurrentIndex(window._translation_alignment.findData('bottom'))
            result['default_alignment_persisted'] = config.load_ai_config()['vertical_alignment'] == 'bottom'
            result['default_alignment_models_reused'] = window.pipeline is pipeline and pipeline.vertical_alignment == 'bottom'
            window._translation_alignment.setCurrentIndex(window._translation_alignment.findData('center'))
            window._pref_toggle.click()
            result['traditional_conversion'] = convert_chinese('发现头发变长了', 'zh-Hant') == '發現頭髮變長了'
            result['simplified_conversion'] = convert_chinese('漫畫終於開始了', 'zh-Hans') == '漫画终于开始了'
            window._target_language.setCurrentIndex(window._target_language.findData('zh-Hant'))
            result['target_language_persisted'] = config.load_ai_config()['target_language'] == 'zh-Hant'
            result['target_language_models_reused'] = window.pipeline is pipeline
            window._target_language.setCurrentIndex(window._target_language.findData('zh-Hans'))
            imported = window._font_picker.import_paths([config.AI_ROOT / config.FONT_DEFAULTS['dialogue']])
            result['font_imported'] = bool(imported) and imported[0].path.parent == font_directory()
            result['font_choice_persisted'] = config.load_ai_config()['translation_font_active']
            if pipeline is not None:
                BatchWorker([], output / 'unused-output', window.config, pipeline=pipeline)._configure_pipeline(pipeline)
                result['font_pipeline_updated'] = pipeline.typesetter.font_map == window.config['font_map']
                result['font_models_reused'] = window.pipeline is pipeline
            else:
                result['font_pipeline_updated'] = result['font_models_reused'] = False
            result['font_editor_updated'] = window.editor_page.typesetter.font_map == window.config['font_map']
            from PIL import Image
            from vertical_typesetter import VerticalTypesetter
            font_root = config.AI_ROOT / 'font_file/Manga'
            lettering_fonts = [font_root / family / f'{family}CJK{variant}-Black.ttf'
                               for family in ('SweiB2Sans', 'SweiToothpaste') for variant in ('sc', 'tc')]
            result['manga_font_pairs_bundled'] = all(path.is_file() for path in lettering_fonts)
            lettering = VerticalTypesetter({'dialogue': str(lettering_fonts[-1])}, 32)
            sample = Image.new('RGB', (360, 440), '#dddddd')
            lettering.draw_text(sample, [30, 30, 330, 410], '祝你\n\n新年快樂！', 'dialogue',
                                direction=1, target_font_size=32, manual_layout=True, text_effect='hollow')
            result['manual_line_breaks'] = {v['column'] for v in lettering.last_layout_debug} == {0, 2}
            result['hollow_lettering'] = (lettering.last_render_layer is not None
                                         and sample.getextrema()[0][0] < 50 and sample.getextrema()[0][1] > 245)
            sample.save(output / 'manual-lettering.png')
            for alignment in ('top', 'bottom'):
                aligned = Image.new('RGB', (360, 440), '#dddddd')
                lettering.draw_text(aligned, [30, 30, 330, 410], '祝你\n\n新年快樂！', 'dialogue',
                                    direction=1, target_font_size=32, manual_layout=True,
                                    text_effect='hollow', vertical_alignment=alignment)
                cells = lettering.last_layout_debug
                columns = [[cell for cell in cells if cell['column'] == col] for col in (0, 2)]
                ends = [col[0 if alignment == 'top' else -1]['center_y'] for col in columns if col]
                result[f'vertical_{alignment}_alignment'] = len(ends) == 2 and ends[0] == ends[1]
                aligned.save(output / f'vertical-{alignment}.png')
            result["screenshot_saved"] = window.grab().save(str(output / "startup.png"))
            catalog = load_catalog()
            result['catalog_families'] = len(catalog['families'])
            result['font_search_enabled'] = (window._font_picker.combo.isEditable()
                                             and window.editor_page._style_combo.isEditable())
            library = FontLibraryDialog(window.config, window)
            library.setAttribute(Qt.WA_DontShowOnScreen, True)
            library.search.setText('志莽')
            result['catalog_search_results'] = library.font_list.count()
            library.show()
            app.processEvents()
            result['font_library_screenshot_saved'] = library.grab().save(str(output / 'font-library.png'))
            library.close()
            result['star_probability'] = STAR_PROMPT_PROBABILITY
            result['star_idle_ms'] = STAR_PROMPT_IDLE_MS
            result['star_prompt_behavior'] = STAR_PROMPT_PROBABILITY == 0.15 and STAR_PROMPT_IDLE_MS == 8000
            chooser = InterfaceLanguageDialog()
            result['onboarding_default_chinese'] = chooser.selected_language == 'zh-CN'
            chooser.language_combo.setCurrentIndex(chooser.language_combo.findData('ja'))
            result['onboarding_japanese_preview'] = chooser.continue_button.text() == '続行'
            chooser.deleteLater()
            original_warmup = MainWindow._start_warmup
            try:
                MainWindow._start_warmup = lambda self: None
                for code in ('en', 'ja'):
                    set_ui_language(code)
                    install_qt_language(app)
                    install_ui_font(app)
                    config.save_ai_config({'ui_language': code, 'ui_language_selected': True})
                    localized = MainWindow()
                    localized.setAttribute(Qt.WA_DontShowOnScreen, True)
                    localized.show()
                    app.processEvents()
                    result[f'{code}_catalog_bundled'] = len(load_ui_catalog(code)) >= 496
                    result[f'{code}_navigation_translated'] = localized._nav_auto.text() in (tr('01  自动处理'), tr('自动处理'))
                    result[f'{code}_settings_language'] = localized.api_config_page._ui_language.currentData() == code
                    localized._star_prompt.show_prompt()
                    result[f'{code}_star_prompt_visible'] = localized._star_prompt.isVisible()
                    result[f'{code}_screenshot_saved'] = localized.grab().save(str(output / f'interface-{code}.png'))
                    localized._star_prompt.close_button.click()
                    result[f'{code}_star_prompt_closed'] = not localized._star_prompt.isVisible()
                    localized.close()
                    localized.deleteLater()
            finally:
                MainWindow._start_warmup = original_warmup
                set_ui_language('zh-CN')
                install_qt_language(app)
                install_ui_font(app)
                config.save_ai_config({'ui_language': 'zh-CN', 'ui_language_selected': True})
            result["success"] = all((result["pipeline_ready"], result["svg_valid"], result["window_visible"],
                                     result["screenshot_saved"], result["brand_font"] == "Skribble",
                                     result["log_font"] == "Aa今日花晴 春懒猫困", not result["missing_glyphs"],
                                     result['font_imported'], result['font_choice_persisted'], result['font_pipeline_updated'],
                                     result['font_models_reused'], result['font_editor_updated'],
                                     result['catalog_families'] == 2056, result['font_search_enabled'],
                                     result['catalog_search_results'] > 0, result['font_library_screenshot_saved'],
                                     result['traditional_conversion'], result['simplified_conversion'],
                                     result['target_language_persisted'], result['target_language_models_reused'],
                                     result['manga_font_pairs_bundled'], result['manual_line_breaks'], result['hollow_lettering'],
                                     result['vertical_top_alignment'], result['vertical_bottom_alignment'],
                                     result['translation_preferences_collapsed'], result['translation_preferences_expand'],
                                     result['default_alignment_persisted'], result['default_alignment_models_reused']))
            result['success'] = result['success'] and all(
                value for name, value in result.items()
                if name.startswith(('en_', 'ja_', 'onboarding_')) or name == 'star_prompt_behavior')
        except Exception as exc:
            result.update(success=False, error=f"{type(exc).__name__}: {exc}")
        (output / "smoke-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.exit(0 if result["success"] else 1)

    QTimer.singleShot(300, finish)
    return app.exec()
