@echo off
cd /d "%~dp0"
py -3.14 -m earnest run %*
echo.
pause
