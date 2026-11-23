# 菜单布局合并与新功能适配交接

日期：2026-11-22。工作目录：`D:\ComiTrans`。

## 分支与交付状态

- 当前分支：`feat/ui-windows-installer`。
- 来源工作区：`C:\Users\OS\.gemini\antigravity\worktrees\ComiTrans\optimize_ui_menu_layout`。
- 实际来源分支：`feat/ui-menu-layout`，来源提交：`fa74a8464f67e44d6b345b50285ef4d55f846db7`。
- 合并前目标提交：`83c2e9c3687e5f0b9e6441227ee04d54c732ddcc`。
- 合并提交：`6d51704508b12a13e58591306dde64f537fb868a`。
- 合并、适配与验收进度：已完成；来源分支已合入，新功能入口适配完成，全部验收通过。

合并提交只包含来源分支的 UI 改动。此前安装器、发布修复、翻译工作流等未提交内容恢复到工作区，新功能与菜单的适配也保留在工作区；不要把整个工作区直接作为一个提交。

## 用户入口

| 功能 | 当前入口与行为 |
|---|---|
| 试译 | 自动处理页保留“试译”直达按钮；试译队列开头 1–3 页，PDF 按页计数 |
| 作品术语库 | “任务 → 作品术语库”；翻译偏好中保留管理入口。任务菜单显示当前作品摘要 |
| 消耗统计 | “任务 → 翻译消耗”；任务结束后可用，支持填写单价与样页预估 |
| 多选气泡 | 列表 Ctrl/Shift 多选，画布 Ctrl 点击、Shift 拖动框选；计数随选择更新 |
| 样式取样与应用 | 气泡右上角“⋯”或列表/画布右键菜单中的“取样式”“应用样式到所选气泡” |
| 连续样式刷 | 同一气泡菜单中的“样式刷”；点击或框选目标应用；Esc 或“退出样式刷”结束 |
| 样式撤销 | 气泡菜单中的“撤销样式”，逐次撤销本页最近的样式操作 |
| 视图与文件 | 视图、文件菜单统一收纳面板切换、长条、导出和关联原图等操作 |
| 填充与字体管理 | 保留来源分支的填充、字体管理菜单；常用编辑操作仍可直接到达 |

所有新增菜单保持单层，菜单内部不嵌套子菜单。样式刷开启时，“退出样式刷”复用原“还原此气泡”按钮的位置；还原命令仍可通过气泡菜单使用。

## 适配约束

1. 右键点击已选中的气泡保留多选组，只切换当前气泡；右键本身不会应用样式。原有画布平移、缩放、取色及背景框选保持独立。
2. 样式刷与背景框选、添加气泡、取色互斥；样式刷开启时不显示可拖动的气泡调整手柄，避免点击取样意外移动气泡。
3. 批量属性编辑只同步实际改动的样式字段。译文、原文、蒙版范围、位置、气泡尺寸不随样式刷复制；已还原原图的气泡受保护。
4. 撤销样式只恢复样式属性，不覆盖后续改过的译文；切页清除本页样式历史，内部样式剪贴板可跨页使用。
5. 新布局的快捷字号框与原字号框使用同一份值，多选时同样触发批量字号修改。
6. 术语库只要求固定译名；类型和识别线索可选。AI 在正常翻译请求中根据上下文匹配，无需用户填写原文，也不额外增加一次识别请求。
7. 试译使用独立结果目录、上下文和断点；完成后可精修试译结果或启动完整任务。失败、取消、页数未知时不生成整本预估。
8. 消耗以翻译接口返回的 token 用量为依据，计入返回无效内容后重试的响应；缺失用量显示未知。估算不含字体探测，缓存折扣等以服务商账单为准。
9. 断点指纹只纳入当前生效术语；修改单价或其他作品的术语不会重跑已付费页面。未启用术语库时兼容原有断点。

## 主要代码位置

