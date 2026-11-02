@echo off
cd /d "%~dp0"
py -3.14 -u -m earnest reset %*
set RC=%ERRORLEVEL%
echo %* | find "--yes" >nul
if errorlevel 1 (
  echo.
  pause
)
exit /b %RC%
