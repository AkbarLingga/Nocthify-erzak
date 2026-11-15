; Nocthify installer (Inno Setup 6). Built by build.py, which passes:
;   /DAppVersion=x.y.z  /DSourceDir=...\dist\Nocthify  /DIconFile=...\nocthify.ico  /DOutputDir=...\release
; Per-user install: no admin prompt, no Python, no PowerShell needed on the target PC.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E3B0F4A-6C1D-4B8E-9A57-2D9C0F1E7A31}
AppName=Nocthify
AppVersion={#AppVersion}
AppVerName=Nocthify {#AppVersion}
AppPublisher=AkbarLingga
AppPublisherURL=https://github.com/AkbarLingga/Nocthify-erzak
DefaultDirName={autopf}\Nocthify
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; the bundled Python 3.12 runtime needs Windows 8.1 or newer
MinVersion=6.3
OutputDir={#OutputDir}
OutputBaseFilename=NocthifySetup-{#AppVersion}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Nocthify.exe
UninstallDisplayName=Nocthify
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; an upgrade must not leave the previous build's libraries behind
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Nocthify"; Filename: "{app}\Nocthify.exe"
Name: "{autoprograms}\Nocthify - Restore Windows taskbar"; Filename: "{app}\Nocthify.exe"; Parameters: "--restore-taskbar"
Name: "{autodesktop}\Nocthify"; Filename: "{app}\Nocthify.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Nocthify.exe"; Description: "Start Nocthify now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; quit the running copy and give the user their Windows taskbar back
Filename: "{app}\Nocthify.exe"; Parameters: "--restore-taskbar"; Flags: runhidden waituntilterminated; RunOnceId: "RestoreTaskbar"

[Code]
procedure QuitRunningNocthify();
var
  Code: Integer;
  Exe: String;
begin
  { works for an installed copy and for a copy started from the source folder:
    --quit is delivered to whichever Nocthify is running }
  Exe := ExpandConstant('{app}\Nocthify.exe');
  if FileExists(Exe) then
  begin
    Exec(Exe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Sleep(1500);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  QuitRunningNocthify();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    { Nocthify registers its own autostart entry; remove it with the app }
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Nocthify');
end;
