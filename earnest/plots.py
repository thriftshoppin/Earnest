"""PNG sheets, 1600x1200 (16x12 in at 100 dpi). Every number drawn here is also written in report.md."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from . import dsp
from .dsp import EDC_BANDS
from .io import FS

FIG = (16, 12)
DPI = 100


def _spec_db(P, f, fmax=20000.0):
    m = f <= fmax
    return 10 * np.log10(np.maximum(P[m], 1e-14)), m


def listen_png(path, x, res, pg, title):
    fig, ax = plt.subplots(3, 2, figsize=FIG, dpi=DPI)
    t, f = pg["t"], pg["f"]
    for k, (name, P) in enumerate((("Left", pg["PL"]), ("Right", pg["PR"]))):
        s, m = _spec_db(P, f)
        a = ax[0, k]
        im = a.pcolormesh(t, f[m], s, vmin=s.max() - 90, vmax=s.max(), shading="auto", cmap="magma")
        a.set_yscale("symlog", linthresh=200)
        a.set_ylim(30, f[m].max())
        a.set_title("%s spectrogram (dB)" % name)
        a.set_xlabel("time (s)")
        a.set_ylabel("Hz")
        fig.colorbar(im, ax=a)
    a = ax[1, 0]
    fe = pg["freq_edges"]
    fp = pg["freq_pan"]
    z = 10 * np.log10(np.maximum(fp / max(fp.max(), 1e-20), 1e-9))
    im = a.pcolormesh(np.linspace(-1, 1, fp.shape[1] + 1), fe, z, vmin=-60, vmax=0, shading="auto", cmap="viridis")
    a.set_yscale("log")
    a.set_title("Panogram: frequency x pan index (dB, -1 left .. +1 right)")
    a.set_xlabel("panning index")
    a.set_ylabel("Hz")
    fig.colorbar(im, ax=a)
    a = ax[1, 1]
    tp = pg["time_pan"]
    z = 10 * np.log10(np.maximum(tp / max(tp.max(), 1e-20), 1e-9))
    im = a.pcolormesh(np.linspace(-1, 1, tp.shape[1] + 1), np.linspace(0, res["seconds"], tp.shape[0] + 1), z, vmin=-60, vmax=0, shading="auto", cmap="viridis")
    a.set_title("Panogram: time x pan index (dB)")
    a.set_xlabel("panning index")
    a.set_ylabel("time (s)")
    fig.colorbar(im, ax=a)
    a = ax[2, 0]
    ws = res["width_series"]
    tt = [w["t"] for w in ws]
    a.plot(tt, [w["width"] for w in ws], label="width (side/(mid+side) energy)")
    a.plot(tt, [w["corr"] if w["corr"] is not None else np.nan for w in ws], label="L/R correlation")
    for r in res["transients"]:
        a.axvline(r["t"], color="k", alpha=0.15)
    a.set_ylim(-1.05, 1.05)
    a.set_title("Width and correlation over time (grey lines = transients)")
    a.set_xlabel("time (s)")
    a.legend(loc="lower right")
    a = ax[2, 1]
    step = max(1, len(x) // 20000)
    a.plot(x[::step, 1], x[::step, 0], ",", alpha=0.4)
    lim = max(float(np.abs(x).max()), 1e-3) * 1.1
    a.set_xlim(-lim, lim)
    a.set_ylim(-lim, lim)
    a.set_aspect("equal")
    a.set_title("Vectorscope (x = right, y = left); diagonal = centre")
    a.grid(alpha=0.3)
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def room_png(path, res, plot, title):
    fig, ax = plt.subplots(3, 2, figsize=FIG, dpi=DPI)
    eg = plot["echogram"]
    n = len(eg["L"])
    tms = np.arange(n) / FS * 1000.0
    a = ax[0, 0]
    a.plot(tms, eg["L"], label="left out", lw=0.8)
    a.plot(tms, eg["R"], label="right out", lw=0.8)
    for tp in res["early_taps"]["taps"]:
        a.axvline(tp["delay_ms"], color=plt.cm.coolwarm((tp["pan"] + 1) / 2), alpha=0.8)
    a.set_ylim(max(min(eg["L"].min(), eg["R"].min()), -140), None)
    a.set_title("Echogram, first 100 ms (energy dB); taps coloured by pan (blue left .. red right); %d found, %s" % (res["early_taps"]["count_found"], res["early_taps"]["status"]))
    a.set_xlabel("ms after arrival")
    a.legend()
    a = ax[0, 1]
    for d, fc in zip(plot["decs"], EDC_BANDS):
        if d is None:
            continue
        a.plot(d["t"], d["edc_db"], label="%d Hz" % fc, lw=1)
    for b in res["tail_bands"]:
        if b["rt60_s"]:
            tt = np.array([0, b["rt60_s"] * 0.6])
            a.plot(tt, -60 * tt / b["rt60_s"], "k:", lw=0.6)
    a.set_ylim(-60, 2)
    a.set_title("Energy decay curves per octave band (dotted = RT60 fit line)")
    a.set_xlabel("s")
    a.set_ylabel("dB")
    a.legend(fontsize=7, ncol=2)
    a = ax[1, 0]
    hz = [b["hz"] for b in res["tail_bands"]]
    a.set_xscale("log")
    a.set_xticks(hz)
    a.set_xticklabels([str(h) for h in hz])
    a.minorticks_off()
    a.semilogx(hz, [b["rt60_s"] if b["rt60_s"] else np.nan for b in res["tail_bands"]], "o-", label="RT60 (s)")
    a.semilogx(hz, [b["edt_s"] if b["edt_s"] else np.nan for b in res["tail_bands"]], "s--", label="EDT (s)")
    a.set_ylabel("s")
    a.set_xlabel("Hz")
    b2 = a.twinx()
    b2.minorticks_off()
    b2.semilogx(hz, [b["iacc"] if b.get("iacc") is not None else np.nan for b in res["tail_bands"]], "r^-", label="IACC")
    b2.set_ylim(-0.1, 1.05)
    b2.set_ylabel("IACC")
    for ax_ in (a, b2):
        ax_.set_xticks(hz)
        ax_.set_xticklabels([str(h) for h in hz])
        ax_.minorticks_off()
    a.legend(loc="upper left")
    b2.legend(loc="upper right")
    a.set_title("RT60, EDT and IACC vs frequency")
    a = ax[1, 1]
    for name, rows in res["pan_map"].items():
        if not rows:
            continue
        a.plot([r["pan_in"] for r in rows], [r["pan_out_direct"] for r in rows], "o-", label=name + " direct")
        a.plot([r["pan_in"] for r in rows], [r["pan_out_tail"] for r in rows], "s--", label=name + " tail")
    a.plot([-1, 1], [-1, 1], "k:", lw=0.5)
    a.set_xlabel("input pan")
    a.set_ylabel("output pan")
    a.set_title("Pan transfer map (direct: -0.5..5 ms; tail: 80-500 ms)")
    a.legend(fontsize=8)
    a.grid(alpha=0.3)
    a = ax[2, 0]
    w = 0.38
    xs = np.arange(len(EDC_BANDS))
    r = res["tail_bands"]
    a.bar(xs, [b["level_db"] for b in r], color="tab:purple")
    a.set_xticks(xs)
    a.set_xticklabels([str(h) for h in EDC_BANDS])
    a.set_title("Reverb energy after the direct sound, relative to direct (dB) per band")
    a.set_xlabel("Hz")
    a = ax[2, 1]
    lin = res["linearity"]
    drawn = False
    if lin.get("run"):
        for k, (label, c) in enumerate(lin["comparisons"].items()):
            if not c.get("run"):
                continue
            a.bar(xs + (k - 0.5) * w, c["magnitude_dev_db"], w, label=label + " (level)")
            drawn = True
        a.axhline(lin["limit_db"], color="r", ls="--")
    a.set_xticks(xs)
    a.set_xticklabels([str(h) for h in EDC_BANDS])
    a.set_title("Linearity check: deviation in dB (red = %.1f dB limit); flagged: %s" % (lin.get("limit_db", 1.0), res["nonlinear_or_time_variant"]))
    if drawn:
        a.legend(fontsize=8)
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def resynth_png(path, stats, title):
    fig, ax = plt.subplots(2, 2, figsize=FIG, dpi=DPI)
    hz = stats["bands_hz"]
    for a, key, lab in ((ax[0, 0], "edc_err_db", "EDC error (dB, mean |diff|, 0..-30 dB)"), (ax[0, 1], "rt60_err_pct", "RT60 error (%)"),
                        (ax[1, 0], "iacc_diff", "IACC difference (synth - reference)"), (ax[1, 1], "spectral_err_db", "Spectral error (dB, synth - reference)")):
        m = np.array([np.nan if v is None else v for v in stats[key]["mean"]], dtype=float)
        s = np.array([np.nan if v is None else v for v in stats[key]["sd"]], dtype=float)
        a.errorbar(range(len(hz)), m, yerr=s, fmt="o-", capsize=3)
        a.axhline(0, color="k", lw=0.5)
        a.set_xticks(range(len(hz)))
        a.set_xticklabels([str(h) for h in hz])
        a.set_title(lab + " - mean +- sd over %d seeds" % stats["seeds"])
        a.set_xlabel("Hz")
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def gen_png(path, sigs, title):
    fig, ax = plt.subplots(4, 2, figsize=FIG, dpi=DPI)
    for a, (name, x) in zip(ax.ravel(), sigs.items()):
        tt = np.arange(len(x)) / FS
        step = max(1, len(x) // 6000)
        a.plot(tt[::step], x[::step, 0], lw=0.5, label="L")
        a.plot(tt[::step], x[::step, 1], lw=0.5, label="R")
        a.set_title("%s (peak %.1f dBFS)" % (name, dsp.db(np.abs(x).max())), fontsize=9)
        a.set_ylim(-0.25, 0.25)
    for a in ax.ravel()[len(sigs):]:
        a.axis("off")
    ax[0, 0].legend()
    fig.suptitle(title, fontsize=13)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
