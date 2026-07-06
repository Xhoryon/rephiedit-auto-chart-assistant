param(
    [switch]$SkipExeBuild
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DistDir = Join-Path $RepoRoot "dist\RePhiEditAutoChartAssistant"
$ExePath = Join-Path $DistDir "RePhiEditAutoChartAssistant.exe"
$InstallerScript = Join-Path $RepoRoot "installer\inno_setup.iss"
$OutputDir = Join-Path $RepoRoot "Release"
$SetupPath = Join-Path $OutputDir "Setup.exe"

function Invoke-Native {
    param(
        [string]$Description,
        [string]$FilePath,
        [string[]]$Arguments = @()
    )
    Write-Host ">> $Description"
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                Write-Host $_.ToString()
            } else {
                Write-Host $_
            }
        }
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }
}

try {
    if (-not $SkipExeBuild -or -not (Test-Path $ExePath)) {
        & (Join-Path $PSScriptRoot "build_windows_exe.ps1")
        if ($LASTEXITCODE -ne 0) {
            throw "Windows EXE build failed with exit code $LASTEXITCODE."
        }
    }

    $IsccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $IsccPath = $null
    if ($IsccCommand) {
        $IsccPath = $IsccCommand.Source
    }
    if (-not $IsccPath) {
        $DefaultIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        if (Test-Path $DefaultIscc) {
            $IsccPath = $DefaultIscc
        }
    }
    if (-not $IsccPath) {
        throw "Inno Setup 6 is required. Install it from https://jrsoftware.org/isinfo.php and ensure ISCC.exe is on PATH."
    }

    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
    Invoke-Native "Compiling Inno Setup installer" $IsccPath @($InstallerScript, "/DSourceDir=$DistDir", "/DOutputDir=$OutputDir")

    if (-not (Test-Path $SetupPath)) {
        throw "Installer was not created: $SetupPath"
    }

    Write-Host "Windows installer build complete: $SetupPath"
} catch {
    Write-Host ""
    Write-Host "Windows installer build failed: $($_.Exception.Message)"
    exit 1
}
