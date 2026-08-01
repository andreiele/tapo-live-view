@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Tapo Live View is not set up yet. Running Setup.bat...
  call Setup.bat
  if errorlevel 1 exit /b 1
)

if not exist "config.json" (
  echo Camera configuration is missing. Running Setup.bat...
  call Setup.bat
  if errorlevel 1 exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" live.py
