#define MyAppName "Jarvis Papa"
#define MyAppVersion "0.7.0"
#define MyAppPublisher "Jarvis Papa"
#define MyAppExeName "JarvisPapa.exe"
#define MyAppUserModelID "JarvisPapa.Desktop"

[Setup]
AppId={{A52CC652-46EA-4A07-B32D-5E27C538C7DA}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Jarvis Papa
DefaultGroupName=Jarvis Papa
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\installer-output
OutputBaseFilename=JarvisPapa-Setup
SetupIconFile=jarvis.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
CloseApplications=yes
RestartApplications=no
ChangesAssociations=no
CreateUninstallRegKey=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Dirs]
Name: "{localappdata}\JarvisPapa"
Name: "{localappdata}\JarvisPapa\runtime"
Name: "{localappdata}\JarvisPapa\runtime\updates"

[Files]
Source: "..\dist\JarvisPapa\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\JarvisNativeHost.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\JarvisDiagnostic.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\jarvis-papa-thunderbird.xpi"; DestDir: "{app}\Thunderbird"; Flags: ignoreversion
Source: "install_thunderbird_host.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\scripts\validate_final_pc.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "jarvis.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\Jarvis"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"; AppUserModelID: "{#MyAppUserModelID}"
Name: "{userprograms}\Jarvis Papa\Jarvis"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"; AppUserModelID: "{#MyAppUserModelID}"
Name: "{userprograms}\Jarvis Papa\Diagnostic Jarvis"; Filename: "{app}\JarvisDiagnostic.exe"; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{userprograms}\Jarvis Papa\Validation complète du PC"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\validate_final_pc.ps1"" -JarvisExe ""{app}\{#MyAppExeName}"""; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{userprograms}\Jarvis Papa\Extension Thunderbird"; Filename: "{app}\Thunderbird"; WorkingDir: "{app}"
Name: "{userprograms}\Jarvis Papa\Désinstaller Jarvis"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Jarvis Papa"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\install_thunderbird_host.ps1"" -InstallRoot ""{app}"""; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer Jarvis maintenant"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\install_thunderbird_host.ps1"" -InstallRoot ""{app}"" -Uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveJarvisThunderbirdHost"

[Messages]
WelcomeLabel1=Installation de Jarvis
WelcomeLabel2=Ce programme installe Jarvis comme une vraie application Windows. Aucun navigateur ni fichier de configuration n'est nécessaire pour utiliser l'interface principale.%n%nL'installation prépare aussi le pont local Thunderbird et le démarrage automatique avec la session Windows.
FinishedHeadingLabel=Jarvis est installé
FinishedLabel=Jarvis est maintenant disponible depuis le Bureau et le menu Démarrer.

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  UpdateDir: String;
  CachedInstaller: String;
begin
  if CurStep = ssPostInstall then
  begin
    UpdateDir := ExpandConstant('{localappdata}\JarvisPapa\runtime\updates');
    if ForceDirectories(UpdateDir) then
    begin
      CachedInstaller := AddBackslash(UpdateDir) + 'current-installer.exe';
      if not CopyFile(ExpandConstant('{srcexe}'), CachedInstaller, False) then
        Log('Jarvis warning: current installer could not be cached for rollback.');
    end
    else
      Log('Jarvis warning: update cache directory could not be created.');
  end;
end;
