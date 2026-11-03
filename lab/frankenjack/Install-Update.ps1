$ErrorActionPreference = 'Stop'
try {
  $installDirectory = $env:EARNEST_LAB_INSTALL_DIR
  if ([string]::IsNullOrWhiteSpace($installDirectory)) { $installDirectory = Join-Path $env:USERPROFILE 'tools\Earnest-VM-Lab' }
  $root = Join-Path $installDirectory 'app'
  $stage = Join-Path $root 'stagejack\StageJack-Earnest.exe'
  $hostFile = Join-Path $root 'earnest\audio\native\EarnestAudioHost-eq.exe'
  if (-not (Test-Path -LiteralPath $stage) -or -not (Test-Path -LiteralPath $hostFile)) { throw "Existing Earnest VM installation not found at $root" }
  $running = Get-Process -Name 'StageJack-Earnest','EarnestAudioHost-eq' -ErrorAction SilentlyContinue
  if ($running) { throw 'Close Frankenjack and its EarnestAudioHost-eq audio window before installing this update.' }
  $backup = Join-Path (Split-Path -Parent $root) ('backup-frankenjack-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
  New-Item -ItemType Directory -Path $backup | Out-Null
  Copy-Item -LiteralPath $stage -Destination (Join-Path $backup 'StageJack-Earnest.exe')
  Copy-Item -LiteralPath $hostFile -Destination (Join-Path $backup 'EarnestAudioHost-eq.exe')
  foreach ($item in @(@('stagejack\StageJack-Earnest.exe',$stage),@('audio-native\EarnestAudioHost-eq.exe',$hostFile))) {
    $source = Join-Path $PSScriptRoot $item[0]
    Copy-Item -LiteralPath $source -Destination $item[1] -Force
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $item[1]).Hash) { throw "Copy verification failed: $($item[1]). Backups are in $backup" }
  }
  Write-Host "Update installed. Backups: $backup" -ForegroundColor Green
  Write-Host 'Reopen Earnest and Frankenjack. The driver does not need reinstalling.'
} catch { Write-Host "UPDATE FAILED: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
