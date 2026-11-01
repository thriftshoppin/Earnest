"""`resynth`: renders a formula against a dry sweep and compares it, statistically, with either the real wet render or the formula's own numbers.
Averages over several noise seeds. No waveform comparison."""
from __future__ import annotations

import numpy as np

from . import dsp, formula
from .dsp import EDC_BANDS
from .io import FS, read_wav
from .room import _side_of, analyze_sweeps


def _ref_edc(rt, edt, t):
    return formula.target_curve_db(rt, edt, t)


def _edc_err(curve, rt, edt):
    if curve is None:
        return None
    t = np.arange(len(curve)) / FS
    ref = _ref_edc(rt, edt, t)
    sel = np.where(ref >= -30)[0]
    sel = sel[sel < len(curve)]
    if len(sel) < 8:
        return None
    return float(np.mean(np.abs(curve[sel] - ref[sel])))


def _edc_err_vs_curve(curve, ref_curve):
    if curve is None or ref_curve is None:
        return None
    m = min(len(curve), len(ref_curve))
    sel = np.where(ref_curve[:m] >= -30)[0]
    return float(np.mean(np.abs(curve[:m][sel] - ref_curve[:m][sel]))) if len(sel) >= 8 else None


def _out_band_db(y):
    return [dsp.db_pow(sum(np.sum(dsp.bandpass_fft(y[:, c], FS, fc, 1) ** 2) for c in range(2))) for fc in EDC_BANDS]


def _stat(rows):
    arr = np.array([[np.nan if v is None else v for v in r] for r in rows], dtype=float)
    with np.errstate(all="ignore"):
        return {"mean": [None if np.isnan(v) else round(float(v), 3) for v in np.nanmean(arr, axis=0)],
                "sd": [None if np.isnan(v) else round(float(v), 3) for v in np.nanstd(arr, axis=0)]}


def run(f: dict, dry_path, compare=None, seeds: int = 5):
    dry, notes = read_wav(dry_path)
    side = _side_of(dry)
    ins = f["inputs"]
    if side not in ins and not (side == "M" and ins == ["M"]):
        notes.append("dry sweep is on %s but the formula inputs are %s: using the first formula input" % (side, ins))
    ref = None
    ref_out = None
    if compare:
        wet, n2 = read_wav(compare)
        notes += ["wet: " + s for s in n2]
        ref, refplot = analyze_sweeps({side: (dry, wet)})
        ref_decs = refplot["decs"]
        ref_out = _out_band_db(wet)
    tl = f["tail"]
    rows = {k: [] for k in ("edc_err_db", "rt60_err_pct", "iacc_diff", "spectral_err_db")}
    one = None
    for sd in range(seeds):
        y = formula.render(f, dry, seed=sd)
        res, plot = analyze_sweeps({side: (dry, y)})
        if one is None:
            one = res
        edc, rt, ia, sp = [], [], [], []
        yb = _out_band_db(y)
        for b, fc in enumerate(EDC_BANDS):
            tb = res["tail_bands"][b]
            dec = plot["decs"][b]
            if ref is not None:
                rb = ref["tail_bands"][b]
                edc.append(_edc_err_vs_curve(None if dec is None else dec["edc_db"], None if ref_decs[b] is None else ref_decs[b]["edc_db"]))
                rr, ri = rb["rt60_s"], rb.get("iacc")
                sp.append(round(yb[b] - ref_out[b], 3))
            else:
                rr, ri = tl["rt60_s"][b], tl["iacc"][b]
                edc.append(_edc_err(None if dec is None else dec["edc_db"], tl["rt60_s"][b] or 1.0, tl["edt_s"][b]) if tl["rt60_s"][b] else None)
                sp.append(None if tl["level_db"][b] is None else round(tb["level_db"] - tl["level_db"][b], 3))
            rt.append(None if (rr is None or tb["rt60_s"] is None) else round((tb["rt60_s"] - rr) / rr * 100.0, 3))
            ia.append(None if (ri is None or tb.get("iacc") is None) else round(tb["iacc"] - ri, 3))
        rows["edc_err_db"].append(edc)
        rows["rt60_err_pct"].append(rt)
        rows["iacc_diff"].append(ia)
        rows["spectral_err_db"].append(sp)
    stats = {k: _stat(v) for k, v in rows.items()}
    stats.update({"bands_hz": EDC_BANDS, "seeds": seeds,
                  "reference": "real wet render: %s" % compare if compare else "the formula's own numbers (self-consistency; not a comparison with real audio)",
                  "notes": notes,
                  "spectral_error_definition": ("10log of band output energy of the synthesised render minus that of the wet file, whole file" if compare else
                                                 "reverb-over-direct level of the synthesised IR minus the formula's level_db")})
    return stats
