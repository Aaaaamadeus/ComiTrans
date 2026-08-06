param([switch]$IncludeModels)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "未找到.venv，请先运行setup 创建虚拟环境。"
    exit 1
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& ".\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ComiTrans.spec
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($IncludeModels) {
    $modelTarget = "dist\ComiTrans\comic-translate-ai\models"
    if (Test-Path "comic-translate-ai\models") {
        New-Item -ItemType Directory -Force -Path $modelTarget | Out-Null
        Copy-Item -Recurse -Force "comic-translate-ai\models\*" $modelTarget
        Write-Host "模型已复制: $modelTarget"
    }
} else {
    Write-Host "已跳过模型复制，模型通过独立模型包分发（见 package_release.ps1）。"
}

Write-Host ""
Write-Host "打包完成: dist\ComiTrans\ComiTrans.exe"
Write-Host "注意: 发布时需要同时上传主程序包和模型包，模型解压到 ComiTrans\comic-translate-ai\models"
