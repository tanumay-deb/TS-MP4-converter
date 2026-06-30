; Inno Setup script for TS to MP4 Converter.
; Build with: iscc installer.iss   (after PyInstaller has produced dist\TSConverter.exe)
; The app is a PyInstaller --onefile build, so the installer bundles a single exe
; (ffmpeg is already baked into it — nothing else to install).

#define AppName "TS to MP4 Converter"
; Overridable from the command line: iscc /DAppVersion=1.4.0 installer.iss
#ifndef AppVersion
  #define AppVersion "1.6.1"
#endif
#define AppPublisher "Tanumay Goswami"
#define AppExe "TSConverter.exe"
#define AppUrl "https://github.com/tanumay-deb/TS-MP4-converter"

[Setup]
AppId={{C7E4F1A8-2B9D-4A36-9F71-6D5C0E3B82A4}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
DefaultDirName={autopf}\TSConverter
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=dist\installer
OutputBaseFilename=TSConverter-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
SetupIconFile=assets\icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; the whole PyInstaller onedir tree (TSConverter.exe + _internal\ with ffmpeg etc.)
Source: "dist\TSConverter\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
