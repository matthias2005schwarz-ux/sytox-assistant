<#
Validate a compiled Inno Setup package on an ISOLATED Windows CI runner.
This is NOT safe to run on an ordinary machine with an existing installation.
Creates a temporary install, executes the INSTALLED EXE, checks user-data retention,
and uninstalls silently. Does not interact with credentials or a real user profile.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'Installer integration tests are restricted to isolated GitHub Actions Windows runners.'
}
Set-Location $PSScriptRoot

# Never let a broken GUI or Inno uninstaller hang an unattended Windows build.
function Invoke-BoundedProcess([string]$Executable, [string[]]$Arguments,
                               [int]$TimeoutSeconds, [string]$Description) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -PassThru
    try {
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            # Kill children too (e.g. spawned runtime subprocesses), on the isolated CI runner.
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
            throw "${Description}: Zeitlimit von $TimeoutSeconds Sekunden ueberschritten."
        }
        if ($process.ExitCode -ne 0) {
            throw "${Description}: Exitcode $($process.ExitCode)."
        }
    } finally {
        $process.Dispose()
    }
}

$installer = Join-Path $PSScriptRoot 'installer\SYTOX_Assistant_Setup_0.3.4.exe'
if (-not (Test-Path -LiteralPath $installer)) { throw "Installer fehlt: $installer" }
$testRoot = Join-Path $env:RUNNER_TEMP ('sytox_install_test_' + [guid]::NewGuid().ToString('N'))
$installDir = Join-Path $testRoot 'Program'
$userData = Join-Path $testRoot 'Profile'
New-Item -ItemType Directory -Path $installDir, $userData -Force | Out-Null
$previousAppData = $env:APPDATA
$previousQtPlatform = $env:QT_QPA_PLATFORM
$uninstaller = Join-Path $installDir 'unins000.exe'
try {
    Write-Host '[TEST] Installiere in temporaeren CI-Ordner ...'
    $installArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
                     "/DIR=`"$installDir`"", '/MERGETASKS=!desktopicon,!autostart')
    Invoke-BoundedProcess $installer $installArgs 180 'Installer' 

    $exe = Join-Path $installDir 'SYTOX_Assistant.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw "Installierte EXE fehlt: $exe" }
    if (-not (Test-Path -LiteralPath $uninstaller)) { throw "Uninstaller fehlt: $uninstaller" }

    $env:APPDATA = $userData
    $env:QT_QPA_PLATFORM = 'offscreen'  # GitHub runners do not guarantee an interactive desktop.
    Write-Host '[TEST] Starte installierte GUI-EXE mit --smoke-test ...'
    try {
        Invoke-BoundedProcess $exe @('--smoke-test') 45 'Installierte EXE'
    } catch {
        $report = Join-Path $userData 'SytoxAssistant\startup_error.log'
        if (Test-Path -LiteralPath $report) { Get-Content -LiteralPath $report -Tail 50 }
        throw
    }

    $dataDir = Join-Path $userData 'SytoxAssistant'
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    $marker = Join-Path $dataDir 'preserve_on_uninstall.txt'
    Set-Content -LiteralPath $marker -Value 'keep-me' -Encoding UTF8

    Write-Host '[TEST] Deinstalliere ohne Loeschen der Benutzerdaten ...'
    Invoke-BoundedProcess $uninstaller @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') 120 'Deinstallation' 
    if (-not (Test-Path -LiteralPath $marker)) { throw 'Deinstallation hat Benutzerdaten geloescht.' }
    if (Test-Path -LiteralPath $exe) { throw 'Installierte EXE ist nach Deinstallation noch vorhanden.' }
    Write-Host '[OK] Installer, installierte EXE, Uninstaller und Datenbeibehaltung geprueft.' -ForegroundColor Green
} finally {
    $env:APPDATA = $previousAppData
    $env:QT_QPA_PLATFORM = $previousQtPlatform
    # On a failed test, do not silently leave the temporary application installed.
    if (Test-Path -LiteralPath $uninstaller) {
        try { Invoke-BoundedProcess $uninstaller @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') 120 'Cleanup-Deinstallation' }
        catch { Write-Warning "Test-Uninstaller konnte nicht ausgefuehrt werden: $_" }
    }
    Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction SilentlyContinue
}
