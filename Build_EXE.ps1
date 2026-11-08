$ErrorActionPreference='Stop'
function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step fehlgeschlagen (Exitcode $LASTEXITCODE)." }
}
Set-Location $PSScriptRoot
if (!(Test-Path .venv\Scripts\python.exe)) { throw 'Erst Setup_Windows.ps1 ausfuehren' }
& .\.venv\Scripts\python.exe -m pip install "pyinstaller>=6.10,<7"
Assert-NativeSuccess 'PyInstaller installieren'
# Convert the user's first SYTOX image into a genuine multi-size Windows icon.
& .\.venv\Scripts\python.exe tools\build_icon.py --source assets\sytox-app.png --output assets\sytox.ico
Assert-NativeSuccess 'SYTOX App-Icon erzeugen'
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name SYTOX_Assistant --icon assets\sytox.ico --add-data 'assets;assets' --collect-all PySide6 --collect-all vosk --collect-all pywinauto --collect-all pyttsx3 --collect-all keyring --add-data 'sytox;source_bundle/sytox' --add-data 'tests;source_bundle/tests' --add-data 'main.py;source_bundle' --add-data 'README.md;source_bundle' --add-data 'requirements.txt;source_bundle' --add-data 'Build_EXE.ps1;source_bundle' --add-data 'Build_Installer.ps1;source_bundle' --add-data 'Installer_Install_Smoke_Test.ps1;source_bundle' --add-data 'Windows_Smoke_Test.ps1;source_bundle' --add-data 'Windows_Installer.iss;source_bundle' --add-data 'Setup_Windows.ps1;source_bundle' --add-data 'Setup_Sprache.ps1;source_bundle' --add-data 'Start_SYTOX.bat;source_bundle' --add-data 'tools;source_bundle/tools' --add-data '.github;source_bundle/.github' main.py
Assert-NativeSuccess 'Windows EXE erstellen'
if (!(Test-Path 'dist\SYTOX_Assistant\SYTOX_Assistant.exe')) { throw 'Build beendet, aber EXE nicht gefunden.' }
Write-Host 'Windows EXE: dist\SYTOX_Assistant\SYTOX_Assistant.exe' -ForegroundColor Green
