# Signs a binary with signtool using environment-provided credentials.
# Tauri invokes this script through bundle.windows.signCommand (the "%1" placeholder
# receives the path of each file to sign: app exe, uninstaller stub, NSIS installer).
#
# Credential sources (mutually exclusive, checked in this order):
#   LIFEOS_SIGN_PFX_PATH       PFX/PKCS#12 file; LIFEOS_SIGN_PFX_PASSWORD optional.
#   LIFEOS_SIGN_THUMBPRINT     SHA-1 thumbprint of a certificate already installed
#                              in the user or machine store (hardware-token friendly).
# Optional:
#   LIFEOS_SIGN_TIMESTAMP_URL  RFC 3161 timestamp server (default digicert).
#   LIFEOS_SIGNTOOL_PATH       Explicit signtool.exe path (else PATH, then Windows Kits).
param([Parameter(Mandatory = $true, Position = 0)][string]$Path)

$ErrorActionPreference = 'Stop'

function Find-SignTool {
    if ($env:LIFEOS_SIGNTOOL_PATH) {
        if (-not (Test-Path -LiteralPath $env:LIFEOS_SIGNTOOL_PATH)) {
            throw "LIFEOS_SIGNTOOL_PATH does not exist: $($env:LIFEOS_SIGNTOOL_PATH)"
        }
        return $env:LIFEOS_SIGNTOOL_PATH
    }
    $onPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    if (Test-Path -LiteralPath $kitsRoot) {
        $candidate = Get-ChildItem -LiteralPath $kitsRoot -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.Directory.Name -eq 'x64' } |
            Sort-Object { $_.Directory.Parent.Name } -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    throw 'signtool.exe not found; install the Windows SDK or set LIFEOS_SIGNTOOL_PATH.'
}

if (-not (Test-Path -LiteralPath $Path)) { throw "File to sign does not exist: $Path" }

$timestampUrl = 'http://timestamp.digicert.com'
if ($env:LIFEOS_SIGN_TIMESTAMP_URL) { $timestampUrl = $env:LIFEOS_SIGN_TIMESTAMP_URL }

$signArgs = @('sign', '/fd', 'sha256', '/td', 'sha256', '/tr', $timestampUrl)
if ($env:LIFEOS_SIGN_THUMBPRINT) {
    $signArgs += @('/sha1', $env:LIFEOS_SIGN_THUMBPRINT)
} elseif ($env:LIFEOS_SIGN_PFX_PATH) {
    if (-not (Test-Path -LiteralPath $env:LIFEOS_SIGN_PFX_PATH)) {
        throw "LIFEOS_SIGN_PFX_PATH does not exist: $($env:LIFEOS_SIGN_PFX_PATH)"
    }
    $signArgs += @('/f', $env:LIFEOS_SIGN_PFX_PATH)
    if ($env:LIFEOS_SIGN_PFX_PASSWORD) { $signArgs += @('/p', $env:LIFEOS_SIGN_PFX_PASSWORD) }
} else {
    throw 'Set LIFEOS_SIGN_THUMBPRINT or LIFEOS_SIGN_PFX_PATH for sign-release.ps1.'
}

$signTool = Find-SignTool
$signArgs += (Resolve-Path -LiteralPath $Path).Path
& $signTool @signArgs
if ($LASTEXITCODE -ne 0) { throw "signtool failed ($LASTEXITCODE) for $Path" }
Write-Host "Signed: $Path"
