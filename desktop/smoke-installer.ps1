param(
    [string]$Installer = (Join-Path $PSScriptRoot 'src-tauri/target/release/bundle/nsis/Personal AI Life OS_0.1.0_x64-setup.exe')
)

$ErrorActionPreference = 'Stop'
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
$alreadyInstalled = @(Get-ItemProperty $uninstallKey -ErrorAction SilentlyContinue |
    Where-Object DisplayName -eq 'Personal AI Life OS')
if ($alreadyInstalled.Count -gt 0) {
    throw 'Use a separate Windows test profile. This account already has Personal AI Life OS installed.'
}
$testRoot = Join-Path $PSScriptRoot ('build/install-smoke-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$project = Split-Path -Parent $PSScriptRoot
$uninstaller = Join-Path $testRoot 'uninstall.exe'
try {
    $setup = Start-Process -FilePath $installerPath -ArgumentList @('/S', "/D=$testRoot") -WindowStyle Hidden -PassThru -Wait
    if ($setup.ExitCode -ne 0) { throw "Installer failed ($($setup.ExitCode))" }
    $shell = Join-Path $testRoot 'lifeos.exe'
    $sidecar = Join-Path $testRoot 'sidecar/lifeos-sidecar.exe'
    foreach ($file in @($shell, $sidecar, $uninstaller)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Expected installed file: $file" }
    }
    Push-Location $project
    try {
        uv run --frozen --group desktop python desktop/smoke-sidecar.py --full $sidecar
        if ($LASTEXITCODE -ne 0) { throw "Installed sidecar smoke failed ($LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
} finally {
    if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        $removed = Start-Process -FilePath $uninstaller -ArgumentList '/S' -WindowStyle Hidden -PassThru -Wait
        if ($removed.ExitCode -ne 0 -or (Test-Path -LiteralPath (Join-Path $testRoot 'lifeos.exe'))) {
            throw 'Silent test uninstall failed.'
        }
    }
}
Get-FileHash -LiteralPath $installerPath
'Local per-user NSIS install, packaged sidecar and uninstall passed.'
