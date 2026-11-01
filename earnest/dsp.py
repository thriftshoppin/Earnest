"""Shared maths. Several routines are ported (not imported) from the desktop bridge's dsp.py: zero-phase band-pass, Schroeder backward integration,
sweep deconvolution idea, M/S and correlation. The bridge itself is never imported."""
from __future__ import annotations

import numpy as np

EPS = 1e-12
EDC_BANDS = [125, 250, 500, 1000, 2000, 4000, 8000]                    # octave centres used for the room formula
LISTEN_BANDS = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]  # octave centres used by `listen`


def db(x) -> float:
    return float(20.0 * np.log10(max(float(x), EPS)))


def db_pow(x) -> float:
    return float(10.0 * np.log10(max(float(x), EPS)))


def edges(fc: float, per_octave: int = 1):
    h = 2.0 ** (1.0 / (2 * per_octave))
    return fc / h, fc * h


def bandpass_fft(x: np.ndarray, fs: float, fc: float, per_octave: int = 1, order: int = 6) -> np.ndarray:
    """Zero-phase band-pass with a smooth Butterworth-shaped magnitude. A brick-wall mask would ring and corrupt decay measurements."""
    n = len(x)
    N = n + int(0.5 * fs)
    X = np.fft.rfft(x, N)
    f = np.fft.rfftfreq(N, 1.0 / fs)
    lo, hi = edges(fc, per_octave)
    with np.errstate(divide="ignore", over="ignore"):
        lp = 1.0 / np.sqrt(1.0 + (f / hi) ** (2 * order))
        hp = np.where(f > 0, 1.0 / np.sqrt(1.0 + (lo / np.maximum(f, 1e-9)) ** (2 * order)), 0.0)
    return np.fft.irfft(X * lp * hp, N)[:n]


def parabolic(y: np.ndarray, k: int) -> float:
    """Sub-sample offset of the peak at index k (-0.5..0.5)."""
    if 0 < k < len(y) - 1:
        y0, y1, y2 = y[k - 1], y[k], y[k + 1]
        d = y0 - 2 * y1 + y2
        if d != 0:
            return float(np.clip(0.5 * (y0 - y2) / d, -0.5, 0.5))
    return 0.0


def pan_from_amps(aL: float, aR: float) -> float:
    """Pan in [-1 (left), +1 (right)] from two amplitudes, the exact inverse of the constant-power law gL=cos(th), gR=sin(th), th=(p+1)*pi/4."""
    th = np.arctan2(abs(aR), abs(aL))
    return float(4.0 * th / np.pi - 1.0)


def pan_gains(p: float):
    th = (p + 1.0) * np.pi / 4.0
    return float(np.cos(th)), float(np.sin(th))


def sweep_signal(fs: float, f1: float, f2: float, seconds: float) -> np.ndarray:
    t = np.arange(int(round(seconds * fs))) / fs
    Lr = seconds / np.log(f2 / f1)
    return np.sin(2 * np.pi * f1 * Lr * (np.exp(t / Lr) - 1.0))


def deconvolve(dry: np.ndarray, wet: np.ndarray, max_len: int | None = None, eps_rel: float = 1e-4, neg_s: float = 2.0, fs: int = 48000):
    """Impulse response h with wet ~ dry * h (single channels), by regularised spectral division. Works for any broadband dry signal (sweep or noise)
    and absorbs latency, including a wet file that starts earlier than the dry one (negative lag, up to neg_s). Returns (h, neg): h[neg] is time zero
    of the dry/wet alignment. Distortion products of a non-linear system sit before the main arrival, so only the part after the peak is used."""
    n = len(dry) + len(wet)
    N = 1 << (n - 1).bit_length()
    X = np.fft.rfft(dry, N)
    Y = np.fft.rfft(wet, N)
    P = np.abs(X) ** 2
    eps = eps_rel * P.max()
    H = np.conj(X) * Y / (P + eps)
    h = np.fft.irfft(H, N)
    neg = min(int(neg_s * fs), N // 4)
    h = np.concatenate([h[N - neg:], h[: (max_len or len(wet))]])
    return h, neg


def smooth(e: np.ndarray, n: int) -> np.ndarray:
    n = max(int(n), 1)
    return np.convolve(e, np.ones(n) / n, mode="same")


def decay(e: np.ndarray, fs: float):
    """Schroeder backward integration of an energy sequence that starts at the arrival. Returns dict(edc_db, t, t20, t30, edt, noise_db_below_peak)."""
    n = len(e)
    if n < 64:
        return None
    noise = float(np.mean(e[int(n * 0.9):]))
    e2 = np.maximum(e - noise, 0)
    sm = smooth(e2, 0.005 * fs)
    ip = int(np.argmax(sm))
    peak = float(sm.max())
    if peak <= 0:
        return None
    thr = max(noise * 2.0, peak * 1e-9)
    idx = np.where(sm[ip:] < thr)[0]
    cut = ip + int(idx[0]) if len(idx) else n
    e3 = e2[:cut]
    if len(e3) < 32:
        return None
    edc = np.cumsum(e3[::-1])[::-1]
    edc_db = 10 * np.log10(np.maximum(edc / edc[0], EPS))
    t = np.arange(len(edc_db)) / fs

    def fit(lo, hi, scale):
        sel = np.where((edc_db <= lo) & (edc_db >= hi))[0]
        if len(sel) < 8:
            return None
        sl = np.polyfit(t[sel], edc_db[sel], 1)[0]
        return None if sl >= 0 else float(-scale / sl * 1.0)

    # slope fitted between lo and hi dB; result is the time for a 60 dB fall at that slope
    return {"edc_db": edc_db, "t": t, "t20": fit(-5, -25, 60.0), "t30": fit(-5, -35, 60.0), "edt": fit(0, -10, 60.0),
            "dyn_range_db": float(-edc_db[-1])}


def iacc(a: np.ndarray, b: np.ndarray, fs: float, max_ms: float = 1.0) -> float | None:
    """Maximum normalised cross-correlation of a and b over lags within +-max_ms."""
    if len(a) < 64 or a.std() == 0 or b.std() == 0:
        return None
    n = len(a)
    N = 1 << (2 * n - 1).bit_length()
    c = np.fft.irfft(np.conj(np.fft.rfft(a, N)) * np.fft.rfft(b, N), N)
    m = int(max_ms * fs / 1000)
    seg = np.concatenate([c[-m:], c[: m + 1]]) if m > 0 else c[:1]
    return float(seg.max() / np.sqrt(np.sum(a * a) * np.sum(b * b)))


def true_peak_db(x: np.ndarray) -> float:
    from scipy.signal import resample_poly
    y = resample_poly(x, 4, 1, axis=0)
    return db(np.abs(y).max())
