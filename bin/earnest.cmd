@echo off
setlocal
set "EARNEST_HOME=%~dp0.."
pushd "%EARNEST_HOME%"
if "%~1"=="" (
    py -3.14 -m earnest --help
) else (
    py -3.14 -m earnest %*
)
set "EARNEST_EXIT=%ERRORLEVEL%"
popd
exit /b %EARNEST_EXIT%
