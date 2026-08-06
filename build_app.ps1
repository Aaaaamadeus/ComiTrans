$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "未找到 .venv，请先运行 setup 或创建虚拟环境。"
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

$modelTarget = "dist\ComiTrans\comic-translate-ai\models"
if (Test-Path "comic-translate-ai\models") {
    New-Item -ItemType Directory -Force -Path $modelTarget | Out-Null
    Copy-Item -Recurse -Force "comic-translate-ai\models\*" $modelTarget
    Write-Host "模型已外置: $modelTarget"
}

Write-Host ""
Write-Host "打包完成: dist\ComiTrans\ComiTrans.exe"
Write-Host "注意: 发布压缩包必须包含 dist\ComiTrans\comic-translate-ai\models 目录"
