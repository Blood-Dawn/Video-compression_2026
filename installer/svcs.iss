; installer/svcs.iss — Inno Setup script for the SVCS desktop installer (M2 TASK 2.4)
;
; Wraps the PyInstaller folder build (dist\SVCS\) into a single
; SVCS-Setup-<version>.exe that installs to Program Files, adds a Start Menu
; shortcut, launches the dashboard, and leaves user data in %APPDATA%\SVCS on
; uninstall.
;
; Build:  iscc installer\svcs.iss   (run AFTER  pyinstaller installer\svcs.spec)
;         -> dist\SVCS-Setup-<version>.exe
; Inno Setup is Windows-only and not in CI; build/test on Windows.
;
; The bundled FFmpeg (~243 MB, TASK 2.3) is a SEPARATE, optional component so a
; user who already has FFmpeg on PATH can skip it (the app's resolver falls back
; to PATH). The ONNX detector weights (~12 MB) stay in the main component.
;
; Author: Bloodawn (KheivenD), 2026-06-03 (TASK 2.4).

#define MyAppName "SVCS"
#define MyAppFullName "SVCS — Selective Video Compression System"
#define MyAppVersion "2.0.0.dev0"
#define MyAppPublisher "SVCS Project"
#define MyAppURL "https://github.com/Blood-Dawn/Video-compression_2026"
#define MyAppExeName "SVCS.exe"

[Setup]
; A stable AppId so upgrades replace the prior install (keep this GUID forever).
AppId={{8E2C1F4A-3B6D-4E2A-9C7F-5A1D0B2E6C44}
AppName={#MyAppName}
AppVerName={#MyAppFullName} {#MyAppVersion}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=SVCS-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Folder-mode PyInstaller build is x64; install into the 64-bit Program Files.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Writing to Program Files needs admin; the app itself runs as the user and
; writes its state to %APPDATA%\SVCS, so no elevation is needed at runtime.
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full";    Description: "Full installation (recommended)"
Name: "compact"; Description: "Compact — use a system FFmpeg on PATH"
Name: "custom";  Description: "Custom installation"; Flags: iscustom

[Components]
Name: "main";   Description: "SVCS dashboard + ONNX detector"; Types: full compact custom; Flags: fixed
Name: "ffmpeg"; Description: "Bundled FFmpeg (~243 MB) — uncheck to use a system FFmpeg on PATH"; Types: full

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Everything EXCEPT the bundled FFmpeg goes in the required "main" component.
Source: "..\dist\SVCS\*"; DestDir: "{app}"; \
    Excludes: "_internal\ffmpeg\*,_internal\src\gui\static\src\*"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
; The bundled FFmpeg is its own optional component.
Source: "..\dist\SVCS\_internal\ffmpeg\*"; DestDir: "{app}\_internal\ffmpeg"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; Components: ffmpeg

[Icons]
Name: "{group}\SVCS Dashboard"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SVCS Dashboard"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,SVCS Dashboard}"; \
    Flags: nowait postinstall skipifsilent

; App data under %LOCALAPPDATA%\SVCS (Flask secret, CPU benchmarks, saved
; destination prefs) is preserved by default across uninstall/reinstall. As of
; FIX 2 the uninstaller OFFERS to remove it (opt-in prompt) so a user can clear
; it deliberately. Compressed videos live in the user-chosen output folder and
; are never touched by the uninstaller.

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDataDir := ExpandConstant('{localappdata}\SVCS');
    if DirExists(AppDataDir) then
    begin
      if MsgBox('Also remove SVCS app data (settings, CPU benchmarks, encryption' + #13#10 +
                'key, and the saved output destination) from:' + #13#10 + AppDataDir + #13#10 + #13#10 +
                'Your compressed video files are stored separately and will NOT be' + #13#10 +
                'deleted. Remove app data?', mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(AppDataDir, True, True, True);
      end;
    end;
  end;
end;
