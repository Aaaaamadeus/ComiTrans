param(
    [Parameter(Mandatory)][string]$Setup,
    [Parameter(Mandatory)][string]$Version,
    [Parameter(Mandatory)][string]$LogDirectory,
    [string]$PreviousSetup
)

# Run only on a disposable Windows runner; this performs a real machine install.
$ErrorActionPreference = 'Stop'
$registrationPath = 'HKLM:\Software\ComiTrans\Installer'
if ((Test-Path $registrationPath) -or (Get-Service ComiTransReleaseCheck -ErrorAction SilentlyContinue)) {
    throw 'The Setup smoke test requires a fresh Windows runner.'
}
$installParent = Join-Path $LogDirectory 'ComiTrans 安装测试'
$installDirectory = Join-Path $installParent 'ComiTrans'
if (Test-Path -LiteralPath $installParent) { throw 'The smoke-test folder already exists.' }
$userSentinel = Join-Path $env:LOCALAPPDATA 'ComiTrans\installer-smoke-sentinel.txt'
if (Test-Path -LiteralPath $userSentinel) { throw 'The user-data sentinel already exists.' }
New-Item -ItemType Directory -Force (Split-Path -Parent $userSentinel) | Out-Null
Set-Content -LiteralPath $userSentinel -Value 'user data must survive'
$installed = $false
$legacyInstalled = $false
$checkKeptFile = $false

function Invoke-Installer($file, $arguments, $expected = 0) {
    $process = Start-Process -FilePath $file -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne $expected) {
        throw "Installer exited with $($process.ExitCode), expected $expected."
    }
}

try {
    if ($PreviousSetup) {
        Invoke-Installer $PreviousSetup '/install /quiet /norestart'
        $previous = Get-ItemProperty -LiteralPath $registrationPath
        if ($previous.InstallerType -eq 'NSIS') {
            $installed = $true
            $installDirectory = $previous.InstallDir
            $installParent = $installDirectory
        } else {
            $legacyInstalled = $true
            # Refusing the incompatible MSI installation must leave it registered.
            Invoke-Installer $Setup '/quiet /norestart' 2
            if (!(Test-Path $registrationPath)) { throw 'MSI migration damaged the old registration.' }
            Invoke-Installer $PreviousSetup '/uninstall /quiet /norestart'
            $legacyInstalled = $false
            if (Test-Path $registrationPath) { throw 'Legacy uninstall did not finish.' }
        }
    }
    $log = Join-Path $LogDirectory 'comitrans-nsis-install.log'
    $installed = $true # also clean up a partially registered installation on failure
    Invoke-Installer $Setup ('/S /LOG="' + $log + '" /D=' + $installParent)
    # Exercise the flags still used by existing installed app update clients.
    Invoke-Installer $Setup ('/quiet /norestart /log "' + $log + '"')
    $registration = Get-ItemProperty -LiteralPath $registrationPath
    $app = Get-Item -LiteralPath (Join-Path $registration.InstallDir 'ComiTrans.exe')
    if ($app.VersionInfo.ProductVersion -ne $Version -or $registration.Version -ne $Version) {
        throw 'Installed application and Setup versions differ.'
    }
    if ($registration.InstallDir -ine $installDirectory -or $registration.InstallerType -ne 'NSIS' -or
        $registration.SetupManaged -ne '1' -or $registration.SetupSource -ine $Setup) {
        throw 'NSIS installation metadata or chosen directory is incorrect.'
    }
    if (!(Test-Path $log)) { throw 'The requested installation log is missing.' }
    $smoke = Join-Path $LogDirectory 'comitrans-installed-smoke'
    $env:QT_QPA_PLATFORM = 'offscreen'
    $smokeProcess = Start-Process -FilePath $app.FullName -ArgumentList ('--smoke-test "' + $smoke + '"') -WindowStyle Hidden -PassThru
    if (!$smokeProcess.WaitForExit(300000)) {
        $smokeProcess.Kill()
        throw 'Installed application smoke test timed out.'
    }
    $smokeReport = Get-Content (Join-Path $smoke 'smoke-result.json') -Raw | ConvertFrom-Json
    if ($smokeProcess.ExitCode -ne 0 -or !$smokeReport.success -or $smokeReport.version -ne $Version) {
        throw 'Installed application failed resource or model verification.'
    }
    if ((Get-Service ComiTransReleaseCheck).Status -ne 'Running') { throw 'Release service did not start.' }
    $service = Get-CimInstance Win32_Service -Filter "Name='ComiTransReleaseCheck'"
    $serviceExe = Join-Path $env:ProgramFiles 'ComiTrans Release Service\ComiTransReleaseService.exe'
    if ($service.PathName -ine ('"' + $serviceExe + '"')) { throw 'Service is outside its protected directory.' }
    $pipe = [IO.Pipes.NamedPipeClientStream]::new('.', 'ComiTrans.ReleaseCheck', [IO.Pipes.PipeDirection]::In)
    try { $pipe.Connect(8000) } finally { $pipe.Dispose() }
    $extension = Get-Item -LiteralPath 'HKLM:\Software\Classes\.comitrans'
    if ($extension.GetValue('') -ne 'ComiTrans.PdfProject') { throw 'PDF project association missing.' }
    foreach ($folder in 'CommonPrograms', 'CommonDesktopDirectory') {
        if (!(Test-Path (Join-Path ([Environment]::GetFolderPath($folder)) 'ComiTrans.lnk'))) {
            throw "Missing $folder shortcut."
        }
    }
    # Uninstall should remove only packaged files, leaving these files alone.
    Set-Content -LiteralPath (Join-Path $installDirectory 'keep-user-file.txt') -Value 'keep'
    $checkKeptFile = $true
} finally {
    if ($legacyInstalled) { Invoke-Installer $PreviousSetup '/uninstall /quiet /norestart' }
    if ($installed -and (Test-Path $registrationPath)) {
        $registration = Get-ItemProperty -LiteralPath $registrationPath
        $uninstall = Join-Path $registration.InstallDir 'Uninstall.exe'
        Invoke-Installer $uninstall '/S'
        for ($attempt = 0; $attempt -lt 20 -and (Test-Path $registrationPath); $attempt++) { Start-Sleep -Milliseconds 500 }
        if ((Test-Path $registrationPath) -or (Get-Service ComiTransReleaseCheck -ErrorAction SilentlyContinue)) {
            throw 'Uninstall left its registration or service behind.'
        }
        $kept = Join-Path $installDirectory 'keep-user-file.txt'
        if ($checkKeptFile -and !(Test-Path -LiteralPath $kept)) { throw 'Uninstall deleted an unrelated file.' }
        if (Test-Path -LiteralPath $kept) { Remove-Item -LiteralPath $kept }
        if (Test-Path -LiteralPath $installDirectory) {
            if (Get-ChildItem -LiteralPath $installDirectory -Force) { throw 'Uninstall left packaged files behind.' }
            Remove-Item -LiteralPath $installDirectory
        }
    }
    if (!(Test-Path -LiteralPath $userSentinel)) { throw 'Uninstall deleted user data.' }
    Remove-Item -LiteralPath $userSentinel
}
