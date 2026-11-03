@echo off
setlocal
cd /d "%~dp0"
py -3.14 -m earnest room-editor --open
if errorlevel 1 pause
