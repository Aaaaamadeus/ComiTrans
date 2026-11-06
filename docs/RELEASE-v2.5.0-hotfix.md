# ComiTrans v2.5.0 修复包（2.5.0-hotfix）

## 这是什么

2.5.0 的维护包，程序内容与 2.5.1 同源，版本号保持 2.5.0，供暂时不升级到 2.5.1 的用户使用。模型不重新分发：继续使用已有的 v2.5.0 模型包。

## 更新内容

修复白色漫画气泡擦字后残留灰斑的问题：纸面足够均匀时，按原图测得的纸色在擦除掩膜内平涂。

新增白气泡整框涂白兜底，把检测器漏掉的字、注音和标点一起清除。触发前要求：纸色取自原图未擦像素、框内各区纸色一致、框内本身有文字种子。气泡边线、跨框轮廓、长发丝和大型画线保持原样；网点、渐变和黑底白字仍走原修补流程。仅在邻框有种子而本框无文字时不会触发，框内画面占三成以上时也会跳过。

## 安装

全新安装：把 `ComiTrans-v2.5.0-hotfix-app.zip` 解压到空目录，与已有的 v2.5.0 模型包合并到同一个 `ComiTrans` 文件夹后启动。

已有的正式 v2.5.0：退出客户端，对包含 `ComiTrans.exe` 的原目录运行 `Apply-Update.ps1`，选择 `ComiTrans-v2.5.0-hotfix-patch.zip`。安装器会核对原版文件、备份变更并校验结果。

## 验证

`SHA256SUMS.txt` 与本目录文件对应。补丁在还原的正式 v2.5.0 目录上实测可安装，安装后 CPU 与 CUDA 冒烟均通过，其中包含新增的整框兜底检查 `white_box_fallback`。

## English

Maintenance build for 2.5.0 with the same program as 2.5.1. Models are not redistributed; keep the existing v2.5.0 model package. Extract the app archive into an empty directory and merge with the model package, or apply `ComiTrans-v2.5.0-hotfix-patch.zip` to an existing v2.5.0 installation with `Apply-Update.ps1`. The patch verifies the original files, backs up changes and validates the result. Verify downloads against `SHA256SUMS.txt`.
