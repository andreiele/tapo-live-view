@echo off
setlocal
cd /d "%~dp0"
title Tapo Live View Setup

echo.
echo ========================================
echo         Tapo Live View Setup
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python was not found.
    echo Install Python 3.9 or newer and tick "Add Python to PATH".
    pause
    exit /b 1
  )
  set "PYTHON=python"
) else (
  set "PYTHON=py -3"
)

if not exist ".venv\Scripts\pythonw.exe" (
  echo Creating local Python environment...
  %PYTHON% -m venv .venv || goto :error
)

echo Installing required packages...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip >nul || goto :error
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :error

where ffplay >nul 2>nul
if errorlevel 1 (
  echo.
  echo FFmpeg / ffplay is not currently on PATH.
  where winget >nul 2>nul
  if not errorlevel 1 (
    choice /M "Install FFmpeg now using winget"
    if not errorlevel 2 winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
  ) else (
    echo Install FFmpeg manually before running the live view.
  )
)

echo.
echo Opening camera setup...
".venv\Scripts\pythonw.exe" first_run.py
if errorlevel 1 goto :error

echo.
echo Setup finished. You can now run Run.bat.
pause
exit /b 0

:error
echo.
echo Setup failed. Review the message above.
pause
exit /b 1
