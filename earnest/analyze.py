"""`analyze` / `analyze-all`: one command from a DAW export to a short written summary. Never plays audio.

An export holds N passes of the SAME suite clip (default 5, Mix 100, 80, 60, 30, 0). The last pass (Mix 0) is the dry reference: it fixes one gain G that is divided out of
every pass, then each pass is analysed against the GENERATED dry blocks (room, stage), and the passes are compared (mixcurve)."""
from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np

from . import mixcurve, plots, report, room, stage, suite
from .io import FS, RUNS, new_run, save_json

DEFAULT_LABELS = [100, 80, 60, 30, 0]
SUMMARY_MAX = 120
ALL_MAX = 100
MIN_RANGE_DB = 45.0


def peak_memory_mb() -> float:
    """Peak working set of this process in MB (Windows)."""
    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    h = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo(wintypes.HANDLE(h), ctypes.byref(pmc), pmc.cb)
    return pmc.PeakWorkingSetSize / 1e6


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", s) or "room"


def room_from_filename(path) -> str:
    return re.split(r"[_\-]", Path(path).stem, maxsplit=1)[0]


def _sets_from_blocks(dry: np.ndarray, manifest: dict, wet_blocks: dict):
    by = {b["name"]: b for b in manifest["blocks"]}

    def d(name):
        b = by[name]
        return dry[b["start_sample"]: b["start_sample"] + b["length_samples"]]
    sets = {"a": {}, "b": {}, "rep": {}}
    for key, suf in (("a", ""), ("b", "_m30"), ("rep", "_rep")):
        for side in ("L", "R"):
            n = "sweep_%s%s" % (side, suf)
            if n in by and n in wet_blocks:
                sets[key][side] = ((d("sweep_" + side) if key == "rep" else d(n)), wet_blocks[n])
    clicks = {n: (d(n), wet_blocks[n]) for n in ("clicks_panned", "clicks_mono") if n in by and n in wet_blocks}
    dry_w = {n: d(n) for n in stage.BLOCKS if n in by}
    return sets, clicks, dry_w


def _fmt(v, nd=2):
    return "n/a" if v is None else "%.*f" % (nd, v)


