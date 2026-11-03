"""Optional adapter for an isolated Basic Pitch transcription backend."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess


def transcribe_basic_pitch(audio: str, output_dir: str, backend: str | None = None) -> dict:
    source = Path(audio).resolve()
    if not source.is_file():
        raise ValueError('input audio file does not exist')
    root = Path(__file__).resolve().parents[2]
    default = root / 'runs' / 'runtime' / 'basic-pitch' / 'Scripts' / ('basic-pitch.exe' if os.name == 'nt' else 'basic-pitch')
    executable = Path(backend or os.environ.get('EARNEST_BASIC_PITCH', str(default))).expanduser().resolve()
    if not executable.is_file():
        raise ValueError('Basic Pitch executable not found; install the optional backend or specify --backend')
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment['PYTHONUTF8'] = '1'
    result = subprocess.run([str(executable), str(output), str(source), '--save-note-events'], env=environment, check=False)
    if result.returncode:
        raise RuntimeError('Basic Pitch failed with exit code %d; partial outputs are in %s' % (result.returncode, output))
    midi = sorted(output.glob('*.mid'))
    if not midi:
        raise RuntimeError('Basic Pitch did not produce MIDI; inspect %s' % output)
    digest = hashlib.sha256()
    with source.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    version = None
    python = executable.parent / ('python.exe' if os.name == 'nt' else 'python')
    if python.is_file():
        check = subprocess.run([str(python), '-c', 'import importlib.metadata as m; print(m.version("basic-pitch"))'],
                               env=environment, capture_output=True, text=True, check=False)
        if check.returncode == 0:
            version = check.stdout.strip()
    manifest = {'schema': 'earnest.transcription.v1', 'backend': 'basic-pitch', 'backend_version': version,
                'backend_executable': str(executable), 'input_file': str(source), 'input_sha256': digest.hexdigest(),
                'midi_files': [str(p.resolve()) for p in midi],
                'note_event_files': [str(p.resolve()) for p in sorted(output.glob('*.csv'))],
                'limits': ['Transcription is an estimate; Basic Pitch works best on one instrument at a time.',
                           'This does not identify instruments or separate a mixture into source tracks.']}
    with (output / 'earnest-transcription.json').open('x', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, allow_nan=False); f.write('\n')
    return manifest
