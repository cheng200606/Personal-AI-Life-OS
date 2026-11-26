param([switch]$Debug, [string]$SevenZip = '7z.exe')

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$tauri = Join-Path $project 'web/node_modules/.bin/tauri.cmd'
if (-not (Test-Path -LiteralPath $tauri)) { throw 'Run npm ci in web/ before building the installer.' }
& (Join-Path $PSScriptRoot 'prepare-ocr.ps1') -SevenZip $SevenZip
& (Join-Path $PSScriptRoot 'build-sidecar.ps1') -TesseractDirectory (Join-Path $PSScriptRoot 'build/ocr')

$arguments = @('build', '--bundles', 'nsis')
if ($Debug) { $arguments += '--debug' }
Push-Location $PSScriptRoot
try {
    & $tauri @arguments -- --locked
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}
