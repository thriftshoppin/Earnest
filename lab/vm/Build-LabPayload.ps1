param(
  [Parameter(Mandatory=$true)][string]$PythonHome,
  [Parameter(Mandatory=$true)][string]$NodeExe,
  [Parameter(Mandatory=$true)][string]$DevconExe,
  [string]$DriverPackage = (Join-Path $PSScriptRoot '..\driver\test-package'),
  [string]$OutputDirectory = (Join-Path $PSScriptRoot 'output'),
  [string]$LipscanModels
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw "Output directory already exists: $output. Choose a new output directory." }
foreach ($file in @((Join-Path $PythonHome 'python.exe'), (Join-Path $PythonHome 'Lib'), (Join-Path $PythonHome 'DLLs'), $NodeExe, $DevconExe, (Join-Path $DriverPackage 'EarnestAudioDevice.inf'), (Join-Path $DriverPackage 'EarnestAudioDevice.sys'), (Join-Path $DriverPackage 'earnestaudiodevice.cat'), (Join-Path $DriverPackage 'EarnestAudioDevice.cer'))) {
  if (-not (Test-Path -LiteralPath $file)) { throw "Missing required build input: $file" }
}
& (Join-Path $PythonHome 'python.exe') -c 'import numpy, scipy, soundfile, h5py, tkinter, tkinterdnd2'
if ($LASTEXITCODE -ne 0) { throw 'Install the Python dependencies into the supplied Python installation first; see requirements-lock.txt.' }
& (Join-Path $repo 'lab\frankenjack\Build.cmd')
if ($LASTEXITCODE -ne 0) { throw 'Frankenjack build failed.' }
New-Item -ItemType Directory -Path $output | Out-Null
$staging = Join-Path $output 'payload'
foreach ($dir in @('app','driver','python','node','app\stagejack','app\live','app\inbox\rooms','app\reference','app\bin')) { New-Item -ItemType Directory -Path (Join-Path $staging $dir) -Force | Out-Null }
function Copy-Tree([string]$source, [string]$destination, [bool]$excludeExecutables = $false) {
  $excluded = @('*.pyc')
  if ($excludeExecutables) { $excluded += '*.exe' }
  & robocopy.exe $source $destination /E /XD __pycache__ /XF $excluded | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "Copy failed from $source to $destination (robocopy $LASTEXITCODE)." }
}
Copy-Tree (Join-Path $repo 'earnest') (Join-Path $staging 'app\earnest') $true
Copy-Tree (Join-Path $PythonHome 'Lib') (Join-Path $staging 'python\Lib')
Copy-Tree (Join-Path $PythonHome 'DLLs') (Join-Path $staging 'python\DLLs')
Get-ChildItem -LiteralPath $PythonHome -File | Where-Object { $_.Name -match '^(python.*\.(exe|dll)|vcruntime.*\.dll|LICENSE\.txt)$' } | Copy-Item -Destination (Join-Path $staging 'python')
Copy-Item -LiteralPath $NodeExe -Destination (Join-Path $staging 'node\node.exe')
Copy-Item -LiteralPath $DevconExe -Destination (Join-Path $staging 'driver\devcon.exe')
Copy-Item -Path (Join-Path $DriverPackage '*') -Destination (Join-Path $staging 'driver') -Recurse
Copy-Item -Path (Join-Path $repo 'lab\frankenjack\build\*') -Destination (Join-Path $staging 'app\stagejack') -Recurse
Copy-Item -LiteralPath (Join-Path $repo 'lab\frankenjack\build\EarnestAudioHost-eq.exe') -Destination (Join-Path $staging 'app\earnest\audio\native\EarnestAudioHost-eq.exe')
Copy-Item -Path (Join-Path $repo 'live\*') -Destination (Join-Path $staging 'app\live') -Recurse
Copy-Item -Path (Join-Path $repo 'bin\*') -Destination (Join-Path $staging 'app\bin') -Recurse
Copy-Item -Path (Join-Path $repo 'probe\*') -Destination (Join-Path $staging 'app\reference')
Copy-Item -LiteralPath (Join-Path $repo 'examples\rooms\Union-Stairs.room.json') -Destination (Join-Path $staging 'app\inbox\rooms')
Copy-Item -Path (Join-Path $repo 'earnest\audio\native\NAudio*.dll') -Destination (Join-Path $staging 'app\live')
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$netstandard = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\netstandard.dll'
& $csc /nologo /optimize+ /target:exe "/out:$(Join-Path $staging 'app\live\EarnestMonitor.exe')" "/reference:$netstandard" "/reference:$(Join-Path $staging 'app\live\NAudio.Core.dll')" "/reference:$(Join-Path $staging 'app\live\NAudio.Wasapi.dll')" (Join-Path $repo 'live\Monitor.cs')
if ($LASTEXITCODE -ne 0) { throw 'Live monitor compilation failed.' }
if ($LipscanModels) { Copy-Tree $LipscanModels (Join-Path $staging 'lipscan-packs') }
$launcher = '@echo off' + "`r`n" + 'setlocal' + "`r`n" + 'set "PATH=%~dp0python;%~dp0node;%PATH%"' + "`r`n" + 'cd /d "%~dp0app"' + "`r`n"
[IO.File]::WriteAllText((Join-Path $staging 'Open-Earnest.cmd'), $launcher + '"%~dp0python\python.exe" -m earnest.desktop_v2' + "`r`n" + 'if errorlevel 1 pause' + "`r`n")
[IO.File]::WriteAllText((Join-Path $staging 'Earnest-CLI.cmd'), $launcher + 'cmd /k' + "`r`n")
[IO.File]::WriteAllText((Join-Path $staging 'Live-View.cmd'), $launcher + '"%~dp0python\python.exe" -m earnest live-view --endpoint "Earnest Virtual Audio Device" --open' + "`r`n" + 'pause' + "`r`n")
[IO.File]::WriteAllText((Join-Path $staging 'python\earnest.cmd'), '@echo off' + "`r`n" + '"%~dp0python.exe" -m earnest %*' + "`r`n")
Add-Type -AssemblyName System.IO.Compression.FileSystem
$payload = Join-Path $output 'Earnest-Payload.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($staging, $payload, [IO.Compression.CompressionLevel]::Optimal, $false)
(Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash | Set-Content -LiteralPath (Join-Path $output 'Earnest-Payload.sha256') -Encoding ASCII
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Install-Earnest-VM.cmd'),(Join-Path $PSScriptRoot 'Install-Earnest-VM.ps1'),(Join-Path $PSScriptRoot 'README-FIRST.txt') -Destination $output
Write-Host "Lab package created at $output. Transfer the files in that folder to the guest; do not publish the private signing key."
