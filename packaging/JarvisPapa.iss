#define MyAppName "Jarvis Papa"
#define MyAppVersion "0.6.0"
#define MyAppPublisher "Jarvis Papa"
#define MyAppExeName "Jarvis.exe"

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

[Files]
Source: "..\dist\Jarvis\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\JarvisNativeHost.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\JarvisDiagnostic.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\jarvis-papa-thunderbird.xpi"; DestDir: "{app}\Thunderbird"; Flags: ignoreversion
Source: "install_thunderbird_host.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\.env.example"; DestDir: "{localappdata}\JarvisPapa"; DestName: ".env"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "jarvis.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\Jarvis"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{userprograms}\Jarvis Papa\Jarvis"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{userprograms}\Jarvis Papa\Diagnostic Jarvis"; Filename: "{app}\JarvisDiagnostic.exe"; WorkingDir: "{app}"; IconFilename: "{app}\jarvis.ico"
Name: "{userprograms}\Jarvis Papa\Extension Thunderbird"; Filename: "{app}\Thunderbird"; WorkingDir: "{app}"
Name: "{userprograms}\Jarvis Papa\Désinstaller Jarvis"; Filename: "{uninstallexe}"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\install_thunderbird_host.ps1"" -InstallRoot ""{app}"""; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer Jarvis maintenant"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\install_thunderbird_host.ps1"" -InstallRoot ""{app}"" -Uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveJarvisThunderbirdHost"

[Messages]
WelcomeLabel1=Installation de Jarvis
WelcomeLabel2=Ce programme installe Jarvis comme une vraie application Windows. Aucun navigateur n'est nécessaire pour utiliser l'interface principale.%n%nL'installation prépare aussi le pont local Thunderbird.
FinishedHeadingLabel=Jarvis est installé
FinishedLabel=Jarvis est maintenant disponible depuis le Bureau et le menu Démarrer.
