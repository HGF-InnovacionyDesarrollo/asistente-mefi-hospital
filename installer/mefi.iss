; Script de Inno Setup para el Asesor Clínico MEFI.
; Requiere haber construido el bundle antes:
;     python scripts/pipeline/build_portable.py
; Compilar (con Inno Setup instalado):
;     iscc installer\mefi.iss
; Produce dist\MEFI-Setup.exe — instalacion por usuario, sin administrador.

#define AppName "Asesor Clinico MEFI"
#define AppVersion "1.0"
#define Bundle "..\dist\MEFI-portable"

[Setup]
AppId={{8F3C1A90-2B7D-4E51-9A4C-6D2F8E05B113}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Hospital Dr. Gustavo Fricke
DefaultDirName={localappdata}\Programs\MEFI
DefaultGroupName=MEFI
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=MEFI-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\MEFI.bat
UninstallDisplayName={#AppName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos adicionales:"; Flags: unchecked

[Files]
Source: "{#Bundle}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\MEFI.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\MEFI.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\MEFI.bat"; Description: "Abrir el Asesor Clinico MEFI ahora"; Flags: nowait postinstall skipifsilent
