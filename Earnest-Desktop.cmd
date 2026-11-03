@echo off
cd /d "%~dp0"
py -3.14 -m earnest.desktop_v2
if errorlevel 1 pause
