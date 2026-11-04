param([string]$InstallDirectory = $env:EARNEST_LAB_INSTALL_DIR)
$ErrorActionPreference = 'Stop'
function Get-Sha256([string]$Path) {
  $stream = [IO.File]::OpenRead($Path)
  $hash = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-', '') }
  finally { $stream.Dispose(); $hash.Dispose() }
}
try {
  if ([string]::IsNullOrWhiteSpace($InstallDirectory)) { $InstallDirectory = Join-Path $env:USERPROFILE 'tools\Earnest-VM-Lab' }
  $target = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd('\')
  $app = Join-Path $target 'app'
  if (-not (Test-Path -LiteralPath (Join-Path $app 'earnest\cli.py')) -or -not (Test-Path -LiteralPath (Join-Path $target 'python\python.exe'))) { throw "Existing VM lab install not found at $target" }
  $running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and ($_.ExecutablePath.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase) -or ($_.CommandLine -and $_.CommandLine.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and $_.Name -match '^(python|node|StageJack|EarnestAudioHost)')) }
  if ($running) { $running | Select-Object ProcessId,Name,ExecutablePath | Format-Table; throw 'Close the listed Earnest lab applications and rerun this update.' }
  $payload = Join-Path $PSScriptRoot 'payload'
  $manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw | ConvertFrom-Json
  if ($manifest.schema -ne 'earnest.vm-update.v1') { throw 'Unsupported update manifest.' }
  foreach ($item in $manifest.files) {
    if ($item.path -notmatch '^app[\\/]' -or $item.path -match '(^|[\\/])\.\.([\\/]|$)' -or [IO.Path]::IsPathRooted($item.path)) { throw "Unsafe payload path: $($item.path)" }
    $source = Join-Path $payload $item.path
    if (-not (Test-Path -LiteralPath $source -PathType Leaf) -or (Get-Sha256 $source) -ne $item.sha256) { throw "Missing or corrupt payload file: $($item.path)" }
  }
  $backup = Join-Path $target ('backup-update-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
  New-Item -ItemType Directory -Path $backup | Out-Null
  $copied = 0
  foreach ($item in $manifest.files) {
    $destination = Join-Path $target $item.path
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
      $saved = Join-Path $backup $item.path
      New-Item -ItemType Directory -Path (Split-Path -Parent $saved) -Force | Out-Null
      Copy-Item -LiteralPath $destination -Destination $saved
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $payload $item.path) -Destination $destination -Force
    if ((Get-Sha256 $destination) -ne $item.sha256) { throw "Verification failed for $destination; backup: $backup" }
    $copied++
  }
  # The first lab install provided this launcher; update it while preserving a backup.
  $cliLauncher = Join-Path $target 'Earnest-CLI.cmd'
  if (Test-Path -LiteralPath $cliLauncher -PathType Leaf) {
    Copy-Item -LiteralPath $cliLauncher -Destination (Join-Path $backup 'Earnest-CLI.cmd')
    $lines = @('@echo off','setlocal','set "PATH=%~dp0python;%~dp0node;%PATH%"','cd /d "%~dp0app"','"%~dp0python\python.exe" -m earnest','if errorlevel 1 pause')
    [IO.File]::WriteAllText($cliLauncher, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
  }
  Write-Host "Updated $copied application files. Backup: $backup" -ForegroundColor Green
  Write-Host 'Rooms, models, settings, the Python runtime, and the installed audio driver were not replaced.'
  Write-Host 'Reopen the CLI, Room Studio, or Frankenjack. Optional transcription/separation backends need separate setup in the VM.'
} catch { Write-Host "UPDATE FAILED: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