def analyze(export, room_name: str, manifest_path=None, labels=None, out=None, dry_path=None, quiet: bool = False):
    """Returns (exit_code, summary_md_path, summary dict). Exit code 0 = clean; 2 = a pass is empty / Mix 0 not clean dry / could not find the passes."""
    t_start = time.time()
    labels = list(labels) if labels else list(DEFAULT_LABELS)
    manifest = suite.load_manifest(manifest_path or suite.PROBE_JSON)
    out = Path(out) if out else new_run("analyze-" + slug(room_name))
    out.mkdir(parents=True, exist_ok=True)
    summary = {"room": room_name, "export": str(export), "labels": labels, "manifest": manifest.get("name"), "problems": [], "steps": [], "version": 1}
    problems = summary["problems"]
    try:
        src, dry, steps, info = suite.plan_steps(export, manifest, len(labels), labels, dry_path)
    except SystemExit as e:
        problems.append(str(e))
        return _finish(out, summary, manifest, None, t_start, quiet, code=2)
    fmt = ["%s, %d Hz, %d ch, %.1f s" % (src.info.subtype, src.fs_in, src.info.channels, src.n_in / src.fs_in)]
    if src.fs_in != FS:
        fmt.append("resampled to 48000 Hz")
    if src.info.subtype == "PCM_16":
        fmt.append("16-bit: floor near -90 dBFS, long tails are cut by it")
    summary["format"] = fmt
    for st in steps:
        if st["inferred"]:
            problems.append("pass %d (Mix %s) left no trace of the sweep: it is EMPTY (placed from the gaps between the other passes)" % (st["index"], st["label"]))
    # calibration from the Mix 0 pass
    cal = {"G": 1.0, "G_db": 0.0, "ok": False, "warnings": ["no Mix 0 pass"], "checks": {}}
    if labels[-1] in (0, "0"):
        raw = suite.cut_blocks(src, manifest, steps[-1]["start"], ("sweep_L", "clicks_mono"))
        cal = suite.calibrate(lambda n: raw[n], dry, manifest)
    summary["calibration"] = cal
    for w in cal["warnings"]:
        problems.append("Mix 0 pass: " + w)
    G = cal["G"] if cal["ok"] else 1.0
    step_results = []
    for st in steps:
        label = st["label"]
        folder = out / suite.step_dirname(st)
        folder.mkdir(exist_ok=True)
        blocks = suite.cut_blocks(src, manifest, st["start"])
        stats = {n: suite.block_stats(x) for n, x in blocks.items()}
        empty = [n for n, (pk, _) in stats.items() if pk < suite.EMPTY_DB]
        row = {"index": st["index"], "label": label, "start_s": round(st["start"] / FS, 3), "offset_ms": round(st["start"] / FS * 1000.0, 3), "empty_blocks": empty,
               "sweep_L_peak_dbfs": stats["sweep_L"][0], "sweep_L_rms_dbfs": stats["sweep_L"][1], "short": bool(any(len(x) < b["length_samples"] for x, b in zip(blocks.values(), manifest["blocks"])))}
        if st["inferred"] or "sweep_L" in empty or "sweep_R" in empty:
            row["status"] = "EMPTY"
            if not st["inferred"]:
                problems.append("pass %d (Mix %s): the sweep blocks are empty (peak under -90 dBFS)" % (st["index"], label))
            summary["steps"].append(row)
            continue
        if empty:
            problems.append("pass %d (Mix %s): empty blocks %s" % (st["index"], label, ", ".join(empty)))
        for n in blocks:
            blocks[n] = blocks[n] / G
        sets, clicks, dry_w = _sets_from_blocks(dry, manifest, blocks)
        res, plot = room.run_room_sets(sets, clicks, [])
        sg = stage.compute(dry_w, blocks)
        row.update({"status": "ok", "room": res, "stage": sg})
        row["min_decay_range_db"] = min([b["decay_range_db"] for b in res["tail_bands"] if b.get("decay_range_db") is not None] or [None])
        low = [b["hz"] for b in res["tail_bands"] if b.get("decay_range_db") is not None and b["decay_range_db"] < MIN_RANGE_DB]
        row["low_range_bands_hz"] = low
        if not res["ir_looks_valid"]:
            problems.append("pass %d (Mix %s): the sweep does not deconvolve cleanly (IR decay %s dB, latency %s ms)" % (st["index"], label, res["ir_decay_db"], res["latency_ms"]))
        res2 = dict(res)
        res2["label"] = label
        save_json(folder / "room.json", res2)
        save_json(folder / "formula.json", __import__("earnest.formula", fromlist=["build"]).build(res, "%s step %d Mix %s" % (room_name, st["index"], label)))
        report.room_report(res, folder / "report.md", "%s, step %d, Mix %s" % (room_name, st["index"], label))
        plots.room_png(folder / "room.png", res, plot, "earnest room: %s step %d Mix %s" % (room_name, st["index"], label))
        del blocks, sets, clicks, plot
        summary["steps"].append(row)
        step_results.append((label, res))
    curve = None
    if len(step_results) >= 2:
        curve, _ = mixcurve.write(step_results, out, room_name)
        summary["mixcurve"] = {"labels": curve["labels"], "metrics": curve["metrics"], "flags": curve["flags"]}
    # Mix 0 sanity line
    s0 = next((s for s in summary["steps"] if s["label"] in (0, "0") and s.get("status") == "ok"), None)
    if s0:
        m = s0["room"]["direct_matrix"]
        L0 = s0["room"]["inputs"][0]
        diag = m[L0][0]
        cross = m[L0][1]
        lvl = s0["room"]["tail_bands"][3]["level_db"]
        ident = abs(diag - 1) < 0.1 and abs(cross) < 0.1 and lvl < -40
        summary["mix0_sanity"] = {"identity": bool(ident), "M_LL": round(diag, 4), "M_LR": round(cross, 4), "tail_level_db_1k": lvl}
    return _finish(out, summary, manifest, curve, t_start, quiet)


def _finish(out, summary, manifest, curve, t_start, quiet, code=None):
    problems = summary["problems"]
    summary["seconds"] = round(time.time() - t_start, 1)
    summary["peak_memory_mb"] = round(peak_memory_mb(), 0)
    bad = any(("EMPTY" in p or "empty" in p or "Mix 0 pass" in p or "not clean" in p) for p in problems)
    summary["exit_code"] = code if code is not None else (2 if bad else 0)
    lines = summary_lines(summary)
    p = out / "summary.md"
    n = report.finish(lines, p) if len(lines) <= SUMMARY_MAX else report.finish(lines[: SUMMARY_MAX - 1] + ["(cut at %d lines; summary.json has everything)" % SUMMARY_MAX], p)
    slim = {k: v for k, v in summary.items()}
    save_json(out / "summary.json", slim)
    if not quiet:
        print("summary: %s" % p)
        for pr in problems:
            print("PROBLEM: " + pr)
    return summary["exit_code"], p, summary


