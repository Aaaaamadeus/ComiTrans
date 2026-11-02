# ComiTrans 精修工具插件接口 v1

插件装在 ComiTrans 桌面端，在「嵌字精修」画布上工作。v1 定义两种操作：框选后执行一次工具，或画完一笔执行一次工具。例如，框选气泡可以涂白残字，沿线稿拖动可以补线。两种工具都只修改清理底图，译文仍可单独移动、改字和排版。

**当前进度**　[Python 接口类型](../comic_translate_desktop/retouch_api.py)可直接导入，下面的示例可独立调用。插件发现、画布派发、撤回和保存对接属于下一阶段的宿主实现。

## 安装与注册约定

每个插件占用 `PROJECT_ROOT/retouch_plugins/<id>/` 下的一个目录。源码运行时根目录是项目目录，打包后是 EXE 所在目录。目录包含清单 `plugin.json` 和入口 `plugin.py`。插件在桌面进程内运行，只加载受信任的本地 Python 代码。

```json
{"id": "manga_cleanup", "name": "漫画清稿", "api_version": 1}
```

宿主先读清单，再导入入口。插件 ID 与目录名一致，插件 ID、工具 ID、参数 key 均匹配 `[a-z][a-z0-9_]*`。宿主只接受整数版本 1。破坏既有调用约定的改动提升主版本，同版本新增的可选字段须有兼容默认值。

宿主对每个编辑器实例调用一次入口的 `create_tools() -> tuple[RetouchTool, ...]`，按返回顺序展示工具。注册阶段只创建描述和回调，模型可在首次执行时加载。同插件的工具 ID 唯一，同工具的参数 key 唯一。工具的稳定标识为 `插件ID.工具ID`，显示名可以更改。清单、入口或工具声明有误时，整组跳过并报告插件 ID 和原因，其余插件继续注册。

## 一次工具调用

| 边界 | v1 约定 |
| --- | --- |
| 工具声明 | `RetouchTool(id, label, input_kind, run, options)`。`IntOption` 声明整数默认值及闭区间，`ColorOption` 声明 `#rrggbb` 颜色。宿主据此生成控件，检查默认值和输入，提交时传入所有已声明参数的只读快照。 |
| 输入底图 | `ToolRequest.background` 是当前内存草稿的独立 Pillow RGB 图，包含已提交的修图笔画。插件可从选区周围取样。文字、水印和画布辅助线在宿主预览阶段叠加。 |
| 框选 | `input_kind="selection"` 对应 `Selection(box)`。用户框选并点击执行才调用工具。原图左上为原点，整数矩形 `(left, top, right, bottom)` 左闭右开、上闭下开，须非空且在页内。修图选区独立于译文的 `mask_box`。 |
| 笔画 | `input_kind="stroke"` 对应 `Stroke(points)`。宿主将缩放和滚动后的画布坐标转换成原图像素。只接受在页内起笔，后续采样限制在页内，松开时传入按时间排列的非空点列，单击只有一个点。拖动中宿主可画轨迹提示，Esc 丢弃本笔。 |
| 返回 | `run(request) -> PixelPatch \| None`。`PixelPatch(box, pixels)` 提供该区域最终的 RGB 像素，尺寸须等于 `(right-left, bottom-top)`。框选工具的补丁必须包含于选区内。笔画工具返回包围笔迹的矩形，其中笔迹外或半透明笔缘的像素由插件从底图取样、合成。返回后像素所有权交给宿主。`None` 表示没有修改。 |
| 取消与失败 | 长操作在各阶段调用 `request.check_cancelled()`，收到 `RetouchCancelled` 时退出。其他异常由宿主显示为本次操作失败，可重试。取消、失败和非法补丁都保留调用前的底图和撤回历史。 |

## 最小插件示例

下面是上述清单对应的完整 `plugin.py`。默认填白适合清除纯白气泡里的残字，颜色可从工具参数面板更改。

```python
from PIL import Image
from comic_translate_desktop.retouch_api import (
    ColorOption, PixelPatch, RetouchTool, Selection, ToolRequest,
)


def fill_selection(request: ToolRequest) -> PixelPatch:
    if not isinstance(request.gesture, Selection):
        raise ValueError("填色需要矩形选区")
    request.check_cancelled()
    box = request.gesture.box
    left, top, right, bottom = box
    color = request.options["color"]
    if not isinstance(color, str):
        raise ValueError("颜色应为 #rrggbb")
    pixels = Image.new("RGB", (right - left, bottom - top), color)
    return PixelPatch(box, pixels)


def create_tools() -> tuple[RetouchTool, ...]:
    return (
        RetouchTool(
            id="fill", label="选区填色", input_kind="selection", run=fill_selection,
            options=(ColorOption("color", "填充颜色", "#ffffff"),),
        ),
    )
```

同一插件可再返回一个 `input_kind="stroke"` 的工具，例如用 `IntOption("diameter", "笔径（像素）", 8, 1, 256)` 声明笔径，回调根据 `Stroke.points` 绘制并返回一笔的补丁。

## 编辑器对接与验收

1. **采集。** 在 `PageCanvas` 和 `ImagePreview` 转发选区或笔迹。切换工具、切页或画布丢失鼠标捕获时丢弃未完成的笔画。仅在配套底图和布局加载成功后启用工具，布局为空的页面也可修图。
2. **执行。** `EditorPage` 提交当前文字编辑，从 `_cleaned_image` 取副本。工具回调在工作线程执行，与现有背景修补共用忙碌状态，每页同时最多执行一个像素操作。运行中锁定保存、切页和关闭。宿主在主线程接收一次结果，检查任务仍有效、未取消且属于同一次页面加载。较慢的模型即使在取消后返回，也应丢弃结果。
3. **提交。** 宿主先校验补丁类型、坐标范围、RGB 模式和尺寸，再把像素贴入底图副本。借用现有背景修补的提交路径，将旧底图压入同一撤回栈、清理渲染缓存、标记草稿并重新排版。一次笔画或一次选区操作占一条撤回记录，`None` 不入栈。撤回恢复前一版底图并保留期间的文字修改。
4. **保存。** Ctrl+S 仍由 `EditorPage.save_image()` 和 `save_editor_files()` 联动写入输出图、清理底图和现有布局 JSON。保存成功才释放历史。预览或写盘失败时应保留草稿和撤回能力，允许重试。插件只返回像素，不需要输出目录和文件路径。

接入时用一页含译文的漫画混合执行「填色 → 原有背景修补 → 改译文 → 撤回两次」，逐像素比较底图并检查译文。另用空布局页验证笔画在不同缩放和滚动位置命中同一原图像素；覆盖拖动取消、越界补丁、后台取消后迟到的结果，以及保存失败重试和保存后重开。[现有精修行为](EDITOR_LIVE_PREVIEW.md)
