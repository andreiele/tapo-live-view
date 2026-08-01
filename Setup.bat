@echo off
cd /d "%~dp0"
start "" wscript.exe //B "run_hidden.vbs" "--setup"
