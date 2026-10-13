# ONNX 后处理模块

本目录保留 `dmMaze/comic-text-detector` 的 `db_utils`、`imgproc_utils`、`textblock`、`textmask` 后处理算法与原始 LICENSE。

当前检测推理由父目录的 `onnx_text_detector.py` 使用 ONNX Runtime 执行，通过 `comic_text_detector.utils` 包直接导入后处理。未使用的旧 PyTorch 网络、训练、数据集、模型导出和合成文本工具已移除；历史源码可从 Git 历史获取。

Python 模块由 PyInstaller 依赖分析打包，不再将整个源码目录作为数据文件重复复制。打包时仅将本说明和原始许可证另存到 `licenses/comic-text-detector/`。
