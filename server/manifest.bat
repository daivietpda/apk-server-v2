@echo off
setlocal
python "%~dp0scripts\update_manifest.py" %*
if errorlevel 1 pause
