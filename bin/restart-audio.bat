@echo off
setlocal
title Earnest - Restart Windows Audio
fltmc >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator elevation...
    set "EARNEST_AUDIO_RESTART_BATCH=%~f0"
    powershell.exe -NoProfile -Command "$q = [char]34; $cmd = '/c ' + $q + $q + $env:EARNEST_AUDIO_RESTART_BATCH + $q + $q; Start-Process -FilePath $env:ComSpec -Verb RunAs -ArgumentList $cmd"
    exit /b
)
echo EARNEST // WINDOWS AUDIO RESTART // ADMINISTRATOR
echo.
taskkill /F /FI "SERVICES eq Audiosrv"
net start Audiosrv
set "EARNEST_AUDIO_RESULT=%ERRORLEVEL%"
echo.
echo Exit code: %EARNEST_AUDIO_RESULT%
pause
exit /b %EARNEST_AUDIO_RESULT%
