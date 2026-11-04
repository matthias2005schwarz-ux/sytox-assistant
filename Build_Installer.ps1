<# Build current Windows EXE + per-user installer. Requires Python env + Inno Setup 6. #>
[CmdletBinding()]
param([switch]$SkipExeBuild)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if (-not $SkipExeBuild) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Build_EXE.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'EXE-Build fehlgeschlagen.' }
}
if (!(Test-Path 'dist\SYTOX_Assistant\SYTOX_Assistant.exe')) { throw 'EXE fehlt. Erst Build_EXE.ps1 ausfuehren.' }
$iscc=(Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
if (-not $iscc) {
    foreach ($candidate in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
        if ($candidate -and (Test-Path $candidate)) { $iscc=$candidate; break }
    }
}
if (-not $iscc) { throw 'Inno Setup 6 ist nicht installiert. Installer-Compiler: https://jrsoftware.org/isinfo.php' }
& $iscc (Join-Path $PSScriptRoot 'Windows_Installer.iss')
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fehlgeschlagen: $LASTEXITCODE" }
$installer=Join-Path $PSScriptRoot 'installer\SYTOX_Assistant_Setup_0.3.0.exe'
if (!(Test-Path $installer)) { throw "Installer-Ausgabe fehlt: $installer" }
Write-Host "Installer erstellt: $installer" -ForegroundColor Green
