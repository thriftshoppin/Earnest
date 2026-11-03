@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-Earnest-VM-Full.ps1" %*
echo.
pause
