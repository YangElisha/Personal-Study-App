; Inno Setup script for MonoSpace-Setup.exe. packaging\build.ps1 compiles it with:
;   ISCC.exe /DSourceDir=<PyInstaller onedir folder> /DOutDir=<folder> /DAppVersion=1.0.0 monospace.iss
; Per-user install (no admin) to %LOCALAPPDATA%\Programs\MonoSpace, Start menu entry, optional
; desktop icon. The uninstaller removes the program only: never the data folder (DATA_DIR),
; never %APPDATA%\MonoSpace\settings.env, never %LOCALAPPDATA%\MonoSpace (logs, window profile).

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\MonoSpace"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

[Setup]
AppId={{8C1F4E2A-5B7D-4C39-9E61-2F0A7D3B9C54}
AppName=MonoSpace
AppVersion={#AppVersion}
AppVerName=MonoSpace {#AppVersion}
AppPublisher=MonoSpace
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\MonoSpace
DefaultGroupName=MonoSpace
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=MonoSpace-Setup
SetupIconFile=..\assets\monospace.ico
UninstallDisplayIcon={app}\MonoSpace.exe
UninstallDisplayName=MonoSpace
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; the uninstall confirmation says what is (and is not) removed
ConfirmUninstall=This removes the MonoSpace program from this PC.%n%nYour decks, progress, backups and module PDFs (your MonoSpace data folder) and your MonoSpace settings are NOT removed.%n%nUninstall MonoSpace?

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\MonoSpace"; Filename: "{app}\MonoSpace.exe"; WorkingDir: "{app}"; Comment: "MonoSpace study app"
Name: "{userdesktop}\MonoSpace"; Filename: "{app}\MonoSpace.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\MonoSpace.exe"; Description: "Start MonoSpace now"; Flags: nowait postinstall skipifsilent

; Only the program's own files are removed ({app} as installed). Nothing under [UninstallDelete]:
; the data folder, settings.env and %LOCALAPPDATA%\MonoSpace stay.

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    MsgBox('MonoSpace has been removed.' + #13#10 + #13#10 +
      'Your data folder (decks, progress, backups, module PDFs) and your settings ' +
      '(%APPDATA%\MonoSpace\settings.env) were kept. Reinstall MonoSpace to use them again, ' +
      'or delete them yourself if you no longer need them.', mbInformation, MB_OK);
end;
