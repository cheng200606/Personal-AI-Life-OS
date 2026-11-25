# Register a daily folder sync with Windows Task Scheduler.
#
# The task calls the existing CLI (`lifeos sync <path> --yes`), which reuses the
# same source identity and SHA-256 deduplication as the manual CLI path. The
# API must already be reachable at LIFEOS_API_URL (default http://127.0.0.1:8000).
#
# Examples:
#   .\scripts\register-scheduled-sync.ps1 -Path C:\Notes -Time 09:00 -WhatIf
#   .\scripts\register-scheduled-sync.ps1 -Path C:\Notes -Time 09:00
#   .\scripts\register-scheduled-sync.ps1 -Remove
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Position = 0)]
    [string]$Path,
    [string]$Time = "09:00",
    [string]$TaskName = "Personal AI Life OS Sync",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

if ($Remove) {
    if ($PSCmdlet.ShouldProcess($TaskName, "Unregister scheduled task")) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'."
    }
    return
}

if ([string]::IsNullOrWhiteSpace($Path)) {
    throw "Path is required unless -Remove is used."
}

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    throw "uv was not found on PATH. Install uv and run 'uv sync' in $ProjectRoot first."
}

$resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
if (-not (Test-Path -LiteralPath $resolved -PathType Container)) {
    throw "Path must be an existing folder: $resolved"
}

try {
    $null = [datetime]::ParseExact(
        $Time,
        "HH:mm",
        [System.Globalization.CultureInfo]::InvariantCulture
    )
} catch {
    throw "Time must use 24-hour HH:mm format, for example 09:00."
}

$logDirectory = Join-Path $ProjectRoot "data\logs"
$logPath = Join-Path $logDirectory "scheduled-sync.log"
$wrapperPath = Join-Path $logDirectory "run-scheduled-sync.ps1"

function Quote-PowerShellLiteral([string]$value) {
    return "'" + $value.Replace("'", "''") + "'"
}

$wrapperTemplate = @'
$ErrorActionPreference = "Stop"
& __UV__ run --project __ROOT__ lifeos sync __PATH__ --yes *>> __LOG__
exit $LASTEXITCODE
'@
$wrapper = $wrapperTemplate
$wrapper = $wrapper.Replace("__UV__", (Quote-PowerShellLiteral $uvCommand.Source))
$wrapper = $wrapper.Replace("__ROOT__", (Quote-PowerShellLiteral $ProjectRoot))
$wrapper = $wrapper.Replace("__PATH__", (Quote-PowerShellLiteral $resolved.Path))
$wrapper = $wrapper.Replace("__LOG__", (Quote-PowerShellLiteral $logPath))

if ($PSCmdlet.ShouldProcess($resolved.Path, "Write wrapper and register daily sync at $Time")) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    Set-Content -LiteralPath $wrapperPath -Value $wrapper -Encoding UTF8
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wrapperPath`"" `
        -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Import changed files from $resolved and deduplicate by SHA-256." `
        -Force | Out-Null
    Write-Host "Registered '$TaskName' for $Time daily."
    Write-Host "Log: $logPath"
    Write-Host "Wrapper: $wrapperPath"
}
