"""`analyze` / `analyze-all`: from DAW exports to short written summaries, through the traced pipeline (pipeline.py). Never plays audio."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

import soundfile as sf

from . import mixcurve, pipeline, probe, report, stage, suite
from .io import new_run, save_json
from .pipeline import DEFAULT_LABELS, classify, room_from_filename, slug  # noqa: F401  (re-exported)

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


def _fmt(v, nd=2):
    return "n/a" if v is None else "%.*f" % (nd, v)


def analyze(export, room_name: str, manifest_path=None, labels=None, out=None, dry_path=None, quiet: bool = False, stop_on_fail: bool = False, probe_path=None, mix=None):
    """One export file (single pass, or several passes in one file) as one room. `dry_path` = the dry reference EXPORT (single-pass use), `probe_path` = the generated probe
    signal file (default: the one next to the manifest, else regenerated), `mix` = the Mix label of a single-pass file."""
    members = [{"path": export, "label": mix}]
    dry = {"path": dry_path} if dry_path else None
    return pipeline.process_room(room_name, members, dry, manifest_path, labels, out, quiet, stop_on_fail, True, None, probe_path)


def _file_line(f: dict) -> str:
    if "peak_dbfs" not in f:
        return "| %s | %s | n/a | n/a | n/a | n/a | n/a | %s: %s |" % (f.get("file", "?"), f.get("role"), f.get("status"), f.get("reason", ""))
    best = {}
    for s in f.get("match") or []:
        best["%s>ch%s" % (s["sweep"].replace("sweep_", ""), "LR"[s["channel"]])] = "%.0f dB@%.0f ms" % (s["peak_to_noise_db"], s["copy_start_ms"])
    return "| %s | %s | %.1f s, %d Hz, %s | %s | %s | %s | %s | %s |" % (
        f.get("file"), f.get("role"), f.get("seconds", 0), f.get("samplerate", 0), ("%s-bit" % f["bits"]) if f.get("bits") else "?",
        "/".join("%.1f" % p for p in f["peak_dbfs"]), "/".join("%.1f" % p for p in f["rms_dbfs"]), "/".join("%.1f" % p for p in f["floor_dbfs"]),
        ", ".join("%s %s" % (k, v) for k, v in best.items()) or "not reached", f.get("status", "?"))


def summary_lines(s):
    L = ["# earnest analyze: %s" % s["room"], "", "Run time %.0f s, peak memory %.0f MB. Labels for multi-pass files: %s." % (s["seconds"], s["peak_memory_mb"], s["labels"]), ""]
    if s["problems"]:
        L += ["## PROBLEMS"] + ["- " + p for p in s["problems"]] + [""]
    if s.get("warnings"):
        L += ["## Warnings"] + ["- " + w for w in s["warnings"]] + [""]
    L += ["## Files (what each file contained, whether or not it could be analysed)",
          "| file | role | length, rate, bits | peak dBFS L/R | RMS dBFS L/R | noise floor dBFS L/R | matched filter vs probe sweeps (peak/noise@lag) | result |", "|---|---|---|---|---|---|---|---|"]
    for f in s["files"]:
        L.append(_file_line(f))
        if f.get("status") == "FAIL" and f.get("cause"):
            L.append("- most likely cause for %s: %s" % (f.get("file"), f["cause"]))
    cal = s.get("calibration")
    if cal:
        L += ["", "## Level calibration", "- gain G = %s dB%s (sweep_L over 200 Hz-8 kHz against the generated probe; divided out of every pass). Checks: %s" % (
            _fmt(cal.get("G_db"), 2), "" if cal.get("ok") else " NOT APPLIED", cal.get("checks") or "none")]
    L += ["", "## Passes", "| step | Mix | clip start s | sweep peak dBFS | noise floor dBFS (silent head and end) | usable range dB | status |", "|---|---|---|---|---|---|---|"]
    for r in s["steps"]:
        fl = r.get("noise_floor_dbfs")
        L.append("| %s | %s | %s | %s | %s | %s | %s%s |" % (r.get("index"), r.get("label"), r.get("start_s"), r.get("signal_peak_dbfs", "n/a"),
                                                          ("%s%s" % (_fmt(fl, 1), " (digital silence)" if r.get("digital_silence") else "")) if fl is not None else "n/a",
                                                          ("%s%s" % (_fmt(r.get("usable_range_db"), 1), " LOW (<45)" if r.get("low_range") else "")) if fl is not None else "n/a",
                                                          r.get("status", "?"), (" (cut short)" if r.get("short") else "")))
    ok = [r for r in s["steps"] if r.get("status") == "ok"]
    order = sorted(ok, key=lambda r: -r["label"] if isinstance(r.get("label"), (int, float)) else 1)
    if ok:
        L += ["", "## Room numbers per Mix step (RT60, EDT, IACC = mean of the 250 Hz-4 kHz octave bands)",
              "| Mix | M L>L | M L>R | M R>R | tail dB re direct | RT60 s | EDT s | IACC | DRR dB | C50 dB | C80 dB | pan slope direct | pan slope tail | taps | nonlinear |", "|" + "---|" * 15]
        for r in order:
            m = mixcurve.metrics(r["room"])
            L.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                r["label"], _fmt(m["M_LL"], 3), _fmt(m["M_LR"], 3), _fmt(m["M_RR"], 3), _fmt(m["tail_level_db"]), _fmt(m["rt60_s"], 3), _fmt(m["edt_s"], 3), _fmt(m["iacc"], 3),
                _fmt(m["drr_db"]), _fmt(m["c50_db"]), _fmt(m["c80_db"]), _fmt(m["pan_slope_direct"], 3), _fmt(m["pan_slope_tail"], 3), m["taps"], m["nonlinear"]))
        L.append("- n/a = the step has no tail (under %d dB re direct), e.g. the Mix 0 pass. EDT is measured from the tail onset, RT60 from the same point (see README)." % -mixcurve.NO_TAIL_DB)
        L += ["", "RT60 by octave band (s):", "| Mix | " + " | ".join("%d" % h for h in mixcurve.EDC_BANDS) + " |", "|---|" + "---|" * len(mixcurve.EDC_BANDS)]
        for r in order:
            L.append("| %s | %s |" % (r["label"], " | ".join(_fmt(v, 3) for v in mixcurve.metrics(r["room"])["rt60_by_band"])))
    if "mix0_sanity" in s:
        z = s["mix0_sanity"]
        L += ["", "Mix 0 sanity: %s (M L>L %s, M L>R %s, tail level at 1 kHz %s dB re direct)" % ("near identity" if z["identity"] else "NOT near identity", z["M_LL"], z["M_LR"], z["tail_level_db_1k"])]
    mc = s.get("mixcurve")
    if mc:
        L += ["", "## Mix curve flags", "- " + ("; ".join("%s %s (%s)" % (f["metric"], f["span"], f["rule"]) for f in mc["flags"]) or "no metric moves across the steps"),
              "- plot: mixcurve.png (same numbers as the table above)"]
    if ok and any(r.get("stage") for r in ok):
        L += ["", "## Stage (width): inputs mid (corr +1), wide (0), side (-1); S/M = side over mid energy in dB (clamped to +-60); tail corr per octave 125 Hz..8 kHz",
              "| Mix | input | in corr | in S/M | direct corr | direct S/M | tail corr (125..8k) | tail S/M broadband | width gain direct / tail dB |", "|---|---|---|---|---|---|---|---|---|"]
        for r in order:
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


# ----------------------------------------------------------------------------- folders

def plan_folder(folder):
    """Reads every .wav/.flac in the folder (headers and a hash) and decides roles. Returns dict(files, rooms, dry, duplicates, notes, all)."""
    folder = Path(folder)
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".wav", ".flac"))
    seen, dups, keep = {}, [], []
    for f in files:
        h = probe.file_hash(f)
        if h in seen:
            dups.append({"file": f.name, "duplicate_of": seen[h]})
            continue
        seen[h] = f.name
        keep.append(f)
    manifest = suite.load_manifest(suite.PROBE_JSON)
    dry, rooms, notes = [], {}, []
    for f in keep:
        c = classify(f)
        try:
            i = sf.info(str(f))
            secs = i.frames / i.samplerate
        except Exception:
            secs = 0.0
        multi = secs >= 1.6 * manifest["total_s"]
        if c["role"] == "dry":
            dry.append(f)
        elif multi:
            rooms.setdefault(room_from_filename(f), []).append({"path": f, "label": None})
        else:
            rooms.setdefault(c["room"], []).append({"path": f, "label": c["mix"]})
    dry_member = None
    if len(dry) == 1:
        dry_member = {"path": dry[0]}
    elif len(dry) > 1:
        notes.append("more than one dry reference file (%s): none used, no calibration" % ", ".join(d.name for d in dry))
    elif any(m["label"] is not None for ms in rooms.values() for m in ms):
        notes.append("no dry reference file (a file whose name starts with 'dry'): single-pass room files are not calibrated")
    return {"files": keep, "rooms": rooms, "dry": dry_member, "duplicates": dups, "notes": notes, "all": files}


def process_folder(folder, labels=None, manifest_path=None, out_root=None, stop_on_fail=False, quiet=True, plan=None, only_rooms=None, cache=None):
    """Runs every room of a folder. Returns (results, plan, out_root): results = [{room, file, code, summary, data}]."""
    plan = plan or plan_folder(folder)
    out_root = Path(out_root) if out_root else new_run("analyze-all")
    results = []
    cache = {} if cache is None else cache
    for room_name, members in plan["rooms"].items():
        if only_rooms is not None and room_name not in only_rooms:
            continue
        members = sorted(members, key=lambda m: -m["label"] if m["label"] is not None else 1)
        names = ", ".join(Path(m["path"]).name for m in members)
        try:
            code, p, s = pipeline.process_room(room_name, members, plan["dry"], manifest_path, labels, out_root / slug(room_name), quiet, stop_on_fail, True, cache)
            results.append({"room": room_name, "file": names, "code": code, "summary": str(p), "data": s})
        except Exception as e:      # one bad room must not stop the rest
            results.append({"room": room_name, "file": names, "code": 3, "summary": None, "error": "%s: %s" % (type(e).__name__, e), "data": None})
        if stop_on_fail and results[-1]["code"] != 0:
            break
    return results, plan, out_root


def analyze_all(folder, labels=None, manifest_path=None, stop_on_fail=False):
    results, plan, out_root = process_folder(folder, labels, manifest_path, stop_on_fail=stop_on_fail, quiet=False)
    bad = all_rooms_report(results, out_root / "all_rooms_summary.md", "Folder: %s" % folder, plan)
    save_json(out_root / "all_rooms_summary.json", [{k: v for k, v in r.items() if k != "data"} | {"problems": (r["data"] or {}).get("problems")} for r in results])
    print("all_rooms_summary: %s" % (out_root / "all_rooms_summary.md"))
    return (1 if bad else 0), out_root / "all_rooms_summary.md"


def all_rooms_report(results, path, where, plan=None) -> list:
    """Writes the one-table summary (100 lines or fewer); returns the list of failed or flagged results."""
    L = ["# earnest all rooms", "", "%s. %d room(s). Each row: one room and one Mix step; numbers are single values (RT60, EDT, IACC = mean of 250 Hz-4 kHz bands; n/a = no tail)." % (where, len(results)), ""]
    bad = [r for r in results if r["code"] != 0]
    if bad:
        L += ["## Failed or flagged"]
        for r in bad:
            L.append("- %s (%s): %s" % (r["room"], r["file"], r.get("error") or "; ".join(r["data"]["problems"]) or "exit code %d" % r["code"]))
        L.append("")
    if plan:
        for n in plan["notes"]:
            L.append("- NOTE: " + n)
        for d in plan["duplicates"]:
            L.append("- DUPLICATE: %s has the same content as %s and was skipped" % (d["file"], d["duplicate_of"]))
        if plan["notes"] or plan["duplicates"]:
            L.append("")
    L += ["## Files (every file in the folder, with what was read from it)", "| file | role | length, rate, bits | peak dBFS L/R | RMS dBFS L/R | noise floor dBFS L/R | matched filter vs probe sweeps | result |", "|---|---|---|---|---|---|---|---|"]
    seen = set()
    for r in results:
        for f in (r["data"] or {}).get("files", []):
            if f.get("file") in seen:
                continue
            seen.add(f.get("file"))
            L.append(_file_line(f))
    L += ["", "| room | Mix | M L>L / L>R | tail dB | RT60 s | EDT s | IACC | DRR dB | C50 dB | pan slope dir / tail | width gain dir / tail dB | corr dir / tail (wide) | S/M dir (side in) dB | noise floor dBFS / range dB |", "|" + "---|" * 14]
    for r in results:
        s = r["data"]
        if not s:
            continue
        for st in sorted(s["steps"], key=lambda x: -x["label"] if isinstance(x.get("label"), (int, float)) else 1):
            if st.get("status") != "ok":
                L.append("| %s | %s | %s | | | | | | | | | | | |" % (r["room"], st.get("label"), st.get("status")))
                continue
            m = mixcurve.metrics(st["room"])
            wide = st["stage"].get("noise_wide") or {}
            side = st["stage"].get("noise_side") or {}
            wg = wide.get("width_gain_db") or {}
            L.append("| %s | %s | %s / %s | %s | %s | %s | %s | %s | %s | %s / %s | %s / %s | %s / %s | %s | %s / %s%s |" % (
                r["room"], st["label"], _fmt(m["M_LL"], 3), _fmt(m["M_LR"], 3), _fmt(m["tail_level_db"], 1), _fmt(m["rt60_s"], 2), _fmt(m["edt_s"], 2), _fmt(m["iacc"], 2), _fmt(m["drr_db"], 1),
                _fmt(m["c50_db"], 1), _fmt(m["pan_slope_direct"], 2), _fmt(m["pan_slope_tail"], 2), _fmt(wg.get("direct"), 1), _fmt(wg.get("tail"), 1),
                _fmt((wide.get("direct") or {}).get("corr"), 2), _fmt((wide.get("tail") or {}).get("broadband_corr"), 2), _fmt((side.get("direct") or {}).get("side_over_mid_db"), 1),
                _fmt(st.get("noise_floor_dbfs"), 1), _fmt(st.get("usable_range_db"), 1), " LOW" if st.get("low_range") else ""))
    L += ["", "Per-room detail: " + "; ".join("%s -> %s" % (r["room"], r["summary"]) for r in results if r["summary"])]
    report.finish(L if len(L) <= ALL_MAX else L[: ALL_MAX - 1] + ["(cut at %d lines)" % ALL_MAX], path)
    return bad
