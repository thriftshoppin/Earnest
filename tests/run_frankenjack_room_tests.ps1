$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$tempDir = Join-Path ([IO.Path]::GetTempPath()) ('earnest-room-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tempDir | Out-Null
try {
    $native = Join-Path $root 'earnest\audio\native'
    Copy-Item (Join-Path $native 'NAudio.Core.dll'), (Join-Path $native 'NAudio.Wasapi.dll') -Destination $tempDir
    $exe = Join-Path $tempDir 'room-tests.exe'
    $net = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\netstandard.dll'
    & $compiler /nologo /target:exe "/out:$exe" /reference:System.Core.dll "/reference:$net" "/reference:$tempDir\NAudio.Core.dll" "/reference:$tempDir\NAudio.Wasapi.dll" (Join-Path $root 'lab\frankenjack\src\EarnestShell.cs') (Join-Path $PSScriptRoot 'FrankenjackRoomTests.cs')
    if ($LASTEXITCODE -ne 0) { throw 'Could not build room selection checks.' }
    & $exe
    if ($LASTEXITCODE -ne 0) { throw 'Room selection checks failed.' }
} finally { Remove-Item -LiteralPath $tempDir -Recurse -Force }
