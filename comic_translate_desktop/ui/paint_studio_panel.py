"""Painting, selection, view transform, and filter studio panel."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from comic_translate_core.paint_engine import (
    BrushSettings,
    BrushTool,
    available_brush_shapes,
    available_paper_textures,
    load_custom_textures,
)
from ..config import ICON_PATH
from ..i18n import tr
from .paint_color_wheel import PaintColorWheel
from .theme import theme_changed, theme_name, ui_font
from .tool_flow import ToolFlowLayout


SIZE_PRESETS = (2, 4, 8, 14, 22, 36, 56, 90, 150)

SHAPE_LABELS = {
    'round': '圆形',
    'flat': '扁头',
    'bristle': '毛刷',
    'scatter': '散点',
}

TEXTURE_LABELS = {
    'none': '无纸纹',
    'paper_fine': '细纸纹',
    'paper_rough': '粗纸纹',
    'tone_dot': '网点',
    'tone_line': '斜线',
}


def _paint_tool_icon(icon_name: str) -> QIcon:
    """Build a dual-state QIcon whose On state inverts stroke contrast for checked @ink buttons."""
    icons_root = ICON_PATH.parent / 'ui' / 'icons'
    light_svg = str(icons_root / f'{icon_name}.svg')
    dark_svg = str(icons_root / 'dark' / f'{icon_name}.svg')
    off_path, on_path = (dark_svg, light_svg) if theme_name() == 'dark' else (light_svg, dark_svg)
    icon = QIcon()
    icon.addFile(off_path, QSize(16, 16), QIcon.Normal, QIcon.Off)
    icon.addFile(on_path, QSize(16, 16), QIcon.Normal, QIcon.On)
    return icon


class PaintStudioPanel(QWidget):
    """Full icon-based tool, parameter, selection, color, view, and filter studio."""

    tool_changed = Signal(str)
    settings_changed = Signal(object)
    selection_action = Signal(str)
    view_changed = Signal(float, bool, bool)
    filter_requested = Signal(str)
    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('paintStudioPanel')
        self._settings = BrushSettings()
        self._tool_buttons: dict[str, QPushButton] = {}
        self._tool_icons: dict[str, str] = {}
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._size_buttons: dict[int, QPushButton] = {}
        self._syncing = False
        self._build_ui()
        theme_changed.changed.connect(self._refresh_tool_icons)
        self.select_tool(BrushTool.PEN)

    def _card(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName('inspectorCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        heading = QLabel(tr(title))
        heading.setObjectName('cardTitle')
        layout.addWidget(heading)
        return card, layout

    def _make_icon_grid(self, specs: tuple[tuple[str, str, str, str], ...], cols: int = 6) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        for idx, (tool_id, icon_name, label, tip) in enumerate(specs):
            btn = self._make_tool_btn(tool_id, icon_name, label, tip)
            grid.addWidget(btn, idx // cols, idx % cols)
        grid.setColumnStretch(cols, 1)
        return grid

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 4, 6)
        root.setSpacing(8)

        # 1. Toolbox card (icon-only tool grids)
        tool_card, tool_layout = self._card('工具箱')

        paint_lbl = QLabel(tr('画笔与修补'))
        paint_lbl.setProperty('muted', True)
        paint_lbl.setFont(ui_font(11))
        tool_layout.addWidget(paint_lbl)
        tool_layout.addLayout(self._make_icon_grid((
            (BrushTool.PENCIL, 'paint-pencil', '铅笔', '铅笔 · P'),
            (BrushTool.PEN, 'paint-pen', '钢笔', '钢笔 · B'),
            (BrushTool.AIRBRUSH, 'paint-airbrush', '喷枪', '喷枪 · A'),
            (BrushTool.WATERCOLOR, 'paint-watercolor', '水彩', '水彩 · W'),
            (BrushTool.BRUSH, 'paint-brush', '画笔', '画笔（混色厚涂）'),
            (BrushTool.MARKER, 'paint-marker', '马克笔', '马克笔（单笔不叠深）'),
            (BrushTool.BINARY, 'paint-binary', '二值笔', '二值笔（硬边像素笔）'),
            (BrushTool.BLUR, 'paint-blur', '模糊', '局部模糊笔'),
            (BrushTool.SMUDGE, 'paint-smudge', '涂抹', '涂抹（指尖混色）'),
            (BrushTool.ERASER, 'paint-eraser', '橡皮', '橡皮擦 · E'),
            (BrushTool.CLONE, 'paint-clone', '图章', '仿制图章（Alt+点击取样点）· S'),
            (BrushTool.EYEDROPPER, 'paint-eyedropper', '吸管', '吸管取色 · I'),
        )))

        sel_lbl = QLabel(tr('选区与填充'))
        sel_lbl.setProperty('muted', True)
        sel_lbl.setFont(ui_font(11))
        tool_layout.addWidget(sel_lbl)
        tool_layout.addLayout(self._make_icon_grid((
            (BrushTool.RECT_SELECT, 'paint-rect-select', '框选', '矩形选区 · M'),
            (BrushTool.LASSO_SELECT, 'paint-lasso-select', '套索', '自由套索 · L'),
            (BrushTool.POLY_LASSO, 'paint-poly-lasso', '多边套索', '多边形套索（点击顶点，双击或回车闭合）'),
            (BrushTool.MAGIC_WAND, 'paint-magic-wand', '魔棒', '魔棒容差选区'),
            (BrushTool.SELECT_PEN, 'paint-select-pen', '选区笔', '选区笔（涂抹增加选区）· K'),
            (BrushTool.DESELECT_PEN, 'paint-deselect-pen', '选区擦', '选区擦（涂抹减去选区）'),
            (BrushTool.MOVE_SELECTION, 'paint-move-selection', '移选区', '移动选区内容'),
            (BrushTool.BUCKET, 'paint-bucket', '油漆桶', '油漆桶填充 · G'),
            (BrushTool.GRADIENT, 'paint-gradient', '渐变', '渐变填充'),
        )))

        shape_lbl = QLabel(tr('几何图形'))
        shape_lbl.setProperty('muted', True)
        shape_lbl.setFont(ui_font(11))
        tool_layout.addWidget(shape_lbl)
        tool_layout.addLayout(self._make_icon_grid((
            (BrushTool.LINE, 'paint-line', '直线', '直线工具'),
            (BrushTool.CURVE, 'paint-curve', '曲线', '二次贝塞尔曲线（拖动端点后点击定曲率）'),
            (BrushTool.RECT_SHAPE, 'paint-rect-shape', '矩形', '矩形工具'),
            (BrushTool.ELLIPSE_SHAPE, 'paint-ellipse-shape', '椭圆', '椭圆工具'),
        )))
        root.addWidget(tool_card)

        # 2. Brush & Tool Parameters card
        param_card, param_layout = self._card('笔刷与工具参数')

        preset_lbl = QLabel(tr('快速笔径 (px)'))
        preset_lbl.setProperty('muted', True)
        preset_lbl.setFont(ui_font(11))
        param_layout.addWidget(preset_lbl)
        preset_flow = ToolFlowLayout()
        preset_flow.setSpacing(4)
        for px in SIZE_PRESETS:
            btn = QPushButton(str(px))
            btn.setCheckable(True)
            btn.setProperty('compact', True)
            btn.setProperty('role', 'chip')
            btn.setProperty('paintPreset', True)
            btn.setFont(ui_font(11, mono=True))
            btn.clicked.connect(lambda _=False, v=px: self._set_size(v))
            preset_flow.addWidget(btn)
            self._size_buttons[px] = btn
        param_layout.addLayout(preset_flow)

        param_grid = QGridLayout()
        param_grid.setContentsMargins(0, 2, 0, 2)
        param_grid.setHorizontalSpacing(6)
        param_grid.setVerticalSpacing(5)
        self._size_slider, self._size_spin = self._slider_spin(1, 500, self._settings.size, ' px', self._on_param_changed)
        self._min_size_slider, self._min_size_spin = self._slider_spin(0, 100, round(self._settings.min_size_ratio * 100), ' %', self._on_param_changed)
        self._opacity_slider, self._opacity_spin = self._slider_spin(1, 100, round(self._settings.opacity * 100), ' %', self._on_param_changed)
        self._hardness_slider, self._hardness_spin = self._slider_spin(0, 100, round(self._settings.hardness * 100), ' %', self._on_param_changed)

        self._add_param_row(param_grid, 0, '笔径', self._size_slider, self._size_spin)
        self._add_param_row(param_grid, 1, '最小直径', self._min_size_slider, self._min_size_spin)
        self._add_param_row(param_grid, 2, '浓度', self._opacity_slider, self._opacity_spin)
        self._add_param_row(param_grid, 3, '边缘硬度', self._hardness_slider, self._hardness_spin)
        param_layout.addLayout(param_grid)

        stab_row = QHBoxLayout()
        stab_row.setSpacing(6)
        stab_lbl = QLabel(tr('手抖修正'))
        stab_lbl.setProperty('muted', True)
        stab_row.addWidget(stab_lbl)
        self._stabilizer_combo = QComboBox()
        for lv in range(16):
            self._stabilizer_combo.addItem(str(lv), lv)
        for s_idx in range(1, 8):
            self._stabilizer_combo.addItem(f'S-{s_idx}', 15 + s_idx)
        self._stabilizer_combo.setCurrentIndex(self._settings.stabilizer)
        self._stabilizer_combo.currentIndexChanged.connect(self._on_param_changed)
        stab_row.addWidget(self._stabilizer_combo, 1)

        sym_lbl = QLabel(tr('对称'))
        sym_lbl.setProperty('muted', True)
        stab_row.addWidget(sym_lbl)
        self._symmetry_combo = QComboBox()
        for label, value in (('关闭', 'none'), ('水平对称', 'horizontal'), ('垂直对称', 'vertical')):
            self._symmetry_combo.addItem(tr(label), value)
        self._symmetry_combo.currentIndexChanged.connect(self._on_param_changed)
        stab_row.addWidget(self._symmetry_combo, 1)
        param_layout.addLayout(stab_row)

        self._mix_container = QWidget()
        mix_grid = QGridLayout(self._mix_container)
        mix_grid.setContentsMargins(0, 0, 0, 0)
        mix_grid.setHorizontalSpacing(6)
        mix_grid.setVerticalSpacing(4)
        self._blend_slider, self._blend_spin = self._slider_spin(0, 100, round(self._settings.blending * 100), ' %', self._on_param_changed)
        self._dilution_slider, self._dilution_spin = self._slider_spin(0, 100, round(self._settings.dilution * 100), ' %', self._on_param_changed)
        self._persist_slider, self._persist_spin = self._slider_spin(0, 100, round(self._settings.persistence * 100), ' %', self._on_param_changed)
        self._add_param_row(mix_grid, 0, '混色', self._blend_slider, self._blend_spin)
        self._add_param_row(mix_grid, 1, '水分量', self._dilution_slider, self._dilution_spin)
        self._add_param_row(mix_grid, 2, '色延伸', self._persist_slider, self._persist_spin)
        param_layout.addWidget(self._mix_container)

        self._eraser_container = QWidget()
        eraser_row = QHBoxLayout(self._eraser_container)
        eraser_row.setContentsMargins(0, 0, 0, 0)
        eraser_row.setSpacing(6)
        eraser_lbl = QLabel(tr('擦除目标'))
        eraser_lbl.setProperty('muted', True)
        eraser_row.addWidget(eraser_lbl)
        self._eraser_mode_combo = QComboBox()
        self._eraser_mode_combo.addItem(tr('涂抹背景色'), 'color')
        self._eraser_mode_combo.addItem(tr('还原处理前原图'), 'original')
        self._eraser_mode_combo.currentIndexChanged.connect(self._on_param_changed)
        eraser_row.addWidget(self._eraser_mode_combo, 1)
        param_layout.addWidget(self._eraser_container)

        self._fill_container = QWidget()
        fill_grid = QGridLayout(self._fill_container)
        fill_grid.setContentsMargins(0, 0, 0, 0)
        fill_grid.setHorizontalSpacing(6)
        fill_grid.setVerticalSpacing(4)
        self._tol_slider, self._tol_spin = self._slider_spin(0, 255, self._settings.tolerance, '', self._on_param_changed)
        self._gap_slider, self._gap_spin = self._slider_spin(0, 5, self._settings.gap_close, ' px', self._on_param_changed)
        self._expand_slider, self._expand_spin = self._slider_spin(0, 5, self._settings.fill_expand, ' px', self._on_param_changed)
        self._add_param_row(fill_grid, 0, '色差容差', self._tol_slider, self._tol_spin)
        self._add_param_row(fill_grid, 1, '闭合间隙', self._gap_slider, self._gap_spin)
        self._add_param_row(fill_grid, 2, '填充扩边', self._expand_slider, self._expand_spin)
        self._contiguous_chk = QCheckBox(tr('仅连续区域'))
        self._contiguous_chk.setChecked(self._settings.contiguous)
        self._contiguous_chk.toggled.connect(self._on_param_changed)
        fill_grid.addWidget(self._contiguous_chk, 3, 0, 1, 3)
        param_layout.addWidget(self._fill_container)

        self._gradient_container = QWidget()
        grad_row = QHBoxLayout(self._gradient_container)
        grad_row.setContentsMargins(0, 0, 0, 0)
        grad_row.setSpacing(6)
        self._grad_shape_combo = QComboBox()
        self._grad_shape_combo.addItem(tr('线性渐变'), 'linear')
        self._grad_shape_combo.addItem(tr('径向渐变'), 'radial')
        self._grad_shape_combo.currentIndexChanged.connect(self._on_param_changed)
        grad_row.addWidget(self._grad_shape_combo, 1)
        self._grad_mode_combo = QComboBox()
        self._grad_mode_combo.addItem(tr('前景色→背景色'), 'fg_bg')
        self._grad_mode_combo.addItem(tr('前景色→透明'), 'fg_transparent')
        self._grad_mode_combo.currentIndexChanged.connect(self._on_param_changed)
        grad_row.addWidget(self._grad_mode_combo, 1)
        param_layout.addWidget(self._gradient_container)

        self._shape_container = QWidget()
        shape_opt_row = QHBoxLayout(self._shape_container)
        shape_opt_row.setContentsMargins(0, 0, 0, 0)
        self._shape_filled_chk = QCheckBox(tr('实心填充图形'))
        self._shape_filled_chk.setChecked(self._settings.shape_filled)
        self._shape_filled_chk.toggled.connect(self._on_param_changed)
        shape_opt_row.addWidget(self._shape_filled_chk)
        param_layout.addWidget(self._shape_container)

        self._select_mode_container = QWidget()
        sel_mode_row = QHBoxLayout(self._select_mode_container)
        sel_mode_row.setContentsMargins(0, 0, 0, 0)
        sel_mode_row.setSpacing(6)
        sel_mode_lbl = QLabel(tr('选区运算'))
        sel_mode_lbl.setProperty('muted', True)
        sel_mode_row.addWidget(sel_mode_lbl)
        self._select_mode_combo = QComboBox()
        for label, value in (('替换选区', 'replace'), ('追加选区', 'add'), ('减去选区', 'subtract'), ('交叉选区', 'intersect')):
            self._select_mode_combo.addItem(tr(label), value)
        self._select_mode_combo.currentIndexChanged.connect(self._on_param_changed)
        sel_mode_row.addWidget(self._select_mode_combo, 1)
        param_layout.addWidget(self._select_mode_container)

        tex_grid = QGridLayout()
        tex_grid.setContentsMargins(0, 2, 0, 0)
        tex_grid.setHorizontalSpacing(6)
        tex_grid.setVerticalSpacing(4)
        self._shape_combo = QComboBox()
        self._shape_combo.currentIndexChanged.connect(self._on_param_changed)
        self._texture_combo = QComboBox()
        self._texture_combo.currentIndexChanged.connect(self._on_param_changed)
        self._tex_strength_slider, self._tex_strength_spin = self._slider_spin(0, 100, round(self._settings.texture_strength * 100), ' %', self._on_param_changed)
        tex_grid.addWidget(QLabel(tr('笔头形状')), 0, 0)
        tex_grid.addWidget(self._shape_combo, 0, 1, 1, 2)
        tex_grid.addWidget(QLabel(tr('纸纹纹理')), 1, 0)
        tex_grid.addWidget(self._texture_combo, 1, 1, 1, 2)
        self._add_param_row(tex_grid, 2, '纹理浓度', self._tex_strength_slider, self._tex_strength_spin)
        param_layout.addLayout(tex_grid)
        self.refresh_texture_lists()

        flags_flow = ToolFlowLayout()
        flags_flow.setSpacing(6)
        self._pressure_size_chk = QCheckBox(tr('笔径压感'))
        self._pressure_size_chk.setChecked(self._settings.pressure_size)
        self._pressure_size_chk.toggled.connect(self._on_param_changed)
        self._pressure_opacity_chk = QCheckBox(tr('浓度压感'))
        self._pressure_opacity_chk.setChecked(self._settings.pressure_opacity)
        self._pressure_opacity_chk.toggled.connect(self._on_param_changed)
        self._antialias_chk = QCheckBox(tr('抗锯齿'))
        self._antialias_chk.setChecked(self._settings.antialias)
        self._antialias_chk.toggled.connect(self._on_param_changed)
        self._right_pick_chk = QCheckBox(tr('右键吸管'))
        self._right_pick_chk.setChecked(True)
        self._right_pick_chk.toggled.connect(self._on_param_changed)
        self._import_tex_btn = QPushButton(tr('导入笔刷贴图目录'))
        self._import_tex_btn.setProperty('compact', True)
        self._import_tex_btn.setProperty('role', 'chip')
        self._import_tex_btn.setToolTip(tr('从本地文件夹导入灰度 .bmp / .png 笔刷形状与纸纹'))
        self._import_tex_btn.clicked.connect(self._import_custom_textures)
        for widget in (self._pressure_size_chk, self._pressure_opacity_chk, self._antialias_chk,
                       self._right_pick_chk, self._import_tex_btn):
            flags_flow.addWidget(widget)
        param_layout.addLayout(flags_flow)
        root.addWidget(param_card)

        # 3. Selection actions card
        sel_card, sel_act_layout = self._card('选区操作')
        sel_btn_flow = ToolFlowLayout()
        sel_btn_flow.setSpacing(4)
        self._sel_all_btn = self._action_btn('全选', 'select_all', 'Ctrl+A')
        self._sel_invert_btn = self._action_btn('反选', 'invert', 'Ctrl+Shift+I')
        self._sel_clear_btn = self._action_btn('取消选区', 'clear', 'Ctrl+D')
        self._sel_expand_btn = self._action_btn('扩张', 'expand', '选区向外扩张 2px')
        self._sel_contract_btn = self._action_btn('收缩', 'contract', '选区向内收缩 2px')
        self._sel_feather_btn = self._action_btn('羽化', 'feather', '羽化选区边缘 3px')
        self._sel_fill_btn = self._action_btn('填充前景色', 'fill', '用前景色填充当前选区')
        self._sel_ai_btn = self._action_btn('AI修补选区', 'ai_repair', '使用 LaMa AI 修补当前选区')
        for btn in (self._sel_all_btn, self._sel_invert_btn, self._sel_clear_btn,
                    self._sel_expand_btn, self._sel_contract_btn, self._sel_feather_btn,
                    self._sel_fill_btn, self._sel_ai_btn):
            sel_btn_flow.addWidget(btn)
        sel_act_layout.addLayout(sel_btn_flow)
        root.addWidget(sel_card)
        self.set_selection_active(False)

        # 4. Color wheel card
        color_card, color_layout = self._card('色彩选择器')
        self.color_wheel = PaintColorWheel()
        self.color_wheel.color_changed.connect(self._on_fg_color_changed)
        self.color_wheel.bg_color_changed.connect(self._on_bg_color_changed)
        color_layout.addWidget(self.color_wheel)
        root.addWidget(color_card)

        # 5. Canvas view transform card
        view_card, view_layout = self._card('画布视图')
        rot_row = QHBoxLayout()
        rot_row.setSpacing(6)
        rot_lbl = QLabel(tr('旋转'))
        rot_lbl.setProperty('muted', True)
        rot_row.addWidget(rot_lbl)
        self._rot_slider = QSlider(Qt.Horizontal)
        self._rot_slider.setRange(-180, 180)
        self._rot_slider.setValue(0)
        self._rot_slider.valueChanged.connect(self._on_view_changed)
        rot_row.addWidget(self._rot_slider, 1)
        self._rot_val = QLabel('0°')
        self._rot_val.setFont(ui_font(11, mono=True))
        self._rot_val.setFixedWidth(36)
        self._rot_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        rot_row.addWidget(self._rot_val)
        view_layout.addLayout(rot_row)

        view_flow = ToolFlowLayout()
        view_flow.setSpacing(4)
        rot_left = QPushButton('-15°')
        rot_left.setProperty('compact', True)
        rot_left.setProperty('role', 'chip')
        rot_left.clicked.connect(lambda: self._step_rotation(-15))
        rot_right = QPushButton('+15°')
        rot_right.setProperty('compact', True)
        rot_right.setProperty('role', 'chip')
        rot_right.clicked.connect(lambda: self._step_rotation(15))
        rot_reset = QPushButton(tr('重置角度'))
        rot_reset.setProperty('compact', True)
        rot_reset.setProperty('role', 'chip')
        rot_reset.clicked.connect(self.reset_view)
        self._flip_h_btn = QPushButton(tr('水平翻转'))
        self._flip_h_btn.setCheckable(True)
        self._flip_h_btn.setProperty('compact', True)
        self._flip_h_btn.setProperty('role', 'chip')
        self._flip_h_btn.setToolTip(tr('镜像显示画布以便检查对称性 · H'))
        self._flip_h_btn.toggled.connect(self._on_view_changed)
        self._grid_btn = QPushButton(tr('辅助网格'))
        self._grid_btn.setCheckable(True)
        self._grid_btn.setProperty('compact', True)
        self._grid_btn.setProperty('role', 'chip')
        self._grid_btn.toggled.connect(self._on_view_changed)
        for btn in (rot_left, rot_right, rot_reset, self._flip_h_btn, self._grid_btn):
            view_flow.addWidget(btn)
        view_layout.addLayout(view_flow)
        root.addWidget(view_card)

        # 6. Filters & Color Adjustments card
        filter_card, filter_layout = self._card('滤镜与调色')
        filter_flow = ToolFlowLayout()
        filter_flow.setSpacing(4)
        for key, label in (
            ('hsl', '色相/饱和度'),
            ('bc', '亮度/对比度'),
            ('levels', '色阶'),
            ('blur', '高斯模糊'),
            ('sharpen', '锐化'),
            ('luma_white', '白底提纯'),
            ('invert', '反相'),
            ('desaturate', '去色'),
        ):
            btn = QPushButton(tr(label))
            btn.setProperty('compact', True)
            btn.setProperty('role', 'chip')
            btn.clicked.connect(lambda _=False, k=key: self.filter_requested.emit(k))
            filter_flow.addWidget(btn)
        filter_layout.addLayout(filter_flow)
        root.addWidget(filter_card)
        root.addStretch(1)

    def _make_tool_btn(self, tool_id: str, icon_name: str, label: str, tip: str) -> QPushButton:
        btn = QPushButton()
        btn.setText('')
        btn.setFixedSize(34, 30)
        btn.setIconSize(QSize(16, 16))
        btn.setIcon(_paint_tool_icon(icon_name))
        btn.setCheckable(True)
        btn.setProperty('compact', True)
        btn.setProperty('role', 'chip')
        btn.setProperty('paintTool', True)
        btn.setAccessibleName(tr(label))
        btn.setToolTip(tr(tip))
        btn.clicked.connect(lambda _=False, tid=tool_id: self.select_tool(tid))
        self._tool_group.addButton(btn)
        self._tool_buttons[tool_id] = btn
        self._tool_icons[tool_id] = icon_name
        return btn

    def _refresh_tool_icons(self, *_args):
        for tool_id, icon_name in self._tool_icons.items():
            btn = self._tool_buttons.get(tool_id)
            if btn is not None:
                btn.setIcon(_paint_tool_icon(icon_name))

    def _action_btn(self, label: str, action: str, tip: str) -> QPushButton:
        btn = QPushButton(tr(label))
        btn.setProperty('compact', True)
        btn.setProperty('role', 'chip')
        btn.setToolTip(tr(tip))
        btn.clicked.connect(lambda _=False, a=action: self.selection_action.emit(a))
        return btn

    def _slider_spin(self, minimum: int, maximum: int, value: int, suffix: str, callback):
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        if suffix:
            spin.setSuffix(suffix)
        spin.setFixedWidth(84)

        def _from_slider(val):
            if self._syncing:
                return
            self._syncing = True
            spin.setValue(val)
            self._syncing = False
            callback()

        def _from_spin(val):
            if self._syncing:
                return
            self._syncing = True
            slider.setValue(val)
            self._syncing = False
            callback()

        slider.valueChanged.connect(_from_slider)
        spin.valueChanged.connect(_from_spin)
        return slider, spin

    def _add_param_row(self, grid: QGridLayout, row: int, label: str, slider: QSlider, spin: QSpinBox):
        lbl = QLabel(tr(label))
        lbl.setProperty('muted', True)
        lbl.setFont(ui_font(11))
        grid.addWidget(lbl, row, 0)
        grid.addWidget(slider, row, 1)
        grid.addWidget(spin, row, 2)

    def current_tool(self) -> str:
        return self._settings.tool

    def select_tool(self, tool_id: str) -> None:
        if tool_id not in self._tool_buttons:
            return
        self._settings.tool = tool_id
        btn = self._tool_buttons[tool_id]
        if not btn.isChecked():
            btn.setChecked(True)
        self._update_context_rows()
        self.tool_changed.emit(tool_id)
        self.settings_changed.emit(self.settings())

    def _update_context_rows(self):
        t = self._settings.tool
        self._mix_container.setVisible(t in (BrushTool.WATERCOLOR, BrushTool.BRUSH, BrushTool.SMUDGE, BrushTool.BLUR))
        self._eraser_container.setVisible(t == BrushTool.ERASER)
        self._fill_container.setVisible(t in (BrushTool.MAGIC_WAND, BrushTool.BUCKET))
        self._gradient_container.setVisible(t == BrushTool.GRADIENT)
        self._shape_container.setVisible(t in (BrushTool.RECT_SHAPE, BrushTool.ELLIPSE_SHAPE))
        self._select_mode_container.setVisible(t in (
            BrushTool.RECT_SELECT, BrushTool.LASSO_SELECT, BrushTool.POLY_LASSO, BrushTool.MAGIC_WAND,
        ))
        self._sync_preset_buttons()

    def _set_size(self, px: int):
        px = max(1, min(500, int(px)))
        self._syncing = True
        self._size_spin.setValue(px)
        self._size_slider.setValue(px)
        self._syncing = False
        self._on_param_changed()

    def step_size(self, direction: int) -> int:
        cur = self._size_spin.value()
        if direction < 0:
            step = 1 if cur <= 10 else 2 if cur <= 30 else 5 if cur <= 80 else 15
            nxt = max(1, cur - step)
        else:
            step = 1 if cur < 10 else 2 if cur < 30 else 5 if cur < 80 else 15
            nxt = min(500, cur + step)
        self._set_size(nxt)
        return nxt

    def _sync_preset_buttons(self):
        cur = self._size_spin.value()
        for px, btn in self._size_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(cur == px)
            btn.blockSignals(False)

    def _on_fg_color_changed(self, qcolor: QColor):
        self._settings.color = (qcolor.red(), qcolor.green(), qcolor.blue())
        self.settings_changed.emit(self.settings())

    def _on_bg_color_changed(self, qcolor: QColor):
        self._settings.bg_color = (qcolor.red(), qcolor.green(), qcolor.blue())
        self.settings_changed.emit(self.settings())

    def set_fg_color(self, qcolor: QColor, *, emit: bool = False) -> None:
        self.color_wheel.set_fg_color(qcolor, emit=emit)
        c = self.color_wheel.fg_color()
        self._settings.color = (c.red(), c.green(), c.blue())
        if emit:
            self.settings_changed.emit(self.settings())

    def set_bg_color(self, qcolor: QColor, *, emit: bool = False) -> None:
        self.color_wheel.set_bg_color(qcolor, emit=emit)
        c = self.color_wheel.bg_color()
        self._settings.bg_color = (c.red(), c.green(), c.blue())
        if emit:
            self.settings_changed.emit(self.settings())

    def swap_colors(self) -> None:
        self.color_wheel.swap_colors()
        fg = self.color_wheel.fg_color()
        bg = self.color_wheel.bg_color()
        self._settings.color = (fg.red(), fg.green(), fg.blue())
        self._settings.bg_color = (bg.red(), bg.green(), bg.blue())
        self.settings_changed.emit(self.settings())

    def reset_colors(self) -> None:
        self.color_wheel.reset_colors()
        self._settings.color = (0, 0, 0)
        self._settings.bg_color = (255, 255, 255)
        self.settings_changed.emit(self.settings())

    def right_click_eyedropper_enabled(self) -> bool:
        return self._right_pick_chk.isChecked()

    def _on_param_changed(self):
        if self._syncing:
            return
        self._settings.size = self._size_spin.value()
        self._settings.min_size_ratio = self._min_size_spin.value() / 100.0
        self._settings.opacity = self._opacity_spin.value() / 100.0
        self._settings.hardness = self._hardness_spin.value() / 100.0
        self._settings.stabilizer = int(self._stabilizer_combo.currentData() or 0)
        self._settings.symmetry = str(self._symmetry_combo.currentData() or 'none')
        self._settings.blending = self._blend_spin.value() / 100.0
        self._settings.dilution = self._dilution_spin.value() / 100.0
        self._settings.persistence = self._persist_spin.value() / 100.0
        self._settings.eraser_mode = str(self._eraser_mode_combo.currentData() or 'color')
        self._settings.tolerance = self._tol_spin.value()
        self._settings.gap_close = self._gap_spin.value()
        self._settings.fill_expand = self._expand_spin.value()
        self._settings.contiguous = self._contiguous_chk.isChecked()
        self._settings.gradient_shape = str(self._grad_shape_combo.currentData() or 'linear')
        self._settings.gradient_mode = str(self._grad_mode_combo.currentData() or 'fg_bg')
        self._settings.shape_filled = self._shape_filled_chk.isChecked()
        self._settings.select_mode = str(self._select_mode_combo.currentData() or 'replace')
        self._settings.shape_name = str(self._shape_combo.currentData() or 'round')
        self._settings.texture_name = str(self._texture_combo.currentData() or 'none')
        self._settings.texture_strength = self._tex_strength_spin.value() / 100.0
        self._settings.pressure_size = self._pressure_size_chk.isChecked()
        self._settings.pressure_opacity = self._pressure_opacity_chk.isChecked()
        self._settings.antialias = self._antialias_chk.isChecked()
        self._sync_preset_buttons()
        self.settings_changed.emit(self.settings())

    def settings(self) -> BrushSettings:
        return BrushSettings(**self._settings.__dict__)

    def set_selection_active(self, active: bool) -> None:
        has = bool(active)
        for btn in (self._sel_clear_btn, self._sel_expand_btn, self._sel_contract_btn,
                    self._sel_feather_btn, self._sel_fill_btn, self._sel_ai_btn):
            btn.setEnabled(has)

    def refresh_texture_lists(self) -> None:
        self._syncing = True
        try:
            cur_shape = self._shape_combo.currentData() or self._settings.shape_name
            cur_tex = self._texture_combo.currentData() or self._settings.texture_name
            self._shape_combo.clear()
            for key in available_brush_shapes():
                label = tr(SHAPE_LABELS[key]) if key in SHAPE_LABELS else key.removeprefix('custom:')
                self._shape_combo.addItem(label, key)
            idx = self._shape_combo.findData(cur_shape)
            self._shape_combo.setCurrentIndex(max(0, idx))

            self._texture_combo.clear()
            for key in available_paper_textures():
                label = tr(TEXTURE_LABELS[key]) if key in TEXTURE_LABELS else key.removeprefix('custom:')
                self._texture_combo.addItem(label, key)
            tidx = self._texture_combo.findData(cur_tex)
            self._texture_combo.setCurrentIndex(max(0, tidx))
        finally:
            self._syncing = False

    def _import_custom_textures(self):
        folder = QFileDialog.getExistingDirectory(self, tr('选择本地笔刷/纸纹目录'))
        if not folder:
            return
        try:
            res = load_custom_textures(folder)
            self.refresh_texture_lists()
            self.status_message.emit(
                tr('已导入 {_0} 个笔头形状、{_1} 个纸纹', _0=len(res['shapes']), _1=len(res['textures']))
            )
        except Exception as exc:
            self.status_message.emit(tr('导入贴图失败：{_0}', _0=exc))

    def rotation_deg(self) -> float:
        return float(self._rot_slider.value())

    def flipped_h(self) -> bool:
        return self._flip_h_btn.isChecked()

    def show_grid(self) -> bool:
        return self._grid_btn.isChecked()

    def _step_rotation(self, delta: int):
        val = self._rot_slider.value() + delta
        if val > 180:
            val -= 360
        elif val < -180:
            val += 360
        self._rot_slider.setValue(val)

    def reset_view(self):
        self._rot_slider.blockSignals(True)
        self._flip_h_btn.blockSignals(True)
        self._rot_slider.setValue(0)
        self._flip_h_btn.setChecked(False)
        self._rot_slider.blockSignals(False)
        self._flip_h_btn.blockSignals(False)
        self._on_view_changed()

    def toggle_flip_h(self):
        self._flip_h_btn.toggle()

    def _on_view_changed(self):
        deg = float(self._rot_slider.value())
        self._rot_val.setText(f'{round(deg)}°')
        self.view_changed.emit(deg, self._flip_h_btn.isChecked(), self._grid_btn.isChecked())
