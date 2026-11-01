"""File input/output: WAV reading (always returns 48 kHz stereo float64), WAV writing (32-bit float), run folders, JSON."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

FS = 48000
ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"


def read_wav(path, fs_out: int = FS):
    """Read a WAV/FLAC file. Returns (x, notes): x is float64 (N, 2) at fs_out; notes is a list of strings describing what was changed."""
    x, fs = sf.read(str(path), dtype="float64", always_2d=True)
    notes = []
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
        notes.append("mono file duplicated to two channels")
    elif x.shape[1] > 2:
        x = x[:, :2]
        notes.append("%d channels in file; only the first two used" % sf.info(str(path)).channels)
    if fs != fs_out:
        g = math.gcd(int(fs), int(fs_out))
        x = resample_poly(x, fs_out // g, int(fs) // g, axis=0)
        notes.append("resampled from %d Hz to %d Hz" % (fs, fs_out))
    return x, notes


def write_wav(path, x, fs: int = FS) -> None:
    sf.write(str(path), np.asarray(x, dtype=np.float32), fs, subtype="FLOAT")


def new_run(cmd: str, base: Path | None = None) -> Path:
    base = base or RUNS
    p = base / ("%s-%s" % (datetime.now().strftime("%Y%m%d-%H%M%S"), cmd))
    n = 1
    while p.exists():
        n += 1
        p = base / ("%s-%s-%d" % (datetime.now().strftime("%Y%m%d-%H%M%S"), cmd, n))
    p.mkdir(parents=True)
    return p


def _default(o):
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def save_json(path, obj) -> None:
    Path(path).write_text(json.dumps(obj, indent=1, default=_default), encoding="utf-8")
