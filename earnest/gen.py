"""`gen`: writes test-signal WAV files (48 kHz, 32-bit float, -18 dBFS peak). Offline only; the files are bounced through a DAW and never auditioned."""
from __future__ import annotations

import numpy as np

from . import dsp
from .io import FS, write_wav

PEAK_DB = -18.0
SWEEP = {"f1": 20.0, "f2": 16000.0, "seconds": 8.0, "lead_s": 0.5, "tail_s": 4.0, "fade_s": 0.010}
PANS = [-1.0, -0.5, 0.0, 0.5, 1.0]
CLICK_T0, CLICK_GAP, CLICK_TAIL = 0.5, 2.0, 4.0
BURST_S = 0.5
FILES = ["sweep_L.wav", "sweep_R.wav", "sweep_L_m30.wav", "sweep_R_m30.wav", "clicks_panned.wav", "clicks_mono.wav", "noise_bursts_panned.wav"]


def amp(db_peak: float) -> float:
    return 10.0 ** (db_peak / 20.0)


def sweep_mono(fs=FS, db_peak=PEAK_DB, tail_s=None):
    p = SWEEP
    tail_s = p["tail_s"] if tail_s is None else tail_s
    s = dsp.sweep_signal(fs, p["f1"], p["f2"], p["seconds"])
    nf = int(p["fade_s"] * fs)
    s[:nf] *= np.linspace(0, 1, nf)
    s[-nf:] *= np.linspace(1, 0, nf)
    out = np.zeros(int(round((p["lead_s"] + p["seconds"] + tail_s) * fs)))
    k = int(p["lead_s"] * fs)
    out[k:k + len(s)] = s * amp(db_peak)
    return out


def sweep_stereo(side: str, db_peak=PEAK_DB, fs=FS, tail_s=None):
    m = sweep_mono(fs, db_peak, tail_s)
    x = np.zeros((len(m), 2))
    x[:, 0 if side == "L" else 1] = m
    return x


def click_times(n: int, fs=FS):
    return [int((CLICK_T0 + i * CLICK_GAP) * fs) for i in range(n)]


def _click_len(fs, tail_s):
    return int(round((CLICK_T0 + CLICK_GAP * len(PANS) + (CLICK_TAIL if tail_s is None else tail_s)) * fs))


def clicks_panned(fs=FS, tail_s=None):
    a = amp(PEAK_DB)
    x = np.zeros((_click_len(fs, tail_s), 2))
    for p, k in zip(PANS, click_times(len(PANS), fs)):
        gl, gr = dsp.pan_gains(p)
        x[k, 0], x[k, 1] = a * gl, a * gr
    return x


def clicks_mono(fs=FS, tail_s=None):
    a = amp(PEAK_DB)
    x = np.zeros((_click_len(fs, tail_s), 2))
    for k in click_times(len(PANS), fs):
        x[k, :] = a
    return x


def pink(n: int, rng) -> np.ndarray:
    w = rng.standard_normal(n)
    W = np.fft.rfft(w)
    f = np.fft.rfftfreq(n, 1.0)
    f[0] = f[1]
    p = np.fft.irfft(W / np.sqrt(f), n)
    return p / np.abs(p).max()


def noise_bursts(fs=FS, tail_s=None):
    rng = np.random.default_rng(1234)      # fixed seed: dry and wet runs use identical bursts
    a = amp(PEAK_DB)
    x = np.zeros((_click_len(fs, tail_s), 2))
    nb = int(BURST_S * fs)
    fade = int(0.005 * fs)
    for p, k in zip(PANS, click_times(len(PANS), fs)):
        b = pink(nb, rng)
        b[:fade] *= np.linspace(0, 1, fade)
        b[-fade:] *= np.linspace(1, 0, fade)
        gl, gr = dsp.pan_gains(p)
        x[k:k + nb, 0], x[k:k + nb, 1] = a * gl * b, a * gr * b
    return x


def make_all(fs=FS):
    return {
        "sweep_L.wav": sweep_stereo("L"), "sweep_R.wav": sweep_stereo("R"),
        "sweep_L_m30.wav": sweep_stereo("L", -30.0), "sweep_R_m30.wav": sweep_stereo("R", -30.0),
        "clicks_panned.wav": clicks_panned(fs), "clicks_mono.wav": clicks_mono(fs), "noise_bursts_panned.wav": noise_bursts(fs),
    }


def run(outdir):
    sigs = make_all()
    info = {}
    for name, x in sigs.items():
        write_wav(outdir / name, x)
        info[name] = {"seconds": round(len(x) / FS, 3), "peak_dbfs": round(dsp.db(np.abs(x).max()), 2)}
    manifest = {"fs": FS, "format": "WAV 32-bit float", "peak_dbfs": PEAK_DB, "sweep": SWEEP, "pans": PANS, "click_t0_s": CLICK_T0,
                "click_gap_s": CLICK_GAP, "pan_law": "constant power: gL=cos((p+1)pi/4), gR=sin((p+1)pi/4)", "files": info,
                "repeat_note": "For the linearity repeat, bounce sweep_L.wav / sweep_R.wav a second time and save the wet copies as sweep_L_rep.wav / sweep_R_rep.wav."}
    return sigs, manifest
