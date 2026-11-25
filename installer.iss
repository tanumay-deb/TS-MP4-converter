; Inno Setup script for TS to MP4 Converter.
; Build with: iscc installer.iss   (after PyInstaller has produced dist\TSConverter\)
; The app is a PyInstaller onedir build, so the installer bundles the whole app
; folder (TSConverter.exe + _internal\ with ffmpeg/ffprobe — nothing else to install).

#define AppName "TS to MP4 Converter"
; Overridable from the command line: iscc /DAppVersion=1.4.0 installer.iss
#ifndef AppVersion
  #define AppVersion "1.7.7"
#endif
#define AppPublisher "Tanumay Goswami"
#define AppExe "TSConverter.exe"
#define AppUrl "https://github.com/tanumay-deb/TS-MP4-converter"
; Uninstall survey: the feedback form's pre-filled link with the reason answer set to
; "Uninstalling" and the version answer last, its value cut off (AppVersion is appended).
; Same form as tsconverter/feedback.py. Empty = no survey.
#ifndef FeedbackUrl
  #define FeedbackUrl "https://docs.google.com/forms/d/e/1FAIpQLSfWqDBaixb86yIZpCTIWi7qgdc51QH50MmLIRZjrljdROA5mQ/viewform?usp=pp_url&entry.1901519186=Uninstalling&entry.645232226="
#endif

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
; For in-app self-update: close a running instance (Restart Manager) so files
; can be replaced; we relaunch the app ourselves.
CloseApplications=yes
RestartApplications=no
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

[Code]
// After a normal (not silent) uninstall, open the feedback form with "Uninstalling"
// preselected. Through explorer.exe so the browser runs as the user, not with the
// uninstaller's admin rights (ShellExecAsOriginalUser is not available at uninstall).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent and ('{#FeedbackUrl}' <> '') then
    Exec(ExpandConstant('{win}\explorer.exe'), '"{#FeedbackUrl}{#AppVersion}"', '',
         SW_SHOWNORMAL, ewNoWait, ResultCode);
end;
