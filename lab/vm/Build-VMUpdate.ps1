param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
function Get-Sha256([string]$Path) {
  $stream = [IO.File]::OpenRead($Path); $hash = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-', '') }
  finally { $stream.Dispose(); $hash.Dispose() }
}
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$out = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $out) { throw "Choose a new output directory: $out" }
New-Item -ItemType Directory -Path $out | Out-Null
$payload = Join-Path $out 'payload'
$app = Join-Path $payload 'app'
New-Item -ItemType Directory -Path $app | Out-Null
$build = Join-Path $repo ('runs\vm-update-build-' + [guid]::NewGuid().ToString('N'))
$previous = $env:EARNEST_BUILD_OUTPUT
try {
  $env:EARNEST_BUILD_OUTPUT = $build
  & (Join-Path $repo 'lab\frankenjack\Build.cmd')
  if ($LASTEXITCODE -ne 0) { throw 'Frankenjack compilation failed.' }
} finally { $env:EARNEST_BUILD_OUTPUT = $previous }
foreach ($name in @('earnest','live','bin')) {
  $source = Join-Path $repo $name; $dest = Join-Path $app $name
  & robocopy.exe $source $dest /E /XD __pycache__ /XF *.pyc *.exe | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "Copy failed for $name (robocopy $LASTEXITCODE)." }
}
New-Item -ItemType Directory -Path (Join-Path $app 'stagejack') -Force | Out-Null
Copy-Item -Path (Join-Path $build '*') -Destination (Join-Path $app 'stagejack') -Recurse
Copy-Item -LiteralPath (Join-Path $build 'EarnestAudioHost-eq.exe') -Destination (Join-Path $app 'earnest\audio\native\EarnestAudioHost-eq.exe')
Copy-Item -LiteralPath (Join-Path $repo 'requirements-basic-pitch.txt') -Destination $app
Copy-Item -LiteralPath (Join-Path $repo 'requirements-demucs.txt') -Destination $app
$frankenjackLauncher = @'
@echo off
setlocal
set "EARNEST_HOME=%~dp0"
set "PATH=%~dp0..\python;%~dp0..\node;%PATH%"
cd /d "%~dp0"
start "" "%~dp0stagejack\StageJack-Earnest.exe"
'@
[IO.File]::WriteAllText((Join-Path $app 'Frankenjack.cmd'), ($frankenjackLauncher -replace "`r?`n", "`r`n") + "`r`n", [Text.Encoding]::ASCII)
$files = @(Get-ChildItem -LiteralPath $payload -Recurse -File | ForEach-Object {
  [ordered]@{path=$_.FullName.Substring($payload.Length+1); sha256=(Get-Sha256 $_.FullName)}
})
[ordered]@{schema='earnest.vm-update.v1'; files=$files} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $out 'manifest.json') -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Update-Earnest-VM.cmd'),(Join-Path $PSScriptRoot 'Update-Earnest-VM.ps1'),(Join-Path $PSScriptRoot 'Update-Earnest-VM-Full.cmd'),(Join-Path $PSScriptRoot 'Update-Earnest-VM-Full.ps1'),(Join-Path $PSScriptRoot 'VM-UPGRADE-README.txt'),(Join-Path $PSScriptRoot 'VM-UPGRADE.md') -Destination $out
$documentation = Join-Path $out 'documentation'
New-Item -ItemType Directory -Path $documentation | Out-Null
foreach ($name in @('BUILD_NOTES_NOV_03.md','ROOM_SOLVER_MATH.md','PHYSICS_NOTES.md','ROADMAP.md','CLI_COMMAND_TRANSLATION.md','ENGINE_ARCHITECTURE.md','SUITE_UPDATES_PLAN.md','HYPOTHESIS_EVALUATION.md','EFFECT_PURSUIT.md','CUDA_BACKEND.md')) {
  Copy-Item -LiteralPath (Join-Path $repo ('docs\' + $name)) -Destination $documentation
}
Copy-Item -LiteralPath (Join-Path $repo 'CHANGELOG.md') -Destination $documentation
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = $out + '.zip'
if (Test-Path -LiteralPath $zip) { throw "ZIP already exists: $zip" }
[IO.Compression.ZipFile]::CreateFromDirectory($out,$zip,[IO.Compression.CompressionLevel]::Optimal,$false)
(Get-Sha256 $zip) | Set-Content -LiteralPath ($zip + '.sha256') -Encoding ASCII
Write-Host "Update package: $zip"
