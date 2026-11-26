param([string]$TesseractDirectory)

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Push-Location $project
try {
    if ($TesseractDirectory) {
        $ocr = (Resolve-Path -LiteralPath $TesseractDirectory).Path
        foreach ($required in @('tesseract.exe', 'tessdata/eng.traineddata', 'tessdata/chi_sim.traineddata')) {
            if (-not (Test-Path -LiteralPath (Join-Path $ocr $required) -PathType Leaf)) {
                throw "Missing Tesseract distribution file: $required"
            }
        }
    }
    uv run --frozen --python 3.12 --group desktop pyinstaller --noconfirm --onedir `
        --name lifeos-sidecar --distpath desktop/dist --workpath desktop/build `
        --specpath desktop/build --paths src --add-data "$project/migrations;migrations" `
        --collect-data tzdata --hidden-import sqlalchemy.dialects.sqlite.pysqlite `
        --hidden-import ijson.backends.yajl2_c src/personal_ai_life_os/desktop.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    if ($TesseractDirectory) {
        # Keep OCR's OpenSSL DLLs out of PyInstaller's dependency resolution.
        Copy-Item -LiteralPath $ocr -Destination 'desktop/dist/lifeos-sidecar/_internal/tesseract' -Recurse
    }
} finally {
    Pop-Location
}
