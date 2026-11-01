"""report.md writers. Plain numbers with units, at most 150 lines, written for a reader who cannot see the PNG."""
from __future__ import annotations

MAX_LINES = 150


def _f(v, nd=2, unit=""):
    return "n/a" if v is None else ("%.*f%s" % (nd, v, unit))


def finish(lines, path):
    if len(lines) > MAX_LINES:
        lines = lines[: MAX_LINES - 1] + ["(report cut at %d lines; the JSON file has everything)" % MAX_LINES]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def gen_report(m, path, outdir):
    L = ["# earnest gen", "", "Written to `%s`" % outdir, "", "All files: %d Hz, 32-bit float WAV, peak %.0f dBFS. Never played; bounce them in the DAW." % (m["fs"], m["peak_dbfs"]), "",
         "| file | seconds | peak dBFS |", "|---|---|---|"]
    for k, v in m["files"].items():
        L.append("| %s | %.3f | %.2f |" % (k, v["seconds"], v["peak_dbfs"]))
    s = m["sweep"]
    L += ["", "Sweep: exponential %g-%g Hz, %g s, %g s silence before, %g s silence after, %g s fades." % (s["f1"], s["f2"], s["seconds"], s["lead_s"], s["tail_s"], s["fade_s"]),
          "Pans for clicks and noise bursts: %s (constant power, gL=cos((p+1)pi/4), gR=sin((p+1)pi/4)); first at %g s, %g s apart." % (m["pans"], m["click_t0_s"], m["click_gap_s"]),
          "clicks_mono.wav: the same click in both channels, five times.", "", m["repeat_note"]]
    return finish(L, path)


def listen_report(r, path, title, notes):
    L = ["# earnest listen: %s" % title, ""]
    if notes:
        L += ["Notes: " + "; ".join(notes), ""]
    ld = r["loudness"]
    L += ["## Levels", "- duration %.3f s; peak %s dBFS; true peak %s dBTP; RMS %s dBFS" % (r["seconds"], _f(r["peak_dbfs"]), _f(r["true_peak_dbtp"]), _f(r["rms_dbfs"])),
          "- integrated loudness %s LUFS" % _f(ld["integrated_lufs"]),
          "- short-term loudness (3 s windows): " + (", ".join("%s s: %s" % (x["t"], _f(x["lufs"], 1)) for x in ld["short_term_lufs"][:12]) or "n/a (file shorter than 3 s)")
          + (" ..." if len(ld["short_term_lufs"]) > 12 else ""),
          "- phase correlation (L vs R, zero lag) %s; mid/side energy ratio %s dB (positive = more mid)" % (_f(r["phase_correlation"], 3), _f(r["mid_side_db"])), "",
          "## Per octave band (pan from level ratio: -1 left .. +1 right)", "| Hz | level dB | ILD dB (L-R) | ILD pan | coherence | corr |", "|---|---|---|---|---|---|"]
    for b in r["bands"]:
        L.append("| %g | %s | %s | %s | %s | %s |" % (b["hz"], _f(b["level_db"]), _f(b["ild_db"]), _f(b["ild_pan"], 3), _f(b["coherence"], 3), _f(b["corr"], 3)))
    pg = r["panogram"]
    L += ["", "## Panogram (Avendano panning index, %d-point FFT, hop %d)" % (pg["fft"], pg["hop"]), "- energy-weighted mean panning index %s" % _f(pg["mean_panning_index"], 3),
          "- energy by pan bin (41 bins, -1 left .. +1 right, dB re total): " + " ".join(_f(v, 0) for v in pg["energy_by_pan_bin_db"])]
    rv = r["reverberance"]
    L += ["", "## Blind reverberance", "- tail/onset energy %s dB (sd %s) over %d onsets" % (_f(rv["tail_over_onset_db_mean"]), _f(rv["tail_over_onset_db_sd"]), rv["onsets_used"]), "- " + rv["meaning"],
          "", "## Transients (%d strongest, with pan)" % len(r["transients"]), "| t s | rise dB | level dBFS | pan |", "|---|---|---|---|"]
    for t in r["transients"][:12]:
        L.append("| %s | %s | %s | %s |" % (t["t"], t["rise_db"], t["level_dbfs"], t["pan"]))
    if len(r["transients"]) > 12:
        L.append("(%d more in the JSON)" % (len(r["transients"]) - 12))
    L += ["", "## Summary in %d segments" % len(r["segments"]), "| from s | to s | RMS dBFS | width (0 mono .. 1 side-only) | corr | pan |", "|---|---|---|---|---|---|"]
    for s in r["segments"]:
        L.append("| %s | %s | %s | %s | %s | %s |" % (s["t_from"], s["t_to"], _f(s["rms_dbfs"]), _f(s["width"], 3), _f(s["corr"], 3), _f(s["pan"], 3)))
    L += ["", "Width over time and correlation are drawn from the same table in the JSON (`width_series`, one row per window)."]
    return finish(L, path)


