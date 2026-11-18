param(
    [Parameter(Mandatory)][string]$Setup,
    [Parameter(Mandatory)][string]$Version,
    [Parameter(Mandatory)][string]$LogDirectory,
    [string]$PreviousSetup
)

$ErrorActionPreference = 'Stop'
$path = 'HKLM:\Software\ComiTrans\Installer'
if ((Test-Path $path) -or (Get-Service ComiTransReleaseCheck -ErrorAction SilentlyContinue)) {
    throw 'The Setup smoke test requires a fresh Windows runner.'
}

function Invoke-Setup($file, $action, $name) {
    $log = Join-Path $LogDirectory "$name.log"
    $process = Start-Process -FilePath $file -ArgumentList $action, '/quiet', '/norestart', '/log', ('"' + $log + '"') -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 50 }
        throw "Setup $action exited with $($process.ExitCode)."
    }
}

$uninstaller = $null
try {
    if ($PreviousSetup) {
        Invoke-Setup $PreviousSetup '/install' 'comitrans-setup-previous'
        $uninstaller = $PreviousSetup
    }
    Invoke-Setup $Setup '/install' 'comitrans-setup-smoke'
    $uninstaller = $Setup
    $registration = Get-ItemProperty -LiteralPath $path
    $app = Get-Item -LiteralPath (Join-Path $registration.InstallDir 'ComiTrans.exe')
    if ($app.VersionInfo.ProductVersion -ne $Version -or $registration.Version -ne $Version) {
        throw 'Installed MSI and EXE versions differ.'
    }
    if ($registration.SetupManaged -ne '1' -or $registration.SetupSource -ine $Setup) {
        throw 'Installed application was not registered as a Setup-managed installation.'
    }
    if ((Get-Service ComiTransReleaseCheck).Status -ne 'Running') { throw 'Release service did not start.' }
    $pipe = [IO.Pipes.NamedPipeClientStream]::new('.', 'ComiTrans.ReleaseCheck', [IO.Pipes.PipeDirection]::In)
    try { $pipe.Connect(8000) } finally { $pipe.Dispose() }
    $extension = Get-Item -LiteralPath 'HKLM:\Software\Classes\.comitrans'
    if ($extension.GetValue('') -ne 'ComiTrans.PdfProject') { throw 'PDF project association missing.' }
    foreach ($folder in 'CommonPrograms', 'CommonDesktopDirectory') {
        if (!(Test-Path (Join-Path ([Environment]::GetFolderPath($folder)) 'ComiTrans.lnk'))) {
            throw "Missing $folder shortcut."
        }
    }
} finally {
    if ($uninstaller) {
        Invoke-Setup $uninstaller '/uninstall' 'comitrans-setup-uninstall'
        if ((Test-Path $path) -or (Get-Service ComiTransReleaseCheck -ErrorAction SilentlyContinue)) {
            throw 'Uninstall left its registration behind.'
        }
    }
}
