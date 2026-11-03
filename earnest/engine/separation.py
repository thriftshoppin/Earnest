"""Optional Demucs source-separation adapter."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess


def separate_demucs(audio: str, output_dir: str, backend: str | None = None, device: str = 'cpu') -> dict:
    source = Path(audio).resolve()
    if not source.is_file():
        raise ValueError('input audio file does not exist')
    if device not in ('cpu', 'cuda'):
        raise ValueError('device must be cpu or cuda')
    root = Path(__file__).resolve().parents[2]
    default = root / 'runs' / 'runtime' / 'demucs' / 'Scripts' / ('demucs.exe' if os.name == 'nt' else 'demucs')
    executable = Path(backend or os.environ.get('EARNEST_DEMUCS', str(default))).expanduser().resolve()
    if not executable.is_file():
        raise ValueError('Demucs executable not found; install the optional backend or specify --backend')
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy(); environment['PYTHONUTF8'] = '1'
    cmd = [str(executable), '-d', device, '-n', 'htdemucs', '--shifts', '0', '--float32', '--filename', '{stem}.{ext}', '-o', str(output), str(source)]
    result = subprocess.run(cmd, env=environment, check=False)
    if result.returncode:
        raise RuntimeError('Demucs failed with exit code %d; partial outputs are in %s' % (result.returncode, output))
    stem_dir = output / 'htdemucs'
    stems = {name: str((stem_dir / (name + '.wav')).resolve()) for name in ('vocals', 'drums', 'bass', 'other')}
    if not all(Path(p).is_file() for p in stems.values()):
        raise RuntimeError('Demucs did not produce all four expected stems; inspect %s' % output)
    digest = hashlib.sha256()
    with source.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): digest.update(block)
    manifest = {'schema': 'earnest.separation.v1', 'backend': 'demucs', 'model': 'htdemucs',
                'backend_executable': str(executable), 'device': device, 'input_file': str(source),
                'input_sha256': digest.hexdigest(), 'stems': stems,
                'limits': ['Stems are model estimates, not original isolated tracks.',
                           'Other may contain multiple instruments; effects and room sound can remain in every stem.',
                           'Demucs may rescale stems to avoid clipping; summing stems is not guaranteed to reproduce the input.']}
    with (output / 'earnest-separation.json').open('x', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, allow_nan=False); f.write('\n')
    return manifest
