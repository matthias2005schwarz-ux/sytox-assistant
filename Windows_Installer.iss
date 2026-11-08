; SYTOX Assistant per-user Inno Setup package; build the exe first on Windows.
; Keep AppId unchanged for all later releases, so upgrades replace this app.
#define MyAppName "SYTOX Assistant"
#define MyAppVersion "0.3.13"
#define MyAppExe "SYTOX_Assistant.exe"
[Setup]
AppId={{5D368754-1CC9-43F0-91B0-A8327A3DDC87}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=SYTOX
DefaultDirName={localappdata}\Programs\SYTOX Assistant
DefaultGroupName=SYTOX Assistant
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}
OutputDir=installer
OutputBaseFilename=SYTOX_Assistant_Setup_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
UsePreviousAppDir=yes
UsePreviousTasks=yes
CloseApplications=yes
RestartApplications=no
; When running, request that the user exit via tray before replacing any files.
AppMutex=Local\SYTOX_Assistant_8B5756C1
WizardStyle=modern
SetupIconFile=assets\sytox.ico
[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
[Files]
Source: "dist\SYTOX_Assistant\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; Flags: checkedonce
Name: "autostart"; Description: "Bei Windows-Anmeldung im Hintergrund starten"; Flags: unchecked
[Icons]
Name: "{group}\SYTOX Assistant"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\SYTOX Assistant"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; Tasks: desktopicon
[Registry]
; HKCU Run: runs as current user, no admin permissions; does not start the microphone.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SYTOX Assistant"; ValueData: """{app}\{#MyAppExe}"" --background"; Flags: uninsdeletevalue; Tasks: autostart
[Run]
Filename: "{app}\{#MyAppExe}"; Description: "SYTOX Assistant jetzt starten"; Flags: nowait postinstall skipifsilent
[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  { Upgrades must respect an unchecked autostart task even if it was enabled
    by a previous installation. The chats/settings folder is never touched. }
  if (CurStep = ssPostInstall) and (not WizardIsTaskSelected('autostart')) then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'SYTOX Assistant');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'SYTOX Assistant');
  { Settings, chats and workspace in APPDATA\SytoxAssistant are retained. }
end;
