"""The traced pipeline: one file in, hops out (FILE, READ, CONVERT, MATCH, SPLIT, then LEVEL, ROOM, WRITE per pass), grouped into rooms.

Two layouts, told apart by the file's length (not by its name):
  * single pass (one copy of the probe, about 190 s): `<room><digits>` is room <room> at Mix <digits>; a file whose name starts with `dry` is the dry reference (the probe
    exported without the effect). One dry file serves every room in the inbox: its gain G (200 Hz-8 kHz, sweep_L) is divided out of every room pass and it becomes the Mix 0 step.
  * several passes in one file (an export of N copies): labels come from --labels, the last copy (Mix 0) is the dry reference.
A hop that FAILS stops that file only; what was learned before the failure stays in the summary."""
from __future__ import annotations

import re
import time
from pathlib import Path

import numpy as np

from . import formula, mixcurve, plots, probe, report, room, stage, suite
from .dsp import db
from .io import FS, new_run, save_json
from .trace import HopFail, Trace

DEFAULT_LABELS = [100, 80, 60, 30, 0]
MIN_RANGE_DB = 45.0
NEEDS_2CH = 2
BIT_FLOOR = {16: -90.3, 24: -138.5}


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", s) or "room"


def room_from_filename(path) -> str:
    return re.split(r"[_\-]", Path(path).stem, maxsplit=1)[0]


def classify(path) -> dict:
    """Role from the file name: dry reference, single pass `<room><digits>` or other (room = text before the first _ or -)."""
    stem = Path(path).stem
    if stem.lower().startswith("dry"):
        return {"role": "dry", "room": None, "mix": 0}
    m = re.fullmatch(r"([A-Za-z][A-Za-z ]*?)[ _\-]?(\d{1,3})", stem)
    if m:
        return {"role": "single", "room": m.group(1).strip(), "mix": int(m.group(2))}
    return {"role": "other", "room": room_from_filename(path), "mix": None}


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


# ----------------------------------------------------------------------------- hops 1-5