| 文件 | 责任 |
|---|---|
| `comic_translate_desktop/ui/editor_page.py` | 单层气泡菜单、多选、样式刷与模式互斥、快捷字号同步 |
| `comic_translate_desktop/ui/main_window.py` | 任务菜单、术语摘要、试译入口与消耗报告 |
| `comic_translate_desktop/ui/preview.py`、`strip_preview.py` | 框选、多选叠加层、画布右键信号转发 |
| `comic_translate_desktop/ui/workflow_dialogs.py` | 作品术语、试译和消耗对话框 |
| `comic_translate_desktop/productivity.py` | 样式字段、术语提示词、用量与费用计算 |
| `comic_translate_desktop/desktop_translation.py`、`worker.py` | 翻译响应计量、试译分页与上下文隔离 |
| `comic_translate_desktop/config.py` | `usage_pricing`、`terminology_project`、`terminology_projects` 三个持久化字段；同文件仍含此前未提交的模型路径修复，提交时需分开选择 |
| `comic_translate_desktop/checkpoints.py` | 当前生效配置与断点兼容 |
| `assets/i18n/en.json`、`ja.json` | 新入口、提示和报告的翻译 |
| `tests/test_productivity_workflow.py`、`test_editor_ui_redesign.py` | 工作流、菜单、手势、窄窗布局与状态回归 |

## 启动与验证

从仓库根目录启动源码：

```powershell
.\.venv\Scripts\python.exe run.py
```

完整测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

NSIS 集成测试会写临时 HKCU 测试键，需要允许此权限的执行环境。它把服务 API 替换为测试 DLL，目录和快捷方式也隔离，不安装真实应用。

