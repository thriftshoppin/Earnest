"""Experimental supervised instrument-family matching from labeled recordings."""
from __future__ import annotations
import hashlib
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.fft import dct

SCHEMA = 'earnest.instrument-reference-model.v1'
FEATURE_VERSION = 'log-spectrum-dct-v1'


def features(samples, fs):
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim == 2:
        x = np.mean(x, axis=1)
    if x.ndim != 1 or len(x) < 256 or not np.isfinite(x).all() or not 8000 <= fs <= 384000:
        raise ValueError('audio must contain finite samples at a supported sample rate')
    if np.max(np.abs(x)) < 1e-5:
        raise ValueError('audio is silent')
    # Cap input duration and normalize level; not suitable for complete songs.
    x = x[:int(fs * 15)]
    x = x / max(float(np.max(np.abs(x))), 1e-12)
    if fs != 16000:
        from math import gcd
        factor = gcd(int(fs), 16000)
        x = signal.resample_poly(x, 16000 // factor, int(fs) // factor)
    if len(x) < 1024:
        x = np.pad(x, (0, 1024 - len(x)))
    _, _, spectrum = signal.stft(x, fs=16000, nperseg=1024, noverlap=768, boundary=None)
    power = np.abs(spectrum) ** 2
    energy = power.sum(axis=0)
    active = energy > max(float(energy.max()) * 1e-4, 1e-12)
    power = power[:, active]
    if power.shape[1] == 0:
        raise ValueError('no active audio frames')
    # Log-spaced spectral energy and DCT supply a small timbre fingerprint.
    hz = np.fft.rfftfreq(1024, 1/16000)
    edges = np.geomspace(50, 8000, 33)
    bands = np.array([power[(hz >= lo) & (hz < hi)].sum(axis=0) for lo, hi in zip(edges[:-1], edges[1:])])
    logbands = np.log(np.maximum(bands, 1e-12))
    coeff = dct(logbands, axis=0, norm='ortho')[1:17]
    return np.concatenate((coeff.mean(axis=1), coeff.std(axis=1))).tolist()


def load_audio(path):
    with sf.SoundFile(str(path)) as f:
        fs = f.samplerate
        data = f.read(frames=fs * 15, dtype='float64', always_2d=True)
    return features(data, fs)


def train(directory):
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError('training directory does not exist')
    records = []
    for folder in sorted(x for x in directory.iterdir() if x.is_dir()):
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in ('.wav', '.flac', '.ogg', '.mp3'):
                v = load_audio(path)
                records.append({'label': folder.name, 'file': str(path.resolve()),
                                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'features': v})
    if len(set(r['label'] for r in records)) < 2:
        raise ValueError('provide recordings in at least two differently labeled folders')
    return {'schema': SCHEMA, 'feature_version': FEATURE_VERSION, 'samples': records,
            'limitations': ['Reference similarity only; not calibrated probabilities.',
              'Designed for short isolated examples; mixtures and unseen instruments may be misleading.',
              'No independent accuracy validation is included.']}


def identify(samples, fs, model):
    if not isinstance(model, dict) or model.get('schema') != SCHEMA or model.get('feature_version') != FEATURE_VERSION:
        raise ValueError('unsupported instrument model')
    records = model.get('samples')
    if not isinstance(records, list) or len(records) < 2:
        raise ValueError('instrument model has insufficient samples')
    try:
        matrix = np.asarray([r['features'] for r in records], dtype=float)
        labels = [r['label'] for r in records]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('invalid model records') from exc
    if matrix.ndim != 2 or matrix.shape[1] != 32 or not np.isfinite(matrix).all() or any(not isinstance(x, str) or not x for x in labels):
        raise ValueError('invalid model features or labels')
    query = np.asarray(features(samples, fs))
    scale = np.maximum(matrix.std(axis=0), 1.0)
    distances = np.sqrt(np.mean(((matrix - query) / scale) ** 2, axis=1))
    best = {}
    for label, dist in zip(labels, distances):
        best[label] = min(best.get(label, float('inf')), float(dist))
    return {'schema': 'earnest.instrument-identification.v1',
            'candidates': [{'label': k, 'distance': v} for k, v in sorted(best.items(), key=lambda x:x[1])],
            'notes': model.get('limitations', []), 'method': FEATURE_VERSION}
