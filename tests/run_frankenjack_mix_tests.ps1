$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$native = Join-Path $root 'earnest\audio\native'
$source = Join-Path $root 'lab\frankenjack\EarnestAudioHost.cs'
$out = Join-Path ([IO.Path]::GetTempPath()) ('earnest-mix-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $out | Out-Null
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$netstandard = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\netstandard.dll'
$exe = Join-Path $out 'FrankenjackMixTests.exe'
& $compiler /nologo /target:exe /main:FrankenjackMixTests "/out:$exe" /reference:System.Core.dll "/reference:$netstandard" "/reference:$(Join-Path $native 'NAudio.Core.dll')" "/reference:$(Join-Path $native 'NAudio.Wasapi.dll')" $source (Join-Path $PSScriptRoot 'FrankenjackMixTests.cs')
if ($LASTEXITCODE -ne 0) { throw 'Could not build native mixer checks.' }
Copy-Item -LiteralPath (Join-Path $native 'NAudio.Core.dll'),(Join-Path $native 'NAudio.Wasapi.dll') -Destination $out
& $exe
if ($LASTEXITCODE -ne 0) { throw 'Native mixer checks failed.' }
Write-Host "Offline check files: $out"
