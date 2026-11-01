"""`room`: sweeps -> impulse-response matrix -> fitted reverb formula, linearity check, and the pan transfer map from panned clicks."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.ndimage import percentile_filter
from scipy.signal import find_peaks

from . import dsp
from .dsp import EDC_BANDS, db, db_pow
from .io import FS, read_wav

PRE_S = 0.04                # IR samples kept before the arrival
TAP_WINDOW_MS = 80.0        # early taps are searched this long after the direct sound
TAP_MIN_MS = 0.5
TAP_MAX = 24
TAP_FLOOR_DB = 40.0       # taps weaker than this below the direct sound are ignored
TAP_MARGIN_DB = 6.0
LIN_LIMIT_DB = 1.0
TAIL_MAX_S = 6.0
MAX_LATENCY_S = 1.0         # a dry->wet offset beyond this is treated as a mismatch
IR_MIN_DECAY_DB = 30.0      # a real IR's first 100 ms must carry at least this much more power than its last 20%; a flat IR means the wet file is probably not a render of the dry sweep
ONSET_FRAC = 10 ** (-15 / 10.0)   # tail onset = smoothed energy first within 15 dB of its peak (the direct sound's deconvolution ring sits ~20 dB below)


# ----------------------------------------------------------------------------- loading

def _is_dual_mono(x: np.ndarray) -> bool:
    return np.abs(x[:, 0] - x[:, 1]).max() <= 1e-6 * max(np.abs(x).max(), 1e-12)


def _side_of(dry: np.ndarray) -> str:
    if _is_dual_mono(dry):
        return "M"
    el, er = np.sum(dry[:, 0] ** 2), np.sum(dry[:, 1] ** 2)
    return "L" if el > er else "R"


def load_sets(dry, wet):
    """Returns (sets, notes). sets maps 'a' (-18 dBFS), 'b' (-30 dBFS), 'rep' (repeat) to {side: (dry, wet)}, plus 'clicks_panned' / 'clicks_mono' pairs."""
    dry, wet = Path(dry), Path(wet)
    notes = []
    sets = {"a": {}, "b": {}, "rep": {}}
    clicks = {}
    if dry.is_file() and wet.is_file():
        d, n1 = read_wav(dry)
        w, n2 = read_wav(wet)
        notes += ["dry: " + s for s in n1] + ["wet: " + s for s in n2]
        sets["a"][_side_of(d)] = (d, w)
        return sets, clicks, notes
    for key, suffix in (("a", ""), ("b", "_m30")):
        for side in ("L", "R"):
            f = "sweep_%s%s.wav" % (side, suffix)
            if (dry / f).exists() and (wet / f).exists():
                d, n1 = read_wav(dry / f)
                w, n2 = read_wav(wet / f)
                sets[key][side] = (d, w)
                notes += ["%s dry: %s" % (f, s) for s in n1] + ["%s wet: %s" % (f, s) for s in n2]
    for side in ("L", "R"):
        f = "sweep_%s_rep.wav" % side
        if (wet / f).exists() and side in sets["a"]:
            w, n2 = read_wav(wet / f)
            sets["rep"][side] = (sets["a"][side][0], w)
    for name in ("clicks_panned", "clicks_mono"):
        f = name + ".wav"
        if (dry / f).exists() and (wet / f).exists():
            clicks[name] = (read_wav(dry / f)[0], read_wav(wet / f)[0])
    return sets, clicks, notes


# ----------------------------------------------------------------------------- impulse responses

def estimate_irs(sweeps: dict, fs: int = FS):
    """sweeps: {side: (dry, wet)}. Returns (irs {side: (n, 2)}, latency_samples). IR index PRE is the arrival of the strongest path."""
    raw = {}
    neg = 0
    for side, (d, w) in sweeps.items():
        ch = 0 if side in ("L", "M") else 1
        x = d[:, ch]
        cols = []
        for c in range(2):
            hh, neg = dsp.deconvolve(x, w[:, c], len(w), fs=fs)
            cols.append(hh)
        raw[side] = np.stack(cols, axis=1)
    n = min(len(h) for h in raw.values())
    comb = np.sqrt(sum(np.sum(h[:n] ** 2, axis=1) for h in raw.values()))
    k0 = int(np.argmax(comb))
    pre = int(PRE_S * fs)
    irs = {}
    for side, h in raw.items():
        seg = h[max(k0 - pre, 0): n]
        if k0 < pre:
            seg = np.pad(seg, ((pre - k0, 0), (0, 0)))
        irs[side] = seg
    return irs, k0 - neg


def _env(h: np.ndarray) -> np.ndarray:
    return np.sqrt(h[:, 0] ** 2 + h[:, 1] ** 2)


def detect_taps(irs: dict, fs: int = FS):
    pre = int(PRE_S * fs)
    ref = max(float(_env(h)[pre - 5: pre + 6].max()) for h in irs.values())
    found = []
    for side, h in irs.items():
        env = _env(h)
        a = pre + int(TAP_MIN_MS * fs / 1000)
        b = min(pre + int(TAP_WINDOW_MS * fs / 1000), len(env))
        seg = env[a:b]
        if len(seg) < 100:
            continue
        floor = 2.08 * percentile_filter(env[pre:b + int(0.01 * fs)], 50, size=int(0.02 * fs) | 1, mode="nearest")[a - pre:b - pre]
        thr = floor * 10 ** (TAP_MARGIN_DB / 20.0)
        pk, _ = find_peaks(seg, distance=max(int(0.0004 * fs), 1))
        g1, g2 = int(0.00045 * fs), int(0.0015 * fs)
        for k in pk:
            if seg[k] >= thr[k]:
                i = a + k
                if db(seg[k] / ref) < -TAP_FLOOR_DB:
                    continue
                nb = np.concatenate([env[max(i - g2, 0): i - g1], env[i + g1 + 1: i + g2 + 1]])
                if len(nb) and seg[k] < nb.max() * 10 ** (TAP_MARGIN_DB / 20.0):
                    continue          # not isolated: a side lobe of a bigger peak, or part of a dense tail
                off = dsp.parabolic(env, i)
                found.append({"delay_ms": round((i + off - pre) / fs * 1000.0, 3), "gain_db": round(db(seg[k] / ref), 2),
                              "pan": round(dsp.pan_from_amps(h[i, 0], h[i, 1]), 3), "source": side, "amp": float(seg[k])})
    found.sort(key=lambda t: -t["amp"])
    n_found = len(found)
    taps = sorted(found[:TAP_MAX], key=lambda t: t["delay_ms"])
    for t in taps:
        t.pop("amp")
    return {"status": "resolved" if n_found >= 3 else "unresolved", "count_found": n_found, "taps": taps if n_found >= 3 else [],
            "rule": "peaks >= %.0f dB above the local floor (2.08 x the median of the echogram in a +-10 ms window, which equals its 95th percentile for noise-like tails but is not raised by neighbouring taps), also %.0f dB above everything within 0.45-1.5 ms either side (isolated), no weaker than %.0f dB below the direct sound, %.1f-%.0f ms after the direct sound, at most %d kept"
                    % (TAP_MARGIN_DB, TAP_MARGIN_DB, TAP_FLOOR_DB, TAP_MIN_MS, TAP_WINDOW_MS, TAP_MAX)}


def direct_matrix(irs: dict, fs: int = FS):
    """Signed direct-path gain per output from each input: sqrt of the mean spectral power of a +-0.25 ms window around the arrival over 200 Hz-8 kHz
    (so the sweep's band limit does not lower it), with the sign of the peak sample."""
    pre = int(PRE_S * fs)
    w = max(int(0.00025 * fs), 2)
    f = np.fft.rfftfreq(4096, 1.0 / fs)
    sel = (f >= 200) & (f <= 8000)
    out = {}
    for side, h in irs.items():
        col = []
        for c in range(2):
            seg = h[pre - w: pre + w + 1, c]
            sgn = 1.0 if seg[int(np.argmax(np.abs(seg)))] >= 0 else -1.0
            mag = float(np.sqrt(np.mean(np.abs(np.fft.rfft(seg, 4096))[sel] ** 2)))
            col.append(sgn * mag)
        out[side] = col
    return out


def band_irs(irs: dict, fc: float, fs: int = FS):
    return {side: np.stack([dsp.bandpass_fft(h[:, c], fs, fc, 1) for c in range(2)], axis=1) for side, h in irs.items()}


def analyze_band(irs: dict, fc: float, fs: int = FS, tap_ms=()):
    pre = int(PRE_S * fs)
    dw = int(max(0.003, 2.7 / fc) * fs)     # the band filter's own ringing after the direct sound lasts about this long
    hb = band_irs(irs, fc, fs)
    n = min(len(h) for h in hb.values())
    e = sum(np.sum(h[:n] ** 2, axis=1) for h in hb.values())
    e_dir = float(e[pre - dw: pre + dw].sum())
    e_after = float(e[pre + dw:].sum())
    # discrete early taps would make the energy decay curve a staircase, so they are masked (+-dw) for the decay, onset and correlation measurements
    em = e.copy()
    for tm in tap_ms:
        c = pre + int(tm * fs / 1000.0)
        em[max(c - dw, pre + dw): c + dw] = 0.0
    dec = dsp.decay(em[pre + dw:], fs)      # decay is measured from the end of the direct-sound window
    res = {"hz": fc, "level_db": round(db_pow(e_after / max(e_dir, dsp.EPS)), 2)}
    if dec is None:
        res.update({"rt60_s": None, "t20_s": None, "t30_s": None, "edt_s": None})
        return res, None, hb
    rt = dec["t30"] if dec["t30"] else dec["t20"]
    res.update({"rt60_s": _r(rt, 3), "t20_s": _r(dec["t20"], 3), "t30_s": _r(dec["t30"], 3), "edt_s": _r(dec["edt"], 3),
                "decay_range_db": round(dec["dyn_range_db"], 1)})
    env = dsp.smooth(em[pre + dw:], 0.002 * fs)
    m = min(int(0.4 * fs), len(env))
    pk = int(np.argmax(env[:m])) if m > 8 else 0
    on = int(np.argmax(env[: pk + 1] >= env[pk] * ONSET_FRAC)) if m > 8 else 0
    res["pre_delay_ms"] = round((dw + on) / fs * 1000.0, 2)
    res["buildup_ms"] = round((pk - on) / fs * 1000.0, 2)
    # tail correlation between the two output channels over the measurable decay
    cut = pre + int(min(TAIL_MAX_S, (dec["t"][-1] if len(dec["t"]) else 1.0)) * fs)
    ia = pre + dw + on
    vals = []
    for side, h in hb.items():
        seg = h[ia:cut]
        v = dsp.iacc(seg[:, 0], seg[:, 1], fs)
        if v is not None:
            vals.append(v)
    res["iacc"] = round(float(np.mean(vals)), 3) if vals else None
    res["modulation"] = _modulation(e[pre:], dec, fs)
    return res, dec, hb


def _r(v, n):
    return None if v is None else round(float(v), n)


def _modulation(e: np.ndarray, dec: dict, fs: int):
    """Slow wobble of the decay envelope around its straight-line fit between -5 and -30 dB. Reported only when one frequency clearly stands out."""
    ed = dec["edc_db"]
    idx = np.where((ed <= -5) & (ed >= -30))[0]
    if len(idx) < int(0.3 * fs):
        return None
    seg = dsp.smooth(e[idx[0]: idx[-1] + 1], 0.01 * fs)
    ldb = 10 * np.log10(np.maximum(seg, dsp.EPS))[:: int(fs / 100)]
    if len(ldb) < 40:
        return None
    t = np.arange(len(ldb))
    r = ldb - np.polyval(np.polyfit(t, ldb, 1), t)
    sp = np.abs(np.fft.rfft(r * np.hanning(len(r)), 4096))
    fr = np.fft.rfftfreq(4096, 0.01)
    m = (fr >= 0.5) & (fr <= 8.0)
    ratio = sp[m].max() / max(np.median(sp[m]), dsp.EPS)
    pp = float(np.percentile(r, 97.5) - np.percentile(r, 2.5))
    if ratio > 12 and pp > 1.5:
        return {"rate_hz": round(float(fr[m][int(np.argmax(sp[m]))]), 2), "depth_db_pp": round(pp, 2)}
    return None


def room_metrics(irs: dict, fs: int = FS):
    pre = int(PRE_S * fs)
    n = min(len(h) for h in irs.values())
    e = sum(np.sum(h[:n] ** 2, axis=1) for h in irs.values())
    a, b = pre - int(0.001 * fs), pre + int(0.0025 * fs)
    out = {"drr_db": round(db_pow(e[a:b].sum() / max(e[b:].sum(), dsp.EPS)), 2)}
    for ms in (50, 80):
        k = pre - int(0.001 * fs) + int(ms * fs / 1000)
        out["c%d_db" % ms] = round(db_pow(e[a:k].sum() / max(e[k:].sum(), dsp.EPS)), 2)
    return out


def echogram(irs: dict, fs: int = FS, ms: float = 100.0):
    pre = int(PRE_S * fs)
    n = int(ms * fs / 1000)
    res = {}
    for c, name in enumerate(("L", "R")):
        e = sum(h[pre:pre + n, c] ** 2 for h in irs.values())
        res[name] = 10 * np.log10(np.maximum(dsp.smooth(e, 0.0005 * fs), 1e-14))
    return res


# ----------------------------------------------------------------------------- linearity

def _band_energy_db(irs, fs):
    out = []
    for fc in EDC_BANDS:
        hb = band_irs(irs, fc, fs)
        out.append(db_pow(sum(np.sum(h ** 2) for h in hb.values())))
    return np.array(out)


def _edc_curves(irs, fs):
    pre = int(PRE_S * fs)
    curves = []
    for fc in EDC_BANDS:
        hb = band_irs(irs, fc, fs)
        n = min(len(h) for h in hb.values())
        e = sum(np.sum(h[:n] ** 2, axis=1) for h in hb.values())
        d = dsp.decay(e[pre:], fs)
        curves.append(None if d is None else d["edc_db"])
    return curves


def linearity(sets: dict, fs: int = FS):
    """Compares IRs from the -18 dBFS sweeps with the -30 dBFS sweeps and with a repeat at -18. Deviation > 1 dB in any band flags the IR."""
    ref = sets["a"]
    if not ref:
        return {"run": False, "reason": "no -18 dBFS sweeps"}
    irs_a, _ = estimate_irs(ref, fs)
    ea, ca = _band_energy_db(irs_a, fs), _edc_curves(irs_a, fs)
    out = {"run": True, "limit_db": LIN_LIMIT_DB, "comparisons": {}}
    flag = False
    for key, label in (("b", "-30 dBFS vs -18 dBFS"), ("rep", "repeat vs first -18 dBFS")):
        if not sets[key]:
            out["comparisons"][label] = {"run": False, "reason": "files not present"}
            continue
        irs_b, _ = estimate_irs(sets[key], fs)
        eb, cb = _band_energy_db(irs_b, fs), _edc_curves(irs_b, fs)
        mag, edc = [], []
        for i in range(len(EDC_BANDS)):
            mag.append(round(float(abs(ea[i] - eb[i])), 2))
            if ca[i] is None or cb[i] is None:
                edc.append(None)
                continue
            m = min(len(ca[i]), len(cb[i]))
            sel = np.where(np.minimum(ca[i][:m], cb[i][:m]) >= -30)[0]
            edc.append(round(float(np.abs(ca[i][:m][sel] - cb[i][:m][sel]).max()), 2) if len(sel) else None)
        worst = max([v for v in mag + edc if v is not None] or [0])
        flag = flag or worst > LIN_LIMIT_DB
        out["comparisons"][label] = {"run": True, "bands_hz": EDC_BANDS, "magnitude_dev_db": mag, "edc_dev_db": edc, "worst_db": worst}
    out["nonlinear_or_time_variant"] = bool(flag)
    return out


# ----------------------------------------------------------------------------- pan transfer map

def _click_peaks(x: np.ndarray, n: int):
    env = np.abs(x).max(axis=1)
    pk, _ = find_peaks(env, height=env.max() * 0.2, distance=int(1.0 * FS))
    return list(pk[:n])


def pan_map(dry: np.ndarray, wet: np.ndarray, latency: int, fs: int = FS):
    rows = []
    for k in _click_peaks(dry, 5):
        p_in = dsp.pan_from_amps(dry[k, 0], dry[k, 1])
        a = k + latency - int(0.003 * fs)
        b = k + latency + int(0.004 * fs)
        if a < 0 or b > len(wet):
            continue
        k0 = a + int(np.argmax(np.abs(wet[a:b]).max(axis=1)))
        ew = wet[k0 - int(0.0005 * fs): k0 + int(0.005 * fs)]
        tw = wet[k0 + int(0.08 * fs): k0 + int(0.5 * fs)]
        e_el, e_er = float(np.sum(ew[:, 0] ** 2)), float(np.sum(ew[:, 1] ** 2))
        t_el, t_er = float(np.sum(tw[:, 0] ** 2)), float(np.sum(tw[:, 1] ** 2))
        m, s = (tw[:, 0] + tw[:, 1]) / 2, (tw[:, 0] - tw[:, 1]) / 2
        c = float(np.corrcoef(tw[:, 0], tw[:, 1])[0, 1]) if tw[:, 0].std() > 0 and tw[:, 1].std() > 0 else None
        rows.append({"pan_in": round(p_in, 3), "pan_out_direct": round(dsp.pan_from_amps(np.sqrt(e_el), np.sqrt(e_er)), 3),
                     "pan_out_tail": round(dsp.pan_from_amps(np.sqrt(t_el), np.sqrt(t_er)), 3), "tail_corr": _r(c, 3),
                     "tail_side_over_mid_db": round(db_pow(np.mean(s ** 2) / max(np.mean(m ** 2), dsp.EPS)), 2),
                     "direct_level_db": round(db_pow(e_el + e_er), 2)})
    return rows


# ----------------------------------------------------------------------------- driver

def analyze_sweeps(sweeps: dict, fs: int = FS):
    irs, latency = estimate_irs(sweeps, fs)
    bands, decs = [], []
    taps = detect_taps(irs, fs)
    tap_ms = [t["delay_ms"] for t in taps["taps"]]
    for fc in EDC_BANDS:
        r, d, _ = analyze_band(irs, fc, fs, tap_ms)
        bands.append(r)
        decs.append(d)
    M = direct_matrix(irs, fs)
    pre = int(PRE_S * fs)
    comb = np.sqrt(sum(np.sum(h[:, :] ** 2, axis=1) for h in irs.values()))
    first = taps["taps"][0]["delay_ms"] if taps["taps"] else None
    res = {"inputs": sorted(irs.keys()), "latency_ms": round(latency / fs * 1000.0, 3), "direct_matrix": M, "early_taps": taps,
           "tail_bands": bands, "room": room_metrics(irs, fs), "first_reflection_ms": first,
           "ir_seconds": round(len(next(iter(irs.values()))) / fs, 2)}
    n = min(len(h) for h in irs.values())
    e = sum(np.sum(h[:n] ** 2, axis=1) for h in irs.values())
    res["ir_decay_db"] = round(db_pow(e[pre:pre + int(0.1 * fs)].mean() / max(e[int(0.8 * n):].mean(), dsp.EPS)), 1)
    res["ir_looks_valid"] = bool(res["ir_decay_db"] >= IR_MIN_DECAY_DB and abs(latency) <= MAX_LATENCY_S * fs)
    # tail-wide stats the Univerb table also uses
    return res, {"irs": irs, "decs": decs, "latency": latency, "echogram": echogram(irs, fs)}


def run_room(dry, wet, fs: int = FS):
    sets, clicks, notes = load_sets(dry, wet)
    if not sets["a"]:
        raise SystemExit("room: no sweep pairs found (need sweep_L.wav / sweep_R.wav in both folders, or two WAV files)")
    res, plot = analyze_sweeps(sets["a"], fs)
    res["notes"] = notes
    res["input_mode"] = "mono_sum" if "M" in res["inputs"] else ("stereo" if len(res["inputs"]) == 2 else "one_channel_only:" + res["inputs"][0])
    res["linearity"] = linearity(sets, fs)
    res["nonlinear_or_time_variant"] = res["linearity"].get("nonlinear_or_time_variant") if res["linearity"].get("run") else None
    res["pan_map"] = {}
    for name, (d, w) in clicks.items():
        res["pan_map"][name] = pan_map(d, w, plot["latency"], fs)
    return res, plot