def ingest(path, manifest, dry, labels, tr: Trace, info: dict):
    """FILE, READ, CONVERT, MATCH, SPLIT for one file. Fills `info` as it goes (so a failure keeps everything learned so far). Returns (src, starts, split_info, n_expected)."""
    path = Path(path)
    info["file"] = path.name
    with tr.hop("FILE") as h:
        try:
            src = suite.Source(path)
        except Exception as e:
            h.fail("cannot open %s: %s" % (path.name, e), "a file that is not audio, an unsupported codec, or a damaged download")
        i = src.info
        info.update({"container": i.format, "subtype": i.subtype, "samplerate": i.samplerate, "channels": i.channels, "bits": probe.BITS.get(i.subtype),
                     "seconds": round(i.frames / i.samplerate, 2), "size": path.stat().st_size})
        exp = "expected 2 ch, 44.1 or 48 kHz, 16-32 bit"
        msg = "%s %s, %d ch, %d Hz, %s, %.1f s, %.1f MB (%s)" % (i.format, i.subtype, i.channels, i.samplerate, "%s-bit" % probe.BITS.get(i.subtype, "?"), i.frames / i.samplerate,
                                                               path.stat().st_size / 1e6, exp)
        if i.channels != NEEDS_2CH:
            h.fail("%d channel(s) in the file, 2 needed" % i.channels, "a mono or multichannel export; export as stereo", container=i.format)
        if i.frames < int(5 * i.samplerate):
            h.fail("only %.1f s of audio" % (i.frames / i.samplerate), "an export that stopped early or the wrong region", frames=i.frames)
        if i.samplerate not in (44100, 48000):
            h.warn(msg + ": unusual sample rate, will be resampled")
        else:
            h.ok(msg)
    with tr.hop("READ") as h:
        st = probe.read_stats(path)
        info.update({"peak_dbfs": st["peak_dbfs"], "rms_dbfs": st["rms_dbfs"], "floor_dbfs": st["floor_dbfs"], "lr_corr": st["lr_corr"], "clipped": st["clipped"], "dc": st["dc"]})
        line = "per channel L/R: frames %s, peak %s dBFS, RMS %s dBFS, DC %s, clipped %s, floor %s dBFS (head 2 s + end 1 s), L/R corr %s" % (
            "/".join(str(f) for f in st["frames"]), "/".join("%.2f" % p for p in st["peak_dbfs"]), "/".join("%.2f" % r for r in st["rms_dbfs"]),
            "/".join("%.1e" % d for d in st["dc"]), "/".join(str(c) for c in st["clipped"]), "/".join("%.1f" % f for f in st["floor_dbfs"]),
            "n/a" if st["lr_corr"] is None else "%.3f" % st["lr_corr"])
        lsb = db(2.0 ** -((info.get("bits") or 24) - 1))             # one step of the file's bit depth
        info["quiet_channels"] = []
        for c, nm in enumerate(("L", "R")):
            if st["peak_dbfs"][c] <= -900:
                h.fail("channel %s is all zeros (%s)" % (nm, line), "channel lost: a muted track, a mono or one-sided export, or a routing problem before the export", peak=st["peak_dbfs"])
            if st["peak_dbfs"][c] <= lsb + 12.0:                       # nothing above 4 steps of the format: only dither / quantisation noise (the probe could still be below it)
                info["quiet_channels"].append(c)
        warn = []
        for c in info["quiet_channels"]:
            warn.append("channel %s carries only quantisation-level noise (peak %.2f dBFS, 4 steps of this %s-bit file = %.1f dBFS): the MATCH hop decides whether the probe is below it" % (
                "LR"[c], st["peak_dbfs"][c], info.get("bits"), lsb + 12.0))
        if max(st["peak_dbfs"]) > -0.1:
            warn.append("peak above -0.1 dBFS (clipping risk, the master may have peaked)")
        if abs(st["peak_dbfs"][0] - st["peak_dbfs"][1]) > 40:
            warn.append("one channel is more than 40 dB below the other")
        if sum(st["clipped"]) > 0:
            warn.append("%d sample(s) at full scale" % sum(st["clipped"]))
        (h.warn if warn else h.ok)(line + ("; " + "; ".join(warn) if warn else ""))
    with tr.hop("CONVERT") as h:
        if src.fs_in == FS:
            h.ok("no resampling needed (%d Hz); frames in %d, out %d" % (src.fs_in, src.n_in, src.n))
        else:
            rc = probe.resample_check(src, info["peak_dbfs"])
            worst = max([abs(d) for d in rc["peak_diff_db"] if d is not None] or [0])
            msg = "resampled %d Hz to %d Hz: frames in %d, out %d; per-channel peak after %s dBFS (change %s dB)" % (src.fs_in, FS, rc["frames_in"], rc["frames_out"],
                                                                                                                  "/".join("%.2f" % p for p in rc["peak_after_dbfs"]),
                                                                                                                  "/".join("%+.2f" % d for d in rc["peak_diff_db"]))
            (h.warn if worst > 0.1 else h.ok)(msg + ("; peaks differ by more than 0.1 dB" if worst > 0.1 else ""))
    with tr.hop("MATCH") as h:
        mt = probe.match_file(src, dry, manifest)
        info["match"] = mt["scores"]
        info["match_threshold_db"] = mt["threshold_db"]
        sc = mt["scores"]
        txt = "; ".join("%s ch%s %.1f dB @ %.1f ms%s" % (s["sweep"], "LR"[s["channel"]], s["peak_to_noise_db"], s["copy_start_ms"], "" if s["detected"] else " (below threshold)") for s in sc)
        best = max(s["peak_to_noise_db"] for s in sc)
        lv = max(s["probe_level_dbfs"] for s in sc)
        info["probe_level_dbfs"] = lv
        if not any(s["detected"] for s in sc):
            h.fail("no probe found: peak %.2f dBFS, noise floor %.1f dBFS, best match %.1f dB (needs at least %.1f dB)" % (max(info["peak_dbfs"]), max(info["floor_dbfs"]), best, mt["threshold_db"]),
                   "this file does not contain the probe (wrong file or region), or the probe is below the noise", best_match_db=best)
        lost = [("L", "R")[c] for c in range(2) if not any(s["detected"] for s in sc if s["channel"] == c)]
        note = " threshold %.1f dB (Gaussian-noise maximum over %d lags, +25 %%); estimated probe level %.1f dBFS" % (mt["threshold_db"], mt["lags"], lv)
        bits = info.get("bits")
        if bits in BIT_FLOOR and lv < BIT_FLOOR[bits]:
            note += "; recovered %.1f dB below the %d-bit step (%.1f dBFS)" % (BIT_FLOOR[bits] - lv, bits, BIT_FLOOR[bits])
        quiet_lost = [("L", "R")[c] for c in info.get("quiet_channels", []) if ("L", "R")[c] in lost]
        if quiet_lost:
            h.fail("channel %s lost: it carries only noise at the format's step and the probe is not in it (%s)" % ("/".join(quiet_lost), txt),
                   "a muted track or a one-sided export (this file has dither noise, so the channel is not exactly zero)", best_match_db=best)
        if lost:
            h.warn("channel(s) %s never match either sweep: %s;%s" % ("/".join(lost), txt, note))
        else:
            h.ok(txt + ";" + note)
    with tr.hop("SPLIT") as h:
        n = 1 if info["seconds"] < 1.6 * manifest["total_s"] else len(labels)
        pos, sinfo = suite.find_copies(src, dry, manifest, n)
        if len(pos) < n:
            h.fail("found %d of %d expected copies of the probe (%s file: %s)" % (len(pos), n, "single-pass" if n == 1 else "multi-pass", [round(p / FS, 2) for p in pos]),
                   "the file holds fewer passes than expected, or a pass is silent and could not be placed", found=len(pos))
        info["copies"] = n
        msg = "%d cop%s at %s s (clip start)%s" % (n, "y" if n == 1 else "ies", [round(p / FS, 3) for p in pos], "; %d pass(es) inferred (silent)" % len(sinfo["inferred"]) if sinfo["inferred"] else "")
        (h.warn if sinfo["inferred"] else h.ok)(msg + ("; single pass" if n == 1 else "; multi-pass file, labels %s" % labels))
    return src, pos, sinfo, n


