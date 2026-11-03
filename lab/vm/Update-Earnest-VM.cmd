@echo off
setlocal
cd /d "%~dp0"
title Earnest VM Application Update
set "EARNEST_LAUNCHER=%~f0"
if not defined EARNEST_LAB_INSTALL_DIR set "EARNEST_LAB_INSTALL_DIR=%USERPROFILE%\tools\Earnest-VM-Lab"
powershell.exe -NoProfile -Command "$p=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent()); if($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 0}else{exit 1}" >nul 2>&1
if errorlevel 1 goto need_admin
goto run_update
:need_admin
if /i "%~1"=="--elevated" goto no_admin
powershell.exe -NoProfile -Command "try { $a='/d /c '+[char]34+[char]34+$env:EARNEST_LAUNCHER+[char]34+' --elevated'+[char]34; Start-Process -FilePath $env:ComSpec -ArgumentList $a -Verb RunAs -ErrorAction Stop | Out-Null } catch { Write-Host ('Could not start elevated: ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 goto failed_elevation
exit /b 0
:no_admin
echo The new window is not running as administrator. Sign in with an administrator account and run this file again.
pause
exit /b 1
:failed_elevation
echo Could not start the administrator window. The update has not run.
pause
exit /b 1
:run_update
echo Running Earnest application update as administrator.
if /i "%~1"=="--elevated" goto elevated_update
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-Earnest-VM.ps1" %*
goto finish_update
:elevated_update
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Update-Earnest-VM.ps1"
:finish_update
set "UPDATE_RESULT=%ERRORLEVEL%"
echo.
echo Update exit code: %UPDATE_RESULT%
echo This window will stay open until you press a key.
pause
exit /b %UPDATE_RESULT%
