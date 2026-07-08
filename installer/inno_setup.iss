#define MyAppName "RePhiEdit Auto Chart Assistant"
#define MyAppDisplayName "Re:PhiEdit Auto Chart Assistant"
#define MyAppSafeName "RePhiEdit Auto Chart Assistant"
#define MyAppSafeId "RePhiEditAutoChartAssistant"
#define MyAppVersion "2.5.2"
#define MyAppPublisher "Jiayi Huang"
#define MyAppURL "https://github.com/"
#define MyAppExeName "RePhiEditAutoChartAssistant.exe"
#ifndef SourceDir
#define SourceDir "..\dist\RePhiEditAutoChartAssistant"
#endif
#ifndef OutputDir
#define OutputDir "..\Release"
#endif
#define MyAppIcon "..\assets\windows\app_icon.ico"

[Setup]
AppId={{7C25FE6D-1F26-4D94-B29E-A6F5136A5D66}
AppName={#MyAppDisplayName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppDisplayName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppSafeName}
DefaultGroupName={#MyAppSafeName}
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=Setup
SetupIconFile={#MyAppIcon}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppDisplayName}
PrivilegesRequired=admin
UsedUserAreasWarning=no
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppDisplayName} Installer
VersionInfoProductName={#MyAppDisplayName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checkedonce
Name: "associatepez"; Description: "Associate .pez files with Chart Analyzer"; GroupDescription: "File associations:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\windows\app_icon.ico"; DestDir: "{app}\assets\windows"; Flags: ignoreversion
Source: "..\assets\windows\ffmpeg.exe"; DestDir: "{app}\assets\windows"; Flags: ignoreversion

[Dirs]
Name: "{localappdata}\RePhiEditAutoChart"
Name: "{localappdata}\RePhiEditAutoChart\config"
Name: "{localappdata}\RePhiEditAutoChart\cache"
Name: "{localappdata}\RePhiEditAutoChart\logs"
Name: "{localappdata}\RePhiEditAutoChart\outputs"
Name: "{localappdata}\RePhiEditAutoChart\temp"

[Icons]
Name: "{autoprograms}\{#MyAppSafeName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\windows\app_icon.ico"; Comment: "{#MyAppDisplayName}"
Name: "{autodesktop}\{#MyAppSafeName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\windows\app_icon.ico"; Comment: "{#MyAppDisplayName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\.pez"; ValueType: string; ValueName: ""; ValueData: "RePhiEditAutoChart.PEZ"; Flags: uninsdeletevalue; Tasks: associatepez
Root: HKCU; Subkey: "Software\Classes\RePhiEditAutoChart.PEZ"; ValueType: string; ValueName: ""; ValueData: "Re:PhiEdit PEZ Package"; Flags: uninsdeletekey; Tasks: associatepez
Root: HKCU; Subkey: "Software\Classes\RePhiEditAutoChart.PEZ\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\assets\windows\app_icon.ico"; Tasks: associatepez
Root: HKCU; Subkey: "Software\Classes\RePhiEditAutoChart.PEZ\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associatepez
Root: HKCU; Subkey: "Software\Jiayi Huang\{#MyAppSafeName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppDisplayName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function IsVCRuntimeInstalled(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', Version) or
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', Version);
end;

function RunPowerShell(Args: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Args, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function InstallVCRuntime(): Boolean;
var
  TempFile: String;
  Args: String;
  ResultCode: Integer;
begin
  TempFile := ExpandConstant('{tmp}\vc_redist.x64.exe');
  Args := '-NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri https://aka.ms/vs/17/release/vc_redist.x64.exe -OutFile ''' + TempFile + '''"';
  if not RunPowerShell(Args) then
  begin
    MsgBox('Microsoft Visual C++ Runtime is missing and could not be downloaded. Check your network connection and run Setup again.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;
  Result := Exec(TempFile, '/install /quiet /norestart', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function CheckWritable(Path: String): Boolean;
var
  Probe: String;
begin
  ForceDirectories(Path);
  Probe := AddBackslash(Path) + 'write_test.tmp';
  Result := SaveStringToFile(Probe, 'ok', False);
  if Result then
    DeleteFile(Probe);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not IsWin64 then
  begin
    MsgBox('This release supports Windows 10/11 x64-compatible systems only.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;
  if not CheckWritable(ExpandConstant('{localappdata}\RePhiEditAutoChart')) then
  begin
    MsgBox('Setup cannot write to LocalAppData. Please run Setup with a normal user profile.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;
  if not CheckWritable(ExpandConstant('{userdocs}')) then
  begin
    MsgBox('Setup cannot write to Documents. Check folder permissions before installing.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;
  if not CheckWritable(ExpandConstant('{userdesktop}')) then
  begin
    MsgBox('Setup cannot write to Desktop. Check folder permissions before installing.', mbCriticalError, MB_OK);
    Result := False;
    exit;
  end;
  if not IsVCRuntimeInstalled() then
  begin
    if MsgBox('Microsoft Visual C++ Runtime is missing. Setup will download and install it now.', mbInformation, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := False;
      exit;
    end;
    Result := InstallVCRuntime();
  end;
end;