def summary_lines(s):
    L = ["# earnest analyze: %s" % s["room"], "", "Export: %s" % s["export"], "Format: %s" % "; ".join(s.get("format", ["unknown"])),
         "Passes expected: %s (Mix labels). Run time %.0f s, peak memory %.0f MB." % (s["labels"], s["seconds"], s["peak_memory_mb"]), ""]
    if s["problems"]:
        L += ["## PROBLEMS"] + ["- " + p for p in s["problems"]] + [""]
    cal = s.get("calibration")
    if cal:
        L += ["## Level calibration (Mix 0 pass)", "- gain G = %s dB%s (measured over 200 Hz-8 kHz on sweep_L; divided out of every pass). Checks: %s" % (
            _fmt(cal.get("G_db"), 2), "" if cal.get("ok") else " NOT APPLIED", cal.get("checks") or "none"), ""]
    L += ["## Passes", "| step | Mix | start s | offset ms | sweep_L peak dBFS | status |", "|---|---|---|---|---|---|"]
    for r in s["steps"]:
        L.append("| %d | %s | %s | %s | %s | %s%s |" % (r["index"], r["label"], r["start_s"], r["offset_ms"], r.get("sweep_L_peak_dbfs"), r.get("status", "?"),
                                                  (" (cut short)" if r.get("short") else "")))
    ok = [r for r in s["steps"] if r.get("status") == "ok"]
    if ok:
        L += ["", "## Room numbers per Mix step (RT60, EDT, IACC = mean of the 250 Hz-4 kHz octave bands)",
              "| Mix | M L>L | M L>R | M R>R | tail dB re direct | RT60 s | EDT s | IACC | DRR dB | C50 dB | C80 dB | pan slope direct | pan slope tail | taps | nonlinear | min decay range dB |",
              "|" + "---|" * 16]
        for r in ok:
            m = mixcurve.metrics(r["room"])
            L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                r["label"], _fmt(m["M_LL"], 3), _fmt(m["M_LR"], 3), _fmt(m["M_RR"], 3), _fmt(m["tail_level_db"]), _fmt(m["rt60_s"], 3), _fmt(m["edt_s"], 3), _fmt(m["iacc"], 3),
                _fmt(m["drr_db"]), _fmt(m["c50_db"]), _fmt(m["c80_db"]), _fmt(m["pan_slope_direct"], 3), _fmt(m["pan_slope_tail"], 3), m["taps"], m["nonlinear"],
                _fmt(m["min_decay_range_db"], 1)))
        low = [(r["label"], r["low_range_bands_hz"]) for r in ok if r.get("low_range_bands_hz")]
        if low:
            L.append("- decay range under %d dB (RT60 fit unreliable): %s" % (MIN_RANGE_DB, "; ".join("Mix %s bands %s Hz" % (a, b) for a, b in low)))
        L += ["", "RT60 by octave band (s):", "| Mix | " + " | ".join("%d" % h for h in mixcurve.EDC_BANDS) + " |", "|---|" + "---|" * len(mixcurve.EDC_BANDS)]
        for r in ok:
            L.append("| %s | %s |" % (r["label"], " | ".join(_fmt(b["rt60_s"], 3) for b in r["room"]["tail_bands"])))
    if "mix0_sanity" in s:
        z = s["mix0_sanity"]
        L += ["", "Mix 0 sanity: %s (M L>L %s, M L>R %s, tail level at 1 kHz %s dB re direct)" % ("near identity" if z["identity"] else "NOT near identity", z["M_LL"], z["M_LR"], z["tail_level_db_1k"])]
    mc = s.get("mixcurve")
    if mc:
        L += ["", "## Mix curve flags", "- " + ("; ".join("%s %s (%s)" % (f["metric"], f["span"], f["rule"]) for f in mc["flags"]) or "no metric moves across the steps"),
              "- plot: mixcurve.png (same numbers as the table above)"]
    if ok and any("stage" in r for r in ok):
        L += ["", "## Stage (width): inputs mid (corr +1), wide (0), side (-1); S/M = side over mid energy in dB (clamped to +-60); tail corr per octave 125 Hz..8 kHz",
              "| Mix | input | in corr | in S/M | direct corr | direct S/M | tail corr (125..8k) | tail S/M broadband | width gain direct / tail dB |", "|---|---|---|---|---|---|---|---|---|"]
        for r in ok:
            for nm in stage.BLOCKS:
                g = r["stage"].get(nm)
                if not g or "error" in g:
                    continue
                wg = g["width_gain_db"]
                L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (r["label"], nm[6:], _fmt(g["input_corr"], 3), _fmt(g["input_side_over_mid_db"]), _fmt(g["direct"]["corr"], 3),
                                                                           _fmt(g["direct"]["side_over_mid_db"]), " ".join(_fmt(v, 2) for v in g["tail"]["corr"]),
                                                                           _fmt(g["tail"]["broadband_side_over_mid_db"]),
                                                                           ("%s / %s" % (_fmt(wg["direct"]), _fmt(wg["tail"]))) if wg else "n/a (input has no side or no mid)"))
    return L


