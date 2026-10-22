; Instalador de Sistema Inteligente Offline (Inno Setup 6).
; Se compila con build.ps1, que primero genera dist\SistemaDiagnostico con PyInstaller (con el colector
; de Windows en Colector y, si se generó en Linux, el de Linux en Colectores).
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
; Windows 10 1803 o posterior: trae .NET Framework 4.7.2+, que usa LibreHardwareMonitor (así Windows
; nunca pide instalar nada aparte)
MinVersion=10.0.17134
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
Type: filesandordirs; Name: "{app}\Colector"
Type: filesandordirs; Name: "{app}\Colectores"

[Files]
Source: "dist\SistemaDiagnostico\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Controlador de sensores PawnIO (temperatura de la CPU con LibreHardwareMonitor). Queda en la carpeta
; del programa para que la pantalla Escanear pueda instalarlo si aquí se canceló el permiso de Windows.
Source: "redist\PawnIO_setup.exe"; DestDir: "{app}\Controladores"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Instala PawnIO en silencio si falta. Un controlador requiere administrador: si la instalación es
; solo para el usuario, Windows pide confirmación únicamente para este paso.
Filename: "{app}\Controladores\PawnIO_setup.exe"; Parameters: "-install -silent"; Verb: "runas"; StatusMsg: "Instalando el controlador de sensores (PawnIO)..."; Flags: shellexec waituntilterminated runhidden; Check: not PawnIOInstalado
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// PawnIO se deja instalado al desinstalar: otros programas (LibreHardwareMonitor, OpenRGB...) también lo usan
function PawnIOInstalado: Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO',
                                'DisplayVersion', Version) and (Version <> '');
end;

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
