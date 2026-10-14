param([string]$Patch, [string]$InstallDir)

$ErrorActionPreference = 'Stop'

function Resolve-ContainedPath([string]$Root, [string]$Name) {
    if ($Name -match '[\\:\x00-\x1f<>"|?*]' -or $Name.StartsWith('/')) { throw "Invalid path: $Name" }
    foreach ($part in $Name.Split('/')) {
        if ($part -in @('', '.', '..') -or $part.EndsWith('.') -or $part.EndsWith(' ') -or
            $part -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)') { throw "Invalid path: $Name" }
    }
    $rootPath = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $resolved = [IO.Path]::GetFullPath((Join-Path $rootPath $Name))
    if (-not $resolved.StartsWith($rootPath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside installation' }
    $check = $rootPath
    foreach ($part in @('') + $Name.Split('/')) {
        if ($part) { $check = Join-Path $check $part }
        if (Test-Path -LiteralPath $check) {
            if ((Get-Item -LiteralPath $check -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Links are not supported in update paths: $check"
            }
        }
    }
    return $resolved
}

function Assert-ManagedName([string]$Name) {
    $parts = $Name.Split('/')
    foreach ($part in $parts) {
        if ($part -in @('models', 'user_fonts', 'page', 'log', 'logs', '__pycache__', '.cache', '.comitrans-update', 'config.yaml') -or
            $part.StartsWith('.env', [StringComparison]::OrdinalIgnoreCase)) { throw "User data is excluded: $Name" }
    }
    if ($Name -cnotin @('ComiTrans.exe', 'README-release.md', 'CHANGELOG.md', 'Apply-Update.ps1', 'Update-ComiTrans.bat') -and
        ($parts.Count -lt 2 -or $parts[0] -cne '_internal')) { throw "Unmanaged file: $Name" }
}

function Get-ManifestFiles($Manifest, [string]$Root) {
    if ($Manifest.schema -ne 1 -or $Manifest.product -cne 'ComiTrans' -or $Manifest.target -cne 'windows-x64' -or
        $Manifest.version -notmatch '^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$' -or $Manifest.build_id -cnotmatch '^[0-9a-f]{64}$') {
        throw 'Unsupported release manifest'
    }
    $files = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::Ordinal)
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($property in $Manifest.files.PSObject.Properties) {
        $name, $record = $property.Name, $property.Value
        Assert-ManagedName $name
        $null = Resolve-ContainedPath $Root $name
        if (-not $seen.Add($name) -or $record.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $record.size -isnot [ValueType] -or $record.size -is [bool] -or $record.size -lt 0 -or [double]$record.size -ne [math]::Floor([double]$record.size)) {
            throw "Invalid file record: $name"
        }
        $files.Add($name, $record)
    }
    if (-not $files.ContainsKey('ComiTrans.exe')) { throw 'Manifest has no executable' }
    return ,$files
}

function Get-ContentSHA256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}

function Assert-FileRecord([string]$Path, $Record) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-Item -LiteralPath $Path).Length -ne $Record.size -or
        (Get-ContentSHA256 $Path) -cne $Record.sha256) {
        throw "File does not match the required build: $Path"
    }
}

