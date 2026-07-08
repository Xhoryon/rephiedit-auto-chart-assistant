[CmdletBinding()]
param(
    [Parameter()]
    [string]$ReleaseDir = "Release",
    [Parameter()]
    [switch]$NoSmokeTest
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$checks = New-Object System.Collections.Generic.List[string]

function Add-Check($Name, $Ok) {
    if ($Ok) {
        $script:checks.Add("[OK] $Name")
    } else {
        throw "[FAIL] $Name"
    }
}

function Resolve-PortableBundledFile($Portable, $RelativePath) {
    $internal = Join-Path $Portable "_internal"
    $candidates = @(
        (Join-Path $Portable $RelativePath),
        (Join-Path $internal $RelativePath)
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Add-BundledFileCheck($Portable, $RelativePath) {
    $found = Resolve-PortableBundledFile $Portable $RelativePath
    if ($found) {
        $script:checks.Add("[OK] Portable contains $RelativePath ($found)")
    } else {
        $rootPath = Join-Path $Portable $RelativePath
        $internalPath = Join-Path (Join-Path $Portable "_internal") $RelativePath
        throw "[FAIL] Portable contains $RelativePath; checked $rootPath and $internalPath"
    }
}

function Invoke-PortableSmokeCheck($Exe) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = "--smoke-check"
    $psi.WorkingDirectory = [System.IO.Path]::GetTempPath()
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    if (-not $process.Start()) {
        throw "[FAIL] Portable EXE smoke check could not start"
    }
    if (-not $process.WaitForExit(30000)) {
        try { $process.Kill() } catch {}
        throw "[FAIL] Portable EXE smoke check timed out after 30 seconds"
    }
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if ($process.ExitCode -ne 0) {
        throw "[FAIL] Portable EXE smoke check failed with exit code $($process.ExitCode). $stdout $stderr"
    }
    $script:checks.Add("[OK] Portable EXE smoke check exits successfully without relying on current working directory")
}

try {
    if ($ReleaseDir -like "-*") {
        throw "ReleaseDir value looks like a switch name ('$ReleaseDir'). Check caller parameter binding."
    }
    $RequestedRelease = if ([System.IO.Path]::IsPathRooted($ReleaseDir)) { $ReleaseDir } else { Join-Path $RepoRoot $ReleaseDir }
    $ReleasePath = Resolve-Path -Path $RequestedRelease -ErrorAction SilentlyContinue
    if (-not $ReleasePath) {
        throw "Release directory not found: $ReleaseDir"
    }

    $ReleasePath = $ReleasePath.Path
    $Setup = Join-Path $ReleasePath "Setup.exe"
    $Portable = Join-Path $ReleasePath "Portable"
    $Exe = Join-Path $Portable "RePhiEditAutoChartAssistant.exe"
    $Icon = Join-Path $Portable "app_icon.ico"
    $Internal = Join-Path $Portable "_internal"

    Add-Check "Release directory exists" (Test-Path $ReleasePath)
    Add-Check "Portable directory exists" (Test-Path $Portable)
    Add-Check "Portable EXE exists" (Test-Path $Exe)
    Add-Check "Portable icon exists" (Test-Path $Icon)
    Add-Check "Portable includes bundled Python runtime" ((Get-ChildItem -Path $Portable -Recurse -Filter "python*.dll" -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
    Add-Check "Portable includes DLL dependencies" ((Get-ChildItem -Path $Portable -Recurse -Filter "*.dll" -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
    Add-Check "Portable includes PyInstaller internal runtime directory" (Test-Path $Internal)

    if (Test-Path $Setup) {
        Add-Check "Installer Setup.exe exists" $true
    } else {
        Write-Warning "Setup.exe not found. This is expected only when -SkipInstaller is used or Inno Setup is unavailable."
    }

    if (Test-Path $Exe) {
        $version = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($Exe)
        Add-Check "EXE ProductName metadata" ($version.ProductName -like "*Auto Chart Assistant*")
        Add-Check "EXE version is 2.5.2" ($version.ProductVersion -like "2.5.2*")
    }

    Add-BundledFileCheck $Portable "assets\windows\ffmpeg.exe"
    $script:checks.Add("[OK] Portable includes bundled ffmpeg")

    foreach ($file in @(
        "config\default_config.json",
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "docs\ALGORITHM.md",
        "docs\V2_SUMMARY.md",
        "docs\V3_PLAN.md"
    )) {
        Add-BundledFileCheck $Portable $file
    }

    $BundledConfig = Resolve-PortableBundledFile $Portable "config\default_config.json"
    if ($BundledConfig) {
        $null = Get-Content $BundledConfig -Raw | ConvertFrom-Json
        Add-Check "Bundled default config is valid JSON" $true
    }

    if (-not $NoSmokeTest) {
        Invoke-PortableSmokeCheck $Exe
    }

    $Iss = Join-Path $RepoRoot "installer\inno_setup.iss"
    Add-Check "Installer script exists" (Test-Path $Iss)
    $IssText = Get-Content $Iss -Raw
    Add-Check "Installer creates desktop shortcut" ($IssText -match "autodesktop")
    Add-Check "Installer creates start menu shortcut" ($IssText -match "autoprograms")
    Add-Check "Installer checks VC Runtime" ($IssText -match "IsVCRuntimeInstalled")
    Add-Check "Installer supports uninstall metadata" ($IssText -match "UninstallDisplayName")
    Add-Check "Installer has icon" ($IssText -match "SetupIconFile")
    Add-Check "Installer defines branded display name" ($IssText -match 'MyAppDisplayName "Re:PhiEdit Auto Chart Assistant"')
    Add-Check "Installer defines filesystem-safe name" ($IssText -match 'MyAppSafeName "RePhiEdit Auto Chart Assistant"')
    Add-Check "Install directory uses safe name" ($IssText -match 'DefaultDirName=\{autopf\}\\\{#MyAppSafeName\}')
    Add-Check "Start menu folder uses safe name" ($IssText -match 'DefaultGroupName=\{#MyAppSafeName\}')
    Add-Check "Shortcut filesystem names use safe name" ($IssText -match 'Name: "\{autoprograms\}\\\{#MyAppSafeName\}"' -and $IssText -match 'Name: "\{autodesktop\}\\\{#MyAppSafeName\}"')
    Add-Check "Installer copies complete PyInstaller directory" ($IssText -match 'Source: "\{#SourceDir\}\\\*"')
    Add-Check "Installer does not require target Python" ($IssText -notmatch "Python 3.12")
    Add-Check "Installer does not pip install on target" ($IssText -notmatch "pip install")

    $Spec = Join-Path $RepoRoot "packaging\windows\RePhiEditAutoChartAssistant.spec"
    Add-Check "PyInstaller spec exists" (Test-Path $Spec)
    $SpecText = Get-Content $Spec -Raw
    Add-Check "PyInstaller bundles default config" ($SpecText -match "default_config\.json")
    Add-Check "PyInstaller bundles ffmpeg" ($SpecText -match "ffmpeg.exe")
    foreach ($dependency in @("numpy", "scipy", "soundfile", "librosa", "PIL", "matplotlib")) {
        Add-Check "PyInstaller collects $dependency" ($SpecText -match $dependency)
    }
    foreach ($excluded in @("numpy.f2py.tests", "numpy.tests", "scipy.tests", "librosa.tests", "matplotlib.tests", "pytest", '"test"', '"tests"')) {
        Add-Check "PyInstaller excludes $excluded" ($SpecText -match [regex]::Escape($excluded))
    }

    $BuildRelease = Get-Content (Join-Path $RepoRoot "scripts\build_release.ps1") -Raw
    Add-Check "Normal release build preserves venv" ($BuildRelease -match "preserving .venv-windows-build")
    Add-Check "Clean release build can remove venv" ($BuildRelease -match "Clean rebuild requested")
    Add-Check "Release build runs release_check" ($BuildRelease -match "release_check\.ps1")

    $BuildExe = Get-Content (Join-Path $RepoRoot "scripts\build_windows_exe.ps1") -Raw
    Add-Check "EXE build uses native command wrapper" ($BuildExe -match "function Invoke-Native")
    Add-Check "EXE build avoids pip show" ($BuildExe -notmatch "pip show")

    $Runtime = Get-Content (Join-Path $RepoRoot "rephi_auto_chart\runtime.py") -Raw
    Add-Check "Runtime supports PyInstaller _MEIPASS resources" ($Runtime -match "_MEIPASS")
    Add-Check "Runtime checks PyInstaller _internal resources" ($Runtime -match "_internal")
    Add-Check "Runtime defines Documents chart export folder" ($Runtime -match "RePhiEdit Charts")
    Add-Check "Runtime can locate bundled ffmpeg" ($Runtime -match "find_ffmpeg" -and $Runtime -match "assets/windows/ffmpeg.exe")

    $Gui = Get-Content (Join-Path $RepoRoot "rephi_auto_chart\gui.py") -Raw
    $SourceConfig = Get-Content (Join-Path $RepoRoot "config\default_config.json") -Raw | ConvertFrom-Json
    Add-Check "GUI does not default to relative outputs" ($Gui -notmatch "outputs/generated")
    Add-Check "Bundled config does not default to relative outputs" ([string]$SourceConfig.export_path -eq "")

    Write-Host "Release checks passed:"
    $checks | ForEach-Object { Write-Host "  $_" }
    exit 0
} catch {
    Write-Host ""
    Write-Host $_.Exception.Message
    exit 1
}
