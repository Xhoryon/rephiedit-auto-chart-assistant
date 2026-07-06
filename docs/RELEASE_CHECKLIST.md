# Release Checklist

## Build Machine

- Windows 10 or Windows 11
- x64-compatible CPU
- Python 3.12 installed for build machine only
- Inno Setup 6 installed
- Internet access for Python packages and optional VC++ Runtime bootstrap

## Build Command

Double-click:

```text
build_release.bat
```

`build_all_windows.bat` is an equivalent one-click release entry point.

Choose:

- `1 Normal incremental build`: preserves `.venv-windows-build` and installs only missing dependencies.
- `2 Clean rebuild`: deletes `build/`, `dist/`, `Release/`, and `.venv-windows-build`.
- Repeated Normal builds must not reinstall all dependencies.
- Clean rebuild is the only mode that deletes `.venv-windows-build`.

Expected output:

```text
Release\Setup.exe
Release\Portable\RePhiEditAutoChartAssistant.exe
```

## Installer Checks

- Windows 10+ requirement
- x64-compatible requirement
- Microsoft Visual C++ Runtime detection
- VC++ Runtime automatic download/install if missing
- LocalAppData write check
- Documents write check
- Desktop write check
- Program Files installation through admin installer privileges

## Installed Files

- Program files under `C:\Program Files\RePhiEdit Auto Chart Assistant`
- Desktop shortcut
- Start menu shortcut
- Optional `.pez` file association
- Runtime folders under `%LOCALAPPDATA%\RePhiEditAutoChart`
- Default chart exports under `%USERPROFILE%\Documents\RePhiEdit Charts`
- No runtime writes to Program Files, the EXE directory, current working directory, or `./outputs`

## Portable Checks

- `Release\Portable\RePhiEditAutoChartAssistant.exe` launches without Python installed.
- `Release\Portable` contains bundled Python runtime files such as `python*.dll`.
- `Release\Portable` contains PyInstaller runtime files under `_internal`.
- MP3/WAV/FLAC/OGG decode dependencies are bundled.
- PyInstaller build output has no `numpy.f2py.tests` / `pytest` collection warnings.
- Bundled `config/default_config.json` exists under `Release\Portable\config` or `Release\Portable\_internal\config`.
- Bundled docs exist under `Release\Portable\docs` or `Release\Portable\_internal\docs`.
- `release_check.ps1` runs `RePhiEditAutoChartAssistant.exe --smoke-check` from outside the Portable working directory.

## Functional Checks

- Launch GUI.
- Select MP3.
- Select difficulty.
- Generate PEZ.
- Open output folder.
- Confirm PEZ ZIP contains `info.txt`, JSON, audio, and PNG.
- Import PEZ in Re:PhiEdit on Windows.
- Run Analyzer on a PEZ file.

## Uninstall Checks

- Start menu shortcut removed.
- Desktop shortcut removed.
- Program Files directory removed.
- Installer registry entries removed.
- User data under `%LOCALAPPDATA%\RePhiEditAutoChart` is preserved unless manually deleted.

## Known Release Limit

This macOS workspace can validate code, scripts, metadata, and release structure, but final `Setup.exe` compilation requires Windows with Inno Setup.
