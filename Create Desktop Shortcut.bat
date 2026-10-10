@echo off
setlocal
cd /d "%~dp0"

rem Point the shortcut straight at the windowless Python so no console ever flashes.
rem Before Setup.bat has created .venv, fall back to the silent VBS launcher.
if exist "%~dp0.venv\Scripts\pythonw.exe" (
  set "TAPO_TARGET=%~dp0.venv\Scripts\pythonw.exe"
  set "TAPO_ARGS="%~dp0wizard.py""
) else (
  set "TAPO_TARGET=wscript.exe"
  set "TAPO_ARGS=//B "%~dp0run_hidden.vbs""
)
set "TAPO_WORKDIR=%~dp0"
set "TAPO_ICON=%~dp0tapo.ico"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory);" ^
  "if ([string]::IsNullOrWhiteSpace($desktop)) { $desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::Desktop) };" ^
  "if ([string]::IsNullOrWhiteSpace($desktop)) { throw 'Windows could not determine the Desktop folder location.' };" ^
  "if (-not (Test-Path -LiteralPath $desktop)) { New-Item -ItemType Directory -Path $desktop -Force | Out-Null };" ^
  "$link = Join-Path $desktop 'Tapo Live View.lnk';" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$s = $ws.CreateShortcut($link);" ^
  "$s.TargetPath = $env:TAPO_TARGET;" ^
  "$s.Arguments = $env:TAPO_ARGS;" ^
  "$s.WorkingDirectory = $env:TAPO_WORKDIR;" ^
  "if (Test-Path -LiteralPath $env:TAPO_ICON) { $s.IconLocation = $env:TAPO_ICON };" ^
  "$s.Description = 'Open the Tapo camera live view';" ^
  "$s.Save();" ^
  "Write-Host ('Desktop shortcut created: ' + $link)"

if errorlevel 1 (
  echo Could not create the shortcut.
  pause
  exit /b 1
)

pause
