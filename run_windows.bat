@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3.12 --version >nul 2>nul
  if %errorlevel%==0 (
    set PYTHON_CMD=py -3.12
  ) else (
    set PYTHON_CMD=py -3
  )
) else (
  set PYTHON_CMD=python
)

if not exist ".venv\Scripts\python.exe" (
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto fail
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m pip install -e ".[audio]"
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -m rephi_auto_chart.gui
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo Failed to start RePhiEdit Auto Chart Assistant.
echo Please install Python 3.12 from https://www.python.org/downloads/windows/
pause
exit /b 1

