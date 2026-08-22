; Port Killer - Inno Setup Script
; Compile with: ISCC.exe setup.iss
; Download Inno Setup: https://jrsoftware.org/isdl.php

#define AppName "Port Killer"
; build.py passes /DAppVersion=<version> read from port_killer.py; the default
; below only matters when compiling this script by hand.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExeName "PortKiller.exe"
#define AppPublisher "Port Killer"

[Setup]
AppId={{7F3A2B1C-D4E5-4F6A-B7C8-D9E0F1A2B3C4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=Output
OutputBaseFilename=PortKiller_Setup_{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=port_killer.ico

[UninstallDelete]
; Pinned-port list written by the app at runtime.
Type: files; Name: "{userappdata}\.port_killer_pins.json"

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; PyInstaller already bundles Python + psutil — just ship the single .exe
Source: "..\..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";                         Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}";   Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}";                 Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent
