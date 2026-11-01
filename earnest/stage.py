"""`stage` metrics from the three width blocks (noise_mid = input correlation +1, noise_wide = 0, noise_side = -1): how the effect changes stereo width.
Per input: L/R correlation and side/mid dB of the direct part (the burst windows) and of the tail (0.5 s to 5 s after each burst ends, cut before the next burst),
and the tail per octave band 125 Hz-8 kHz."""
from __future__ import annotations

import numpy as np

from . import dsp
from .dsp import EDC_BANDS
from .io import FS

BLOCKS = ("noise_mid", "noise_wide", "noise_side")
CLAMP_DB = 60.0
TAIL_FROM_S, TAIL_TO_S = 0.5, 5.0


def burst_windows(dry: np.ndarray, fs: int = FS):
    """(start, end) sample pairs of the bursts in a dry width block, from its envelope."""
    env = np.abs(dry).max(axis=1)
    on = np.where(env > 0.01 * env.max())[0]
    if not len(on):
        return []
    gaps = np.where(np.diff(on) > int(0.2 * fs))[0]
    starts = [on[0]] + [on[g + 1] for g in gaps]
    ends = [on[g] for g in gaps] + [on[-1]]
    return list(zip(starts, ends))


def _power(x: np.ndarray, wins) -> float:
    n = sum(b - a for a, b in wins)
    return float(sum(np.sum(x[a:b] ** 2) for a, b in wins) / max(n, 1))


NO_TAIL_RATIO = 1e-7          # tail power below this fraction of the direct power: there is no tail to measure (the Mix 0 pass)


def _pooled(x: np.ndarray, wins):
    """Zero-lag L/R correlation and side/mid dB pooled over several windows (energy-weighted)."""
    sl = sr = slr = em = es = 0.0
    for a, b in wins:
        L, R = x[a:b, 0], x[a:b, 1]
        sl += float(np.sum(L * L))
        sr += float(np.sum(R * R))
        slr += float(np.sum(L * R))
        em += float(np.sum(((L + R) / 2) ** 2))
        es += float(np.sum(((L - R) / 2) ** 2))
    corr = slr / np.sqrt(sl * sr) if sl > 0 and sr > 0 else None
    sm = float(np.clip(10 * np.log10(max(es, 1e-30) / max(em, 1e-30)), -CLAMP_DB, CLAMP_DB))
    return (None if corr is None else round(float(corr), 4)), round(sm, 2)


def compute(dry_blocks: dict, wet_blocks: dict, fs: int = FS) -> dict:
    out = {}
    for name in BLOCKS:
        if name not in dry_blocks or name not in wet_blocks:
            continue
        d, w = dry_blocks[name], wet_blocks[name]
        bw = burst_windows(d, fs)
        if not bw or len(w) < bw[-1][1]:
            out[name] = {"error": "no bursts found or wet block too short"}
            continue
        dwin = [(a, min(b + int(0.05 * fs), len(w))) for a, b in bw]
        twin = []
        for i, (a, b) in enumerate(bw):
            nxt = bw[i + 1][0] if i + 1 < len(bw) else len(w)
            t0, t1 = b + int(TAIL_FROM_S * fs), min(b + int(TAIL_TO_S * fs), nxt - int(0.1 * fs), len(w))
            if t1 - t0 > int(0.5 * fs):
                twin.append((t0, t1))
        ic, ism = _pooled(d, [(a, b) for a, b in bw])
        dc, dsm = _pooled(w, dwin)
        tb = {"bands_hz": [], "corr": [], "sm_db": []}
        has_tail = bool(twin) and _power(w, twin) > NO_TAIL_RATIO * _power(w, dwin)
        for fc in EDC_BANDS:
            xb = np.stack([dsp.bandpass_fft(w[:, c], fs, fc, 1) for c in range(2)], axis=1) if has_tail else None
            c, s = _pooled(xb, twin) if has_tail else (None, None)
            tb["bands_hz"].append(fc)
            tb["corr"].append(c)
            tb["sm_db"].append(s)
        tc, tsm = _pooled(w, twin) if has_tail else (None, None)
        res = {"input_corr": ic, "input_side_over_mid_db": ism, "direct": {"corr": dc, "side_over_mid_db": dsm},
               "has_tail": has_tail, "tail": {"broadband_corr": tc, "broadband_side_over_mid_db": tsm, **tb}, "tail_window_s": "0.5 s after each burst ends, up to 5 s or 0.1 s before the next burst",
               "width_gain_db": None}
        if name == "noise_wide":       # the input has side and mid energy, so a gain is defined
            res["width_gain_db"] = {"direct": round(dsm - ism, 2), "tail": None if tsm is None else round(tsm - ism, 2)}
        out[name] = res
    return out