def room_report(r, path, title):
    L = ["# earnest room: %s" % title, "", "Input mode: %s. IR length %s s. Latency dry->wet %s ms. Notes: %s" % (r["input_mode"], r["ir_seconds"], r["latency_ms"], "; ".join(r["notes"]) or "none"),
         "IR power in its first 100 ms is %s dB above its last 20%%; %s" % (r["ir_decay_db"], "looks like a valid deconvolution." if r["ir_looks_valid"] else "**WARNING: decay below 30 dB or latency over 1 s: the wet file is probably not a render of this dry sweep; the numbers below are not trustworthy.**"), ""]
    lin = r["linearity"]
    L.append("## Linearity (limit %.1f dB in any band 125 Hz-8 kHz)" % lin.get("limit_db", 1.0))
    if not lin.get("run"):
        L.append("- linearity: %s" % lin.get("reason"))
    else:
        for k, c in lin["comparisons"].items():
            if not c.get("run"):
                L.append("- %s: not run (%s)" % (k, c.get("reason")))
            else:
                L.append("- %s: level deviation per band %s dB; EDC deviation %s dB; worst %.2f dB" % (k, c["magnitude_dev_db"], c["edc_dev_db"], c["worst_db"]))
        L.append("- **nonlinear_or_time_variant: %s**" % str(lin["nonlinear_or_time_variant"]).lower())
    L += ["", "## Direct matrix M (signed gain, output <- input)"]
    for i in r["inputs"]:
        L.append("- input %s -> L out %.4f, R out %.4f" % (i, r["direct_matrix"][i][0], r["direct_matrix"][i][1]))
    et = r["early_taps"]
    L += ["", "## Early taps: %s (%d found)" % (et["status"], et["count_found"]), "- rule: " + et["rule"]]
    if et["taps"]:
        L += ["| delay ms | gain dB re direct | pan | source |", "|---|---|---|---|"]
        for t in et["taps"]:
            L.append("| %.3f | %.2f | %.3f | %s |" % (t["delay_ms"], t["gain_db"], t["pan"], t["source"]))
    L += ["", "## Tail per octave band", "| Hz | level dB re direct | RT60 s | T20 s | T30 s | EDT s | pre-delay ms | build-up ms | IACC | modulation |", "|---|---|---|---|---|---|---|---|---|---|"]
    for b in r["tail_bands"]:
        mod = b.get("modulation")
        L.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (b["hz"], _f(b["level_db"]), _f(b["rt60_s"], 3), _f(b["t20_s"], 3), _f(b["t30_s"], 3), _f(b["edt_s"], 3),
                                                                      _f(b.get("pre_delay_ms")), _f(b.get("buildup_ms")), _f(b.get("iacc"), 3),
                                                                      ("%s Hz, %s dB p-p" % (mod["rate_hz"], mod["depth_db_pp"])) if mod else "not detected"))
    rm = r["room"]
    L += ["", "## Room metrics", "- DRR %s dB; C50 %s dB; C80 %s dB; first reflection %s ms" % (_f(rm["drr_db"]), _f(rm["c50_db"]), _f(rm["c80_db"]), _f(r["first_reflection_ms"], 3))]
    L += ["", "## Pan transfer map (output pan of the direct click, and of the 80-500 ms tail)"]
    if not r["pan_map"]:
        L.append("- no click files found")
    for name, rows in r["pan_map"].items():
        L += ["### %s" % name, "| pan in | pan out (direct) | pan out (tail) | tail L/R corr | tail side/mid dB | direct level dB |", "|---|---|---|---|---|---|"]
        for x in rows:
            L.append("| %s | %s | %s | %s | %s | %s |" % (x["pan_in"], x["pan_out_direct"], x["pan_out_tail"], _f(x["tail_corr"], 3), x["tail_side_over_mid_db"], x["direct_level_db"]))
    L += ["", "The formula is in formula.json. The tail is statistical (shaped noise); the model assumes a linear, time-invariant system."]
    return finish(L, path)


