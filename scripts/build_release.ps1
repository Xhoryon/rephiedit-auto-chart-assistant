param(
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ReleaseDir = Join-Path $RepoRoot "Release"
$PortableDir = Join-Path $ReleaseDir "Portable"
$DistDir = Join-Path $RepoRoot "dist\RePhiEditAutoChartAssistant"
$SetupPath = Join-Path $ReleaseDir "Setup.exe"
$ExePath = Join-Path $DistDir "RePhiEditAutoChartAssistant.exe"
$VenvDir = Join-Path $RepoRoot ".venv-windows-build"

function Remove-DirectoryIfExists($Path) {
    if (Test-Path $Path) {
        Remove-Item -Recurse -Force $Path
    }
}

function Invoke-ReleaseScript {
    param(
        [string]$Description,
        [string]$ScriptPath,
        [hashtable]$NamedArguments = @()
    )
    Write-Host ">> $Description"
    & $ScriptPath @NamedArguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

try {
    Write-Host "== Re:PhiEdit Auto Chart Assistant Release Build =="
    Write-Host "Repo: $RepoRoot"

    if ($PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows) {
        Write-Warning "This release script creates a Windows installer. Run it on Windows for final Setup.exe output."
    }

    Write-Host "== Cleaning previous release artifacts =="
    foreach ($target in @(
        "build",
        "dist",
        "Release",
        "outputs",
        ".pytest_cache",
        ".pycache_tmp",
        "tmp",
        "temp",
        "logs",
        "cache",
        "release_old",
        "installer_tmp"
    )) {
        Remove-DirectoryIfExists (Join-Path $RepoRoot $target)
    }

    if ($Clean) {
        if (Test-Path $VenvDir) {
            Write-Host "Clean rebuild requested: removing dependency environment $VenvDir"
            Remove-Item -Recurse -Force $VenvDir
        } else {
            Write-Host "Clean rebuild requested: dependency environment does not exist."
        }
    } else {
        Write-Host "Normal build: preserving .venv-windows-build dependency environment."
    }

    Get-ChildItem -Path $RepoRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

    Write-Host "== Building portable EXE =="
    $exeArgs = @{}
    if ($SkipTests) {
        $exeArgs["SkipTests"] = $true
    }
    if ($Clean) {
        $exeArgs["Clean"] = $true
    }
    Invoke-ReleaseScript "Windows EXE build" (Join-Path $PSScriptRoot "build_windows_exe.ps1") $exeArgs

    if (-not (Test-Path $ExePath)) {
        throw "Portable EXE was not created: $ExePath"
    }

    Write-Host "== Preparing Release\Portable =="
    Copy-Item -Recurse -Force $DistDir $PortableDir
    foreach ($file in @("README.md", "LICENSE", "CHANGELOG.md")) {
        Copy-Item -Force (Join-Path $RepoRoot $file) (Join-Path $PortableDir $file)
    }
    Copy-Item -Force (Join-Path $RepoRoot "assets\windows\app_icon.ico") (Join-Path $PortableDir "app_icon.ico")

    if (-not $SkipInstaller) {
        Write-Host "== Building installer =="
        Invoke-ReleaseScript "Windows installer build" (Join-Path $PSScriptRoot "build_windows_installer.ps1") @{ SkipExeBuild = $true }
        if (-not (Test-Path $SetupPath)) {
            throw "Installer was not created: $SetupPath"
        }
    } else {
        Write-Warning "Skipping installer build by request."
    }

    Write-Host "== Running release checks =="
    if (-not (Test-Path $ReleaseDir)) {
        throw "Release directory does not exist before release checks: $ReleaseDir"
    }
    Invoke-ReleaseScript "Release checks" (Join-Path $RepoRoot "release_check.ps1") @{ ReleaseDir = $ReleaseDir }

    Write-Host "Release ready:"
    Write-Host "  $SetupPath"
    Write-Host "  $PortableDir"
} catch {
    Write-Host ""
    Write-Host "Release build failed: $($_.Exception.Message)"
    exit 1
}
