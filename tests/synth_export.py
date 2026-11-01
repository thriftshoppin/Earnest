"""Builds synthetic DAW exports with known answers: N passes of the same suite clip, each through a crossfade effect  y = (1-m)*dry + m*reverb(dry)  over a known
reverb, the last pass dry (m = 0); irregular gaps; normalised to 0 dBFS peak; written at 44.1 kHz / 16-bit by default."""
from __future__ import annotations

import sys
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve, resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from earnest import suite  # noqa: E402
from earnest.io import FS  # noqa: E402
from run_tests import synth_system  # noqa: E402

TAPS = [{"delay_ms": 7.3, "gain_db": -6.0, "pan": -0.6, "source": "L"}, {"delay_ms": 13.1, "gain_db": -9.0, "pan": 0.4, "source": "R"},
        {"delay_ms": 21.7, "gain_db": -12.0, "pan": -0.2, "source": "L"}, {"delay_ms": 34.9, "gain_db": -14.0, "pan": 0.8, "source": "R"},
        {"delay_ms": 52.3, "gain_db": -17.0, "pan": 0.0, "source": "L"}]


def reverb_irs(rt=1.2, rho=0.3, seed=7, level_db=-10.0):
    return synth_system(rt, rho=rho, seed=seed, taps=TAPS, level_db=level_db)


def apply_irs(x, irs):
    y = np.zeros((len(x), 2))
    for k, side in enumerate(("L", "R")):
        for c in range(2):
            y[:, c] += fftconvolve(x[:, k], irs[side][:, c])[: len(x)]
    return y


def make_export(path, mode="full", mixes=(1.0, 0.8, 0.6, 0.3, 0.0), gaps_s=(5.0, 4.5, 9.0, 6.0), lead_s=3.0, fs_out=44100, subtype="PCM_16", normalize=True,
                silent=(), irs=None, manifest_dir=None, gain=None, dither=False, seed=5):
    """Returns truth dict: starts (48 kHz samples, multiples of 480), norm gain, irs. silent = pass indices (0-based) replaced by silence."""
    clip, man = suite.build(mode)
    irs = irs if irs is not None else reverb_irs()
    wet = apply_irs(clip, irs)
    n = len(mixes)
    starts, pos = [], int(round(lead_s * FS) // 480 * 480)
    total = pos
    for i in range(n):
        starts.append(pos)
        pos += len(clip) + (int(round(gaps_s[i % len(gaps_s)] * FS)) // 480 * 480 if i < n - 1 else 0)
    total = pos + int(2 * FS)
    peak = 0.0
    passes = []
    for i, m in enumerate(mixes):
        if i in silent:
            passes.append(np.zeros_like(clip))
            continue
        y = (1.0 - m) * clip + m * wet
        passes.append(y.astype(np.float32))
        peak = max(peak, float(np.abs(y).max()))
    g = (1.0 / peak) if normalize else 1.0
    if gain is not None:
        g = gain
    g_ratio = fs_out // gcd(FS, fs_out), FS // gcd(FS, fs_out)
    up, down = fs_out // gcd(FS, fs_out), FS // gcd(FS, fs_out)
    n_out = int(np.ceil(total * up / down))
    out = np.zeros((n_out, 2), dtype=np.float32)
    for i, p in enumerate(passes):
        q = resample_poly(p.astype(np.float64) * g, up, down, axis=0) if fs_out != FS else p * g
        a = starts[i] * up // down
        out[a:a + len(q)] = q[: n_out - a]
    if dither and subtype == "PCM_16":      # TPDF dither, +-1 LSB, everywhere including the silent parts (what a DAW export with dither does)
        rng = np.random.default_rng(seed)
        for a in range(0, len(out), 4_000_000):
            blk = out[a:a + 4_000_000]
            blk += ((rng.random(blk.shape) - rng.random(blk.shape)) / 32768.0).astype(np.float32)
    sf.write(str(path), out, fs_out, subtype=subtype)
    if manifest_dir is not None:
        import json
        Path(manifest_dir).mkdir(parents=True, exist_ok=True)
        (Path(manifest_dir) / (man["name"] + ".json")).write_text(json.dumps(man), encoding="utf-8")
    return {"starts": starts, "norm_gain": g, "irs": irs, "mixes": list(mixes), "manifest": man, "seconds": n_out / fs_out}