function Invoke-ComiTransPatch([string]$PatchPath, [string]$Installation) {
    $root = (Resolve-Path -LiteralPath $Installation).Path
    if (-not (Test-Path -LiteralPath (Join-Path $root 'ComiTrans.exe') -PathType Leaf)) { throw 'Select the folder containing ComiTrans.exe' }
    $exe = Resolve-ContainedPath $root 'ComiTrans.exe'
    foreach ($process in @(Get-Process -Name ComiTrans -ErrorAction SilentlyContinue)) {
        if ($process.Path -eq $exe) { throw 'Close ComiTrans before installing a patch' }
    }
    $source = (Resolve-Path -LiteralPath $PatchPath).Path
    $archive = $null
    try {
        if (Test-Path -LiteralPath $source -PathType Container) {
            $metadata = Resolve-ContainedPath $source 'patch.json'
            $update = Get-Content -LiteralPath $metadata -Raw -Encoding UTF8 | ConvertFrom-Json
        } else {
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $archive = [IO.Compression.ZipFile]::OpenRead($source)
            $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
            foreach ($entry in $archive.Entries) {
                $null = Resolve-ContainedPath $root $entry.FullName
                if (-not $seen.Add($entry.FullName)) { throw 'Duplicate ZIP entry' }
            }
            $metadata = $archive.GetEntry('patch.json')
            if (-not $metadata -or $metadata.Length -gt 16MB) { throw 'Patch metadata is missing or too large' }
            $reader = [IO.StreamReader]::new($metadata.Open(), [Text.Encoding]::UTF8)
            try { $update = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        }
        if ($update.schema -ne 1 -or $update.product -cne 'ComiTrans' -or $update.requires_manifest -isnot [bool]) { throw 'Unsupported patch' }
        $before = Get-ManifestFiles $update.base $root
        $after = Get-ManifestFiles $update.target $root
        if ($update.base.build_id -eq $update.target.build_id) { throw 'Patch contains no new build' }
        $changed = @($after.Keys | Where-Object { -not $before.ContainsKey($_) -or
            $before[$_].sha256 -cne $after[$_].sha256 -or $before[$_].size -ne $after[$_].size } | Sort-Object)
        $deleted = @($before.Keys | Where-Object { -not $after.ContainsKey($_) } | Sort-Object)
        foreach ($kind in @('changed', 'deleted')) {
            $declared = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
            foreach ($name in @($update.$kind)) {
                if (-not $declared.Add([string]$name)) { throw 'Duplicate patch operation' }
            }
            $expected = [string[]]$changed
            if ($kind -eq 'deleted') { $expected = [string[]]$deleted }
            if (-not $declared.SetEquals($expected)) { throw 'Patch operation list does not match its baselines' }
        }
        $oldNames = [Collections.Generic.Dictionary[string,string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach ($name in $before.Keys) { $oldNames.Add($name, $name) }
        foreach ($name in $after.Keys) {
            if ($oldNames.ContainsKey($name) -and $oldNames[$name] -cne $name) { throw 'Case-only renames are unsupported' }
        }
        $manifestPath = Resolve-ContainedPath $root 'release-manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $installed = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($installed.build_id -cne $update.base.build_id -or $installed.version -cne $update.base.version) { throw 'Patch is for a different build' }
        } elseif ($update.requires_manifest) { throw 'This installation needs the 2.4.0 baseline first' }
        Write-Host 'Verifying installed program files...'
        foreach ($name in $before.Keys) { Assert-FileRecord (Resolve-ContainedPath $root $name) $before[$name] }
        foreach ($name in $changed) {
            if (-not $before.ContainsKey($name) -and (Test-Path -LiteralPath (Resolve-ContainedPath $root $name))) {
                throw "A new program path is already occupied: $name"
            }
        }
        $workName = '.comitrans-update/' + [Guid]::NewGuid().ToString('N')
        $work = Resolve-ContainedPath $root $workName
        $null = New-Item -ItemType Directory -Path $work -Force
        $affected = @($changed) + @($deleted) + @('release-manifest.json')
        $existed = @{}
        foreach ($name in $affected) {
            $path = Resolve-ContainedPath $root $name
            $existed[$name] = Test-Path -LiteralPath $path -PathType Leaf
            if ($existed[$name]) {
                $backup = Resolve-ContainedPath $work ('backup/' + $name)
                $null = New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($backup)) -Force
                [IO.File]::Copy($path, $backup, $true)
            }
        }
        foreach ($name in $changed) {
            $staged = Resolve-ContainedPath $work ('staged/' + $name)
            $null = New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($staged)) -Force
            if ($archive) {
                $entry = $archive.GetEntry('files/' + $name)
                if (-not $entry -or $entry.Length -ne $after[$name].size) { throw "Missing or invalid patch payload: $name" }
                $inputStream = $entry.Open()
                $outputStream = [IO.File]::Create($staged)
                try { $inputStream.CopyTo($outputStream) } finally { $inputStream.Dispose(); $outputStream.Dispose() }
            } else {
                [IO.File]::Copy((Resolve-ContainedPath $source ('files/' + $name)), $staged, $true)
            }
            Assert-FileRecord $staged $after[$name]
        }
        $journal = @{ base = $update.base.build_id; target = $update.target.build_id; files = $existed; status = 'prepared' }
        $journalPath = Join-Path $work 'journal.json'
        $journal | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $journalPath -Encoding UTF8
        try {
            foreach ($name in $changed) {
                $path = Resolve-ContainedPath $root $name
                $null = New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($path)) -Force
                Move-Item -LiteralPath (Resolve-ContainedPath $work ('staged/' + $name)) -Destination $path -Force
            }
            foreach ($name in $deleted) { Remove-Item -LiteralPath (Resolve-ContainedPath $root $name) -Force }
            $update.target | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
            foreach ($name in $after.Keys) { Assert-FileRecord (Resolve-ContainedPath $root $name) $after[$name] }
            $journal.status = 'complete'
            $journal | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $journalPath -Encoding UTF8
        } catch {
            $failure = $_
            $restoreErrors = @()
            foreach ($name in $affected) {
                try {
                    $path = Resolve-ContainedPath $root $name
                    if ($existed[$name]) { [IO.File]::Copy((Resolve-ContainedPath $work ('backup/' + $name)), $path, $true) }
                    elseif (Test-Path -LiteralPath $path -PathType Leaf) { Remove-Item -LiteralPath $path -Force }
                } catch { $restoreErrors += $_.Exception.Message }
            }
            $journal.status = if ($restoreErrors.Count) { 'restore-incomplete' } else { 'rolled-back' }
            $journal | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $journalPath -Encoding UTF8
            if ($restoreErrors.Count) { throw "Update failed; retain backups at $work. $($restoreErrors -join '; ')" }
            throw "Update failed and original files were restored: $($failure.Exception.Message)"
        }
        Write-Host "Updated to $($update.target.version). Build: $($update.target.build_id)"
        Write-Host "Backup: $work"
    } finally { if ($archive) { $archive.Dispose() } }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        if (-not $Patch -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'patch.json'))) { $Patch = $PSScriptRoot }
        if (-not $InstallDir -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'ComiTrans.exe'))) { $InstallDir = $PSScriptRoot }
        if (-not $Patch -or -not $InstallDir) {
            Add-Type -AssemblyName System.Windows.Forms
            if (-not $Patch) {
                $dialog = [Windows.Forms.OpenFileDialog]::new()
                $dialog.Title = 'Select ComiTrans patch ZIP'
                $dialog.Filter = 'ComiTrans patch (*.zip)|*.zip'
                if ($dialog.ShowDialog() -ne 'OK') { exit 0 }
                $Patch = $dialog.FileName
                $dialog.Dispose()
            }
            if (-not $InstallDir) {
                $dialog = [Windows.Forms.FolderBrowserDialog]::new()
                $dialog.Description = 'Select the folder containing ComiTrans.exe'
                if ($dialog.ShowDialog() -ne 'OK') { exit 0 }
                $InstallDir = $dialog.SelectedPath
                $dialog.Dispose()
            }
        }
        Invoke-ComiTransPatch $Patch $InstallDir
    } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }
}
