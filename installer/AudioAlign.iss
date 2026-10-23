; AudioAlign 安装器（Inno Setup 6）
; 编译：ISCC.exe installer\AudioAlign.iss
; 需要先生成 dist\AudioAlign（python tools\build_desktop.py）

#define MyAppName "AudioAlign"
#define MyAppVersion "0.1.0"
#define MyAppExe "AudioAlign.exe"

[Setup]
AppId={{B7F3E1C2-6D4A-4C2E-9F1B-2A8D5C7E4F10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=ONEBOXTOOL
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=AudioAlign-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "..\dist\AudioAlign\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "启动 AudioAlign"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