def resynth_report(s, path, title):
    L = ["# earnest resynth: %s" % title, "", "Reference: %s" % s["reference"], "Seeds: %d (mean +- sd). Notes: %s" % (s["seeds"], "; ".join(s["notes"]) or "none"),
         "Comparison is statistical; no waveform comparison. Spectral error: %s." % s["spectral_error_definition"], "",
         "| Hz | EDC error dB | RT60 error % | IACC diff | spectral error dB |", "|---|---|---|---|---|"]

    def ms(k, i, nd):
        m, d = s[k]["mean"][i], s[k]["sd"][i]
        return "n/a" if m is None else "%.*f +- %.*f" % (nd, m, nd, d if d is not None else 0)
    for i, hz in enumerate(s["bands_hz"]):
        L.append("| %d | %s | %s | %s | %s |" % (hz, ms("edc_err_db", i, 2), ms("rt60_err_pct", i, 1), ms("iacc_diff", i, 3), ms("spectral_err_db", i, 2)))
    L += ["", "Nothing here is called matched: judge the numbers above against your own limits."]
    return finish(L, path)


def suite_report(m, path, outdir):
    L = ["# earnest gen --suite %s" % m["mode"], "", "Written to `%s`" % outdir, "",
         "One WAV, %d Hz, 32-bit float stereo, %.3f s long (%.0f s silence at the start, %.0f s at the end, %.0f s silent tail inside each block). Import it into the DAW, "
         "export it through the effect (same sample rate if possible), then run `split`." % (m["fs"], m["length_s"], m["lead_s"], m["end_s"], m["block_tail_s"]), "",
         "| block | start s | length s | peak dBFS |", "|---|---|---|---|"]
    for b in m["blocks"]:
        L.append("| %s | %.3f | %.3f | %.2f |" % (b["name"], b["start_s"], b["length_s"], b["peak_dbfs"]))
    s = m["sweep"]
    L += ["", "Sweep blocks: exponential %g-%g Hz, %g s, 0.5 s before the sweep. Click and noise-burst blocks: pans %s (constant power), first at 0.5 s, 2 s apart." % (s["f1"], s["f2"], s["seconds"], m["blocks"][-1].get("pans")),
          m["note"] + ".", "Pan law: " + m["pan_law"] + "."]
    return finish(L, path)


def split_report(r, path, wet_path):
    cal = r["calibration"]
    L = ["# earnest split: %s" % wet_path, "", "Manifest %s (%s). Wet file %.3f s long. Notes: %s" % (r["manifest"], r["mode"], r["wet_seconds"], "; ".join(r["notes"]) or "none"), ""]
    if cal.get("applied"):
        L.append("**Level calibration from the Mix 0 pass: G = %.3f dB, divided out of every cut file.** Checks: %s." % (cal["G_db"], cal["checks"]))
    elif cal.get("warnings"):
        L.append("**Level calibration NOT applied:** " + "; ".join(cal["warnings"]))
    else:
        L.append("No calibration requested (needs --labels ending in 0).")
    L += ["", "Position of the dry suite's time zero in the wet file (offset) for each copy. It includes where the clip was placed and the effect's own latency.", ""]
    for st in r["steps"]:
        L += ["## step %d%s: offset %.3f ms, start %.3f s%s" % (st["index"], (" (Mix %s)" % st["label"]) if st["label"] is not None else "", st["offset_ms"], st["start_s"],
                                                           "  **EMPTY: no trace of the suite found, position inferred from the gaps**" if st["inferred"] else ""),
              "| block | peak dBFS | RMS dBFS | length s | flags |", "|---|---|---|---|---|"]
        for b in st["blocks"]:
            L.append("| %s | %.2f | %.2f | %.3f | %s |" % (b["name"], b["peak_dbfs"], b["rms_dbfs"], b["length_s"], "EMPTY (peak under -90 dBFS)" if b["empty"] else "-"))
        if st["cut_short"]:
            L.append("- this copy is cut short by the end of the file")
        L.append("")
    return finish(L, path)
