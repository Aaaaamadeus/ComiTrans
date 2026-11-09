param([switch]$IncludeModels)

# Native tools such as PyInstaller write progress to stderr. Under Windows
# PowerShell 5.1 that becomes a NativeCommandError, which "Stop" would turn into
# a premature abort, so keep "Continue" and check $LASTEXITCODE after each step.
$ErrorActionPreference = "Continue"

Set-Location (Split-Path -Parent $MyInvocation.MyCommand.Path)

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "未找到 .venv，请按 README 创建虚拟环境。"
    exit 1
}

& ".\.venv\Scripts\python.exe" -c "import PyInstaller"
if ($LASTEXITCODE -ne 0) {
    Write-Host "缺少构建依赖，请执行：.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt"
    exit 1
}

& ".\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ComiTrans.spec
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($IncludeModels) {
    $modelTarget = "dist\ComiTrans\comic-translate-ai\models"
    if (Test-Path "comic-translate-ai\models") {
        New-Item -ItemType Directory -Force -Path $modelTarget | Out-Null
        # The development model tree also contains non-ONNX weights. Use the release allowlist.
        & ".\.venv\Scripts\python.exe" -c "import pathlib, shutil; from package_release import collect_models; root=pathlib.Path('dist'); [( (root / name).parent.mkdir(parents=True, exist_ok=True), shutil.copyfile(path, root / name)) for path, name in collect_models()]"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Write-Host "模型已复制: $modelTarget"
    }
} else {
    Write-Host "已跳过模型复制，模型通过独立模型包分发（见 package_release.py）。"
}

Write-Host ""
Write-Host "打包完成: dist\ComiTrans\ComiTrans.exe"
Write-Host "发布时只上传程序和模型两个包；GPU 运行库由软件内的官方安装链接提供，不打包上传。"
