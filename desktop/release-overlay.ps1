# Emits the path of a Tauri config overlay for public-distribution builds, or nothing
# when no signing/updater environment is configured (the build stays a plain local
# candidate build). The overlay JSON is written under src-tauri/target/ (git-ignored)
# because certificate identity is machine-local and must not be committed.
#
# Inputs:
#   LIFEOS_SIGN_THUMBPRINT        sign with a store-installed certificate via Tauri's
#                                 native signtool call (app exe, uninstaller, installer).
#   LIFEOS_SIGN_PFX_PATH          sign via desktop/sign-release.ps1 (signCommand shim);
#   LIFEOS_SIGN_PFX_PASSWORD      Tauri's native path cannot take a PFC/PFX file.
#   LIFEOS_SIGN_TIMESTAMP_URL     RFC 3161 timestamp server (default digicert).
#   TAURI_SIGNING_PRIVATE_KEY     enable bundle.createUpdaterArtifacts (updater
#   TAURI_SIGNING_PRIVATE_KEY_PASSWORD  artifacts: installer + .sig sidecar).
#
# Precedence: LIFEOS_SIGN_THUMBPRINT wins over LIFEOS_SIGN_PFX_PATH.
$ErrorActionPreference = 'Stop'

$wantSigning = [bool]$env:LIFEOS_SIGN_THUMBPRINT -or [bool]$env:LIFEOS_SIGN_PFX_PATH
$wantUpdaterArtifacts = [bool]$env:TAURI_SIGNING_PRIVATE_KEY
if (-not ($wantSigning -or $wantUpdaterArtifacts)) { exit 0 }

$overlay = [ordered]@{ bundle = [ordered]@{} }
if ($wantUpdaterArtifacts) { $overlay.bundle.createUpdaterArtifacts = $true }
if ($wantSigning) {
    $timestampUrl = 'http://timestamp.digicert.com'
    if ($env:LIFEOS_SIGN_TIMESTAMP_URL) { $timestampUrl = $env:LIFEOS_SIGN_TIMESTAMP_URL }
    $windows = [ordered]@{
        digestAlgorithm = 'sha256'
        timestampUrl = $timestampUrl
    }
    if ($env:LIFEOS_SIGN_THUMBPRINT) {
        $windows.certificateThumbprint = $env:LIFEOS_SIGN_THUMBPRINT
    } else {
        $windows.signCommand = @{
            cmd = 'powershell.exe'
            args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'sign-release.ps1'), '%1')
        }
    }
    $overlay.bundle.windows = $windows
}

$targetDir = Join-Path $PSScriptRoot 'src-tauri/target'
if (-not (Test-Path -LiteralPath $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}
$overlayPath = Join-Path $targetDir 'release-overlay.json'
# WriteAllText keeps UTF-8 without BOM; serde_json rejects a BOM.
[System.IO.File]::WriteAllText($overlayPath, ($overlay | ConvertTo-Json -Depth 6))
Write-Output $overlayPath
