"""`listen` / `zoom`: the stereo scene sheet. Loudness, correlation, M/S, per-octave pan and coherence, panning-index panogram (Avendano), width over time,
transients with their pan, blind reverberance, and a summary in at most 20 segments."""
from __future__ import annotations

import numpy as np
import pyloudnorm as pyln
from scipy.signal import coherence, find_peaks, stft

from . import dsp
from .dsp import LISTEN_BANDS, db, db_pow
from .io import FS

PAN_BINS = 41
MAX_SEGMENTS = 20


def _r(v, n=2):
    return None if v is None or not np.isfinite(v) else round(float(v), n)


def _corr(a, b):
    return float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else None


def loudness(x: np.ndarray, fs: int):
    meter = pyln.Meter(fs)
    out = {"integrated_lufs": None, "short_term_lufs": []}
    if len(x) >= int(0.4 * fs):
        try:
            v = meter.integrated_loudness(x)
            out["integrated_lufs"] = _r(v) if np.isfinite(v) else None
        except Exception:
            pass
    win, hop = int(3 * fs), int(max(1.0, len(x) / fs / 60.0) * fs)
    for i in range(0, max(len(x) - win, 0) + 1, hop):
        if len(x) < win:
            break
        try:
            v = meter.integrated_loudness(x[i:i + win])
            out["short_term_lufs"].append({"t": _r(i / fs), "lufs": _r(v) if np.isfinite(v) else None})
        except Exception:
            pass
    return out


def panogram(x: np.ndarray, fs: int, nperseg: int, hop: int):
    f, t, ZL = stft(x[:, 0], fs, nperseg=nperseg, noverlap=nperseg - hop, boundary=None, padded=False)
    _, _, ZR = stft(x[:, 1], fs, nperseg=nperseg, noverlap=nperseg - hop, boundary=None, padded=False)
    pl, pr = np.abs(ZL) ** 2, np.abs(ZR) ** 2
    psi = 2 * np.abs(ZL * np.conj(ZR)) / np.maximum(pl + pr, 1e-20)          # similarity: 1 centre, 0 hard-panned
    idx = (1 - psi) * np.where(pr >= pl, 1.0, -1.0)                              # panning index: -1 left .. +1 right
    wgt = pl + pr
    fb = np.unique(np.round(np.geomspace(max(f[1], 30.0), fs / 2, 65)).astype(float))
    fi = np.clip(np.searchsorted(fb, f) - 1, 0, len(fb) - 2)
    pb = np.clip(((idx + 1) / 2 * (PAN_BINS - 1)).round().astype(int), 0, PAN_BINS - 1)
    fp = np.zeros((len(fb) - 1, PAN_BINS))
    np.add.at(fp, (np.repeat(fi[:, None], len(t), 1), pb), wgt)
    nt = min(120, len(t))
    ti = np.minimum((np.arange(len(t)) * nt / len(t)).astype(int), nt - 1)
    tp = np.zeros((nt, PAN_BINS))
    np.add.at(tp, (np.repeat(ti[None, :], len(f), 0), pb), wgt)
    return {"f": f, "t": t, "PL": pl, "PR": pr, "freq_pan": fp, "freq_edges": fb, "time_pan": tp, "time_bins": nt,
            "mean_index": float(np.sum(idx * wgt) / max(wgt.sum(), 1e-20))}


