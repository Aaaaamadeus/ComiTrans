# 项目瘦身记录

日期：2026-10-08。范围：当前 PySide6 桌面应用及其 ONNX 推理、构建和文档。

## 删除范围

按用户确认的[精确清单](cleanup-deletions.json)删除 82 个受 Git 管理的文件，共 248,075 字节：

- 旧 Web 架构 64 个文件：Vue、Spring Boot、FastAPI、Nginx、Docker、SQL 及配套文档。
- 失效的独立 CLI 和旧版 README。
- 检测器中未使用的 PyTorch 网络、训练、数据集、合成文本和导出工具。

删除后清除了空目录和遗留 Python 字节码。检测器仍保留四个 ONNX 后处理模块、包入口、来源说明和原始 LICENSE；历史代码可从 Git 历史获取。

## 空间回收

清除了 pip 缓存、旧构建工作目录以及两组已完成验收的临时构建副本，累计 **5,036,596,628 字节，约 5.04 GB / 4.69 GiB**。逐目录大小和文件数见[缓存清理记录](cleanup-cache.json)。该统计不计入删除源码的 248,075 字节，也不计入本次验收后移除的临时产物。

保留当前虚拟环境、本地模型、字体、用户配置、漫画输入与输出，以及原有 `dist` / `release` 发布文件。`tmp` 中的字体实验数据和脚本仍被研究文档引用，未整目录删除。

## 逻辑与依赖修正

- 检测器通过 `comic_text_detector.utils` 正常包导入，取消目录探测、通用 `utils` 名称和额外 `sys.path` 注入，避免被其它同名包截获。
- PyInstaller 根据模块依赖收集后处理代码，取消整目录源码复制；许可证和来源说明单独放到 `licenses/comic-text-detector/`。
- 空文件任务只负责预热模型，完成后直接退出，不创建输出目录、临时目录或文档任务。
- 删除无人调用的旧气泡判断、无用锁、重复导入和变量、无效字体参数，以及本地 ONNX 流程不使用的镜像环境变量。
- AI 诊断在成功和异常时都关闭 HTTP 客户端；失败不写入对话历史。工作线程复用统一的密钥脱敏函数。
- 删除 `python-dotenv`、`setuptools<81`、`tqdm`、`loguru` 四项无直接用途的依赖声明。运行库需要的间接依赖仍由其自身声明安装。
- 新增 `requirements-build.txt`，固定已验收的 PyInstaller 6.21.0；构建脚本不再自动下载、升级构建工具。
- 清理旧 Web 和重叠的忽略规则；中英文 README 按真实行为说明：多模态翻译和实验性字体比对是独立开关，字体比对默认关闭。

本轮没有改变翻译提示词、字体判断门控或排版算法；后续多模态改进仍见 [MULTIMODAL_TRANSLATION_PLAN.md](MULTIMODAL_TRANSLATION_PLAN.md)。

## 验收

- `python -m unittest discover -s tests -v`：117 项通过。新增回归覆盖同名包冲突、预热不创建文档输出、诊断成功与异常时的客户端关闭。
- 八张本地空白漫画页使用真实模型完成检测、修复、排版和保存，成功 8、失败 0；翻译客户端禁止创建。[运行结果](ui-review/cleanup-runtime.json)。这验证本地链路，不代表在线翻译质量。
- 临时 PyInstaller 构建成功。隔离配置启动打包后的应用，本地模型预热成功，UI 字体无缺字、SVG 有效。[启动结果](ui-review/cleanup-startup.json)、[启动截图](ui-review/cleanup-startup.png)。
- `git diff --check` 通过；实际删除路径与确认清单一致。

验收使用独立配置与设置目录，没有读取用户 API 密钥或发起外部翻译请求。临时构建产物验收后清除，原有发布版 EXE 未覆盖；当前代码可通过 `start.bat` 运行。
