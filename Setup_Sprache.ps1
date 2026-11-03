# Optional voice-model download. Vosk transcription remains entirely on this PC.
$ErrorActionPreference = 'Stop'
$ModelName = 'vosk-model-small-de-0.15'
$DataDir = Join-Path $env:APPDATA 'SytoxAssistant'
$ModelDir = Join-Path (Join-Path $DataDir 'models') $ModelName
$Zip = Join-Path $env:TEMP ($ModelName + '.zip')
if (Test-Path (Join-Path $ModelDir 'conf')) {
    Write-Host 'Deutsches Sprachmodell bereits installiert:' $ModelDir -ForegroundColor Green
    exit 0
}
New-Item -Force -ItemType Directory (Join-Path $DataDir 'models') | Out-Null
Write-Host 'Vosk-Deutsch-Modell: rund 45 MB Download von alphacephei.com.' -ForegroundColor Yellow
$answer = Read-Host 'Sprachmodell jetzt herunterladen? [j/N]'
if ($answer -notmatch '^[jJyY]') { Write-Host 'Abgebrochen.'; exit 0 }
$Url = 'https://alphacephei.com/vosk/models/vosk-model-small-de-0.15.zip'
try {
    Invoke-WebRequest -Uri $Url -OutFile $Zip -UseBasicParsing
    if ((Get-Item $Zip).Length -lt 1000000 -or (Get-Item $Zip).Length -gt 110000000) {
        throw 'Unerwartete Dateigroesse.'
    }
    Expand-Archive -LiteralPath $Zip -DestinationPath (Join-Path $DataDir 'models') -Force
    if (!(Test-Path (Join-Path $ModelDir 'conf'))) { throw 'Sprachmodell nicht vollstaendig entpackt.' }
    Write-Host 'Sprachmodell eingerichtet:' $ModelDir -ForegroundColor Green
    Write-Host 'SYTOX erkennt den Ordner beim naechsten Start automatisch, falls noch keiner gewaehlt wurde.'
} finally {
    Remove-Item -LiteralPath $Zip -Force -ErrorAction SilentlyContinue
}
