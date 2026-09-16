from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import mask_api_key
from comic_translate_core.languages import SOURCE_LANGUAGES
from .manga_components import ChapterBanner


class ApiConfigPage(QWidget):
    save_requested = Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("editorPanel")
        scroll.setWidget(content)
        outer.addWidget(scroll)
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(14)

        header = ChapterBanner('03', '设置', '翻译服务 / OCR 模型 / 默认输出')
        root.addWidget(header)
        subtitle = QLabel("配置翻译服务与本地推理选项，保存后将在下一次任务生效。")
        subtitle.setProperty("muted", True)
        root.addWidget(subtitle)

        api_group = QGroupBox("翻译服务")
        api_form = QFormLayout(api_group)
        api_form.setLabelAlignment(Qt.AlignRight)
        api_form.setSpacing(12)

        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.Password)
        self._key_input.setPlaceholderText("请输入 API Key，不要填模型名")
        self._key_input.setToolTip("DeepSeek / OpenAI 等平台的密钥通常以 sk- 开头")
        self._show_key_check = QCheckBox("显示密钥")
        self._show_key_check.toggled.connect(self._toggle_key_visibility)
        key_row = QHBoxLayout()
        key_row.addWidget(self._key_input, 1)
        key_row.addWidget(self._show_key_check)

        self._base_input = QLineEdit()
        self._base_input.setPlaceholderText("https://api.openai.com/v1")
        self._model_input = QLineEdit()
        self._model_input.setPlaceholderText("gemini-2.5-flash")
        self._multimodal_check = QCheckBox("多模态翻译（发送整页图片，并用 AI 配置字体）")

        api_form.addRow("API Key", key_row)
        api_form.addRow("API Base URL", self._base_input)
        api_form.addRow("翻译模型", self._model_input)
        api_form.addRow("多模态", self._multimodal_check)
        root.addWidget(api_group)

        runtime_group = QGroupBox("运行设置")
        runtime_form = QFormLayout(runtime_group)
        runtime_form.setLabelAlignment(Qt.AlignRight)
        runtime_form.setSpacing(12)

        self._gpu_check = QCheckBox("使用 GPU（需要本机 CUDA 可用）")
        self._ocr_backend = QComboBox()
        self._source_language = QComboBox()
        for code, label in SOURCE_LANGUAGES:
            self._source_language.addItem(label, code)
        self._source_language.currentIndexChanged.connect(self._refresh_ocr_choices)
        self._ocr_backend.currentIndexChanged.connect(self._refresh_custom_visibility)

        self._output_input = QLineEdit()
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_output)
        output_row = QHBoxLayout()
        output_row.addWidget(self._output_input, 1)
        output_row.addWidget(browse_btn)

        self._issue_input = QLineEdit()
        self._issue_input.setPlaceholderText("https://github.com/你的用户名/ComiTrans/issues")

        self._model_info = QLabel()
        self._model_info.setWordWrap(True)
        self._model_info.setProperty("muted", True)

        runtime_form.addRow("硬件", self._gpu_check)
        runtime_form.addRow("被翻译语言", self._source_language)
        runtime_form.addRow("OCR 引擎", self._ocr_backend)
        runtime_form.addRow("输出目录", output_row)
        runtime_form.addRow("Issue 链接", self._issue_input)
        runtime_form.addRow("模型路径", self._model_info)
        root.addWidget(runtime_group)

        self._ppocr_group = QGroupBox("韩语 / 英语本地 OCR")
        ppocr_form = QFormLayout(self._ppocr_group)
        self._korean_model = QLineEdit()
        self._english_model = QLineEdit()
        for label, field in (("韩语模型", self._korean_model), ("英语模型", self._english_model)):
            row = QHBoxLayout()
            button = QPushButton("浏览...")
            button.clicked.connect(lambda _checked=False, target=field: self._browse_model(target))
            row.addWidget(field, 1)
            row.addWidget(button)
            ppocr_form.addRow(label, row)
        note = QLabel("使用 PP-OCRv5 ONNX 模型。模型包缺失时，按 docs/MULTILINGUAL_OCR.md 下载后选择模型文件。")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        ppocr_form.addRow(note)
        root.addWidget(self._ppocr_group)

        self._custom_group = QGroupBox("自定义 OCR")
        custom_form = QFormLayout(self._custom_group)
        self._custom_language = QLineEdit()
        self._custom_language.setPlaceholderText("例如 fr、de、th；选择自定义 OCR 语言时必填")
        self._custom_language_name = QLineEdit()
        self._custom_language_name.setPlaceholderText("例如 法语（可选）")
        self._custom_protocol = QComboBox()
        self._custom_protocol.addItem("标准 HTTP OCR", "http")
        self._custom_protocol.addItem("兼容 OpenAI 的视觉模型", "openai")
        self._custom_url = QLineEdit()
        self._custom_url.setPlaceholderText("HTTP 完整识别地址；视觉模型填写 Base URL")
        self._custom_key = QLineEdit()
        self._custom_key.setEchoMode(QLineEdit.Password)
        self._custom_key.setPlaceholderText("独立 OCR 密钥，本地无鉴权服务可留空")
        self._custom_model = QLineEdit()
        self._custom_model.setPlaceholderText("视觉模型必填；标准 HTTP 可选")
        self._custom_timeout = QSpinBox()
        self._custom_timeout.setRange(1, 300)
        self._custom_timeout.setSuffix(" 秒")
        custom_form.addRow("源语言代码", self._custom_language)
        custom_form.addRow("语言名称", self._custom_language_name)
        custom_form.addRow("接入方式", self._custom_protocol)
        custom_form.addRow("OCR 地址", self._custom_url)
        custom_form.addRow("OCR API Key", self._custom_key)
        custom_form.addRow("OCR 模型", self._custom_model)
        custom_form.addRow("请求超时", self._custom_timeout)
        note = QLabel('此模式会将文本区域图片发送到配置的 OCR 服务。标准 HTTP 返回 {"text": "原文"}；完整接入协议见 docs/MULTILINGUAL_OCR.md。输出译文为简体中文。')
        note.setWordWrap(True)
        note.setProperty("muted", True)
        custom_form.addRow(note)
        root.addWidget(self._custom_group)

        actions = QHBoxLayout()
        self._save_btn = QPushButton("保存配置")
        self._save_btn.setProperty("role", "primary")
        self._save_status = QLabel("")
        self._save_status.setProperty("muted", True)
        actions.addWidget(self._save_btn)
        actions.addWidget(self._save_status)
        actions.addStretch(1)
        root.addLayout(actions)
        root.addStretch(1)

        self._save_btn.clicked.connect(self.save_requested)
        self.load_config(config)

    def _toggle_key_visibility(self, checked: bool) -> None:
        self._key_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self._output_input.text())
        if path:
            self._output_input.setText(path)

    def _browse_model(self, field) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 ONNX 模型", field.text(), "ONNX 模型 (*.onnx)")
        if path:
            field.setText(path)

    def _refresh_ocr_choices(self) -> None:
        previous = self._ocr_backend.currentData()
        self._ocr_backend.blockSignals(True)
        self._ocr_backend.clear()
        language = self._source_language.currentData()
        if language == "ja":
            choices = [("自动（优先 Baberu，缺失时回退）", "auto"), ("Baberu OCR", "baberu"), ("manga-ocr", "manga-ocr")]
        elif language in ("ko", "en"):
            choices = [("自动（PP-OCRv5 本地识别）", "auto")]
        else:
            choices = []
        for label, value in choices + [("自定义 OCR", "custom")]:
            self._ocr_backend.addItem(label, value)
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
        self._config = config
        self._key_input.clear()
        if config.get("api_key"):
            self._key_input.setPlaceholderText(f"当前密钥: {mask_api_key(config['api_key'])}")
        self._base_input.setText(config.get("api_base_url", ""))
        self._model_input.setText(config.get("translation_model", ""))
        self._multimodal_check.setChecked(bool(config.get("multimodal", False)))
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
        self._output_input.setToolTip(self._output_input.text())
        self._output_input.setCursorPosition(len(self._output_input.text()))
        self._issue_input.setText(config.get("issue_url", ""))
        self._model_info.setText(
            f"检测: {config.get('detector_model', '')}\n"
            f"Baberu OCR: {config.get('baberu_ocr_model', '')}\n"
            f"manga-ocr: {config.get('ocr_model', '')}\n"
            f"修复: {config.get('lama_model', '')}"
        )

    def values(self) -> dict:
        data = {
            "api_base_url": self._base_input.text().strip(),
            "translation_model": self._model_input.text().strip(),
            "multimodal": self._multimodal_check.isChecked(),
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
        self._save_status.setText("配置已保存")
