$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$exe = Join-Path ([IO.Path]::GetTempPath()) ('earnest-control-tests-' + [guid]::NewGuid().ToString('N') + '.exe')
& $compiler /nologo /target:exe "/out:$exe" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll (Join-Path $root 'lab\frankenjack\src\AdvancedMix.cs') (Join-Path $PSScriptRoot 'FrankenjackControlTests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Could not build Frankenjack control checks.' }
& $exe
if ($LASTEXITCODE -ne 0) { throw 'Frankenjack control checks failed.' }
Write-Host "Offline check binary: $exe"