def analyze_all(folder, labels=None, manifest_path=None):
    folder = Path(folder)
    files = sorted([p for p in folder.iterdir() if p.suffix.lower() in (".wav", ".flac")])
    results = []
    out_root = new_run("analyze-all")
    for f in files:
        name = room_from_filename(f)
        try:
            code, p, s = analyze(f, name, manifest_path, labels, out=out_root / slug(name), quiet=True)
            results.append({"file": f.name, "room": name, "code": code, "summary": str(p), "data": s})
        except Exception as e:      # one bad file must not stop the rest
            results.append({"file": f.name, "room": name, "code": 3, "summary": None, "error": "%s: %s" % (type(e).__name__, e), "data": None})
    L = ["# earnest all rooms", "", "Folder: %s. %d file(s). Each row: one room and one Mix step; numbers are single values (RT60, EDT, IACC = mean of 250 Hz-4 kHz bands)." % (folder, len(results)), ""]
    bad = [r for r in results if r["code"] != 0]
    if bad:
        L += ["## Failed or flagged"]
        for r in bad:
            L.append("- %s (%s): %s" % (r["room"], r["file"], r.get("error") or "; ".join(r["data"]["problems"]) or "exit code %d" % r["code"]))
        L.append("")
    L += ["| room | Mix | M L>L / L>R | tail dB | RT60 s | EDT s | IACC | DRR dB | C50 dB | pan slope dir / tail | width gain dir / tail dB | corr dir / tail (wide) | S/M dir (side in) dB |", "|" + "---|" * 13]
    for r in results:
        s = r["data"]
        if not s:
            continue
        for st in s["steps"]:
            if st.get("status") != "ok":
                L.append("| %s | %s | EMPTY | | | | | | | | | | |" % (r["room"], st["label"]))
                continue
            m = mixcurve.metrics(st["room"])
            wide = st["stage"].get("noise_wide") or {}
            side = st["stage"].get("noise_side") or {}
            wg = wide.get("width_gain_db") or {}
            L.append("| %s | %s | %s / %s | %s | %s | %s | %s | %s | %s | %s / %s | %s / %s | %s / %s | %s |" % (
                r["room"], st["label"], _fmt(m["M_LL"], 3), _fmt(m["M_LR"], 3), _fmt(m["tail_level_db"], 1), _fmt(m["rt60_s"], 2), _fmt(m["edt_s"], 2), _fmt(m["iacc"], 2), _fmt(m["drr_db"], 1),
                _fmt(m["c50_db"], 1), _fmt(m["pan_slope_direct"], 2), _fmt(m["pan_slope_tail"], 2), _fmt(wg.get("direct"), 1), _fmt(wg.get("tail"), 1),
                _fmt((wide.get("direct") or {}).get("corr"), 2), _fmt((wide.get("tail") or {}).get("broadband_corr"), 2), _fmt((side.get("direct") or {}).get("side_over_mid_db"), 1)))
    L += ["", "Per-room detail: " + "; ".join("%s -> %s" % (r["room"], r["summary"]) for r in results if r["summary"])]
    n = report.finish(L if len(L) <= ALL_MAX else L[: ALL_MAX - 1] + ["(cut at %d lines)" % ALL_MAX], out_root / "all_rooms_summary.md")
    save_json(out_root / "all_rooms_summary.json", [{k: v for k, v in r.items() if k != "data"} | {"problems": (r["data"] or {}).get("problems")} for r in results])
    print("all_rooms_summary: %s" % (out_root / "all_rooms_summary.md"))
    return (1 if bad else 0), out_root / "all_rooms_summary.md"
