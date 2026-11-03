param([string]$InstallDirectory = $env:EARNEST_LAB_INSTALL_DIR)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($InstallDirectory)) { $InstallDirectory = Join-Path $env:USERPROFILE 'tools\Earnest-VM-Lab' }
$target = [IO.Path]::GetFullPath($InstallDirectory)
$package = Join-Path $PSScriptRoot 'Earnest-Payload.zip'
$checksum = Join-Path $PSScriptRoot 'Earnest-Payload.sha256'
$staging = $null
try {
  Write-Host 'EARNEST VM LAB SETUP' -ForegroundColor Cyan
  $computer = Get-CimInstance Win32_ComputerSystem
  if (($computer.Manufacturer + ' ' + $computer.Model) -notmatch 'VMware|VirtualBox|Virtual Machine|QEMU|KVM') { throw 'This test-signed package is restricted to a recognized virtual machine.' }
  if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required.' }
  try { $secure = Confirm-SecureBootUEFI } catch { throw 'Could not check guest Secure Boot state.' }
  if ($secure) { throw 'Guest Secure Boot is enabled. Test-signed drivers need it disabled inside the guest.' }
  foreach ($file in @($package, $checksum)) { if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing package file: $file. Run setup directly from the deployment disc or extract the entire deployment ZIP." } }
  Write-Host '[1/5] Checking payload integrity...'
  $expected = (Get-Content -LiteralPath $checksum -Raw).Trim()
  if ($expected -notmatch '^[0-9a-fA-F]{64}$') { throw 'The payload checksum file is invalid.' }
  if ((Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash -ne $expected) { throw 'The payload archive is incomplete or corrupt. Re-copy the deployment disc or ZIP.' }
  $tempRoot = [IO.Path]::GetPathRoot([IO.Path]::GetTempPath())
  $targetRoot = [IO.Path]::GetPathRoot($target)
  if ($tempRoot -eq $targetRoot) {
    if ((New-Object IO.DriveInfo($tempRoot)).AvailableFreeSpace -lt 1GB) { throw 'At least 1 GB of free space is needed on the guest drive for setup.' }
  } else {
    foreach ($root in @($tempRoot, $targetRoot)) {
      if ((New-Object IO.DriveInfo($root)).AvailableFreeSpace -lt 512MB) { throw "At least 512 MB free space is needed on guest drive $root." }
    }
  }
  Write-Host '[2/5] Extracting the complete payload...'
  $staging = Join-Path ([IO.Path]::GetTempPath()) ('Earnest-Setup-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $staging | Out-Null
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [IO.Compression.ZipFile]::ExtractToDirectory($package, $staging)
  foreach ($rel in @('app\earnest\cli.py','app\earnest\desktop_v2.py','python\python.exe','python\python314.dll','node\node.exe','driver\EarnestAudioDevice.inf','driver\EarnestAudioDevice.sys','driver\earnestaudiodevice.cat','driver\EarnestAudioDevice.cer','driver\devcon.exe','Open-Earnest.cmd')) {
    if (-not (Test-Path -LiteralPath (Join-Path $staging $rel) -PathType Leaf)) { throw "The package is missing $rel." }
  }
  Write-Host '[3/5] Repairing or installing files (existing files are preserved)...'
  New-Item -ItemType Directory -Path $target -Force | Out-Null
  $sourceRoot = $staging.TrimEnd('\') + '\'
  $count = 0
  foreach ($file in Get-ChildItem -LiteralPath $staging -Recurse -File) {
    $rel = $file.FullName.Substring($sourceRoot.Length)
    $destination = Join-Path $target $rel
    if (-not (Test-Path -LiteralPath $destination -PathType Leaf)) {
      New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
      Copy-Item -LiteralPath $file.FullName -Destination $destination
      $count++
    }
  }
  Write-Host "  Added $count missing files to $target"
  foreach ($rel in @('app\earnest\cli.py','app\earnest\desktop_v2.py','python\python.exe','python\python314.dll','node\node.exe','driver\EarnestAudioDevice.inf','driver\EarnestAudioDevice.sys','driver\earnestaudiodevice.cat','driver\EarnestAudioDevice.cer','driver\devcon.exe')) {
    $installed = Join-Path $target $rel
    $packaged = Join-Path $staging $rel
    if ((Get-FileHash -LiteralPath $installed -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $packaged -Algorithm SHA256).Hash) { throw "Existing essential file differs from this package: $installed. It was preserved. Rename that file and run setup again." }
  }
  $driver = Join-Path $target 'driver'
  $marker = Join-Path $target 'test-signing-needs-restart.txt'
  if (Test-Path -LiteralPath $marker) {
    $changed = [datetime]::Parse((Get-Content -LiteralPath $marker -Raw)).ToUniversalTime()
    if ((Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime() -le $changed) { throw 'Restart the guest, then run this installer again.' }
    Remove-Item -LiteralPath $marker
  }
  Write-Host '[4/5] Checking guest test-signing configuration...'
  $bcd = (& bcdedit.exe /enum '{current}' | Out-String)
  if ($LASTEXITCODE -ne 0) { throw 'Could not inspect guest boot configuration.' }
  if ($bcd -notmatch '(?im)^\s*testsigning\s+Yes\s*$') {
    & bcdedit.exe /set '{current}' testsigning on
    if ($LASTEXITCODE -ne 0) { throw 'Could not enable test signing in the guest.' }
    (Get-Date).ToUniversalTime().ToString('o') | Set-Content -LiteralPath $marker
    Write-Host 'Restart the guest, then run this installer again to install the driver.' -ForegroundColor Yellow
    exit 0
  }
  Write-Host '[5/5] Installing the guest test certificate and device...'
  $cert = Join-Path $driver 'EarnestAudioDevice.cer'
  foreach ($store in @('Root', 'TrustedPublisher')) {
    Write-Host "  Importing guest test certificate into $store..."
    & certutil.exe -f -addstore $store $cert
    if ($LASTEXITCODE -ne 0) { throw "Certificate import failed in $store (certutil exit $LASTEXITCODE)." }
  }
  $findDevice = { Get-CimInstance Win32_PnPEntity | Where-Object { $_.HardwareID -contains 'ROOT\EARNESTAUDIODEVICE' } }
  $device = & $findDevice
  if (-not $device) {
    & (Join-Path $driver 'devcon.exe') install (Join-Path $driver 'EarnestAudioDevice.inf') 'Root\EarnestAudioDevice'
    $device = & $findDevice
    if (-not $device) { throw "Device creation failed (DevCon exit $LASTEXITCODE). See C:\Windows\INF\setupapi.dev.log." }
  } else { Write-Host 'Existing Earnest device found; no duplicate created.' }
  $device | Format-Table Status,Name,DeviceID,ConfigManagerErrorCode -AutoSize
  $desktop = [Environment]::GetFolderPath('Desktop')
  $shell = New-Object -ComObject WScript.Shell
  foreach ($entry in @(@('Earnest VM Lab','Open-Earnest.cmd'),@('Earnest CLI','Earnest-CLI.cmd'),@('Earnest Live View','Live-View.cmd'))) {
    $shortcut = $shell.CreateShortcut((Join-Path $desktop ($entry[0] + '.lnk')))
    $shortcut.TargetPath = Join-Path $target $entry[1]; $shortcut.WorkingDirectory = $target; $shortcut.Save()
  }
  if (@($device | Where-Object { $_.ConfigManagerErrorCode -ne 0 }).Count) { throw 'The device exists but Windows reports a problem. Check the device error code above in Device Manager.' }
  Write-Host "`nSetup finished. Files: $target" -ForegroundColor Green
  Write-Host 'Windows reports no device error. Audio routing and playback still require a separate test.'
} catch {
  Write-Host "`nSETUP FAILED: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
} finally {
  if ($staging -and (Test-Path -LiteralPath $staging)) { Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue }
}
