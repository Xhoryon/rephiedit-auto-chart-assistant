@echo off
setlocal
cd /d "%~dp0"

echo Building Re:PhiEdit Auto Chart Assistant 2.5.1 Release...
echo.
echo Select build mode:
echo   1 Normal incremental build (reuse .venv-windows-build)
echo   2 Clean rebuild (delete build, dist, Release, and .venv-windows-build)
echo.
set /p BUILD_MODE=Enter choice [1]:
if "%BUILD_MODE%"=="" set BUILD_MODE=1

set CLEAN_ARG=
if "%BUILD_MODE%"=="2" (
  set CLEAN_ARG=-Clean
) else (
  if not "%BUILD_MODE%"=="1" (
    echo Invalid choice.
    pause
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release.ps1 %CLEAN_ARG%
if errorlevel 1 (
  echo.
  echo Build failed. Review the messages above for the failing release step.
  pause
  exit /b 1
)

echo.
echo Build finished. Check Release\Setup.exe and Release\Portable.
pause
exit /b 0
