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

Write-Host ""
Write-Host "打包完成: dist\ComiTrans\ComiTrans.exe"
