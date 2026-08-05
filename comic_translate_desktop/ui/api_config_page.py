from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import mask_api_key


class ApiConfigPage(QWidget):
    save_requested = Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = config

        root = QVBoxLayout(self)
        root.setSpacing(14)

        header = QLabel("API 配置")
        header.setStyleSheet("font-size: 18px; font-weight: 600;")
        root.addWidget(header)

        api_group = QGroupBox("翻译 API")
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
        self._model_info.setStyleSheet("color: #666; font-size: 12px;")

        runtime_form.addRow("硬件", self._gpu_check)
        runtime_form.addRow("输出目录", output_row)
        runtime_form.addRow("Issue 链接", self._issue_input)
        runtime_form.addRow("模型路径", self._model_info)
        root.addWidget(runtime_group)

        actions = QHBoxLayout()
        self._save_btn = QPushButton("保存配置")
        self._save_btn.setStyleSheet(
            "background: #2f6fed; color: white; padding: 6px 18px; border-radius: 4px;"
        )
        self._save_status = QLabel("")
        self._save_status.setStyleSheet("color: #2e7d32;")
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

    def load_config(self, config: dict) -> None:
        self._config = config
        self._key_input.clear()
        if config.get("api_key"):
            self._key_input.setPlaceholderText(f"当前密钥: {mask_api_key(config['api_key'])}")
        self._base_input.setText(config.get("api_base_url", ""))
        self._model_input.setText(config.get("translation_model", ""))
        self._multimodal_check.setChecked(bool(config.get("multimodal", False)))
        self._gpu_check.setChecked(bool(config.get("use_gpu", False)))
        self._output_input.setText(config.get("page_output_dir", ""))
        self._issue_input.setText(config.get("issue_url", ""))
        self._model_info.setText(
            f"检测: {config.get('detector_model', '')}\n"
            f"OCR: {config.get('ocr_model', '')}\n"
            f"修复: {config.get('lama_model', '')}"
        )

    def values(self) -> dict:
        data = {
            "api_base_url": self._base_input.text().strip(),
            "translation_model": self._model_input.text().strip(),
            "multimodal": self._multimodal_check.isChecked(),
            "use_gpu": self._gpu_check.isChecked(),
            "page_output_dir": self._output_input.text().strip(),
            "issue_url": self._issue_input.text().strip(),
        }
        key = self._key_input.text().strip()
        if key:
            data["api_key"] = key
        return data

    def mark_saved(self) -> None:
        self._save_status.setText("配置已保存")
