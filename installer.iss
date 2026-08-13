#define MyAppName "KeepAwake"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "KeepAwake"
#define MyAppExeName "KeepAwake.exe"

[Setup]
AppId={{7FD74F50-DF87-4EF2-9FD4-06E9B7CE2ED8}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
UsedUserAreasWarning=no
OutputDir=output
OutputBaseFilename=KeepAwakeSetup-v1.3
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "startup"; \
    Description: "Windows ile otomatik başlat"; \
    GroupDescription: "Başlangıç seçenekleri:"

[Files]
Source: "dist\KeepAwake\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
Root: HKCU; \
    Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; \
    ValueName: "KeepAwake"; \
    ValueData: """{app}\{#MyAppExeName}"" --background"; \
    Tasks: startup; \
    Flags: uninsdeletevalue

[Icons]
Name: "{group}\KeepAwake"; \
    Filename: "{app}\{#MyAppExeName}"

Name: "{group}\KeepAwake Kaldır"; \
    Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "KeepAwake'i şimdi çalıştır"; \
    Flags: nowait postinstall skipifsilent

; Sessiz kurulum yalnızca auto-updater'dan gelir: ayar penceresini
; göstermeden doğrudan tray'e dönmesi için --background ile açılır.
Filename: "{app}\{#MyAppExeName}"; \
    Parameters: "--background"; \
    Flags: nowait skipifnotsilent

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; \
    Parameters: "--quit"; \
    RunOnceId: "KeepAwakeQuit"; \
    Flags: runhidden waituntilterminated

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  SettingsPath: String;
  MessageText: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    RegDeleteValue(
      HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      'KeepAwake'
    );
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    SettingsPath := ExpandConstant('{userappdata}\KeepAwake');

    if DirExists(SettingsPath) then
    begin
      MessageText :=
        'KeepAwake kullanıcı ayarlarını da silmek ister misiniz?' +
        Chr(13) + Chr(10) +
        Chr(13) + Chr(10) +
        'Evet: ayarlar da silinir.' +
        Chr(13) + Chr(10) +
        'Hayır: daha sonra tekrar kurarsanız ayarlarınız korunur.';

      if MsgBox(
        MessageText,
        mbConfirmation,
        MB_YESNO
      ) = IDYES then
      begin
        DelTree(
          SettingsPath,
          True,
          True,
          True
        );
      end;
    end;
  end;
end;
