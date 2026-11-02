"""Tests for the traced pipeline and single-pass rooms: ping, synthetic single-pass inboxes at two probe levels, the matched filter's floor, duplicates, the watchdog, the
stop function and the trace log. Plain script: python tests/run_trace_tests.py (about 12 minutes). PASS/FAIL with raw numbers; exit code 1 if any FAIL."""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from earnest import analyze, mixcurve, ping, probe, suite  # noqa: E402
from earnest.io import FS  # noqa: E402
from earnest.pipeline import ingest  # noqa: E402
from earnest.trace import HopFail, Trace  # noqa: E402
from run_tests import RESULTS, check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MIXES = (100, 80, 60, 40, 20)


def lite_manifest(td):
    _, man = suite.build("lite")
    p = Path(td) / "lite_manifest.json"
    p.write_text(json.dumps(man), encoding="utf-8")
    return p


def build_inbox(folder, gain_db, rooms, clip):
    """dry.flac + `<room><mix>.flac` files, the probe at `gain_db` relative to the generated one, crossfade effect over a known reverb per room."""
    folder.mkdir(parents=True, exist_ok=True)
    g = 10 ** (gain_db / 20.0)
    ping.write_flac(folder / "dry.flac", clip * g)
    truth = {}
    for name, (rt, seed) in rooms.items():
        irs = ping.reverb_irs(rt=rt, seed=seed)
        for m in MIXES:
            ping.write_flac(folder / ("%s%d.flac" % (name, m)), ping.crossfade(clip, irs, m / 100.0) * g)
            truth[(name, m)] = ping.truth(irs, m / 100.0)
    return truth


def test_single_pass(td):
    clip, _ = suite.build("lite")
    mp = lite_manifest(td)
    rooms = {"rooma": (1.2, 7), "roomb": (0.6, 11)}
    for tag, gain in (("v1 level (-18 dBFS probe)", 0.0), ("v2_loud level (+15 dB, -3 dBFS probe)", 15.0)):
        folder = td / ("in_%d" % int(gain))
        truth = build_inbox(folder, gain, rooms, clip)
        t0 = time.time()
        results, plan, out_root = analyze.process_folder(folder, manifest_path=str(mp), out_root=td / ("out_%d" % int(gain)), quiet=True)
        secs = time.time() - t0
        errs, worst = [], 0.0
        ok_rooms = len(results) == 2 and all(r["code"] == 0 for r in results)
        for r in results:
            d = r["data"]
            by_label = {s["label"]: s for s in d["steps"] if s.get("status") == "ok"}
            for m in MIXES:
                got = mixcurve.metrics(by_label[m]["room"])
                lv, drr = truth[(r["room"], m)]
                e = (round(got["tail_level_db"] - lv, 2), round(got["drr_db"] - drr, 2))
                errs.append((r["room"], m) + e)
                worst = max(worst, abs(e[0]), abs(e[1]))
        cal = results[0]["data"]["calibration"]
        n_files = sum(len(r["data"]["files"]) for r in results)
        check("single-pass inbox, %s: 2 rooms x 5 Mix levels + dry; tail level and DRR within 1 dB of the known crossfade" % tag,
              ok_rooms and worst <= 1.0 and abs(cal["G_db"] - gain) <= 0.3,
              "rooms %s; G = %.3f dB (true %.1f); worst error %.2f dB; (room, Mix, tail dB err, DRR dB err) %s; files listed %d (dry counted once per room); %.0f s" % (
                  [r["room"] for r in results], cal["G_db"], gain, worst, errs, n_files, secs))
        d0 = results[0]["data"]
        check("single-pass inbox %s: summary lists every file with role, peak, floor and matched-filter scores; Mix 0 step comes from the dry file" % tag,
              all("peak_dbfs" in f and f.get("match") for f in d0["files"]) and any(s["label"] == 0 and s["status"] == "ok" for s in d0["steps"]) and len(d0["files"]) == 6,
              "files %s" % [(f["file"], f["role"], f["status"]) for f in d0["files"]])


