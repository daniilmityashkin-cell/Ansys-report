; Inno Setup 6 script: builds AnsysReport_Setup.exe from dist\AnsysReport
#define AppName "Ansys Report"
#define AppVersion "0.9.0"
#define AppExe "AnsysReport.exe"

[Setup]
AppId={{6B2B1C7E-5D0A-4E0B-9C57-3A1F7E3A9A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Ansys Report
DefaultDirName={autopf}\AnsysReport
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=AnsysReport_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Files]
Source: "..\dist\AnsysReport\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent
