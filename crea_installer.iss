#define MyAppVersion "1.10.0"
; Script Inno Setup per Gestionale Preventivi

[Setup]
AppName=Gestionale Preventivi
AppVersion={#MyAppVersion}
; <-- CORREZIONE: La riga AppId era malformattata
AppId={{1b225a05-a2de-4abe-bf8d-425ebb9bd47d}}
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

; La migrazione dei dati utente rimane identica, ed è corretta
Source: "data\*"; DestDir: "{userappdata}\GestionalePreventivi"; Excludes: "users.json, comuni.json, preventivi, allegati, clienti, gh_token.txt"; Flags: recursesubdirs createallsubdirs uninsneveruninstall

[Icons]
; L'eseguibile ora si chiama 'Gestionale.exe'
Name: "{group}\Avvia Gestionale Preventivi"; Filename: "{app}\Gestionale.exe"
Name: "{autodesktop}\Avvia Gestionale Preventivi"; Filename: "{app}\Gestionale.exe"; Tasks: desktopicon

[Run]
; Anche qui, il nome del file da avviare è cambiato
Filename: "{app}\Gestionale.exe"; Description: "{cm:LaunchProgram,Gestionale Preventivi}"; Flags: nowait postinstall