界面检查分别执行浅色与深色：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe scripts/review_ui.py --theme light --screen-size 1920 1080 --output build/menu-merge-ui/light --scratch tmp/menu-merge-review-light
.\.venv\Scripts\python.exe scripts/review_ui.py --theme dark --screen-size 1920 1080 --output build/menu-merge-ui/dark --scratch tmp/menu-merge-review-dark
```

`--screen-size` 指定审查脚本的虚拟桌面边界，避免无显示器环境把 1440/1024 的审查图缩成 820。检查报告须确认实际宽度包含 1440、1024、820，并确认字体白名单断言。

审查脚本在页面切换后等待 240 ms，再截取 180/190 ms 淡入动画结束后的稳定画面，避免把过渡中的空画布当成最终界面。

验收记录：

- 完整测试：524 项，1341.498 秒，`OK`，退出码 0。
- 桌面、编辑器布局、实时预览与大图回归：91 项通过；功能与菜单集成回归最终 12 项通过；主题、字体、语言及偏好回归 44 项通过。上述测试均包含在完整验收中，不相加作为独立覆盖数量。
- 浅色、深色各生成 73 张审查图，两份报告均为 `success: true`，实际宽度包含 1440、1024、820；另外检查了 820×480 紧凑界面。
- 两种主题分别检查画布、译文区和工具入口；中文、英文、日文另行检查任务菜单、气泡菜单、样式刷、术语、试译和消耗对话框。
- `QFontInfo(ui_font()).family()` 为白名单中的 `Source Han Sans SC`；本轮相关三个界面模块的静态 `tr(...)` 文案在英文、日文目录中均有对应项。
- 与本轮菜单及文档无关的 52 个原文件，和合并前备份逐字节一致；生成的漫画输出未移动或覆盖。

## 工作区与后续处理

- 合并前备份：`build/menu-merge-20261122-170016/`，含文件清单、原文件、补丁、来源提交和菜单合并索引树。
- 合并后的工作区补丁为同目录的 `final-working-tree.patch`，相对上述合并提交生成；新增工作流模块与更新后的功能测试另存于 `final-untracked/`，用于本机交接恢复。原始备份和任务自建的 stash 也保留。
- 生成的漫画输出留在原处；模型权重、安装包和本地配置没有作为合并内容提交。
- `build/menu-merge-full-tests.log` 为完整测试日志；相关快速回归见 `build/menu-merge-targeted-tests.log`、`build/menu-merge-settings-tests.log`、`build/menu-merge-productivity-tests.log`。
- 布局报告及截图：`build/menu-merge-ui/`；这些验证产物不提交。
- 原来的界面密度评估见 `UI_MENU_ASSESSMENT_2026-11-22.md`，其中“尚未实施”的结论属于合并前状态，以本文为准。
- 尚未重新构建安装程序。本地 `release/` 中旧安装包不包含本轮菜单和功能适配。
- 源码版本当前仍为 `2.5.2`；此前 `2.6.0` 安装包通过构建快照覆盖版本生成。后续打包要从当前完整工作区生成新快照，避免沿用旧快照遗漏菜单、新模块或相对模型路径修复。
- 后续若提交当前未提交功能，请显式选择实现、配置、翻译和测试依赖，按 `AGENTS.md` 分离 UI、安装器和发布内容，不提交 `build/`、`release/`、`output_layout/`、模型权重、配置与日志。

## 2026-11-22 · 人工开合偏好面板后的动画修复

- 反馈：反复开合翻译偏好时，`_RippleOverlay.paintEvent()` 持续报告缺少 `_target`。
- 构造边界回归可复现同样异常：原生 QWidget 初始化尚未返回，Qt 绘制回调已读取 Python 动画状态。`motion.py` 中的涟漪与焦点动画层现均先设置空闲绘制状态，再调用 QWidget 构造及几何设置。
- `tests/test_motion_overlay_lifecycle.py` 覆盖构造期间的 Qt 绘制回调，以及初始化后涟漪正常绘制、结束和停止计时器；旧实现会在构造回归中失败。
- `tests/test_retouch_and_motion.py` 增加真实按钮点击、动画中途反向开合、浅/深色和三个窗口尺寸的回归；Qt 回调异常纳入失败条件。
- 本轮相关回归 96 项通过，Windows 原生平台额外执行 3 项通过；浅/深色各 73 张审查图通过，字体为 `Source Han Sans SC`。日志及图像位于 `build/ripple-fix-*`。上文 524 项为菜单合并阶段的完整验收记录。
- 修复与新增测试保留在当前工作区；已运行的程序需关闭后从源码重新启动。前述菜单交接备份对应此次动画修复之前的状态。
- 本轮远端同步遇到镜像 403 和直连代理 TLS 错误，重试后仍失败；保留现有远端和协议配置，本地修复与回归已完成。

## 2026-11-22 · 试译、术语与消耗弹窗确认修复

- 人工反馈：试译确认、术语保存后，主窗口访问 `dialog.Accepted` 抛出 `AttributeError`；消耗报告入口也有同样写法。
- `main_window.py` 的三处返回值判断统一为 `QDialog.DialogCode.Accepted`。
- 新增 `tests/test_workflow_dialog_actions.py`，通过真实弹窗和按钮触发验证试译页数与取消、术语持久化与取消、消耗单价保存与取消，以及从报告进入完整翻译/精修；同时验证弹窗释放和 Qt 回调不报错。
- 新增测试在无显示器平台与 Windows 原生平台各 7 项通过；连同生产力、偏好、更新相关回归共 32 项通过。日志为 `build/dialog-actions-tests.log`、`build/dialog-actions-windows-tests.log`、`build/dialog-workflow-regression.log`。
- `QIODevice::read (QSslSocket): device not open` 尚未形成稳定复现，本轮未修改网络逻辑。代码中 Qt 网络请求由后台更新检查发起，翻译请求走 Python 客户端；目前不能将该网络警告判定为已解决。
- 修复保留在当前工作区，已运行的程序需关闭后重新启动。远端同步本轮仍遇到代理连接错误，未推送。
