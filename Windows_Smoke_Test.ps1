<#
Non-destructive Windows verification.
- Requires a Windows Python virtualenv created by Setup_Windows.ps1.
- Runs Python component tests, real Win32 window enumeration/UIA import,
  and full Qt GUI startup using a temporary APPDATA profile.
- Optionally builds and starts the PyInstaller EXE.
- No automatic keyboard/mouse input or accounts are touched.
#>
[CmdletBinding()]
param(
    [switch]$BuildExe,
    [switch]$InteractiveDesktop
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') {
    throw 'Windows-Smoketests benoetigen Windows.'
}
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Zuerst Setup_Windows.ps1 auf Windows ausfuehren.' }

function Invoke-Native([string]$Description, [string]$Exe, [string[]]$Arguments) {
    Write-Host "[TEST] $Description" -ForegroundColor Cyan
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Description fehlgeschlagen (Exitcode $LASTEXITCODE)." }
}

$beforeAppData = $env:APPDATA
$beforeQtPlatform = $env:QT_QPA_PLATFORM
$beforePythonPath = $env:PYTHONPATH
$testHome = Join-Path ([IO.Path]::GetTempPath()) ('sytox_windows_test_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testHome -Force | Out-Null
try {
    $env:APPDATA = $testHome
    if ($env:GITHUB_ACTIONS -eq 'true') { $env:QT_QPA_PLATFORM = 'offscreen' }
    # Native Qt GUI tests must own their QApplication in isolated processes.
    # All 107 component tests and 6 Qt tests still run; none are skipped.
    Invoke-Native 'Python-Komponententests ohne native Qt-Fenster' $python @('tools/run_nonqt_tests.py')
    $env:PYTHONPATH = (Join-Path $PSScriptRoot 'tests') + ';' + $PSScriptRoot
    Invoke-Native 'Qt-Dialog/Setup-Thread-Tests' $python @('-m','unittest','-v','test_ollama_ui.OllamaAutoSetupQtTests')
    Invoke-Native 'Qt-Hauptfenster-Verbindungstests' $python @('-m','unittest','-v','test_ollama_ui.OllamaQtOnboardingTests')
    Invoke-Native 'Echte Win32-Fensterliste und UI-Automation laden' $python @('-c',
        "from sytox.pc_control import WindowsDesktop; from pywinauto import Desktop; wins = WindowsDesktop().windows(); print('Windows-Fenster gefunden:', len(wins)); assert isinstance(wins,list); Desktop(backend='uia'); print('Win32 + UIA OK')")
    Invoke-Native 'Vollstaendiger Qt-GUI-Start' $python @('main.py','--smoke-test')
    if ($InteractiveDesktop) {
        Invoke-Native 'Echte Eingabe nur in eigenes Testfenster' $python @('tools\windows_interactive_smoke.py')
    }
    if ($BuildExe) {
        $build = Join-Path $PSScriptRoot 'Build_EXE.ps1'
        Invoke-Native 'Windows-EXE bauen' 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',$build)
        $exe = Join-Path $PSScriptRoot 'dist\SYTOX_Assistant\SYTOX_Assistant.exe'
        if (-not (Test-Path -LiteralPath $exe)) { throw "Windows-EXE fehlt: $exe" }
        # PowerShell can return immediately for GUI-subsystem programs. Always
        # wait for the process and check its real exit code, not LASTEXITCODE.
        Write-Host '[TEST] Gebaute Windows-EXE starten' -ForegroundColor Cyan
        $process = Start-Process -FilePath $exe -ArgumentList '--smoke-test' -PassThru
        if (-not $process.WaitForExit(30000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw 'Windows-EXE-Smoketest hat sich nicht binnen 30 Sekunden beendet.'
        }
        if ($process.ExitCode -ne 0) {
            $report = Join-Path $testHome 'SytoxAssistant\startup_error.log'
            if (Test-Path -LiteralPath $report) { Get-Content -LiteralPath $report -Tail 50 }
            throw "Windows-EXE-Smoketest fehlgeschlagen (Exitcode $($process.ExitCode))."
        }
    }
    Write-Host '[OK] Alle angeforderten Windows-Tests erfolgreich.' -ForegroundColor Green
} finally {
    $env:APPDATA = $beforeAppData
    $env:QT_QPA_PLATFORM = $beforeQtPlatform
    $env:PYTHONPATH = $beforePythonPath
    Remove-Item -LiteralPath $testHome -Recurse -Force -ErrorAction SilentlyContinue
}
