# ComiTrans v2.5.0 Windows 修补包

## 下载与安装

已有正式 v2.5.0 的用户退出 ComiTrans，在安装目录运行 Update-ComiTrans.bat，选择 ComiTrans-v2.5.0-hotfix-patch.zip 和包含 ComiTrans.exe 的原目录。安装器会核对原版文件、备份变更并校验结果。全新安装使用 ComiTrans-v2.5.0-hotfix-app.zip，搭配正式 v2.5.0 模型包。

## 更新内容

修复白色漫画气泡擦字后出现灰斑的问题：先检查框内纸色和笔画周围的像素，纸面足够均匀时，在已有擦除掩膜内按原纸色填充。

在「设置 → 运行与输出 → GPU 安装说明与下载」点击「下载安装便携 GPU 运行库」，完成后重启。首次下载约 1.53 GB，需要兼容的 NVIDIA 驱动。DLL 保存在程序旁的 gpu-runtime 目录，无需另外安装 Python 或配置 PATH。

补上本版 Python 建立 HTTPS 连接时需要的证书策略文件。失败弹窗会复制当前配置和日志。Windows 版会发现标准目录下的 CUDA 12.x 和 cuDNN 9.x，以及当前用户的 `%LOCALAPPDATA%\ComiTrans\gpu-runtime\bin`，并分别从找到的目录加载运行库。用户目录需要已有兼容的 NVIDIA DLL。检测与 LaMa 支持 CUDA，Baberu 量化 OCR 使用 CPU。

## 验证

使用同目录 SHA256SUMS.txt 核对程序包、补丁和构建清单。开启 GPU 后查看检测和 LaMa 的模型初始化日志，两个模型均应显示 CUDA。可从正式 v2.5.0 标签应用 runtime.patch 复现程序源码更改。

## English

Close ComiTrans and use Update-ComiTrans.bat to apply the patch to an official v2.5.0 installation. For a fresh install, extract the hotfix app archive together with the original v2.5.0 models. This fix restores HTTPS client creation, refreshes copied diagnostics, and discovers CUDA 12 and cuDNN 9 in versioned Windows installation folders or the current user's ComiTrans runtime directory. Check SHA256SUMS.txt and confirm the detector and LaMa report CUDA.
