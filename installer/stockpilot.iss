; Inno Setup 6/7 — instalador do StockPilot
; Compilar:  ISCC.exe /DAppVersion=0.1.0 installer\stockpilot.iss     (o build_windows.bat faz isso)
#ifndef AppVersion
  #define AppVersion "0.7.1"
#endif
#if AppVersion == ""
  #undef AppVersion
  #define AppVersion "0.7.1"
#endif
#define AppName "StockPilot"
#define AppExe "StockPilot.exe"

[Setup]
AppId={{8F3C2B1E-5D47-4A9B-9C0E-6B7D2A1F4E85}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=StockPilot
DefaultDirName={autopf}\StockPilot
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=StockPilot-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
; Atualizar por cima: o mesmo AppId substitui os arquivos do programa e NÃO toca nos dados do cliente.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\StockPilot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName} agora"; Flags: nowait postinstall skipifsilent

; Os dados do cliente ficam em %LOCALAPPDATA%\StockPilot (banco, backups, logs; instalações antigas: StockPilotAI) — FORA da pasta do programa.
; Por segurança o desinstalador NÃO apaga esses dados. Para removê-los, apague essa pasta manualmente.
[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    MsgBox('O programa foi removido. Seus dados (banco de dados e backups) foram MANTIDOS em:' + #13#10 +
           ExpandConstant('{localappdata}\StockPilot') + #13#10#13#10 +
           'Apague essa pasta somente se tiver certeza de que não precisa mais deles.', mbInformation, MB_OK);
end;
