@echo off
setlocal
set "ROOT=%~dp0"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
set "NETSTANDARD=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\netstandard.dll"
set "NAUDIO=%ROOT%..\..\earnest\audio\native"
set "BUILD_OUTPUT=%ROOT%build"
if defined EARNEST_BUILD_OUTPUT set "BUILD_OUTPUT=%EARNEST_BUILD_OUTPUT%"
if not exist "%BUILD_OUTPUT%" mkdir "%BUILD_OUTPUT%"
"%CSC%" /nologo /optimize+ /target:winexe /win32icon:"%ROOT%assets\StageJack.ico" /out:"%BUILD_OUTPUT%\StageJack-Earnest.exe" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Core.dll /reference:"%NETSTANDARD%" /reference:"%NAUDIO%\NAudio.Core.dll" /reference:"%NAUDIO%\NAudio.Wasapi.dll" "%ROOT%src\AssemblyInfo.cs" "%ROOT%src\StageJackApp.cs" "%ROOT%src\EarnestShell.cs" "%ROOT%src\StageJackMonitor.cs" "%ROOT%src\StageSlider.cs" "%ROOT%src\EqView.cs" "%ROOT%src\AdvancedMix.cs"
if errorlevel 1 exit /b 1
"%CSC%" /nologo /optimize+ /target:exe /out:"%BUILD_OUTPUT%\EarnestAudioHost-eq.exe" /reference:System.Core.dll /reference:"%NETSTANDARD%" /reference:"%NAUDIO%\NAudio.Core.dll" /reference:"%NAUDIO%\NAudio.Wasapi.dll" "%ROOT%EarnestAudioHost.cs"
if errorlevel 1 exit /b 1
copy /y "%NAUDIO%\NAudio.Core.dll" "%BUILD_OUTPUT%\" >nul
copy /y "%NAUDIO%\NAudio.Wasapi.dll" "%BUILD_OUTPUT%\" >nul
copy /y "%ROOT%assets\fonts\*.ttf" "%BUILD_OUTPUT%\" >nul
echo Build complete. No audio was started.
