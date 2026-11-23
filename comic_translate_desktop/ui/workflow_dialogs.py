"""Focused dialogs for work terminology, trial translation and usage."""
from copy import deepcopy
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout)

from ..i18n import tr
from ..productivity import terminology_projects, trial_projection, usage_cost


class TerminologyDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('作品术语库'))
        self.resize(660, 460)
        self.projects = deepcopy(terminology_projects(config.get('terminology_projects')))
        self._current = ''
        root = QVBoxLayout(self)
        hint = QLabel(tr('只填写固定译名即可，AI 会根据上下文自动匹配原文。类型和识别线索可帮助区分同名角色；不确定时不会强行套用。'))
        hint.setWordWrap(True)
        root.addWidget(hint)
        row = QHBoxLayout()
        self.project = QComboBox()
        self.project.setMinimumContentsLength(12)
        self.project.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.project.addItem(tr('不使用术语库'), '')
        for identity, project in self.projects.items():
            self.project.addItem(project['name'], identity)
        row.addWidget(self.project, 1)
        new = QPushButton(tr('新建作品'))
        new.clicked.connect(self._new_project)
        row.addWidget(new)
        self.remove_project = QPushButton(tr('删除作品'))
        self.remove_project.clicked.connect(self._remove_project)
        row.addWidget(self.remove_project)
        root.addLayout(row)
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr('作品名称'))
        root.addWidget(self.name)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr('固定译名'), tr('类型（可选）'), tr('识别线索（可选）')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setWordWrap(False)
        root.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.add_term = QPushButton(tr('添加词条'))
        self.add_term.clicked.connect(lambda: self.table.insertRow(self.table.rowCount()))
        self.remove_term = QPushButton(tr('删除选中词条'))
        self.remove_term.clicked.connect(self._remove_terms)
        row.addWidget(self.add_term)
        row.addWidget(self.remove_term)
        row.addStretch(1)
        root.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.project.currentIndexChanged.connect(self._switch_project)
        self.project.setCurrentIndex(max(0, self.project.findData(config.get('terminology_project', ''))))
        self._switch_project()

    def _store(self):
        if self._current not in self.projects:
            return
        def text(row, col):
            item = self.table.item(row, col)
            return item.text().strip() if item else ''
        previous = self.projects[self._current]['name']
        self.projects[self._current] = dict(name=self.name.text().strip() or previous, terms=[
            dict(term=text(row, 0), kind=text(row, 1), note=text(row, 2))
            for row in range(self.table.rowCount()) if text(row, 0)])
        index = self.project.findData(self._current)
        self.project.setItemText(index, self.projects[self._current]['name'])

    def _switch_project(self):
        self._store()
        self._current = self.project.currentData() or ''
        data = self.projects.get(self._current, {})
        self.name.setText(data.get('name', ''))
        self.table.setRowCount(0)
        for entry in data.get('terms', []):
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, key in enumerate(('term', 'kind', 'note')):
                self.table.setItem(row, col, QTableWidgetItem(entry[key]))
        for widget in (self.name, self.table, self.add_term, self.remove_term, self.remove_project):
            widget.setEnabled(bool(self._current))

    def _new_project(self):
        name, ok = QInputDialog.getText(self, tr('新建作品'), tr('作品名称'))
        if not ok or not name.strip():
            return
        identity = uuid.uuid4().hex
        self.projects[identity] = dict(name=name.strip(), terms=[])
        self.project.addItem(name.strip(), identity)
        self.project.setCurrentIndex(self.project.count() - 1)

    def _remove_project(self):
        if not self._current:
            return
        if QMessageBox.question(self, tr('删除作品'), tr('删除此作品的术语库？'),
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.projects.pop(self._current, None)
        self.project.removeItem(self.project.currentIndex())

    def _remove_terms(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def accept(self):
        # A save click can arrive before the active cell editor loses focus.
        editor = self.table.indexWidget(self.table.currentIndex())
        if editor is not None:
            self.table.commitData(editor)
        super().accept()

    def values(self):
        self._store()
        return dict(terminology_projects=terminology_projects(self.projects),
                    terminology_project=self.project.currentData() or '')


class TrialDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('试译'))
        root = QVBoxLayout(self)
        hint = QLabel(tr('试译当前队列开头的 1–3 页，PDF 按页面计数。试译结果单独保存，使用独立上下文，不占用正式任务的断点。'))
        hint.setWordWrap(True)
        hint.setMinimumWidth(320)
        root.addWidget(hint)
        form = QFormLayout()
        self.pages = QSpinBox()
        self.pages.setRange(1, 3)
        self.pages.setValue(3)
        form.addRow(tr('试译页数'), self.pages)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(tr('开始试译'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class UsageDialog(QDialog):
    def __init__(self, report, pricing, parent=None):
        super().__init__(parent)
        self.report = report
        self.action = ''
        self.setWindowTitle(tr('试译报告') if report.get('trial') else tr('翻译消耗'))
        self.resize(540, 460)
        root = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.enabled = QCheckBox(tr('填写单价以估算费用'))
        self.enabled.setChecked(bool(pricing.get('enabled')))
        root.addWidget(self.enabled)
        form = QFormLayout()
        self.input_price, self.output_price = QDoubleSpinBox(), QDoubleSpinBox()
        for spin, key, label in ((self.input_price, 'input', tr('输入 / 百万 token')),
                                 (self.output_price, 'output', tr('输出 / 百万 token'))):
            spin.setRange(0, 1_000_000)
            spin.setDecimals(6)
            spin.setValue(float(pricing.get(key) or 0))
            spin.valueChanged.connect(self._refresh)
            form.addRow(label, spin)
        self.currency = QComboBox()
        self.currency.addItems(['USD', 'CNY', 'JPY', 'EUR'])
        self.currency.setCurrentText(pricing.get('currency') or 'USD')
        self.currency.currentTextChanged.connect(self._refresh)
        form.addRow(tr('币种'), self.currency)
        root.addLayout(form)
        self.estimate = QLabel()
        self.estimate.setWordWrap(True)
        root.addWidget(self.estimate)
        note = QLabel(tr('仅统计翻译 API 返回的用量，包含重试响应，不含字体探测。费用按填写单价估算，缓存折扣等以服务商账单为准。整本预估基于样页平均值，受页面密度、上下文长度和并行度影响。'))
        note.setWordWrap(True)
        note.setProperty('muted', True)
        root.addWidget(note)
        root.addStretch(1)
        actions = QHBoxLayout()
        if report.get('trial') and report.get('outputs'):
            inspect = QPushButton(tr('精修试译'))
            inspect.clicked.connect(lambda: self._finish('edit'))
            actions.addWidget(inspect)
        if report.get('trial') and not report.get('cancelled') and not report.get('failed'):
            full = QPushButton(tr('翻译整本'))
            full.clicked.connect(lambda: self._finish('full'))
            actions.addWidget(full)
        actions.addStretch(1)
        close = QPushButton(tr('保存并关闭'))
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        root.addLayout(actions)
        self.enabled.toggled.connect(self._refresh)
        self._refresh()

    def pricing(self):
        return dict(enabled=self.enabled.isChecked(), input=self.input_price.value(),
                    output=self.output_price.value(), currency=self.currency.currentText())

    def _finish(self, action):
        self.action = action
        self.accept()

    def _refresh(self):
        for widget in (self.input_price, self.output_price, self.currency):
            widget.setEnabled(self.enabled.isChecked())
        report, usage = self.report, self.report.get('usage', {})
        text = tr('模型：{_0}\n完成 {_1} / {_2} 页 · 用时 {_3} 秒\n翻译响应 {_4} 次 · 已报告用量 {_5} 次\n输入 {_6} token · 输出 {_7} token',
                  _0=report.get('model', ''), _1=report.get('completed_pages', 0),
                  _2=report.get('planned_pages', 0), _3=round(report.get('elapsed_seconds', 0), 1),
                  _4=usage.get('requests', 0), _5=usage.get('reported', 0),
                  _6=usage.get('prompt_tokens', 0), _7=usage.get('completion_tokens', 0))
        if report.get('cancelled') or report.get('failed'):
            text += '\n' + tr('任务已停止或有失败页面，不生成整本预估。')
        if not report.get('total_pages_known', True):
            text += '\n' + tr('部分文件无法读取，整本页数未知。')
        if usage.get('reported', 0) < usage.get('requests', 0):
            text += '\n' + tr('部分响应未提供用量；以上 token 为已知部分，费用未知。')
        self.summary.setText(text)
        pricing = self.pricing()
        cost = usage_cost(usage, pricing)
        cost_text = tr('费用未知') if cost is None else f"{cost:.6f} {pricing['currency']}"
        lines = [tr('本次估算费用：{_0}', _0=cost_text)]
        if report.get('trial'):
            projection = trial_projection(report, pricing)
            if projection:
                total_cost = tr('费用未知') if projection['cost'] is None else f"{projection['cost']:.6f} {pricing['currency']}"
                lines.append(tr('队列共 {_0} 页 · 粗估全量 {_1} 分钟 · {_2}',
                                _0=report['total_pages'], _1=round(projection['seconds'] / 60, 1), _2=total_cost))
        self.estimate.setText('\n'.join(lines))
