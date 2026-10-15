; Instalador de Sistema Inteligente Offline (Inno Setup 6).
; Se compila con build.ps1, que primero genera dist\SistemaDiagnostico con PyInstaller.
; Los datos del usuario (base de datos, reportes, copias y paquete de IA) viven en
; %APPDATA%\SistemaDiagnostico y no se tocan al actualizar.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Sistema Inteligente Offline"
#define AppExe "SistemaDiagnostico.exe"

[Setup]
AppId={{A06AF43C-01BD-419E-B808-7C53EF75A063}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\SistemaDiagnostico
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Sin permisos de administrador se instala solo para este usuario; el asistente permite elegir
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=dist\instalador
OutputBaseFilename=SistemaDiagnostico-Setup-{#AppVersion}
SetupIconFile=app\assets\icono.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; El programa crea este mutex: el instalador pide cerrarlo antes de actualizar o desinstalar
AppMutex=SistemaDiagnosticoMutex
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Al actualizar se eliminan los archivos de la versión anterior (los datos no están aquí)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\SistemaDiagnostico\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Datos: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Datos := ExpandConstant('{userappdata}\SistemaDiagnostico');
    if DirExists(Datos) and not UninstallSilent then
      if MsgBox('¿Desea eliminar también los datos del programa?' + #13#10#13#10 +
                'Se borrarán los casos, los reportes, las copias de seguridad y el paquete de IA de:' + #13#10 +
                Datos + #13#10#13#10 +
                'Si piensa volver a instalar el programa, elija No.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Datos, True, True, True);
  end;
end;
