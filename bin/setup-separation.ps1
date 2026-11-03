param([string]$RuntimeDir = '')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $RuntimeDir) { $RuntimeDir = Join-Path $root 'runs\runtime\demucs' }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first, then rerun this script.' }
uv python install 3.11
if ($LASTEXITCODE -ne 0) { throw 'Could not install Python 3.11.' }
$python = Join-Path $RuntimeDir 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    uv venv --python 3.11 $RuntimeDir
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the separation environment.' }
}
uv pip install --python $python -r (Join-Path $root 'requirements-demucs.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install Demucs dependencies.' }
Write-Host "Demucs executable: $(Join-Path $RuntimeDir 'Scripts\demucs.exe')"
Write-Host 'First use downloads model weights. For a custom runtime directory pass the executable to earnest separate --backend.'