# ----------------------------------------------------------------------------- hops 6-8, per pass

def run_pass(tr: Trace, src, start: int, inferred: bool, manifest, dry, G: float, cal_ok: bool, label, folder: Path, room_name: str, index: int, plot_png: bool = True) -> dict:
    """LEVEL, ROOM, WRITE for one pass. Returns the row used by the summary (status ok / EMPTY)."""
    row = {"index": index, "label": label, "start_s": round(start / FS, 3), "empty_blocks": [], "inferred": inferred}
    blocks = suite.cut_blocks(src, manifest, start)
    stats = {n: suite.block_stats(x) for n, x in blocks.items()}
    row["empty_blocks"] = [n for n, (pk, _) in stats.items() if pk < suite.EMPTY_DB]
    row["sweep_L_peak_dbfs"] = stats["sweep_L"][0]
    row["short"] = bool(any(len(x) < b["length_samples"] for x, b in zip(blocks.values(), manifest["blocks"])))
    sil = np.concatenate([src.read(start, start + int(manifest.get("head_s", 2.0) * FS)),
                          src.read(start + manifest["total_samples"] - int(manifest.get("end_s", 1.0) * FS), start + manifest["total_samples"])])
    rms = float(np.sqrt(np.mean(sil ** 2))) if len(sil) else 0.0
    floor = max(db(rms), -140.0) if rms > 0 else -140.0
    peak_sw = max(stats["sweep_L"][0], stats["sweep_R"][0])
    row.update({"noise_floor_dbfs": round(floor, 1), "digital_silence": bool(rms == 0.0), "signal_peak_dbfs": peak_sw, "usable_range_db": round(peak_sw - floor, 1),
                "low_range": bool(peak_sw - floor < MIN_RANGE_DB)})
    with tr.hop("LEVEL") as h:
        if inferred or "sweep_L" in row["empty_blocks"] or "sweep_R" in row["empty_blocks"]:
            row["status"] = "EMPTY"
            h.fail("this pass is empty: sweep blocks peak at %s dBFS (needs more than %.0f dBFS)" % (stats["sweep_L"][0], suite.EMPTY_DB),
                   "a silent track, a muted pass or the wrong region of the export", sweep_peak=stats["sweep_L"][0])
        if cal_ok:
            h.ok("calibration gain G = %.2f dB divided out; sweep peak %.1f dBFS before, usable range %.1f dB over a floor of %.1f dBFS%s" % (
                db(G), peak_sw, row["usable_range_db"], floor, " (digital silence)" if row["digital_silence"] else ""))
        else:
            h.warn("no calibration (levels as exported); sweep peak %.1f dBFS, floor %.1f dBFS" % (peak_sw, floor))
    for n in blocks:
        blocks[n] = blocks[n] / G
    with tr.hop("ROOM") as h:
        sets, clicks, dry_w = _sets_from_blocks(dry, manifest, blocks)
        res, plot = room.run_room_sets(sets, clicks, [])
        sg = stage.compute(dry_w, blocks)
        row.update({"status": "ok", "room": res, "stage": sg})
        dm = res["direct_matrix"]
        L0 = res["inputs"][0]
        e_ir = float(sum(np.sum(hh ** 2) for hh in plot["irs"].values()))
        pk = {s: ["%.3f" % v for v in dm[s]] for s in dm}
        lv = mixcurve.metrics(res)
        msg = "direct matrix (out L/R per input) %s, IR energy %.1f dB, latency %.1f ms, tail %s (%.1f dB re direct), early taps %s (%d found)%s" % (
            pk, db(np.sqrt(e_ir)), res["latency_ms"], "absent" if lv["no_tail"] else "present", lv["tail_level_db"] if lv["tail_level_db"] is not None else float("nan"),
            res["early_taps"]["status"], res["early_taps"]["count_found"], "" if res["ir_looks_valid"] else "; sweep does not deconvolve cleanly (IR decay %s dB)" % res["ir_decay_db"])
        if not res["ir_looks_valid"]:
            h.warn(msg)
        else:
            h.ok(msg)
        row["low_range_note"] = row["low_range"]
    with tr.hop("WRITE") as h:
        folder.mkdir(parents=True, exist_ok=True)
        res2 = dict(res)
        res2["label"] = label
        save_json(folder / "room.json", res2)
        save_json(folder / "formula.json", formula.build(res, "%s pass %d Mix %s" % (room_name, index, label)))
        report.room_report(res, folder / "report.md", "%s, pass %d, Mix %s" % (room_name, index, label))
        names = ["room.json", "formula.json", "report.md"]
        if plot_png:
            plots.room_png(folder / "room.png", res, plot, "earnest room: %s pass %d Mix %s" % (room_name, index, label))
            names.append("room.png")
        h.ok("wrote %s to %s" % (", ".join(names), folder))
    return row


