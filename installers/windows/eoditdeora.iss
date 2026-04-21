; Inno Setup installer script for 어딨더라 (Eoditdeora).
; Produces Eoditdeora-<ver>-setup.exe — a single double-clickable
; installer for Windows 10/11 x64. Run by CI (installers/windows/build-msi.ps1)
; after PyInstaller has frozen the launcher into dist\eoditdeora\.

#define AppId         "{{4B0F8B2E-4D6C-4E6E-9C1E-EODITDEORA-0001}"
#define AppName       "Eoditdeora"
#define AppDisplay    "어딨더라 (Eoditdeora)"
#define AppVersion    "1.0.0"
#define AppPublisher  "Eoditdeora Project"
#define AppUrl        "https://github.com/Cheol-H-Jeong/eoditdeora"
#define AppSupport    "https://github.com/Cheol-H-Jeong/eoditdeora/issues"
#define AppExeName    "eoditdeora.exe"
#define AppCopyright  "Copyright (C) 2026 Eoditdeora Contributors. AGPL-3.0-or-later."

[Setup]
AppId={#AppId}
AppName={#AppDisplay}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=Eoditdeora local document knowledge base installer
VersionInfoCopyright={#AppCopyright}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppSupport}
AppUpdatesURL={#AppUrl}/releases
AppContact=https://github.com/Cheol-H-Jeong
AppComments=Local-only personal document knowledge base with semantic search and strict-provenance RAG. Source code AGPL-3.0.
DefaultDirName={autopf}\Eoditdeora
DefaultGroupName=Eoditdeora
DisableProgramGroupPage=yes
OutputDir=..\..\installers\windows\out
OutputBaseFilename=Eoditdeora-{#AppVersion}-setup
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppDisplay}
SetupIconFile=icon.ico
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean";  MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕화면 바로가기 생성"; \
  GroupDescription: "추가 작업:"
Name: "autostart";   Description: "Windows 로그인 시 자동 시작"; \
  GroupDescription: "추가 작업:"; Flags: checkedonce

[Files]
; Launcher + all PyInstaller output
Source: "..\..\installers\windows\dist\eoditdeora\*"; \
  DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppDisplay}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppDisplay}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppDisplay}"; Filename: "{app}\{#AppExeName}"; \
  Tasks: desktopicon

[Registry]
; Autostart entry points to the installed executable so it survives upgrades.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "Eoditdeora"; \
  ValueData: """{app}\{#AppExeName}"" --autostart"; \
  Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExeName}"; \
  Description: "지금 어딨더라 실행"; \
  Flags: postinstall nowait skipifsilent unchecked

[UninstallDelete]
; Remove user-local cache that the installer itself did not place, but
; the app fills in: opt-in — only the install dir by default. The
; document index stays in %LOCALAPPDATA%\eoditdeora\ and is kept across
; uninstalls so users can reinstall and resume.
Type: filesandordirs; Name: "{app}"
