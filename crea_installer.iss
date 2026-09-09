#define MyAppVersion "2.4.4"
; Script Inno Setup per Gestionale Preventivi

[Setup]
AppName=Gestionale Preventivi
AppVersion={#MyAppVersion}
; <-- CORREZIONE: La riga AppId era malformattata
AppId={{5ce91cd0-86eb-44e7-8f20-d7be25228cc3}}
AppPublisher=Cerlab srls
UninstallDisplayIcon={app}\Gestionale.exe
DefaultDirName={autopf}\Gestionale Preventivi
DefaultGroupName=Gestionale Preventivi
PrivilegesRequired=admin
CloseApplications=force
OutputDir=userdesktop
OutputBaseFilename=setup_gestionale_preventivi_{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}";

[Files]
; La cartella di output di PyInstaller ora si chiama 'Gestionale'
Source: "dist\Gestionale\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

Source: "version.txt"; DestDir: "{userappdata}\gestionalepreventivi"; Flags: ignoreversion

; NUOVO: Modelli Excel per analisi e cashflow
Source: "modello cashflow.xlsx"; DestDir: "{userappdata}\gestionalepreventivi\templates"; Flags: ignoreversion
Source: "template_analisi.xlsx"; DestDir: "{userappdata}\gestionalepreventivi\templates"; Flags: ignoreversion

; La migrazione dei dati utente rimane identica, ed è corretta
Source: "data\*"; DestDir: "{userappdata}\GestionalePreventivi"; Excludes: "users.json, tasks.json, comuni.json, preventivi, allegati, clienti, gh_token.txt,tagbox.json,notifications.json,messages.json,pdf_generation.log"; Flags: recursesubdirs createallsubdirs uninsneveruninstall

[Icons]
; L'eseguibile ora si chiama 'Gestionale.exe'
Name: "{group}\Avvia Gestionale Preventivi"; Filename: "{app}\Gestionale.exe"
Name: "{autodesktop}\Avvia Gestionale Preventivi"; Filename: "{app}\Gestionale.exe"; Tasks: desktopicon

[Run]
; Anche qui, il nome del file da avviare è cambiato
Filename: "{app}\Gestionale.exe"; Description: "{cm:LaunchProgram,Gestionale Preventivi}"; Flags: nowait postinstall

[Code]
// GUID univoco e permanente del programma
const
  CurrentAppIdKey = '{5ce91cd0-86eb-44e7-8f20-d7be25228cc3}_is1';

// Rimuove vecchie chiavi di disinstallazione duplicate dal registro di Windows
procedure CleanUninstallKeysInRoot(RootKey: Integer; BaseSubKey: String);
var
  SubKeys: TArrayOfString;
  I: Integer;
  SubKeyPath: String;
  DisplayName: String;
  AppPath: String;
  InstallLocation: String;
  UninstallString: String;
  TargetAppDir: String;
begin
  if not RegGetSubkeyNames(RootKey, BaseSubKey, SubKeys) then
    Exit;

  TargetAppDir := ExpandConstant('{app}');

  for I := 0 to GetArrayLength(SubKeys) - 1 do
  begin
    // Ignora la voce ufficiale corrente
    if CompareText(SubKeys[I], CurrentAppIdKey) <> 0 then
    begin
      SubKeyPath := BaseSubKey + '\' + SubKeys[I];
      DisplayName := '';
      AppPath := '';
      InstallLocation := '';
      UninstallString := '';

      RegQueryStringValue(RootKey, SubKeyPath, 'DisplayName', DisplayName);
      RegQueryStringValue(RootKey, SubKeyPath, 'Inno Setup: App Path', AppPath);
      RegQueryStringValue(RootKey, SubKeyPath, 'InstallLocation', InstallLocation);
      RegQueryStringValue(RootKey, SubKeyPath, 'UninstallString', UninstallString);

      // Se la chiave appartiene a Gestionale Preventivi (ma ha un vecchio GUID diverso)
      if (Pos('Gestionale Preventivi', DisplayName) > 0) or
         ((AppPath <> '') and (CompareText(AppPath, TargetAppDir) = 0)) or
         ((InstallLocation <> '') and (CompareText(InstallLocation, TargetAppDir) = 0)) or
         ((UninstallString <> '') and (Pos('Gestionale Preventivi', UninstallString) > 0)) then
      begin
        Log('Rimozione vecchia registrazione di disinstallazione orfana: ' + SubKeys[I]);
        RegDeleteKeyIncludingSubkeys(RootKey, SubKeyPath);
      end;
    end;
  end;
end;

procedure CleanAllOldUninstallKeys();
var
  UninstallPath: String;
begin
  UninstallPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall';
  CleanUninstallKeysInRoot(HKLM, UninstallPath);
  CleanUninstallKeysInRoot(HKCU, UninstallPath);
  if IsWin64 then
  begin
    CleanUninstallKeysInRoot(HKLM64, UninstallPath);
    CleanUninstallKeysInRoot(HKCU64, UninstallPath);
  end;
end;

// Elimina eventuali vecchi file di disinstallazione orfani (es. unins001.exe, unins001.dat)
procedure CleanOldUninstallerFiles();
var
  AppDir: String;
  FindRec: TFindRec;
begin
  AppDir := ExpandConstant('{app}');
  if DirExists(AppDir) then
  begin
    if FindFirst(AppDir + '\unins*.*', FindRec) then
    begin
      try
        repeat
          DeleteFile(AppDir + '\' + FindRec.Name);
        until not FindNext(FindRec);
      finally
        FindClose(FindRec);
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    // Eseguito prima della copia dei nuovi file e della registrazione dell'uninstaller
    CleanAllOldUninstallKeys();
    CleanOldUninstallerFiles();
    // Pulisce la cartella _internal precedente per eliminare file/librerie orfane o incompatibili
    if DirExists(ExpandConstant('{app}\_internal')) then
    begin
      DelTree(ExpandConstant('{app}\_internal'), True, True, True);
    end;
  end;
end;