def transients(x: np.ndarray, fs: int):
    hop = int(0.005 * fs)
    m = x.mean(axis=1)
    n = len(m) // hop
    e = np.sqrt((m[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    edb = 20 * np.log10(np.maximum(e, 1e-9))
    base = np.array([np.median(edb[max(i - 10, 0):i]) if i > 0 else edb[0] for i in range(n)])
    rise = edb - base
    pk, _ = find_peaks(rise, height=9.0, distance=20)
    out = []
    for p in pk:
        if edb[p] < -60:
            continue
        s = p * hop
        seg = x[s:s + int(0.02 * fs)]
        el, er = float(np.sum(seg[:, 0] ** 2)), float(np.sum(seg[:, 1] ** 2))
        out.append({"t": _r(s / fs, 3), "rise_db": _r(rise[p]), "level_dbfs": _r(edb[p]), "pan": _r(dsp.pan_from_amps(np.sqrt(el), np.sqrt(er)), 2)})
    out.sort(key=lambda r: -r["rise_db"])
    return out[:24], pk * hop


def reverberance(x: np.ndarray, fs: int, onsets: np.ndarray):
    vals = []
    ms = x.mean(axis=1) ** 2
    for i, s in enumerate(onsets):
        nxt = onsets[i + 1] if i + 1 < len(onsets) else len(ms)
        if nxt - s < int(0.45 * fs) or s + int(0.4 * fs) > len(ms):
            continue
        e_on = ms[s:s + int(0.03 * fs)].mean()
        e_tail = ms[s + int(0.15 * fs): s + int(0.4 * fs)].mean()
        vals.append(db_pow(e_tail / max(e_on, 1e-20)))
    return {"tail_over_onset_db_mean": _r(np.mean(vals)) if vals else None, "tail_over_onset_db_sd": _r(np.std(vals)) if vals else None, "onsets_used": len(vals),
            "meaning": "mean energy 150-400 ms after an onset relative to the 30 ms onset itself; higher (closer to 0 dB) = more reverberant. Only onsets with 450 ms of room before the next one."}


def analyze(x: np.ndarray, fs: int = FS, hires: bool = False):
    n = len(x)
    L, R = x[:, 0], x[:, 1]
    res = {"seconds": _r(n / fs, 3), "peak_dbfs": _r(db(np.abs(x).max())), "true_peak_dbtp": _r(dsp.true_peak_db(x)),
           "rms_dbfs": _r(db(np.sqrt(np.mean(x ** 2))))}
    res["loudness"] = loudness(x, fs)
    res["phase_correlation"] = _r(_corr(L, R), 3)
    M, S = (L + R) / 2, (L - R) / 2
    res["mid_side_db"] = _r(db_pow(np.mean(M ** 2)) - db_pow(np.mean(S ** 2)))
    bands = []
    for fc in LISTEN_BANDS:
        if fc * 2 ** 0.5 > fs / 2:
            continue
        bl, br = dsp.bandpass_fft(L, fs, fc, 1), dsp.bandpass_fft(R, fs, fc, 1)
        rl, rr = float(np.sqrt(np.mean(bl ** 2))), float(np.sqrt(np.mean(br ** 2)))
        lo, hi = dsp.edges(fc, 1)
        coh = None
        if n >= 4096:
            f, c = coherence(L, R, fs, nperseg=4096)
            sel = (f >= lo) & (f < hi)
            coh = float(c[sel].mean()) if sel.any() else None
        bands.append({"hz": fc, "level_db": _r(db(np.sqrt(rl ** 2 + rr ** 2))), "ild_pan": _r(dsp.pan_from_amps(rl, rr), 3), "ild_db": _r(db(rl) - db(rr)),
                      "coherence": _r(coh, 3), "corr": _r(_corr(bl, br), 3)})
    res["bands"] = bands
    npr, hop = (4096, 1024) if hires else (2048, 512)
    pg = panogram(x, fs, npr, hop)
    res["panogram"] = {"mean_panning_index": _r(pg["mean_index"], 3), "fft": npr, "hop": hop,
                       "energy_by_pan_bin_db": [_r(db_pow(v / max(pg["freq_pan"].sum(), 1e-20))) for v in pg["freq_pan"].sum(axis=0)]}
    # width and correlation over time
    wl = int(0.5 * fs) if not hires else int(0.1 * fs)
    series = []
    for i in range(0, n - wl + 1, wl):
        a, b = L[i:i + wl], R[i:i + wl]
        m, s = (a + b) / 2, (a - b) / 2
        em, es = np.mean(m ** 2), np.mean(s ** 2)
        series.append({"t": _r(i / fs, 3), "width": _r(es / max(em + es, 1e-20), 3), "corr": _r(_corr(a, b), 3), "rms_dbfs": _r(db(np.sqrt(np.mean(np.stack([a, b]) ** 2)))),
                       "pan": _r(dsp.pan_from_amps(np.sqrt(np.mean(a ** 2)), np.sqrt(np.mean(b ** 2))), 3)})
    res["width_series"] = series
    tr, onsets = transients(x, fs)
    res["transients"] = tr
    res["reverberance"] = reverberance(x, fs, onsets)
    segs = []
    ns = min(MAX_SEGMENTS, max(1, len(series)))
    for k in range(ns):
        part = series[k * len(series) // ns:(k + 1) * len(series) // ns]
        if not part:
            continue
        segs.append({"t_from": part[0]["t"], "t_to": _r(part[-1]["t"] + wl / fs, 3), "rms_dbfs": _r(np.mean([p["rms_dbfs"] for p in part])),
                     "width": _r(np.mean([p["width"] for p in part]), 3), "corr": _r(np.mean([p["corr"] for p in part if p["corr"] is not None] or [np.nan]), 3),
                     "pan": _r(np.mean([p["pan"] for p in part]), 3)})
    res["segments"] = segs
    return res, pg
