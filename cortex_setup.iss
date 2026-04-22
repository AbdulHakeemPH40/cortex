; Cortex AI IDE Setup Script
; Creates professional Windows installer with Next/Back wizard

#define MyAppName "Cortex AI Agent"
#define MyAppVersion "1.0.15"
#define MyAppPublisher "Cortex AI"
#define MyAppURL "https://github.com/cortex-ai"
#define MyAppExeName "Cortex.exe"

[Setup]
AppId=CORTEX-AI-IDE-2026-UNIQUE
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Cortex
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=.\installer_output
OutputBaseFilename=Cortex_Setup_v{#MyAppVersion}
SetupIconFile=src\assets\logo\logo.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; When PrivilegesRequired=lowest:
; - "Install for me only" = no admin prompt, installs to user folder
; - "Install for all users" = admin prompt, installs to Program Data
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=AI-Powered IDE for Developers
VersionInfoTextVersion={#MyAppVersion}
VersionInfoCopyright=Copyright (C) 2026 {#MyAppPublisher}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenuicon"; Description: "Create Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "Create Quick Launch shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Main executable and all files from dist\Cortex folder
Source: "dist\Cortex\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Configuration files
Source: ".env.example"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion

; License file (create this if you have one)
; Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion

; LSP servers - all installed for full language support
; Bundled via PyInstaller in dist\Cortex, no extra Inno Setup entries needed
; (pyright, typescript-language-server, bash-language-server, vscode-langservers-extracted)

[Icons]
; Start Menu shortcuts
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Desktop shortcut
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; Quick Launch shortcut
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
; Launch after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Messages]
; Custom message for Windows security warning
WelcomeLabel2=This will install [name] on your computer.%n%nNote: Windows may show a security warning during installation. If you see "Windows protected your PC", click "More info" then "Run anyway" to continue.%n%nIt is recommended that you close all other applications before continuing.

[Registry]
; Optional: Add to PATH (uncomment if needed)
; Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

; Right-click on a folder: "Open with Cortex IDE"
; Uses HKCU (user-level) instead of HKCR to work without admin privileges
Root: HKCU; Subkey: "Software\Classes\Directory\shell\CortexIDE"; ValueType: string; ValueName: ""; ValueData: "Open with Cortex IDE"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\CortexIDE"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\Cortex.exe"",0"
Root: HKCU; Subkey: "Software\Classes\Directory\shell\CortexIDE\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Cortex.exe"" ""%1"""

; Right-click on folder background (inside a folder): "Open with Cortex IDE"
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\CortexIDE"; ValueType: string; ValueName: ""; ValueData: "Open with Cortex IDE"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\CortexIDE"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\Cortex.exe"",0"
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\CortexIDE\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Cortex.exe"" ""%V"""

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath)
  then begin
    Result := true;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;
