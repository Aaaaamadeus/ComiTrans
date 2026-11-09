# AGENTS.md

本文件约束 ComiTrans 仓库内的分支、提交、推送与验收操作，作用于所有在本仓库工作的 Agent 与协作者。改动本文件需要作者确认。

## 1. 分支模型

| 分支 | 用途 | 允许的改动 |
|---|---|---|
| `main` | 发布基线，只通过 PR 合入 | **禁止直接提交/推送** |
| `codex/model-adaptation-update` | 模型适配、v2.5.x 发布与擦字修复 | 模型/推理/发布记录，**不含 UI** |
| `feat/ui-2.0` | UI 美化与体验升级（画布、右栏、点选、夜墨主题、字体兜底） | 只含 UI/主题/文案/计划文档 |

- UI 子任务从 `feat/ui-2.0` 切出 `feat/ui-<slug>`（如 `feat/ui-canvas`、`feat/ui-theme`），完成后合回 `feat/ui-2.0`，再由 `feat/ui-2.0` → `main` 提 PR。
- 模型/推理改动走 `codex/model-adaptation-update`。UI 分支需要模型侧修复时，用 `git merge origin/codex/model-adaptation-update` 带进来，不要在两条分支上重复改同一份代码。
- 两条线不混提交：UI 分支不夹带模型权重、发布包、生成产物；模型分支不夹带 UI 样式改动。

## 2. 开工与收尾

1. `git fetch origin`。
2. `git branch --show-current` 确认分支：UI 改动必须发生在 `feat/ui-2.0` 或其子分支。
3. 按文件显式 `git add <path>`，不使用 `git commit -a`。
4. 跑完第 5 节门禁再提交。
5. 按第 4 节推送，最后用 `git status -sb` 确认与远端同步。

## 3. 提交信息

- 英文，`<type>: <summary>`；type 取 `feat` / `fix` / `docs` / `refactor` / `test` / `perf` / `chore`。
- UI 提交建议 scope：`ui(editor)`、`ui(theme)`、`ui(canvas)`、`ui(inspector)`。
- 一个提交只做一件事；计划/文档提交与实现提交分开。
- 提交前确认 `git diff --cached --stat` 里没有无关文件。

## 4. 推送

`~/.gitconfig` 里有 `url.https://gh-proxy.com/https://github.com/.insteadOf https://github.com/`，gh-proxy 对写操作只读，`git push origin` 会报 `No anonymous write access`。改用直连 + 本机代理：

```powershell
$branch = 'feat/ui-2.0'
$tmp = Join-Path $env:TEMP 'gitconfig-push-direct'
@"
[http]
    proxy = http://127.0.0.1:7897
[credential]
    helper = manager
"@ | Set-Content -Encoding utf8 $tmp
$env:GIT_CONFIG_GLOBAL = $tmp
$env:GCM_INTERACTIVE = 'never'
$env:GIT_TERMINAL_PROMPT = '0'
git push https://github.com/Aaaaamadeus/ComiTrans.git $branch
Remove-Item $tmp -Force
```

- 只推自己的分支；不 force-push 他人分支，不推 `main`。
- 首次出现 `TLS connect error ... unexpected eof` 多为代理抖动，重试一次；仍失败就停下报告，不要改远端、不要换协议或改用 gh-proxy 写。
- 若作者移除 `insteadOf`，恢复 `git push origin $branch` 即可。

## 5. 门禁（合并前必须通过）

- `python -m unittest discover -s tests` 全绿；UI 改动至少覆盖 `tests/test_desktop_ui.py`、`tests/test_editor_live_preview.py`、`tests/test_large_editor.py`。
- `scripts/review_ui.py` 出图：浅色/深色两套 × 1440 / 1024 / 820；截图中不得有半截文字，`QFontInfo(ui_font()).family()` 必须是白名单字体（思源黑体 / Noto Sans CJK / Microsoft YaHei / 内置兜底）。
- 新增界面文案同步 `assets/i18n/en.json` 与 `ja.json`。
- UI 改动不得改变漫画像素、排版算法与导出结果；深色主题独立测试，不从浅色推断。

## 6. 不要提交

- 构建与生成产物：`dist/`、`build/`、`release/`、`output/`、`output_layout/`、`tmp/`。
- 模型权重（`.pt` / `.pth` / `.onnx`）与模型目录下的临时文件；只提交许可、配置与清单。
- 未使用的营销素材：`docs/images/comitrans-hero-v1.png`、`docs/images/comitrans-hero-v1.prompt.md`、`docs/images/comitrans-hero-v2.prompt.md`——除非作者明确要求。
- 本地配置、日志、`config.yaml`。

## 7. UI 计划与顺序

- 计划文档：`docs/UI_UPGRADE_PLAN_2026-11-06.md`（目标版本 v2.6.x）。
- 顺序：P0-0 字体兜底与截图断言 → P0-2 画布手势 → P0-1 夜墨主题 → P1-1 右栏重构 → P1-2 画布点选。
- 每项完成后更新计划里的状态，并在 PR 描述中附前后截图。
