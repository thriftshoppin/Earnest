param([string]$InstallDirectory = $env:EARNEST_LAB_INSTALL_DIR)
$ErrorActionPreference = 'Stop'
try {
    if ([string]::IsNullOrWhiteSpace($InstallDirectory)) { $InstallDirectory = Join-Path $env:USERPROFILE 'tools\Earnest-VM-Lab' }
    $target = [IO.Path]::GetFullPath($InstallDirectory)
    Write-Host '[1/5] Updating the existing lab application...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'Update-Earnest-VM.ps1') -InstallDirectory $target
    if ($LASTEXITCODE -ne 0) { throw 'Application update failed; check the error above.' }
    Write-Host '[2/5] Checking model setup prerequisites...'
    $uv = Get-Command uv.exe -ErrorAction SilentlyContinue
    if (-not $uv) {
        if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { throw 'The app is updated, but winget is unavailable. Install uv, then rerun this full update.' }
        & winget.exe install --id astral-sh.uv --exact --scope user --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { throw "The app is updated, but installing uv failed (exit $LASTEXITCODE). Install uv and rerun this full update." }
        $env:PATH += ';' + (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links') + ';' + (Join-Path $env:USERPROFILE '.local\bin')
        $uv = Get-Command uv.exe -ErrorAction SilentlyContinue
        if (-not $uv) { throw 'The app is updated, but uv is not visible yet. Open a new command window and rerun this full update.' }
    }
    $app = Join-Path $target 'app'
    Write-Host '[3/5] Installing Demucs and its separate Python runtime (download may be large)...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'bin\setup-separation.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'The app is updated, but Demucs setup failed. Check the error above and rerun this full update.' }
    Write-Host '[4/5] Installing Basic Pitch and its separate Python runtime...'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'bin\setup-transcription.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'The app is updated, but Basic Pitch setup failed. Check the error above and rerun this full update.' }
    foreach ($file in @('runs\runtime\demucs\Scripts\demucs.exe','runs\runtime\basic-pitch\Scripts\basic-pitch.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $app $file) -PathType Leaf)) { throw "Model executable not found: $file" }
    }
    Write-Host '[5/5] Loading model backends and downloading Demucs weights...'
    & (Join-Path $app 'runs\runtime\demucs\Scripts\python.exe') -c "from demucs.pretrained import get_model; model=get_model('htdemucs'); print('Demucs htdemucs ready')"
    if ($LASTEXITCODE -ne 0) { throw 'The app and runtimes are installed, but loading Demucs or downloading its model failed. Check the error above and rerun the full update.' }
    & (Join-Path $app 'runs\runtime\basic-pitch\Scripts\python.exe') -c "import basic_pitch.inference; print('Basic Pitch ready')"
    if ($LASTEXITCODE -ne 0) { throw 'The app and runtimes are installed, but Basic Pitch could not load. Check the error above and rerun the full update.' }
    Write-Host 'Full application and model-runtime update completed.' -ForegroundColor Green
    Write-Host 'Open app\Frankenjack.cmd. CUDA host bridge and continuous live separation are not included.'
} catch { Write-Host "FULL UPDATE FAILED: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }
