"""`crosscheck`: fits the eight Univerb room renders (read-only) and tabulates them against the earlier measurements in univerb_results.csv.
The table reports differences only; it does not call anything matched."""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from . import report
from .dsp import EDC_BANDS
from .io import FS, new_run, read_wav, save_json
from .room import PRE_S, analyze_sweeps, _side_of

HOME = Path.home()
DRY = HOME / "Claude" / "test-audio" / "univerb_ess_20-20k_8s.wav"
WET_DIR = HOME / "Cakewalk" / "Next" / "Projects" / "New Project(1)" / "Exports"
CSV = HOME / "Claude" / "test-audio" / "univerb_results.csv"
NAMES = {"atrium": "Atrium", "campussteps": "Campus Steps", "classroom": "Classroom", "dormhall": "Dorm Hall", "innovationhall": "Innovation Hall",
         "rhythmchamber": "Rhythm Chamber", "unionstairs": "Union Stairwell", "womenschamber": "Women's Institute"}


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_csv(path):
    rows = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        rows[r["Type"]] = {"rt60": [_num(r.get(k)) for k in ("RT60_125Hz_s", "RT60_250Hz_s", "RT60_500Hz_s", "RT60_1kHz_s", "RT60_2kHz_s", "RT60_4kHz_s", "RT60_8kHz_s")],
                           "first": _num(r["First_reflection_ms"]), "corr": _num(r["Tail_L-R_correlation"]), "e2l": _num(r["Early_to_late_dB"]), "notes": r["Notes"]}
    return rows


def broadband_stats(plot, first_ms):
    """Same definitions the earlier table used: zero-lag L/R correlation of the response from the first reflection (or 5 ms), and early(80 ms)/late energy."""
    irs = plot["irs"]
    pre = int(PRE_S * FS)
    h = sum(irs.values()) if len(irs) == 1 else None
    h = next(iter(irs.values())) if h is None else h
    onset = pre + int((first_ms if first_ms else 5.0) * FS / 1000)
    seg = h[onset:]
    corr = float(np.corrcoef(seg[:, 0], seg[:, 1])[0, 1]) if len(seg) > 256 and seg[:, 0].std() > 0 and seg[:, 1].std() > 0 else None
    e = h[:, 0] ** 2 + h[:, 1] ** 2
    k = pre + int(0.08 * FS)
    e2l = 10 * np.log10(max(e[pre:k].sum(), 1e-20) / max(e[k:].sum(), 1e-20))
    return corr, float(e2l)


def run_cmd(a):
    dry, _ = read_wav(a.dry)
    side = _side_of(dry)
    ref = load_csv(a.csv)
    out = new_run("crosscheck")
    rows, js, invalid = [], {}, []
    for stem, name in NAMES.items():
        f = Path(a.wet_dir) / (stem + ".wav")
        if not f.exists():
            rows.append((name, None))
            continue
        wet, _ = read_wav(f)
        res, plot = analyze_sweeps({side: (dry, wet)})
        if not res["ir_looks_valid"]:
            rows.append((name, None))
            invalid.append("%s (IR decay %.1f dB, latency %.0f ms)" % (stem, res["ir_decay_db"], res["latency_ms"]))
            continue
        corr, e2l = broadband_stats(plot, res["first_reflection_ms"])
        mine = {"rt60": [b["rt60_s"] for b in res["tail_bands"]], "first": res["first_reflection_ms"], "corr": corr, "e2l": e2l,
                "taps_status": res["early_taps"]["status"], "taps_found": res["early_taps"]["count_found"], "iacc": [b.get("iacc") for b in res["tail_bands"]]}
        rows.append((name, mine))
        js[name] = {"earnest": mine, "earlier": ref.get(name)}
    save_json(out / "crosscheck.json", js)

    def cell(m, c, nd=2):
        if m is None and c is None:
            return "-"
        if m is None or c is None:
            return "%s / %s" % ("n/a" if m is None else "%.*f" % (nd, m), "n/a" if c is None else "%.*f" % (nd, c))
        return "%.*f / %.*f (%+.*f)" % (nd, m, nd, c, nd, m - c)
    L = ["# earnest crosscheck: Univerb renders vs univerb_results.csv", "",
         ("**Not usable: these wet files do not look like renders of the dry sweep (%s). Cells for them are blank.**" % "; ".join(invalid)) if invalid else "All wet files passed the IR validity check.", "", "Each cell: earnest / earlier csv (difference). RT60 in s, first reflection in ms, correlation unitless, early-to-late in dB.",
         "Earlier csv came from the bridge's `impulse_response`; earnest is a separate port, so differences include method differences. Nothing here is called matched.", "",
         "Dry: %s (%s sweep input). Wet: %s" % (a.dry, side, a.wet_dir), "", "## RT60 per octave (s)", "| room | " + " | ".join("%d Hz" % h for h in EDC_BANDS) + " |", "|---|" + "---|" * len(EDC_BANDS)]
    for name, m in rows:
        c = ref.get(name)
        L.append("| %s | %s |" % (name, " | ".join(cell(m["rt60"][i] if m else None, c["rt60"][i] if c else None) for i in range(len(EDC_BANDS)))))
    L += ["", "## Other numbers", "| room | first reflection ms | tail L/R corr (broadband, zero lag) | early-to-late dB | earnest taps | earnest IACC by band |", "|---|---|---|---|---|---|"]
    for name, m in rows:
        c = ref.get(name)
        if m is None:
            L.append("| %s | missing or not a render of this sweep | | | | |" % name)
            continue
        L.append("| %s | %s | %s | %s | %s (%d found) | %s |" % (name, cell(m["first"], c["first"] if c else None, 1), cell(m["corr"], c["corr"] if c else None, 2),
                                                                cell(m["e2l"], c["e2l"] if c else None, 1), m["taps_status"], m["taps_found"],
                                                                " ".join("n/a" if v is None else "%.2f" % v for v in m["iacc"])))
    # summary of absolute RT60 differences
    d = [abs(m["rt60"][i] - ref[n]["rt60"][i]) for n, m in rows if m and n in ref for i in range(len(EDC_BANDS)) if m["rt60"][i] is not None and ref[n]["rt60"][i] is not None]
    pct = [abs(m["rt60"][i] - ref[n]["rt60"][i]) / ref[n]["rt60"][i] * 100 for n, m in rows if m and n in ref for i in range(len(EDC_BANDS))
           if m["rt60"][i] is not None and ref[n]["rt60"][i]]
    if d:
        L += ["", "RT60 differences over %d room/band cells where both exist: mean |diff| %.3f s, median %.3f s, max %.3f s; mean |diff| %.1f %%, median %.1f %%." %
              (len(d), np.mean(d), np.median(d), np.max(d), np.mean(pct), np.median(pct))]
    n = report.finish(L, out / "report.md")
    print("crosscheck: %s (report %d lines)" % (out, n))
    return 0