# ----------------------------------------------------------------------------- one room

def process_room(room_name: str, members: list, dry_member=None, manifest_path=None, labels=None, out=None, quiet: bool = False, stop_on_fail: bool = False, plot_png: bool = True,
                 dry_cache=None, probe_path=None):
    """members: [{'path', 'label'}] single-pass files (label = Mix) or a multi-pass file (label None; passes labelled by `labels`). dry_member: {'path'} of the dry file.
    Returns (exit_code, summary_md_path, summary dict)."""
    from . import analyze as _an
    t0 = time.time()
    labels = list(labels) if labels else list(DEFAULT_LABELS)
    manifest = suite.load_manifest(manifest_path or suite.PROBE_JSON)
    dry = suite.dry_signal(manifest, probe_path)
    out = Path(out) if out else new_run("analyze-" + slug(room_name))
    out.mkdir(parents=True, exist_ok=True)
    summary = {"room": room_name, "labels": labels, "manifest": manifest.get("name"), "problems": [], "warnings": [], "steps": [], "files": [], "version": 2}
    problems = summary["problems"]
    traces = []
    cal = {"G": 1.0, "G_db": 0.0, "ok": False, "warnings": [], "checks": {}}
    rows = []
    stop = False

    def file_trace(path):
        tr = Trace(Path(path).name)
        tr.out_dir = out / "trace" / slug(Path(path).stem)
        traces.append(tr)
        return tr

    # --- the dry reference (analysed once per folder when a cache is given: every room uses the same dry file)
    if dry_member:
        key = str(dry_member["path"])
        if dry_cache is not None and key in dry_cache:
            c = dry_cache[key]
            cal, row, info, tr0 = c["cal"], c["row"], dict(c["info"]), c["trace"]
            tr = Trace(Path(dry_member["path"]).name, log=False)
            tr.hops = list(tr0.hops)
            tr.failed = tr0.failed
            tr.out_dir = out / "trace" / slug(Path(dry_member["path"]).stem)
            traces.append(tr)
            info["_tr"] = tr
            summary["files"].append(info)
            if row is not None:
                rows.append(row)
            for w in cal["warnings"]:
                problems.append("dry reference: " + w)
            if info.get("status") == "FAIL":
                problems.append("%s: hop %s failed: %s" % (Path(dry_member["path"]).name, info.get("failed_hop"), info.get("reason")))
        else:
            tr = file_trace(dry_member["path"])
            info = {"role": "dry reference (Mix 0)", "label": 0, "_tr": tr}
            summary["files"].append(info)
            row = None
            try:
                src, pos, sinfo, n = ingest(dry_member["path"], manifest, dry, labels, tr, info)
                start = pos[-1] if n > 1 else pos[0]
                with tr.hop("LEVEL") as h:
                    raw = suite.cut_blocks(src, manifest, start, ("sweep_L", "clicks_mono"))
                    cal = suite.calibrate(lambda nm: raw[nm], dry, manifest)
                    if cal["ok"]:
                        h.ok("dry reference: G = %.3f dB (sweep_L over 200 Hz-8 kHz against the generated block); checks %s" % (cal["G_db"], cal["checks"]))
                    else:
                        h.warn("; ".join(cal["warnings"]))
                for w in cal["warnings"]:
                    problems.append("dry reference: " + w)
                G = cal["G"] if cal["ok"] else 1.0
                row = run_pass(tr, src, start, False, manifest, dry, G, cal["ok"], 0, out / "step_mix0", room_name, 0, plot_png)
                rows.append(row)
                info["status"] = tr.status
            except HopFail as e:
                info["status"] = "FAIL"
                info["failed_hop"] = e.hop
                info["reason"] = e.reason
                problems.append("%s: hop %s failed: %s" % (Path(dry_member["path"]).name, e.hop, e.reason))
                stop = stop_on_fail
            if dry_cache is not None:
                snap = {k: v for k, v in info.items() if k != "_tr"}
                dry_cache[key] = {"cal": cal, "row": row, "info": snap, "trace": tr}
    else:
        summary["warnings"].append("no dry reference file: levels are not calibrated" + ("" if not members or members[0].get("label") is not None else " (multi-pass file: its last pass is used when it is Mix 0)"))
    G = cal["G"] if cal["ok"] else 1.0
    # --- the room files
    for mbr in members:
        if stop:
            break
        tr = file_trace(mbr["path"])
        info = {"role": ("%s Mix %s" % (room_name, mbr["label"])) if mbr.get("label") is not None else "%s (multi-pass)" % room_name, "label": mbr.get("label"), "_tr": tr}
        summary["files"].append(info)
        try:
            src, pos, sinfo, n = ingest(mbr["path"], manifest, dry, labels, tr, info)
            if n > 1 and not dry_member and labels[-1] in (0, "0"):       # multi-pass: calibrate from the last pass
                with tr.hop("LEVEL") as h:
                    raw = suite.cut_blocks(src, manifest, pos[-1], ("sweep_L", "clicks_mono"))
                    cal = suite.calibrate(lambda nm: raw[nm], dry, manifest)
                    (h.ok if cal["ok"] else h.warn)(("Mix 0 pass: G = %.3f dB; checks %s" % (cal["G_db"], cal["checks"])) if cal["ok"] else "; ".join(cal["warnings"]))
                for w in cal["warnings"]:
                    problems.append("Mix 0 pass: " + w)
                G = cal["G"] if cal["ok"] else 1.0
            for i, p in enumerate(pos):
                lab = labels[i] if n > 1 else mbr.get("label")
                sub = tr if n == 1 else Trace("%s pass %d" % (Path(mbr["path"]).name, i + 1))
                if n > 1:
                    sub.out_dir = out / "trace" / ("%s_pass%d" % (slug(Path(mbr["path"]).stem), i + 1))
                    traces.append(sub)
                folder = out / ("step_mix%s" % lab if n == 1 else "step%d_mix%s" % (i + 1, lab))
                try:
                    row = run_pass(sub, src, p, p in sinfo["inferred"], manifest, dry, G, cal["ok"], lab, folder, room_name, len(rows) + 1, plot_png)
                    rows.append(row)
                except HopFail as e:
                    rows.append({"index": len(rows) + 1, "label": lab, "start_s": round(p / FS, 3), "status": "EMPTY" if e.hop == "LEVEL" else "FAIL", "empty_blocks": [], "failed_hop": e.hop})
                    problems.append("%s pass %d (Mix %s): hop %s failed: %s" % (Path(mbr["path"]).name, i + 1, lab, e.hop, e.reason + (" [EMPTY]" if e.hop == "LEVEL" else "")))
                    if stop_on_fail:
                        stop = True
                        break
            info["status"] = tr.status
        except HopFail as e:
            info["status"] = "FAIL"
            info["failed_hop"] = e.hop
            info["reason"] = e.reason
            info["cause"] = e.cause
            problems.append("%s: hop %s failed: %s (most likely: %s)" % (Path(mbr["path"]).name, e.hop, e.reason, e.cause))
            if stop_on_fail:
                stop = True
    # --- keep what each file's trace learned (so a failed hop never leaves blanks)
    for info in summary["files"]:
        t = info.pop("_tr")
        info["hops"] = [{"hop": h["hop"], "status": h["status"], "msg": h["msg"]} for h in t.hops]
    summary["steps"] = rows
    ok_rows = [r for r in rows if r.get("status") == "ok"]
    if any(r.get("status") == "EMPTY" for r in rows):
        for r in rows:
            if r.get("status") == "EMPTY":
                problems.append("pass %s (Mix %s) is EMPTY" % (r.get("index"), r.get("label")))
    summary["calibration"] = cal
    for r in ok_rows:
        if r.get("low_range"):
            summary["warnings"].append("Mix %s: usable range only %.1f dB (noise floor %.1f dBFS): RT60 fits are unreliable" % (r["label"], r["usable_range_db"], r["noise_floor_dbfs"]))
    curve = None
    steps_for_curve = sorted([(r["label"], r["room"]) for r in ok_rows if r.get("label") is not None], key=lambda t: -t[0] if isinstance(t[0], (int, float)) else 0)
    if len(steps_for_curve) >= 2:
        curve, _ = mixcurve.write(steps_for_curve, out, room_name)
        summary["mixcurve"] = {"labels": curve["labels"], "metrics": curve["metrics"], "flags": curve["flags"], "excluded_no_tail": curve.get("excluded_no_tail", [])}
    s0 = next((r for r in ok_rows if r["label"] in (0, "0")), None)
    if s0:
        m = s0["room"]["direct_matrix"]
        L0 = s0["room"]["inputs"][0]
        lvl = s0["room"]["tail_bands"][3]["level_db"]
        ident = abs(m[L0][0] - 1) < 0.1 and abs(m[L0][1]) < 0.1 and lvl < -40
        summary["mix0_sanity"] = {"identity": bool(ident), "M_LL": round(m[L0][0], 4), "M_LR": round(m[L0][1], 4), "tail_level_db_1k": lvl}
    summary["seconds"] = round(time.time() - t0, 1)
    summary["peak_memory_mb"] = round(_an.peak_memory_mb(), 0)
    # traces: write each, print the combined table at the end
    all_tr = Trace("room " + room_name, log=False)
    for tr in traces:
        all_tr.extend(tr, prefix="[%s] " % tr.label)
        tr.finish(tr.out_dir, quiet=True)
    all_tr.finish(out, quiet=True)
    if not quiet:
        for tr in traces:
            print(tr.render())
            print()
    bad = bool(problems) or any(f.get("status") == "FAIL" for f in summary["files"]) or any(r.get("status") != "ok" for r in rows)
    summary["exit_code"] = 2 if bad else 0
    lines = _an.summary_lines(summary)
    p = out / "summary.md"
    report.finish(lines if len(lines) <= _an.SUMMARY_MAX else lines[: _an.SUMMARY_MAX - 1] + ["(cut at %d lines; summary.json has everything)" % _an.SUMMARY_MAX], p)
    save_json(out / "summary.json", summary)
    if not quiet:
        print("summary: %s" % p)
        for pr in problems:
            print("PROBLEM: " + pr)
    return summary["exit_code"], p, summary
