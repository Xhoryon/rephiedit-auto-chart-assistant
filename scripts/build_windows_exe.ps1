param(
    [switch]$SkipTests,
    [switch]$NoAudioExtras,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvDir = Join-Path $RepoRoot ".venv-windows-build"
$SpecFile = Join-Path $RepoRoot "packaging\windows\RePhiEditAutoChartAssistant.spec"
$DistExe = Join-Path $RepoRoot "dist\RePhiEditAutoChartAssistant\RePhiEditAutoChartAssistant.exe"

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

function Test-NativeSuccess {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @()
    )
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @Arguments *> $null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Find-Python312 {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if (Test-NativeSuccess "py" @("-3.12", "-c", "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)")) {
            return @{ Command = "py"; Arguments = @("-3.12") }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        if (Test-NativeSuccess "python" @("-c", "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)")) {
            return @{ Command = "python"; Arguments = @() }
        }
    }
    throw "Python 3.12 is required on the build machine. End users do not need Python after the installer is built."
}

function Test-VenvPython312($PythonPath) {
    if (-not (Test-Path $PythonPath)) {
        return $false
    }
    return Test-NativeSuccess $PythonPath @("-c", "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)")
}

function Test-Import($PythonPath, $ImportName) {
    return Test-NativeSuccess $PythonPath @("-c", "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ImportName') else 1)")
}

function Test-Distribution($PythonPath, $DistributionName) {
    $code = "import importlib.metadata as m, sys; sys.exit(0 if any(d.metadata['Name'].lower() == '$($DistributionName.ToLower())' for d in m.distributions()) else 1)"
    return Test-NativeSuccess $PythonPath @("-c", $code)
}

function Install-MissingPackage($PythonPath, $PipName, $ImportName) {
    if (Test-Import $PythonPath $ImportName) {
        Write-Host "Dependency present: $PipName"
        return
    }
    Invoke-Native "Installing missing dependency: $PipName" $PythonPath @("-m", "pip", "install", $PipName)
}

try {
    if ($PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows) {
        Write-Warning "This script is intended to build a Windows EXE. Run it on Windows for a usable .exe."
    }

    if ($Clean -and (Test-Path $VenvDir)) {
        Write-Host "Clean build requested: removing $VenvDir"
        Remove-Item -Recurse -Force $VenvDir
    }

    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if ((Test-Path $VenvDir) -and -not (Test-VenvPython312 $VenvPython)) {
        Write-Warning ".venv-windows-build is not Python 3.12; recreating it."
        Remove-Item -Recurse -Force $VenvDir
    }

    if (-not (Test-Path $VenvDir)) {
        $Python312 = Find-Python312
        Write-Host "Creating build venv with Python 3.12: $VenvDir"
        Invoke-Native "Creating build virtual environment" $Python312.Command ($Python312.Arguments + @("-m", "venv", $VenvDir))
    } else {
        Write-Host "Reusing build venv: $VenvDir"
    }

    if (-not (Test-VenvPython312 $VenvPython)) {
        throw "Build venv is not Python 3.12: $VenvPython"
    }

    if (-not (Test-Import $VenvPython "pip")) {
        Invoke-Native "Bootstrapping pip" $VenvPython @("-m", "ensurepip", "--upgrade")
    } else {
        Write-Host "Dependency present: pip"
    }
    Install-MissingPackage $VenvPython "setuptools" "setuptools"
    Install-MissingPackage $VenvPython "wheel" "wheel"
    Install-MissingPackage $VenvPython "pyinstaller" "PyInstaller"

    if (-not (Test-Distribution $VenvPython "rephi-auto-chart-assistant")) {
        Invoke-Native "Installing project in editable mode" $VenvPython @("-m", "pip", "install", "-e", $RepoRoot)
    } else {
        Write-Host "Project editable install already present."
    }

    $Dependencies = @(
        @{ Pip = "numpy"; Import = "numpy" },
        @{ Pip = "scipy"; Import = "scipy" },
        @{ Pip = "soundfile"; Import = "soundfile" },
        @{ Pip = "librosa"; Import = "librosa" },
        @{ Pip = "Pillow"; Import = "PIL" },
        @{ Pip = "matplotlib"; Import = "matplotlib" },
        @{ Pip = "numba"; Import = "numba" },
        @{ Pip = "llvmlite"; Import = "llvmlite" },
        @{ Pip = "soxr"; Import = "soxr" },
        @{ Pip = "audioread"; Import = "audioread" }
    )

    if (-not $NoAudioExtras) {
        foreach ($dependency in $Dependencies) {
            Install-MissingPackage $VenvPython $dependency.Pip $dependency.Import
        }
    }

    if (-not $SkipTests) {
        Invoke-Native "Running unit tests" $VenvPython @("-m", "unittest", "discover", "-s", (Join-Path $RepoRoot "tests"))
    }

    Invoke-Native "Building PyInstaller onedir EXE" $VenvPython @("-m", "PyInstaller", "--noconfirm", "--clean", $SpecFile)

    if (-not (Test-Path $DistExe)) {
        throw "Build failed: $DistExe was not created."
    }

    Write-Host "Windows EXE build complete: $DistExe"
} catch {
    Write-Host ""
    Write-Host "Windows EXE build failed: $($_.Exception.Message)"
    exit 1
}