def test_low_level(td):
    clip, man = suite.build("lite")
    dry = suite.dry_signal(man)
    rows = []
    for level in (-100, -110, -120, -130, -140, -150, -160, -170, -180):
        for dith in (True, False):
            x = clip * 10 ** ((level + 18) / 20.0)
            p = td / ("low_%d_%s.flac" % (-level, "d" if dith else "n"))
            if dith:
                ping.write_flac(p, x)
            else:
                import soundfile as sf
                k = np.rint(x * 2 ** 23).astype(np.int32) << 8
                sf.write(str(p), k, FS, subtype="PCM_24", format="FLAC")
            tr = Trace(p.name, log=False)
            info = {}
            res = "all hops OK"
            try:
                ingest(p, man, dry, [None], tr, info)
            except HopFail as e:
                res = "FAIL at %s: %s" % (e.hop, e.reason[:90])
            mt = next((h for h in tr.hops if h["hop"] == "MATCH"), None)
            best = max([s["peak_to_noise_db"] for s in info.get("match", [])] or [0])
            rows.append((level, dith, tr.status, round(best, 1), info.get("probe_level_dbfs"), res))
    lines = ["%d dBFS peak, %s: %s, best match %.1f dB, estimated probe %s dBFS | %s" % (l, "dithered" if d else "no dither", st, b, pl, r) for l, d, st, b, pl, r in rows]
    found_d = [l for l, d, st, b, pl, r in rows if d and st in ("OK", "WARN") and "FAIL" not in r]
    found_n = [l for l, d, st, b, pl, r in rows if not d and st in ("OK", "WARN") and "FAIL" not in r]
    r130 = next(x for x in rows if x[0] == -130 and x[1])
    check("matched filter finds a -130 dBFS probe in a dithered 24-bit file (below the 24-bit step, -138.5 dBFS is the step; peak 8 dB above it)", r130[2] in ("OK", "WARN") and "FAIL" not in r130[5] and abs((r130[4] or -999) + 130) <= 3,
          "result %s, best match %.1f dB, estimated probe level %s dBFS" % (r130[2], r130[3], r130[4]))
    check("matched filter floor reported (information): lowest level at which the probe is still found", len(found_d) > 0,
          "dithered: found down to %s dBFS, not found below; undithered: found down to %s dBFS | %s" % (min(found_d) if found_d else None, min(found_n) if found_n else None, " || ".join(lines)))
    # noise only: +-1 LSB of 24-bit
    rng = np.random.default_rng(5)
    import soundfile as sf
    noise = (rng.integers(-1, 2, size=(len(clip), 2)).astype(np.int32) << 8)
    p = td / "lsb_noise.flac"
    sf.write(str(p), noise, FS, subtype="PCM_24", format="FLAC")
    tr = Trace(p.name, log=False)
    info = {}
    try:
        ingest(p, man, dry, [None], tr, info)
    except HopFail as e:
        pass
    mt = next((h for h in tr.hops if h["hop"] == "MATCH"), None)
    check("a file holding only +-1 LSB noise: MATCH fails with the 'no probe found' line", mt is not None and mt["status"] == "FAIL" and mt["msg"].startswith("no probe found"), mt["msg"] if mt else [h["hop"] for h in tr.hops])


def test_duplicates(td):
    clip, _ = suite.build("lite")
    mp = lite_manifest(td)
    f = td / "in_dup"
    f.mkdir()
    ping.write_flac(f / "dry.flac", clip)
    ping.write_flac(f / "rooma100.flac", ping.crossfade(clip, ping.reverb_irs(), 1.0))
    import shutil
    shutil.copy(f / "rooma100.flac", f / "rooma100_copy.flac")
    results, plan, out_root = analyze.process_folder(f, manifest_path=str(mp), out_root=td / "out_dup", quiet=True)
    md = td / "dup_summary.md"
    analyze.all_rooms_report(results, md, "dup test", plan)
    txt = md.read_text(encoding="utf-8")
    names = [x.get("file") for r in results for x in r["data"]["files"]]
    check("two identical files: the second is flagged DUPLICATE and skipped, the first is analysed", len(plan["duplicates"]) == 1 and plan["duplicates"][0]["file"] == "rooma100_copy.flac"
          and "DUPLICATE: rooma100_copy.flac" in txt and "rooma100.flac" in names and "rooma100_copy.flac" not in names, "duplicates %s; analysed files %s" % (plan["duplicates"], names))


