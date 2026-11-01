"""The reverb formula: schema (built from a `room` analysis) and the synthesiser that renders it.

y_o(t) = sum_i [ M[o][i] x_i(t) + sum_k a_k x_i(t - tau_k) g_o(p_k)  (taps whose source is i) + (tail_i * x_i)_o ]
The tail is decorrelated noise per octave band: level re direct, EDT-then-RT60 decay, pre-delay, build-up, and L/R correlation (IACC)."""
from __future__ import annotations

import numpy as np
from scipy.signal import fftconvolve

from . import dsp
from .dsp import EDC_BANDS
from .io import FS

PRE_S = 0.04
VERSION = 1


def build(res: dict, source: str = "") -> dict:
    ins = res["inputs"]
    M = [[res["direct_matrix"][i][o] for i in ins] for o in range(2)]
    tb = res["tail_bands"]
    f = {
        "version": VERSION, "fs": FS, "source": source, "inputs": ins,
        "input_mode": res.get("input_mode"), "nonlinear_or_time_variant": res.get("nonlinear_or_time_variant"),
        "M": M,
        "early_taps": res["early_taps"],
        "tail": {
            "bands_hz": [b["hz"] for b in tb], "level_db": [b["level_db"] for b in tb], "rt60_s": [b["rt60_s"] for b in tb],
            "t20_s": [b["t20_s"] for b in tb], "t30_s": [b["t30_s"] for b in tb], "edt_s": [b["edt_s"] for b in tb],
            "pre_delay_ms": [b.get("pre_delay_ms") for b in tb], "buildup_ms": [b.get("buildup_ms") for b in tb],
            "iacc": [b.get("iacc") for b in tb], "modulation": [b.get("modulation") for b in tb],
        },
        "room": res["room"],
        "notes": "tail is statistical: noise shaped by these numbers, not the original waveform; linear time-invariant assumption (see nonlinear_or_time_variant)",
    }
    return f


def _fill(vals, default):
    v = [x for x in vals if x is not None]
    if not v:
        return [default] * len(vals)
    out, last = [], None
    for x in vals:
        last = x if x is not None else (last if last is not None else v[0])
        out.append(last)
    return out


def target_curve_db(rt60: float, edt: float | None, t: np.ndarray) -> np.ndarray:
    """Energy decay curve (dB) implied by the formula: EDT slope down to -10 dB, then the RT60 slope."""
    edt = edt or rt60
    t10 = edt / 6.0
    return np.where(t < t10, -60.0 * t / edt, -10.0 - 60.0 * (t - t10) / rt60)


def synth_ir(f: dict, seed: int = 0, fs: int = FS) -> dict:
    """Impulse responses {input: (n, 2)} with the arrival at index PRE_S*fs."""
    rng = np.random.default_rng(seed)
    pre = int(PRE_S * fs)
    ins = f["inputs"]
    tl = f["tail"]
    rt = _fill(tl["rt60_s"], 1.0)
    T = float(min(max(rt) * 1.25 + 0.6, 8.0))
    n = pre + int(T * fs)
    edt = _fill(tl["edt_s"], 1.0)
    lev = _fill(tl["level_db"], -20.0)
    pd = _fill(tl["pre_delay_ms"], 5.0)
    bu = _fill(tl["buildup_ms"], 0.0)
    ia = _fill(tl["iacc"], 0.3)
    irs = {}
    ref = max(float(np.hypot(*[f["M"][o][k] for o in range(2)])) for k in range(len(ins)))
    for k, side in enumerate(ins):
        h = np.zeros((n, 2))
        h[pre, 0], h[pre, 1] = f["M"][0][k], f["M"][1][k]
        for t in f["early_taps"].get("taps", []):
            if t["source"] != side:
                continue
            x = pre + t["delay_ms"] * fs / 1000.0
            i0 = int(np.floor(x))
            fr = x - i0
            a = ref * 10 ** (t["gain_db"] / 20.0)
            gl, gr = dsp.pan_gains(t["pan"])
            for idx, w in ((i0, 1 - fr), (i0 + 1, fr)):
                if idx < n:
                    h[idx, 0] += a * gl * w
                    h[idx, 1] += a * gr * w
        irs[side] = h
    tt = np.arange(n - pre) / fs
    dw_of = lambda fc: int(max(0.003, 2.7 / fc) * fs)
    for b, fc in enumerate(EDC_BANDS):
        dw = dw_of(fc)
        hb_base = {s: np.stack([dsp.bandpass_fft(irs[s][:, c], fs, fc, 1) for c in range(2)], axis=1) for s in ins}
        e_dir = sum(np.sum(hb[pre - dw: pre + dw] ** 2) for hb in hb_base.values())
        e_base_after = sum(np.sum(hb[pre + dw:] ** 2) for hb in hb_base.values())
        tails = {}
        for s in ins:
            w1, w2 = rng.standard_normal(n - pre), rng.standard_normal(n - pre)
            rho = float(np.clip(ia[b], 0.0, 0.999))
            nl, nr = w1, rho * w1 + np.sqrt(1 - rho ** 2) * w2
            ldb = target_curve_db(rt[b], edt[b], tt)
            t_pre, t_pk = pd[b] / 1000.0, (pd[b] + bu[b]) / 1000.0
            env = 10 ** (ldb / 20.0)
            ramp = np.where(tt < t_pre, 0.0, np.where(tt < t_pk, 10 ** (-15 / 20.0 * np.clip(1 - (tt - t_pre) / max(t_pk - t_pre, 1e-9), 0.0, 1.0)), 1.0))
            env = env * ramp
            # the decay curve is referenced to the build-up peak
            if t_pk > 0:
                env = np.where(tt >= t_pk, 10 ** (target_curve_db(rt[b], edt[b], tt - t_pk) / 20.0), env)
            tails[s] = np.stack([dsp.bandpass_fft(nl, fs, fc, 1) * env, dsp.bandpass_fft(nr, fs, fc, 1) * env], axis=1)
        e_tail = sum(np.sum(t[dw:] ** 2) for t in tails.values())
        target_after = e_dir * 10 ** (lev[b] / 10.0)
        need = max(target_after - e_base_after, 0.0)
        s = np.sqrt(need / max(e_tail, 1e-30))
        for side in ins:
            irs[side][pre:] += s * tails[side]
    return irs


def render(f: dict, x: np.ndarray, seed: int = 0, fs: int = FS) -> np.ndarray:
    irs = synth_ir(f, seed, fs)
    pre = int(PRE_S * fs)
    n = len(x)
    out = np.zeros((n + len(next(iter(irs.values()))) - pre, 2))
    for k, side in enumerate(f["inputs"]):
        src = x[:, 0] if side == "L" else x[:, 1] if side == "R" else (x[:, 0] + x[:, 1]) / 2.0
        for o in range(2):
            y = fftconvolve(src, irs[side][pre:, o])
            out[: len(y), o] += y
    return out[:n]
