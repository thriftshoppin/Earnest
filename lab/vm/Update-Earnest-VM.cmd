@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-Earnest-VM.ps1" %*
echo.
pause
