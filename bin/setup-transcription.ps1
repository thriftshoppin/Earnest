param([string]$RuntimeDir = '')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $RuntimeDir) { $RuntimeDir = Join-Path $root 'runs\runtime\basic-pitch' }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first, then rerun this script.' }
uv python install 3.11
if ($LASTEXITCODE -ne 0) { throw 'Could not install Python 3.11.' }
$python = Join-Path $RuntimeDir 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    uv venv --python 3.11 $RuntimeDir
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the transcription environment.' }
}
uv pip install --python $python -r (Join-Path $root 'requirements-basic-pitch.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install Basic Pitch dependencies.' }
Write-Host "Basic Pitch executable: $(Join-Path $RuntimeDir 'Scripts\basic-pitch.exe')"
Write-Host 'If using a custom runtime directory, pass that executable to earnest transcribe --backend.'
