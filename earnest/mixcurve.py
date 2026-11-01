"""`mixcurve`: how the room metrics move with the effect's Mix setting, one curve per room. Steps are (label, room-result) pairs, in the order given."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .dsp import EDC_BANDS
from .report import finish

MID = [250, 500, 1000, 2000, 4000]       # bands averaged for single-number metrics
FLAG = 0.10                              # a metric that moves by more than this fraction of its mean is flagged


def _mean(res, key):
    v = [b[key] for b in res["tail_bands"] if b["hz"] in MID and b.get(key) is not None]
    return float(np.mean(v)) if v else None


def _slope(rows, key):
    if not rows or len(rows) < 3:
        return None
    return float(np.polyfit([r["pan_in"] for r in rows], [r[key] for r in rows], 1)[0])


NO_TAIL_DB = -40.0       # a step whose tail sits this far below its direct sound (e.g. the Mix 0 pass) has no reverb to describe


def metrics(res: dict) -> dict:
    dm = res["direct_matrix"]
    ins = res["inputs"]
    L = ins[0]
    R = ins[1] if len(ins) > 1 else None
    pm = (res.get("pan_map") or {}).get("clicks_panned")
    ranges = [b["decay_range_db"] for b in res["tail_bands"] if b.get("decay_range_db") is not None]
    out = _metrics(res, dm, L, R, pm, ranges)
    lv = out["tail_level_db"]
    out["no_tail"] = bool(lv is not None and lv < NO_TAIL_DB)
    if out["no_tail"]:
        for k in ("rt60_s", "edt_s", "iacc"):
            out[k] = None
        for k in ("rt60_by_band", "edt_by_band", "iacc_by_band"):
            out[k] = [None] * len(out[k])
    return out


def _metrics(res, dm, L, R, pm, ranges):
    return {"M_LL": dm[L][0], "M_LR": dm[L][1], "M_RL": dm[R][0] if R else None, "M_RR": dm[R][1] if R else None,
            "tail_level_db": _mean(res, "level_db"), "rt60_s": _mean(res, "rt60_s"), "edt_s": _mean(res, "edt_s"), "iacc": _mean(res, "iacc"),
            "drr_db": res["room"]["drr_db"], "c50_db": res["room"]["c50_db"], "c80_db": res["room"]["c80_db"],
            "pan_slope_direct": _slope(pm, "pan_out_direct"), "pan_slope_tail": _slope(pm, "pan_out_tail"),
            "rt60_by_band": [b["rt60_s"] for b in res["tail_bands"]], "edt_by_band": [b["edt_s"] for b in res["tail_bands"]],
            "iacc_by_band": [b.get("iacc") for b in res["tail_bands"]], "level_by_band": [b["level_db"] for b in res["tail_bands"]],
            "taps": res["early_taps"]["status"], "nonlinear": res.get("nonlinear_or_time_variant"),
            "min_decay_range_db": min(ranges) if ranges else None}


def curves(steps) -> dict:
    labels = [s[0] for s in steps]
    ms = [metrics(s[1]) for s in steps]
    keys = ["M_LL", "M_LR", "M_RL", "M_RR", "tail_level_db", "rt60_s", "edt_s", "iacc", "drr_db", "c50_db", "c80_db", "pan_slope_direct", "pan_slope_tail"]
    flags = []
    for k in keys:
        v = [m[k] for m in ms if m[k] is not None]
        if len(v) < 2:
            continue
        span = max(v) - min(v)
        base = max(abs(np.mean(v)), 1e-6)
        if k.endswith("_db"):            # dB values: flag by absolute movement of 1 dB or more
            if span >= 1.0:
                flags.append({"metric": k, "span": round(span, 2), "rule": "moves by >= 1 dB"})
        elif span / base > FLAG:
            flags.append({"metric": k, "span": round(span, 3), "rule": "moves by > %d%% of its mean" % int(FLAG * 100)})
    return {"labels": labels, "metrics": ms, "flags": flags}


def _f(v, nd=3):
    return "n/a" if v is None else "%.*f" % (nd, v)


def report_lines(c: dict, title: str):
    L = ["# earnest mixcurve: %s" % title, "", "Metrics against the Mix label. Single numbers average the 250 Hz-4 kHz octave bands. Mix is measured separately for every room; nothing is combined across rooms.", ""]
    lab = c["labels"]
    L += ["| Mix | M L>L | M L>R | M R>L | M R>R | tail dB re direct | RT60 s | EDT s | IACC | DRR dB | C50 dB | C80 dB | pan slope direct | pan slope tail |", "|" + "---|" * 14]
    for lb, m in zip(lab, c["metrics"]):
        L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            lb, _f(m["M_LL"]), _f(m["M_LR"]), _f(m["M_RL"]), _f(m["M_RR"]), _f(m["tail_level_db"], 2), _f(m["rt60_s"]), _f(m["edt_s"]), _f(m["iacc"]),
            _f(m["drr_db"], 2), _f(m["c50_db"], 2), _f(m["c80_db"], 2), _f(m["pan_slope_direct"]), _f(m["pan_slope_tail"])))
    for key, name, nd in (("rt60_by_band", "RT60 s by octave band", 3), ("edt_by_band", "EDT s by octave band", 3), ("iacc_by_band", "IACC by octave band", 3),
                          ("level_by_band", "tail level dB re direct by band", 2)):
        L += ["", "### %s" % name, "| Mix | " + " | ".join("%d Hz" % h for h in EDC_BANDS) + " |", "|---|" + "---|" * len(EDC_BANDS)]
        for lb, m in zip(lab, c["metrics"]):
            L.append("| %s | %s |" % (lb, " | ".join(_f(v, nd) for v in m[key])))
    L += ["", "### Flags (metrics that move across the Mix steps)"]
    L += ["- %s: %s (%s)" % (f["metric"], f["span"], f["rule"]) for f in c["flags"]] or ["- none"]
    L += ["", "Early taps per step: " + ", ".join("%s=%s" % (lb, m["taps"]) for lb, m in zip(lab, c["metrics"])),
          "Nonlinear/time-variant flag per step: " + ", ".join("%s=%s" % (lb, m["nonlinear"]) for lb, m in zip(lab, c["metrics"]))]
    return L


def png(path, c, title):
    lab = [str(x) for x in c["labels"]]
    x = np.arange(len(lab))
    fig, ax = plt.subplots(3, 2, figsize=(16, 12), dpi=100)
    ms = c["metrics"]

    def line(a, keys, ylabel, ttl):
        for k in keys:
            a.plot(x, [np.nan if m[k] is None else m[k] for m in ms], "o-", label=k)
        a.set_xticks(x)
        a.set_xticklabels(lab)
        a.set_xlabel("Mix")
        a.set_ylabel(ylabel)
        a.set_title(ttl)
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    line(ax[0, 0], ["M_LL", "M_LR", "M_RL", "M_RR"], "gain", "Direct matrix M")
    line(ax[0, 1], ["tail_level_db", "drr_db"], "dB", "Tail level re direct, and DRR")
    line(ax[1, 0], ["rt60_s", "edt_s"], "s", "RT60 and EDT (mean 250 Hz-4 kHz)")
    line(ax[1, 1], ["iacc"], "IACC", "Tail IACC (mean 250 Hz-4 kHz)")
    line(ax[2, 0], ["c50_db", "c80_db"], "dB", "C50 and C80")
    line(ax[2, 1], ["pan_slope_direct", "pan_slope_tail"], "slope", "Pan transfer slope (output pan per input pan)")
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def load_run(folder):
    return json.loads((Path(folder) / "room.json").read_text(encoding="utf-8"))


def write(steps, outdir, title):
    c = curves(steps)
    n = finish(report_lines(c, title), Path(outdir) / "report.md")
    png(Path(outdir) / "mixcurve.png", c, title)
    return c, n
