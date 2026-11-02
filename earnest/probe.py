"""Looking at an export file before any analysis: per-channel statistics, the resampling check, and the matched filter (is the probe in here, in which channel, how strongly).
Everything streams from disk in chunks."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import find_peaks

from .dsp import db
from .io import FS

BITS = {"PCM_16": 16, "PCM_24": 24, "PCM_32": 32, "FLOAT": 32, "DOUBLE": 64, "PCM_U8": 8, "PCM_S8": 8}
CLIP = 0.9999


def file_hash(path, block=1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _db(x):
    return round(db(x), 2) if x > 0 else -999.0


def read_stats(path, head_s: float = 2.0, end_s: float = 1.0, chunk: int = 1 << 20) -> dict:
    """Per channel: frames, peak, RMS, DC offset, clipped sample count, noise floor from the first head_s and last end_s seconds, and the L/R correlation. Streams the file."""
    info = sf.info(str(path))
    ch = info.channels
    n = np.zeros(ch)
    peak = np.zeros(ch)
    s1 = np.zeros(ch)
    s2 = np.zeros(ch)
    clipped = np.zeros(ch, dtype=np.int64)
    sxy = 0.0
    frames = 0
    with sf.SoundFile(str(path)) as f:
        while True:
            x = f.read(chunk, dtype="float64", always_2d=True)
            if not len(x):
                break
            frames += len(x)
            a = np.abs(x)
            peak = np.maximum(peak, a.max(axis=0))
            s1 += x.sum(axis=0)
            s2 += (x ** 2).sum(axis=0)
            clipped += (a >= CLIP).sum(axis=0)
            if ch >= 2:
                sxy += float((x[:, 0] * x[:, 1]).sum())
    n[:] = frames
    fs = info.samplerate
    hd = int(head_s * fs)
    ed = int(end_s * fs)
    head, _ = sf.read(str(path), start=0, frames=min(hd, frames), dtype="float64", always_2d=True)
    tail, _ = sf.read(str(path), start=max(frames - ed, 0), frames=ed, dtype="float64", always_2d=True)
    sil = np.concatenate([head, tail])
    floor = [float(np.sqrt(np.mean(sil[:, c] ** 2))) for c in range(ch)]
    rms = np.sqrt(s2 / max(frames, 1))
    corr = None
    if ch >= 2 and s2[0] > 0 and s2[1] > 0:
        # correlation of the means-removed channels
        m0, m1 = s1[0] / frames, s1[1] / frames
        num = sxy / frames - m0 * m1
        den = np.sqrt((s2[0] / frames - m0 ** 2) * (s2[1] / frames - m1 ** 2))
        corr = float(num / den) if den > 0 else None
    return {"path": str(path), "frames": [int(frames)] * ch, "channels": ch, "samplerate": fs, "seconds": frames / fs, "subtype": info.subtype, "format": info.format,
            "bits": BITS.get(info.subtype), "peak_dbfs": [_db(p) for p in peak], "rms_dbfs": [_db(r) for r in rms],
            "dc": [float(s1[c] / max(frames, 1)) for c in range(ch)], "clipped": [int(c) for c in clipped],
            "floor_dbfs": [(_db(v) if v > 0 else -140.0) for v in floor], "digital_silence_floor": [bool(v == 0) for v in floor], "lr_corr": corr}


def resample_check(src, read_peak_dbfs) -> dict:
    """Per-channel peak after resampling to 48 kHz, streamed, against the peak read from the file."""
    after = np.zeros(2)
    for a, x in src.chunks(40 * FS, 0):
        after = np.maximum(after, np.abs(x).max(axis=0))
    after_db = [_db(v) for v in after]
    diff = [round(after_db[c] - read_peak_dbfs[c], 3) if read_peak_dbfs[c] > -900 and after_db[c] > -900 else None for c in range(2)]
    return {"frames_in": int(src.n_in), "frames_out": int(src.n), "peak_after_dbfs": after_db, "peak_diff_db": diff}


def match_file(src, dry, manifest) -> dict:
    """Matched filter of EACH channel of the file against EACH sweep block (sweep_L, sweep_R). The whole file is correlated (FFT, chunked), so the sweep's processing gain
    (about 56 dB for an 8 s sweep) is used. Per (channel, sweep): peak-to-noise in dB, where the probe copy starts (ms), the estimated probe level in the file in dBFS.
    Noise = robust sigma of the correlation away from its peak; the detection threshold is the expected maximum of Gaussian noise over all lags (sigma * sqrt(2 ln N)) plus a 25 % margin."""
    out = {"scores": [], "threshold_db": None}
    by = {b["name"]: b for b in manifest["blocks"]}
    size = 40 * FS
    refs = {}
    for name, ch in (("sweep_L", 0), ("sweep_R", 1)):
        b = by[name]
        refs[name] = (dry[b["start_sample"]: b["start_sample"] + b["length_samples"], ch], b)
    L = max(len(r) for r, _ in refs.values())
    N = 1 << (size + L - 1).bit_length()
    FR = {k: np.conj(np.fft.rfft(r, N)) for k, (r, _) in refs.items()}
    cands = {(c, k): [] for c in range(2) for k in refs}
    noise = {(c, k): [] for c in range(2) for k in refs}
    n_lags = max(src.n - L, 1)
    for a, x in src.chunks(size, L + FS):
        X = [np.fft.rfft(x[:, c], N) for c in range(2)]
        for k, (r, b) in refs.items():
            for c in range(2):
                v = np.fft.irfft(X[c] * FR[k], N)[: max(len(x) - len(r) + 1, 1)]
                av = np.abs(v)
                pk_i, _ = find_peaks(av, distance=FS)
                top = pk_i[np.argsort(av[pk_i])[::-1][:6]] if len(pk_i) else np.array([int(np.argmax(av))])
                cands[(c, k)] += [(float(av[i]), a + int(i) - b["start_sample"]) for i in top]
                noise[(c, k)].append(av[:: 61].copy())
    thr_db = None
    best = {}
    for key, cl in cands.items():     # the strongest peak; where several are about equal (sweep_L and its repeat), the earliest one is the copy start
        mx = max((v for v, _ in cl), default=0.0)
        early = min((p for v, p in cl if v >= 0.8 * mx), default=0)
        best[key] = [mx, early]
    for (c, k), (pk, pos) in best.items():
        r, b = refs[k]
        samp = np.concatenate(noise[(c, k)]) if noise[(c, k)] else np.zeros(1)
        sigma = float(np.median(samp) / 0.6745) if len(samp) else 0.0
        pn = db(pk / sigma) if sigma > 0 and pk > 0 else (200.0 if pk > 0 else 0.0)
        thr = sigma * np.sqrt(2 * np.log(n_lags)) * 1.25
        thr_db_k = db(thr / sigma) if sigma > 0 else 0.0
        thr_db = thr_db_k
        amp = pk / max(float(np.sum(r ** 2)), 1e-30)          # estimated gain of the probe sweep in this channel (the dry reference sweep is at its own level)
        level = db(amp * float(np.abs(r).max())) if amp > 0 else -999.0
        out["scores"].append({"channel": c, "sweep": k, "peak_to_noise_db": round(pn, 1), "copy_start_ms": round(pos / FS * 1000.0, 1), "probe_level_dbfs": round(level, 1),
                              "detected": bool(pk > thr) and pk > 0})
    out["threshold_db"] = round(thr_db or 0.0, 1)
    out["lags"] = int(n_lags)
    return out
