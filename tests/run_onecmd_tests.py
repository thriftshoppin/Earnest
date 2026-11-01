"""Tests for the one-command build: EDT convention, dry-step n/a and flags, noise-floor range, clip-start column, every CLI command run for real, and `run` (inbox, latest, skip logic).
Plain script: python tests/run_onecmd_tests.py (about 8 minutes). Prints PASS/FAIL with raw numbers; exit code 1 if any FAIL."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth_export as se  # noqa: E402
from earnest import dsp, mixcurve, room, suite  # noqa: E402
from earnest.io import FS, write_wav  # noqa: E402
from run_tests import RESULTS, check, synth_system, run_sweeps  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LABELS = [100, 80, 60, 30, 0]
MIXES = (1.0, 0.8, 0.6, 0.3, 0.0)


def cli(args, cwd=ROOT):
    t0 = time.time()
    p = subprocess.run([sys.executable, "-m", "earnest"] + [str(a) for a in args], capture_output=True, text=True, cwd=str(cwd))
    return p, time.time() - t0


def lite_files(td):
    x, man = suite.build("lite")
    mp, dp = Path(td) / "lite_manifest.json", Path(td) / "lite_dry.wav"
    mp.write_text(json.dumps(man), encoding="utf-8")
    write_wav(dp, x)
    return mp, dp


def test_edt():
    ok, rows = True, []
    for rt in (0.3, 1.2, 2.5):
        t = np.arange(int(5 * FS)) / FS
        e = 10 ** (-6.0 * t / rt)                       # exact exponential energy decay, no noise
        d = dsp.decay(e, FS)
        err = (d["edt"] - rt) / rt * 100
        ok = ok and abs(err) <= 0.5
        rows.append("RT60 %.1f: EDT %.4f s (%.3f %%), T20 %.4f s, T30 %.4f s" % (rt, d["edt"], err, d["t20"], d["t30"]))
    check("EDT convention: exact exponential decay, EDT = RT60 within 0.5 %", ok, "; ".join(rows))
    out, ok2 = [], True
    for rt in (0.3, 1.2, 2.5):
        irs = synth_system(rt, rho=0.3, seed=int(rt * 10) + 7, taps=[], tail_start_ms=3.5)
        res, _ = room.analyze_sweeps(run_sweeps(irs))
        edt = [b["edt_s"] for b in res["tail_bands"]]
        mean = float(np.mean(edt))
        spread = max(abs(v - rt) / rt * 100 for v in edt)
        ok2 = ok2 and abs(mean - rt) / rt <= 0.05
        out.append("RT60 %.1f: EDT per band %s, mean %.3f s (%.1f %%), worst single band %.1f %%; RT60 per band %s" % (
            rt, edt, mean, (mean - rt) / rt * 100, spread, [b["rt60_s"] for b in res["tail_bands"]]))
    check("EDT convention: noise tail with no pre-delay through the real sweep chain, mean EDT over the 7 bands within 5 % of RT60 (single bands are noisy, listed)", ok2, " | ".join(out))


def test_dry_step_and_columns(td):
    mp, dp = lite_files(td)
    wet = td / "lite_100-80-60-30-0.wav"
    se.make_export(wet, "lite", MIXES, irs=se.reverb_irs(), dither=True)
    p, secs = cli(["analyze", wet, "--room", "liteX", "--manifest", mp, "--dry", dp])
    m = re.search(r"summary: (.*summary\.md)", p.stdout)
    ok_run = p.returncode == 0 and m is not None
    check("CLI: analyze --manifest <lite manifest> --dry <lite dry wav> runs and exits 0", ok_run, "exit %d, %.0f s; stdout %s; stderr %s" % (p.returncode, secs, p.stdout.strip()[-160:], p.stderr[-200:].strip()))
    if not ok_run:
        return None
    sm = Path(m.group(1))
    txt = sm.read_text(encoding="utf-8")
    sj = json.loads(sm.with_name("summary.json").read_text(encoding="utf-8"))
    steps = [(s["label"], s["room"]) for s in sj["steps"] if s.get("status") == "ok"]
    c = mixcurve.curves(steps)
    m0 = c["metrics"][-1]
    rt_row = [ln for ln in txt.splitlines() if ln.startswith("| 0 |")]
    n_a = all(v is None for v in m0["rt60_by_band"] + m0["edt_by_band"] + m0["iacc_by_band"]) and m0["rt60_s"] is None and m0["edt_s"] is None and m0["iacc"] is None
    text_na = len(rt_row) >= 2 and all("n/a" in ln for ln in rt_row[:2])
    rt_rows = [ln for ln in txt.splitlines() if ln.startswith("| 0 |") and "n/a" in ln]
    flagged = [f["metric"] for f in c["flags"]]
    check("dry step (Mix 0): RT60/EDT/IACC are n/a everywhere (data, summary table and by-octave table) and the step is out of the flags",
          n_a and text_na and c["excluded_no_tail"] == [0] and not any(k in flagged for k in ("rt60_s", "edt_s", "iacc")),
          "Mix 0 rt60 %s edt %s iacc %s; rows starting '| 0 |' with n/a: %d; excluded %s; flags now %s; true RT60 is constant (1.2 s) across Mix 100-30" % (
              m0["rt60_s"], m0["edt_s"], m0["iacc"], len(rt_rows), c["excluded_no_tail"], flagged))
    fl = [s["noise_floor_dbfs"] for s in sj["steps"] if "noise_floor_dbfs" in s]
    import soundfile as sf
    head, _ = sf.read(str(wet), start=0, frames=int(2.5 * 44100), dtype="float64")       # independent measurement: the file's own digital-silence lead-in, read directly
    exp = 20 * np.log10(float(np.sqrt(np.mean(head ** 2))))
    theory = 20 * np.log10(0.5 / 32768.0)
    check("noise floor from the silent head/end of a dithered 16-bit file is within 3 dB of the file's own measured floor (independent read of its first 2.5 s)", all(abs(v - exp) <= 3 for v in fl) and len(fl) == 5,
          "reported %s dBFS per pass; independent RMS of the file's silent lead-in %.1f dBFS; usable range %s dB. (Textbook TPDF+rounding would be %.1f dBFS; libsndfile truncates instead of rounding, which adds a DC offset and gives the higher value. The nominal 16-bit figure -90 is %.1f dB above the measured one.)" % (
              fl, exp, [s["usable_range_db"] for s in sj["steps"] if "usable_range_db" in s], theory, -90 - exp))
    check("summary says 'clip start s' and has no 'offset ms'", "clip start s" in txt and "offset ms" not in txt.lower(), "found clip start: %s; found 'offset ms': %s" % ("clip start s" in txt, "offset ms" in txt.lower()))
    return sj, sm.parent, mp, dp, wet


def test_floor_digital_silence(td, mp, dp):
    wet = td / "lite_nodither.wav"
    se.make_export(wet, "lite", MIXES, irs=se.reverb_irs(rt=0.5, seed=3), dither=False)
    p, _ = cli(["analyze", wet, "--room", "nodither", "--manifest", mp, "--dry", dp])
    m = re.search(r"summary: (.*summary\.md)", p.stdout)
    sj = json.loads(Path(m.group(1)).with_name("summary.json").read_text(encoding="utf-8")) if m else None
    ok = sj is not None and all(s.get("digital_silence") and s["noise_floor_dbfs"] == -140.0 for s in sj["steps"] if "noise_floor_dbfs" in s)
    check("digital silence in the head/end is reported as such (-140 dBFS) and not flagged low-range", ok,
          "floors %s; low_range %s" % ([s["noise_floor_dbfs"] for s in sj["steps"]] if sj else None, [s.get("low_range") for s in sj["steps"]] if sj else None))


def test_cli_split_mixcurve_all(td, sj_dir, mp, dp, wet):
    # split, for real
    out, dry_out = td / "cli_split", td / "cli_dry"
    p, secs = cli(["split", wet, mp, out, "--repeats", "5", "--labels", "100,80,60,30,0", "--dry-out", dry_out])
    dirs = sorted(d.name for d in out.iterdir() if d.is_dir()) if out.exists() else []
    rep = (out / "report.md").read_text(encoding="utf-8") if (out / "report.md").exists() else ""
    check("CLI: split --repeats 5 --labels ... --dry-out writes step1_mix100..step5_mix0, report.md says 'clip start' and the calibration", p.returncode == 0 and dirs == ["step1_mix100", "step2_mix80", "step3_mix60", "step4_mix30", "step5_mix0"]
          and "clip start" in rep and "G = " in rep and "offset" not in rep.split("Clip start")[0].lower().replace("clip start", ""),
          "exit %d, %.0f s; folders %s; calibration line: %s; stdout %s" % (p.returncode, secs, dirs, [ln for ln in rep.splitlines() if "calibration" in ln.lower()][:1], p.stdout.strip()[-120:]))
    # mixcurve from run folders
    steps = sorted(d for d in sj_dir.iterdir() if d.is_dir() and d.name.startswith("step"))
    p, secs = cli(["mixcurve"] + steps + ["--labels", "100,80,60,30,0", "--title", "cli test"])
    mrep = re.search(r"mixcurve: (.*?) \(report", p.stdout)
    ok = p.returncode == 0 and mrep is not None and (Path(mrep.group(1)) / "report.md").exists() and (Path(mrep.group(1)) / "mixcurve.png").exists()
    check("CLI: mixcurve <5 step folders> --labels ... writes report.md and mixcurve.png", ok, "exit %d, %.0f s; stdout %s; stderr %s" % (p.returncode, secs, p.stdout.strip()[-140:], p.stderr[-200:].strip()))
    # analyze-all on a folder with two lite files (--manifest)
    folder = td / "allf"
    folder.mkdir()
    shutil.copy(wet, folder / "roomA_100-80-60-30-0.wav")
    se.make_export(folder / "roomB-100-80-60-30-0.wav", "lite", MIXES, irs=se.reverb_irs(rt=0.6, seed=11), silent=(1,))
    p, secs = cli(["analyze-all", folder, "--manifest", mp])
    m = re.search(r"all_rooms_summary: (.*all_rooms_summary\.md)", p.stdout)
    txt = Path(m.group(1)).read_text(encoding="utf-8") if m else ""
    check("CLI: analyze-all --manifest: two rooms, empty pass listed as failed, exit 1", m is not None and "roomA" in txt and "roomB" in txt and "EMPTY" in txt and p.returncode == 1,
          "exit %d, %.0f s; %d lines; stderr %s" % (p.returncode, secs, len(txt.splitlines()), p.stderr[-200:].strip()))


def test_run(td, mp):
    inbox, latest = td / "inbox", td / "latest"
    inbox.mkdir()
    se.make_export(inbox / "alpha_100-80-60-30-0.wav", "lite", MIXES, irs=se.reverb_irs(rt=1.0, seed=2), dither=True)
    se.make_export(inbox / "beta-100-80-60-30-0.wav", "lite", MIXES, irs=se.reverb_irs(rt=0.6, seed=4), silent=(2,))
    before = {f.name: (f.stat().st_size, f.stat().st_mtime_ns) for f in inbox.iterdir()}
    args = ["run", "--inbox", inbox, "--latest", latest, "--manifest", mp, "--no-open"]
    p, secs = cli(args)
    want = {"all_rooms_summary.md", "alpha_summary.md", "alpha_mixcurve.png", "alpha_room.png", "beta_summary.md", "beta_mixcurve.png", "beta_room.png"}
    have = {f.name for f in latest.iterdir()} if latest.exists() else set()
    st = json.loads((inbox / "processed.json").read_text(encoding="utf-8"))
    check("run: latest\\ has the expected files, the room with a silent pass is flagged EMPTY, exit 1, processed.json has both files",
          want <= have and "beta: EMPTY" in p.stdout and "alpha: OK" in p.stdout and p.returncode == 1 and set(st["files"]) == {"alpha_100-80-60-30-0.wav", "beta-100-80-60-30-0.wav"},
          "exit %d, %.0f s; missing files %s; lines: %s" % (p.returncode, secs, sorted(want - have), [ln.strip() for ln in p.stdout.splitlines() if ln.strip().startswith(("alpha", "beta"))]))
    p2, secs2 = cli(args)
    check("run again: both files skipped as unchanged, nothing analyzed", p2.stdout.count("skipping") == 2 and "analyzed 0, skipped 2" in p2.stdout and "analyzing" not in p2.stdout,
          "%.0f s; %s" % (secs2, p2.stdout.strip().splitlines()[-1]))
    p3, secs3 = cli(args + ["--force"])
    check("run --force: both files redone", p3.stdout.count("analyzing") == 2 and "analyzed 2, skipped 0" in p3.stdout, "%.0f s; %s" % (secs3, p3.stdout.strip().splitlines()[-1]))
    se.make_export(inbox / "gamma-100-80-60-30-0.wav", "lite", MIXES, irs=se.reverb_irs(rt=1.6, seed=6))
    p4, secs4 = cli(args)
    have4 = {f.name for f in latest.iterdir()}
    check("run after adding a third file: only the new file is analyzed, latest\\ now holds all three rooms", p4.stdout.count("analyzing") == 1 and "gamma" in p4.stdout.split("analyzing")[1] and p4.stdout.count("skipping") == 2
          and "gamma_summary.md" in have4 and "alpha_summary.md" in have4 and "beta_summary.md" in have4, "%.0f s; %s" % (secs4, p4.stdout.strip().splitlines()[-1]))
    after = {f.name: (f.stat().st_size, f.stat().st_mtime_ns) for f in inbox.iterdir() if f.suffix == ".wav"}
    check("run never touches the user's files (names, sizes, modified times unchanged)", all(after.get(k) == v for k, v in before.items()), "%d files compared" % len(before))
    txt = (latest / "all_rooms_summary.md").read_text(encoding="utf-8")
    check("all_rooms_summary.md in latest\\ is 100 lines or fewer and lists the failed room on top", len(txt.splitlines()) <= 100 and "## Failed or flagged" in txt and "beta" in txt.split("| room")[0], "%d lines" % len(txt.splitlines()))


def main():
    t0 = time.time()
    test_edt()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        r = test_dry_step_and_columns(td)
        if r:
            sj, sdir, mp, dp, wet = r
            test_floor_digital_silence(td, mp, dp)
            test_cli_split_mixcurve_all(td, sdir, mp, dp, wet)
            test_run(td, mp)
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n%d checks, %d failed, %.0f s" % (len(RESULTS), n_fail, time.time() - t0))
    Path(__file__).with_name("last_onecmd_results.txt").write_text("\n".join("%s  %s  %s" % ("PASS" if ok else "FAIL", n, d) for n, ok, d in RESULTS) + "\n", encoding="utf-8")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
