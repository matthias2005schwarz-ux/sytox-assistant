$ErrorActionPreference='Stop'
function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step fehlgeschlagen (Exitcode $LASTEXITCODE)." }
}
Set-Location $PSScriptRoot
Write-Host '=== SYTOX Assistant: Windows Setup ===' -ForegroundColor Magenta
$py=Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & py -3 -m venv .venv
    Assert-NativeSuccess 'Python-Umgebung erstellen'
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m venv .venv
    Assert-NativeSuccess 'Python-Umgebung erstellen'
} else {
    Write-Host 'Python 3.11+ erforderlich: https://www.python.org/downloads/windows/' -ForegroundColor Yellow
    exit 1
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
Assert-NativeSuccess 'pip aktualisieren'
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
Assert-NativeSuccess 'Abhaengigkeiten installieren'
Write-Host 'Installiere Playwright Chromium fuer den eigenen Browser-Login ...' -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m playwright install chromium
Assert-NativeSuccess 'Playwright Chromium installieren'
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host 'Ollama gefunden.' -ForegroundColor Green
    $pull=Read-Host 'KI-Modell qwen2.5-coder:7b jetzt herunterladen (mehrere GB)? [j/N]'
    if ($pull -match '^[jJyY]') {
        & ollama pull qwen2.5-coder:7b
        Assert-NativeSuccess 'KI-Modell herunterladen'
    }
} else {
    Write-Host 'Ollama fehlt. Bitte installieren: https://ollama.com/download/windows' -ForegroundColor Yellow
    Write-Host 'Anschliessend: ollama pull qwen2.5-coder:7b' -ForegroundColor Yellow
}
$speech = Read-Host 'Lokales deutsches Sprachmodell fuer den Gespraechsmodus installieren? [j/N]'
if ($speech -match '^[jJyY]') {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Setup_Sprache.ps1')
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Sprachmodell konnte nicht installiert werden. Setup der restlichen App bleibt erhalten.' }
}
Write-Host 'Setup abgeschlossen. Start: Start_SYTOX.bat' -ForegroundColor Green
