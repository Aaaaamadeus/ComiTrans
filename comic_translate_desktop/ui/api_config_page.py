from __future__ import annotations
from ..i18n import tr

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import mask_api_key
from ..i18n import UI_LANGUAGES
from comic_translate_core.languages import SOURCE_LANGUAGES
from .manga_components import PanelHeading


class ApiConfigPage(QWidget):
    save_requested = Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config
        self._loading_config = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QFrame()
        body.setObjectName('pageBody')
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 16, 24, 12)
        self._sections = QTabWidget()
        self._sections.setDocumentMode(True)
        self._sections.setAccessibleName(tr('设置分类'))
        body_layout.addWidget(self._sections)
        outer.addWidget(body, 1)
        root = self._add_section(tr('01  翻译服务'), tr('连接你的翻译服务'), tr('配置接口、翻译方式和输出水印，保存后将在下一次任务生效。'))
        ocr_root = self._add_section(tr('02  文字识别'), tr('选择语言与识别方式'), tr('本地识别和自定义 OCR 均在这里配置。'))
        runtime_root = self._add_section(tr('03  运行与输出'), tr('安排输出与运行选项'), tr('设置默认保存位置和硬件加速。'))

        api_group = QGroupBox(tr('翻译服务'))
        api_form = QFormLayout(api_group)
        self._style_form(api_form)

        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText(tr('请输入 API Key，不要填模型名'))
        self._key_input.setToolTip(tr('DeepSeek / OpenAI 等平台的密钥通常以 sk- 开头'))
        self._show_key_check = QCheckBox(tr('显示密钥'))
        self._show_key_check.toggled.connect(self._toggle_key_visibility)
        key_row = QHBoxLayout()
        key_row.addWidget(self._key_input, 1)
        key_row.addWidget(self._show_key_check)

        self._base_input = QLineEdit()
        self._base_input.setPlaceholderText('https://api.openai.com/v1')
        self._model_input = QLineEdit()
        self._model_input.setPlaceholderText('gemini-2.5-flash')
        self._multimodal_check = QCheckBox(tr('发送整页图片辅助翻译'))
        self._multimodal_check.setToolTip(
            tr('勾选后会把整页图片发给翻译服务，结合画面翻译；默认字体在翻译页选择。字号与排版方向由本地算法决定，AI 字体判别需另行启用。')
        )

        self._font_probe_check = QCheckBox(tr('AI 字体判别（实验，默认关闭）'))
        self._font_probe_check.setToolTip(
            tr('真实漫画页实测：同一页多次运行可能给出不同判定，且每块需数千 reasoning token。\n不勾选时多模态只做翻译，字体完全交给本地算法（更稳定）。详见 docs/FONT_STYLE_STRATEGY.md §4.14。\n仅在‘自动匹配漫画风格’时运行；翻译页指定的字体优先。')
        )
        self._no_thinking_check = QCheckBox(tr('关闭思考模式（省 token，默认开启）'))
        self._no_thinking_check.setToolTip(
            tr('实测同一页翻译：输出 token 214 → 51，耗时 1.8s → 0.7s，译文质量相当。\n若你的服务不支持该参数，会自动去掉并重试。详见 docs/FONT_STYLE_STRATEGY.md §4.15。')
        )

        api_form.addRow('API Key', key_row)
        api_form.addRow('API Base URL', self._base_input)
        api_form.addRow(tr('翻译模型'), self._model_input)
        api_form.addRow(tr('多模态'), self._multimodal_check)
        api_form.addRow(tr('字体判别'), self._font_probe_check)
        api_form.addRow(tr('思考模式'), self._no_thinking_check)
        root.addWidget(api_group)
        self._watermark_check = QCheckBox(tr('添加 @ComiTrans 水印（默认开启）'))
        self._watermark_check.setToolTip(tr('在输出图片和 PDF 每页右下角添加小号半透明字标，精修保存时同样生效。取消勾选并保存可关闭。'))
        root.addWidget(self._watermark_check)
        interface_group = QGroupBox(tr('界面语言'))
        interface_form = QFormLayout(interface_group)
        self._style_form(interface_form)
        self._ui_language = QComboBox()
        self._ui_language.setAccessibleName(tr('界面语言'))
        for code, name in UI_LANGUAGES:
            self._ui_language.addItem(tr(name), code)
        interface_form.addRow(tr('显示语言'), self._ui_language)
        interface_note = QLabel(tr('保存后下次启动生效，不影响漫画译文语言。'))
        interface_note.setWordWrap(True)
        interface_note.setProperty('muted', True)
        interface_form.addRow(tr(interface_note))
        root.insertWidget(0, interface_group)
        root.addStretch(1)

        runtime_group = QGroupBox(tr('运行设置'))
        runtime_form = QFormLayout(runtime_group)
        self._style_form(runtime_form)

        self._gpu_check = QCheckBox(tr('使用 GPU（需要本机 CUDA 可用）'))
        self._ocr_backend = QComboBox()
        self._source_language = QComboBox()
        for code, label in SOURCE_LANGUAGES:
            self._source_language.addItem(tr(label), code)
        self._source_language.currentIndexChanged.connect(self._refresh_ocr_choices)
        self._ocr_backend.currentIndexChanged.connect(self._refresh_custom_visibility)

        self._output_input = QLineEdit()
        browse_btn = QPushButton(tr('浏览...'))
        browse_btn.clicked.connect(self._browse_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self._output_input, 1)
        output_row.addWidget(browse_btn)

        self._issue_input = QLineEdit()
        self._issue_input.setPlaceholderText(tr('https://github.com/你的用户名/ComiTrans/issues'))

        self._model_info = QLabel()
        self._model_info.setWordWrap(True)
        self._model_info.setProperty("muted", True)

        runtime_form.addRow(tr('硬件'), self._gpu_check)
        runtime_form.addRow(tr('输出目录'), output_row)
        runtime_form.addRow(tr('Issue 链接'), self._issue_input)
        runtime_root.addWidget(runtime_group)
        runtime_root.addStretch(1)
        ocr_group = QGroupBox(tr('语言与引擎'))
        ocr_form = QFormLayout(ocr_group)
        self._style_form(ocr_form)
        ocr_form.addRow(tr('原文语言'), self._source_language)
        ocr_form.addRow(tr('OCR 引擎'), self._ocr_backend)
        ocr_form.addRow(tr('本地模型'), self._model_info)
        self._model_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ocr_root.addWidget(ocr_group)

        self._ppocr_group = QGroupBox(tr('韩语 / 英语本地 OCR'))
        ppocr_form = QFormLayout(self._ppocr_group)
        self._style_form(ppocr_form)
        self._korean_model = QLineEdit()
        self._english_model = QLineEdit()
        for label, field in ((tr('韩语模型'), self._korean_model), (tr('英语模型'), self._english_model)):
            row = QHBoxLayout()
            button = QPushButton(tr('浏览...'))
            button.clicked.connect(lambda _checked=False, target=field: self._browse_model(target))
            row.addWidget(field, 1)
            row.addWidget(button)
            ppocr_form.addRow(tr(label), row)
        note = QLabel(tr('使用 PP-OCRv5 ONNX 模型。模型包缺失时，按 docs/MULTILINGUAL_OCR.md 下载后选择模型文件。'))
        note.setWordWrap(True)
        note.setProperty("muted", True)
        ppocr_form.addRow(tr(note))
        ocr_root.addWidget(self._ppocr_group)

        self._custom_group = QGroupBox(tr('自定义 OCR'))
        custom_form = QFormLayout(self._custom_group)
        self._style_form(custom_form)
        self._custom_language = QLineEdit()
        self._custom_language.setPlaceholderText(tr('例如 fr、de、th；选择自定义 OCR 语言时必填'))
        self._custom_language_name = QLineEdit()
        self._custom_language_name.setPlaceholderText(tr('例如 法语（可选）'))
        self._custom_protocol = QComboBox()
        self._custom_protocol.addItem(tr('标准 HTTP OCR'), "http")
        self._custom_protocol.addItem(tr('兼容 OpenAI 的视觉模型'), "openai")
        self._custom_url = QLineEdit()
        self._custom_url.setPlaceholderText(tr('HTTP 完整识别地址；视觉模型填写 Base URL'))
        self._custom_key = QLineEdit()
        self._custom_key.setEchoMode(QLineEdit.Password)
        self._custom_key.setPlaceholderText(tr('独立 OCR 密钥，本地无鉴权服务可留空'))
        self._custom_model = QLineEdit()
        self._custom_model.setPlaceholderText(tr('视觉模型必填；标准 HTTP 可选'))
        self._custom_timeout = QSpinBox()
        self._custom_timeout.setRange(1, 300)
        self._custom_timeout.setSuffix(tr(' 秒'))
        custom_form.addRow(tr('源语言代码'), self._custom_language)
        custom_form.addRow(tr('语言名称'), self._custom_language_name)
        custom_form.addRow(tr('接入方式'), self._custom_protocol)
        custom_form.addRow(tr('OCR 地址'), self._custom_url)
        custom_form.addRow('OCR API Key', self._custom_key)
        custom_form.addRow(tr('OCR 模型'), self._custom_model)
        custom_form.addRow(tr('请求超时'), self._custom_timeout)
        note = QLabel(tr('此模式会将文本区域图片发送到配置的 OCR 服务。标准 HTTP 返回 {"text": "原文"}；完整接入协议见 docs/MULTILINGUAL_OCR.md。译文简繁在翻译页选择。'))
        note.setWordWrap(True)
        note.setProperty("muted", True)
        custom_form.addRow(tr(note))
        ocr_root.addWidget(self._custom_group)
        ocr_root.addStretch(1)

        footer = QFrame()
        footer.setObjectName('pageActions')
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(24, 12, 24, 12)
        self._save_btn = QPushButton(tr('保存配置'))
        self._save_btn.setProperty("role", "primary")
        self._save_status = QLabel(tr('修改后点击保存，下次任务生效'))
        self._save_status.setProperty("muted", True)
        actions.addWidget(self._save_status)
        actions.addStretch(1)
        actions.addWidget(self._save_btn)
        outer.addWidget(footer)

        self._save_btn.clicked.connect(self.save_requested)
        self.load_config(config)
        for field in self.findChildren(QLineEdit):
            field.textChanged.connect(self._mark_unsaved)
        for combo in self.findChildren(QComboBox):
            combo.currentIndexChanged.connect(self._mark_unsaved)
        for check in self.findChildren(QCheckBox):
            if check is not self._show_key_check:
                check.toggled.connect(self._mark_unsaved)
        self._custom_timeout.valueChanged.connect(self._mark_unsaved)

    def _add_section(self, tab_title, title, description):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        canvas = QFrame()
        canvas.setObjectName('editorPanel')
        centered = QHBoxLayout(canvas)
        centered.setContentsMargins(0, 0, 0, 0)
        content = QFrame()
        content.setObjectName('editorPanel')
        content.setMaximumWidth(1040)
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 24, 20, 24)
        root.setSpacing(16)
        heading = PanelHeading('', title)
        root.addWidget(heading)
        hint = QLabel(tr(description))
        hint.setProperty('muted', True)
        hint.setWordWrap(True)
        root.addWidget(hint)
        centered.addStretch(1)
        centered.addWidget(content, 8)
        centered.addStretch(1)
        scroll.setWidget(canvas)
        self._sections.addTab(scroll, tr(tab_title))
        return root

    @staticmethod
    def _style_form(form):
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(14)

    def _mark_unsaved(self, *args):
        if not self._loading_config:
            self._save_status.setText(tr('有未保存的修改'))

    def _toggle_key_visibility(self, checked: bool) -> None:
        self._key_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr('选择输出目录'), self._output_input.text())
        if path:
            self._output_input.setText(path)

    def _browse_model(self, field) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr('选择 ONNX 模型'), field.text(), tr('ONNX 模型 (*.onnx)'))
        if path:
            field.setText(tr(path))

    def _refresh_ocr_choices(self) -> None:
        previous = self._ocr_backend.currentData()
        self._ocr_backend.blockSignals(True)
        self._ocr_backend.clear()
        language = self._source_language.currentData()
        if language == "ja":
            choices = [(tr('自动（优先 Baberu，缺失时回退）'), "auto"), ("Baberu OCR", "baberu"), ("manga-ocr", "manga-ocr")]
        elif language in ("ko", "en"):
            choices = [(tr('自动（PP-OCRv5 本地识别）'), "auto")]
        else:
            choices = []
        for label, value in choices + [(tr('自定义 OCR'), "custom")]:
            self._ocr_backend.addItem(tr(label), value)
        index = self._ocr_backend.findData(previous)
        self._ocr_backend.setCurrentIndex(max(0, index))
        self._ocr_backend.blockSignals(False)
        self._refresh_custom_visibility()

    def _refresh_custom_visibility(self) -> None:
        if not hasattr(self, "_custom_group"):
            return
        self._custom_group.setVisible(self._ocr_backend.currentData() == "custom")
        custom_language = self._source_language.currentData() == "custom"
        self._custom_language.setEnabled(custom_language)
        self._custom_language_name.setEnabled(custom_language)
        self._ppocr_group.setVisible(self._source_language.currentData() in ("ko", "en") and self._ocr_backend.currentData() != "custom")

    def load_config(self, config: dict) -> None:
        self._loading_config = True
        self._config = config
        self._key_input.clear()
        self._ui_language.setCurrentIndex(max(0, self._ui_language.findData(config.get('ui_language', 'zh-CN'))))
        if config.get("api_key"):
            self._key_input.setPlaceholderText(tr('当前密钥: {_0}', _0=mask_api_key(config['api_key'])))
        self._base_input.setText(config.get("api_base_url", ""))
        self._model_input.setText(config.get("translation_model", ""))
        self._multimodal_check.setChecked(bool(config.get("multimodal", False)))
        self._font_probe_check.setChecked(bool(config.get("multimodal_font_probe", False)))
        self._no_thinking_check.setChecked(bool(config.get("disable_thinking", True)))
        self._gpu_check.setChecked(bool(config.get("use_gpu", False)))
        self._source_language.setCurrentIndex(max(0, self._source_language.findData(config.get("source_language", "ja"))))
        self._refresh_ocr_choices()
        backend = str(config.get("ocr_backend") or "auto")
        backend = {"manga": "manga-ocr", "ppocr": "auto"}.get(backend, backend)
        backend_index = self._ocr_backend.findData(backend)
        self._ocr_backend.setCurrentIndex(max(0, backend_index))
        self._korean_model.setText(config.get("korean_ocr_model", ""))
        self._english_model.setText(config.get("english_ocr_model", ""))
        self._custom_language.setText(config.get("custom_source_language") or "")
        self._custom_language_name.setText(config.get("custom_source_language_name") or "")
        self._custom_protocol.setCurrentIndex(max(0, self._custom_protocol.findData(config.get("custom_ocr_protocol", "http"))))
        self._custom_url.setText(config.get("custom_ocr_url") or "")
        self._custom_key.setText(config.get("custom_ocr_api_key") or "")
        self._custom_model.setText(config.get("custom_ocr_model") or "")
        self._custom_timeout.setValue(int(config.get("custom_ocr_timeout") or 60))
        self._refresh_custom_visibility()
        self._output_input.setText(config.get("page_output_dir", ""))
        self._watermark_check.setChecked(bool(config.get("watermark_enabled", True)))
        self._output_input.setToolTip(self._output_input.text())
        self._output_input.setCursorPosition(len(self._output_input.text()))
        self._issue_input.setText(config.get("issue_url", ""))
        self._model_info.setText(
            tr('检测: {_0}\nBaberu OCR: {_1}\nmanga-ocr: {_2}\n修复: {_3}', _0=config.get('detector_model', ''), _1=config.get('baberu_ocr_model', ''), _2=config.get('ocr_model', ''), _3=config.get('lama_model', ''))
        )
        self._loading_config = False
        self._save_status.setText(tr('修改后点击保存，下次任务生效'))

    def values(self) -> dict:
        data = {
            "ui_language": self._ui_language.currentData(),
            "ui_language_selected": True,
            "api_base_url": self._base_input.text().strip(),
            "translation_model": self._model_input.text().strip(),
            "multimodal": self._multimodal_check.isChecked(),
            "multimodal_font_probe": self._font_probe_check.isChecked(),
            "disable_thinking": self._no_thinking_check.isChecked(),
            "watermark_enabled": self._watermark_check.isChecked(),
            "use_gpu": self._gpu_check.isChecked(),
            "ocr_backend": self._ocr_backend.currentData(),
            "source_language": self._source_language.currentData(),
            "korean_ocr_model": self._korean_model.text().strip(),
            "english_ocr_model": self._english_model.text().strip(),
            "custom_source_language": self._custom_language.text().strip(),
            "custom_source_language_name": self._custom_language_name.text().strip(),
            "custom_ocr_protocol": self._custom_protocol.currentData(),
            "custom_ocr_url": self._custom_url.text().strip(),
            "custom_ocr_api_key": self._custom_key.text().strip(),
            "custom_ocr_model": self._custom_model.text().strip(),
            "custom_ocr_timeout": self._custom_timeout.value(),
            "page_output_dir": self._output_input.text().strip(),
            "issue_url": self._issue_input.text().strip(),
        }
        key = self._key_input.text().strip()
        if key:
            data["api_key"] = key
        return data

    def mark_saved(self) -> None:
        self._save_status.setText(tr('配置已保存'))
