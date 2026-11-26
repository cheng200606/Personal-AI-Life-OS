param([string]$SevenZip = '7z.exe')

$ErrorActionPreference = 'Stop'
$build = Join-Path $PSScriptRoot 'build'
$expanded = Join-Path $build 'ocr-installer'
$distribution = Join-Path $build 'ocr'
$installer = Join-Path $build 'tesseract-5.4.0.exe'
$model = Join-Path $distribution 'tessdata/chi_sim.traineddata'
New-Item -ItemType Directory -Force $build, $expanded, (Split-Path $model) | Out-Null

function Get-VerifiedFile([string]$Url, [string]$Destination, [string]$Sha256) {
    if (-not (Test-Path -LiteralPath $Destination) -or (Get-FileHash -LiteralPath $Destination).Hash -ne $Sha256) {
        curl.exe --fail --location --silent --show-error --retry 2 --max-time 180 $Url --output $Destination
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    }
    if ((Get-FileHash -LiteralPath $Destination).Hash -ne $Sha256) { throw "SHA-256 mismatch: $Destination" }
}

Get-VerifiedFile 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe' `
    $installer 'C885FFF6998E0608BA4BB8AB51436E1C6775C2BAFC2559A19B423E18678B60C9'
Get-VerifiedFile 'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/chi_sim.traineddata' `
    $model 'A5FCB6F0DB1E1D6D8522F39DB4E848F05984669172E584E8D76B6B3141E1F730'

& $SevenZip x -y -tNsis $installer "-o$expanded" 'tesseract.exe' '*.dll' 'doc/*' 'tessdata/eng.traineddata' '-x!$PLUGINSDIR'
if ($LASTEXITCODE -gt 1) { throw "Tesseract extraction failed ($LASTEXITCODE)" }
Get-ChildItem -LiteralPath $expanded -File | Where-Object { $_.Name -eq 'tesseract.exe' -or $_.Extension -eq '.dll' } |
    Copy-Item -Destination $distribution -Force
Copy-Item -LiteralPath (Join-Path $expanded 'tessdata/eng.traineddata') -Destination (Split-Path $model) -Force
Copy-Item -LiteralPath (Join-Path $expanded 'doc') -Destination $distribution -Recurse -Force
$languages = & (Join-Path $distribution 'tesseract.exe') --tessdata-dir (Split-Path $model) --list-langs
if ($LASTEXITCODE -ne 0 -or 'eng' -notin $languages -or 'chi_sim' -notin $languages) {
    throw 'Bundled Tesseract could not load both language packs.'
}
$languages