def test_stop_and_watchdog(td):
    clip, _ = suite.build("lite")
    mp = lite_manifest(td)
    f = td / "in_stop"
    f.mkdir()
    ping.write_flac(f / "bad.flac", np.random.default_rng(1).standard_normal(clip.shape) * 10 ** (-60 / 20))
    ping.write_flac(f / "good100.flac", ping.crossfade(clip, ping.reverb_irs(), 1.0))
    r1, _, _ = analyze.process_folder(f, manifest_path=str(mp), out_root=td / "o1", quiet=True)
    r2, _, _ = analyze.process_folder(f, manifest_path=str(mp), out_root=td / "o2", quiet=True, stop_on_fail=True)
    bad = next(r for r in r1 if r["room"] == "bad")
    fb = next(x for x in bad["data"]["files"] if x["file"] == "bad.flac")
    check("a failed hop stops that file only: the next room is still processed; the failing file keeps its format, peaks and match scores in the summary",
          len(r1) == 2 and bad["code"] != 0 and fb.get("failed_hop") == "MATCH" and "peak_dbfs" in fb and fb.get("match") and any(r["room"] == "good" and r["code"] == 0 for r in r1),
          "rooms %s; bad file failed at %s: %s; kept peaks %s and %d match scores" % ([(r["room"], r["code"]) for r in r1], fb.get("failed_hop"), fb.get("reason", "")[:120], fb.get("peak_dbfs"), len(fb.get("match", []))))
    check("--stop-on-fail aborts the whole batch at the first failure", len(r2) == 1 and r2[0]["room"] == "bad", "rooms processed with --stop-on-fail: %s" % [r["room"] for r in r2])
    code = ("import sys,time; sys.path.insert(0, r'%s')\nfrom earnest.trace import Trace\nt = Trace('wd', watchdog_s=1.0, log=False)\n"
            "with t.hop('SLOW') as h:\n    time.sleep(6)\n" % str(ROOT))
    t0 = time.time()
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    check("watchdog: a hop over the limit is a FAIL 'stuck at hop SLOW' and the process exits 3 with the trace printed", p.returncode == 3 and "stuck at hop SLOW" in p.stdout,
          "exit %d after %.1f s (limit 1 s, hop would have slept 6 s); stdout %s" % (p.returncode, time.time() - t0, p.stdout.strip()[:200]))
    # trace log
    log = td / "trace_log.csv"
    os.environ["EARNEST_TRACE_LOG"] = str(log)
    t = Trace("logtest")
    with t.hop("FILE") as h:
        h.ok("fine", a=1)
    t.finish(td / "tl", quiet=True)
    t2 = Trace("logtest2")
    t2.add("READ", "FAIL", "boom")
    t2.finish(td / "tl2", quiet=True)
    del os.environ["EARNEST_TRACE_LOG"]
    rows = list(csv.reader(open(log, encoding="utf-8")))
    check("data\\trace_log.csv: append-only rows (header, then one row per hop per file), trace.txt and trace.json saved", rows[0][:4] == ["timestamp", "file", "hop", "status"] and len(rows) == 3
          and (td / "tl" / "trace.txt").exists() and (td / "tl2" / "trace.json").exists(), "rows %s" % [r[1:4] for r in rows[1:]])


def test_ping():
    t0 = time.time()
    code = ping.run()
    txt = (ping.PING_DIR / "ping.txt").read_text(encoding="utf-8")
    verdict = [ln for ln in txt.splitlines() if ln.startswith("PING")]
    check("ping: self-test passes (clean, effect x2, 16-bit, channel lost, noise only), under 2 minutes", code == 0 and verdict and verdict[0].startswith("PING OK") and time.time() - t0 < 120,
          "%s; %.0f s" % (verdict, time.time() - t0))


def main():
    t0 = time.time()
    os.environ["EARNEST_TRACE_LOG"] = str(Path(tempfile.gettempdir()) / "earnest_test_trace_log.csv")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        test_stop_and_watchdog(td)
        test_duplicates(td)
        test_low_level(td)
        test_single_pass(td)
    os.environ.pop("EARNEST_TRACE_LOG", None)
    test_ping()
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n%d checks, %d failed, %.0f s" % (len(RESULTS), n_fail, time.time() - t0))
    Path(__file__).with_name("last_trace_results.txt").write_text("\n".join("%s  %s  %s" % ("PASS" if ok else "FAIL", n, d) for n, ok, d in RESULTS) + "\n", encoding="utf-8")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
