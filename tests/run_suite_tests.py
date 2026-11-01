"""Tests for the multi-pass workflow: split --repeats, Mix 0 calibration, 44.1 kHz/16-bit and other formats, empty passes, mixcurve, stage, analyze, analyze-all.
Plain script: python tests/run_suite_tests.py   (about 10 minutes). Prints PASS/FAIL with raw numbers; exit code 1 if any FAIL."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth_export as se  # noqa: E402
from earnest import analyze, dsp, mixcurve, room, stage, suite  # noqa: E402
from earnest.io import FS  # noqa: E402
from run_tests import check, RESULTS  # noqa: E402

LABELS = [100, 80, 60, 30, 0]
MIXES = (1.0, 0.8, 0.6, 0.3, 0.0)
MID = [250, 500, 1000, 2000, 4000]


def truth_for_m(irs_rev, m):
    """Tail level (mean 250 Hz-4 kHz, dB re direct) and DRR of the exact crossfade y = (1-m) x + m reverb(x), by the same estimators, no sweep involved."""
    pre = int(room.PRE_S * FS)
    ir = {}
    for k, side in enumerate(("L", "R")):
        h = m * irs_rev[side].copy()
        h[0, k] += 1.0 - m
        ir[side] = h
    comb = np.sqrt(sum(np.sum(h ** 2, axis=1) for h in ir.values()))
    k0 = int(np.argmax(comb))
    ir = {s: (np.concatenate([np.zeros((pre - k0, 2)), h]) if k0 < pre else h[k0 - pre:]) for s, h in ir.items()}
    lv = float(np.mean([room.analyze_band(ir, fc)[0]["level_db"] for fc in MID]))
    return lv, room.room_metrics(ir)["drr_db"], k0


def lite_manifest(td):
    _, man = suite.build("lite")
    p = Path(td) / "lite_manifest.json"
    p.write_text(json.dumps(man), encoding="utf-8")
    return p


def test_split_lite(td):
    irs = se.reverb_irs()
    wet = td / "lite_100-80-60-30-0.wav"
    tr = se.make_export(wet, "lite", MIXES, irs=irs)
    mp = lite_manifest(td)
    t0 = time.time()
    r = suite.run_split(wet, mp, td / "lite_out", td / "lite_dry", 5, LABELS)
    secs = time.time() - t0
    diffs, truths = [], []
    for i, st in enumerate(r["steps"]):
        _, _, k0 = truth_for_m(irs, MIXES[i])
        exp = tr["starts"][i] + k0
        diffs.append(st["start_sample"] - exp)
    check("split --repeats 5 (lite, 44.1 kHz/16-bit, normalised, irregular gaps): all five found within +-1 sample", all(abs(d) <= 1 for d in diffs) and len(r["steps"]) == 5,
          "offset errors in samples %s; starts s %s; split took %.0f s" % (diffs, [s["start_s"] for s in r["steps"]], secs))
    true_g = 20 * np.log10(tr["norm_gain"])
    cal = r["calibration"]
    check("calibration from the Mix 0 pass within 0.3 dB of the true gain", cal["ok"] and abs(cal["G_db"] - true_g) <= 0.3,
          "true %.3f dB, measured %.3f dB (diff %.3f); checks %s; notes %s" % (true_g, cal["G_db"], cal["G_db"] - true_g, cal["checks"], r["notes"]))
    # room on every step against the generated dry blocks, then mixcurve
    steps = []
    for st in r["steps"]:
        d = suite.step_dirname(st)
        res, _ = room.run_room(td / "lite_dry" / d, td / "lite_out" / d)
        steps.append((st["label"], res))
    c = mixcurve.curves(steps)
    errs = []
    for i, m in enumerate(MIXES[:-1]):
        lv, drr, _ = truth_for_m(irs, m)
        got = c["metrics"][i]
        errs.append((m, round(got["tail_level_db"] - lv, 2), round(got["drr_db"] - drr, 2), round(lv, 2), round(drr, 2)))
    worst = max(max(abs(e[1]), abs(e[2])) for e in errs)
    check("mixcurve recovers the crossfade (tail level and DRR) within 1 dB, Mix 100/80/60/30", worst <= 1.0,
          "(Mix, tail dB error, DRR dB error, true tail dB, true DRR dB) = %s; worst %.2f dB" % (errs, worst))
    last = c["metrics"][-1]
    check("Mix 0 step is a near identity with no tail", abs(last["M_LL"] - 1) < 0.1 and abs(last["M_LR"]) < 0.1 and last["tail_level_db"] < -40 and last["no_tail"],
          "M L>L %.3f, M L>R %.3f, tail level %.1f dB, no_tail %s" % (last["M_LL"], last["M_LR"], last["tail_level_db"], last["no_tail"]))
    return tr


def test_silent_pass(td):
    wet = td / "silent.wav"
    tr = se.make_export(wet, "lite", MIXES, irs=se.reverb_irs(), silent=(2,))
    mp = lite_manifest(td)
    r = suite.run_split(wet, mp, td / "silent_out", None, 5, LABELS, write_files=False)
    st = r["steps"]
    good = all(abs(st[i]["start_sample"] - (tr["starts"][i] + (144 if MIXES[i] >= 0.5 else 0))) <= 1 for i in (0, 1, 3, 4))
    check("a silent pass is reported EMPTY (never skipped), the other four are still placed within +-1 sample",
          len(st) == 5 and st[2]["inferred"] and st[2]["all_empty"] and good and not any(s["inferred"] for s in (st[0], st[1], st[3], st[4])),
          "pass 3 inferred %s, all sweep blocks empty %s, placed at %.1f s (true %.1f s); empty blocks %s; others ok %s" % (
              st[2]["inferred"], st[2]["all_empty"], st[2]["start_s"], tr["starts"][2] / FS, st[2]["empty_blocks"], good))
    # fewer copies than asked and none inferable: abort naming the count
    try:
        suite.run_split(wet, mp, td / "x", None, 9, None, write_files=False)
        ok = False
        msg = "no error"
    except SystemExit as e:
        ok, msg = "found" in str(e) and "of 9" in str(e), str(e)[:120]
    check("asking for more copies than exist aborts with a clear count", ok, msg)


def test_formats(td):
    irs = se.reverb_irs()
    for name, fs_out, sub in (("24-bit 48 kHz", 48000, "PCM_24"), ("32-bit float 48 kHz", 48000, "FLOAT"), ("16-bit 44.1 kHz not normalised", 44100, "PCM_16")):
        wet = td / ("fmt_%s_%s.wav" % (fs_out, sub))
        norm = "not normalised" not in name
        tr = se.make_export(wet, "lite", MIXES, irs=irs, fs_out=fs_out, subtype=sub, normalize=norm, gain=None if norm else 0.5)
        r = suite.run_split(wet, lite_manifest(td), td / ("fmt_out_" + sub + str(fs_out)), None, 5, LABELS, write_files=False)
        true_g = 20 * np.log10(tr["norm_gain"])
        d = [r["steps"][i]["start_sample"] - (tr["starts"][i] + (144 if MIXES[i] >= 0.5 else 0)) for i in range(5)]
        cal = r["calibration"]
        check("format %s: five passes found within +-1 sample and G within 0.3 dB" % name, all(abs(x) <= 1 for x in d) and cal["ok"] and abs(cal["G_db"] - true_g) <= 0.3,
              "offset errors %s; true G %.3f dB, measured %.3f dB; notes %s" % (d, true_g, cal["G_db"], r["notes"]))


def test_dirty_mix0(td):
    """A last pass that is not dry (here Mix 0.5): calibration must warn and not be applied."""
    wet = td / "dirty.wav"
    se.make_export(wet, "lite", (1.0, 0.8, 0.6, 0.3, 0.5), irs=se.reverb_irs())
    r = suite.run_split(wet, lite_manifest(td), td / "dirty_out", None, 5, LABELS, write_files=False)
    cal = r["calibration"]
    check("a Mix 0 pass that is not clean dry is warned about and calibration is not applied", (not cal["ok"]) and not cal["applied"] and len(cal["warnings"]) >= 1,
          "ok %s applied %s; warnings %s" % (cal["ok"], cal["applied"], cal["warnings"]))


def test_stage():
    """Known decorrelated tail and boosted side channel: the stage numbers must match within 1 dB / 0.05 correlation.
    The tail is kept 30 dB under the direct sound so that the burst window is nearly all direct sound; mid/side inputs have clamped S/M, so only their correlations are compared."""
    dry, man = suite.build("full")
    g_db = 6.0
    g = 10 ** (g_db / 20)
    rho = 0.2
    irs = se.synth_system(2.0, rho=rho, seed=21, tail_start_ms=10.0, level_db=-30.0, taps=[], direct_xtalk=0.0)
    dry_w, wet_w = {}, {}
    for b in man["blocks"]:
        if b["name"] not in stage.BLOCKS:
            continue
        x = dry[b["start_sample"]: b["start_sample"] + b["length_samples"]]
        y = se.apply_irs(x, irs)
        m, s = (y[:, 0] + y[:, 1]) / 2, (y[:, 0] - y[:, 1]) / 2
        wet_w[b["name"]] = np.stack([m + g * s, m - g * s], axis=1)
        dry_w[b["name"]] = x
    sg = stage.compute(dry_w, wet_w)
    em, es = (1 + rho) / 2, (1 - rho) / 2
    exp_tail_corr = (em - g * g * es) / (em + g * g * es)
    exp_tail_sm = 10 * np.log10(g * g * es / em)
    rows, worst_c, worst_db = [], 0.0, 0.0
    for nm in stage.BLOCKS:
        r = sg[nm]
        d = dry_w[nm]
        Em, Es = np.mean(((d[:, 0] + d[:, 1]) / 2) ** 2), np.mean(((d[:, 0] - d[:, 1]) / 2) ** 2)
        exp_dc = (Em - g * g * Es) / (Em + g * g * Es)
        exp_dsm = float(np.clip(10 * np.log10(max(g * g * Es, 1e-30) / max(Em, 1e-30)), -60, 60))
        tc_mid = float(np.mean([v for v, h in zip(r["tail"]["corr"], stage.EDC_BANDS) if h in MID]))
        tsm_mid = float(np.mean([v for v, h in zip(r["tail"]["sm_db"], stage.EDC_BANDS) if h in MID]))
        errs_c = [r["direct"]["corr"] - exp_dc, tc_mid - exp_tail_corr]
        errs_db = [tsm_mid - exp_tail_sm]
        if nm == "noise_wide":
            errs_db.append(r["direct"]["side_over_mid_db"] - exp_dsm)
        worst_c = max([worst_c] + [abs(e) for e in errs_c])
        worst_db = max([worst_db] + [abs(e) for e in errs_db])
        rows.append("%s: direct corr %.3f (exp %.3f), direct S/M %.2f (exp %.2f%s), tail corr 250-4k mean %.3f (exp %.3f), tail S/M 250-4k mean %.2f (exp %.2f), tail corr per band 125..8k %s" % (
            nm, r["direct"]["corr"], exp_dc, r["direct"]["side_over_mid_db"], exp_dsm, "" if nm == "noise_wide" else ", not compared: clamped and leak-limited", tc_mid, exp_tail_corr, tsm_mid,
            exp_tail_sm, r["tail"]["corr"]))
    wg = sg["noise_wide"]["width_gain_db"]
    check("stage: direct/tail correlation within 0.05 and side/mid within 1 dB of the known values (+6 dB side boost, tail rho 0.2)", worst_c <= 0.05 and worst_db <= 1.0,
          "worst corr error %.3f, worst S/M error %.2f dB | " % (worst_c, worst_db) + " | ".join(rows))
    check("stage: width gain of noise_wide = +6.02 dB direct (within 1 dB)", abs(wg["direct"] - g_db) <= 1.0, "direct %.2f dB, tail %.2f dB (tail expected %.2f)" % (wg["direct"], wg["tail"], exp_tail_sm - sg["noise_wide"]["input_side_over_mid_db"]))


def run_cli(args):
    t0 = time.time()
    p = subprocess.run([sys.executable, "-m", "earnest"] + args, capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent))
    return p, time.time() - t0


def test_analyze(td):
    irs = se.reverb_irs()
    wet = td / "synthroom_100-80-60-30-0.wav"
    tr = se.make_export(wet, "full", MIXES, irs=irs)
    p, secs = run_cli(["analyze", str(wet), "--room", "synthroom"])
    m = re.search(r"summary: (.*summary\.md)", p.stdout)
    mem = re.search(r"peak memory (\d+) MB", p.stdout)
    check("analyze runs to the end on a synthetic 5-pass, 190.5-s-per-pass export (44.1 kHz/16-bit, 982 s, 173 MB)", p.returncode == 0 and m is not None,
          "exit %d; wall time %.0f s; peak memory %s MB (analyze process, measured inside); stderr %s" % (p.returncode, secs, mem.group(1) if mem else "?", p.stderr[-200:].strip()))
    if not m:
        print(p.stdout, p.stderr)
        return
    sj = json.loads(Path(m.group(1)).with_name("summary.json").read_text(encoding="utf-8"))
    lines = len(Path(m.group(1)).read_text(encoding="utf-8").splitlines())
    check("summary.md is 120 lines or fewer", lines <= 120, "%d lines" % lines)
    true_g = 20 * np.log10(tr["norm_gain"])
    check("analyze: calibration within 0.3 dB", abs(sj["calibration"]["G_db"] - true_g) <= 0.3, "true %.3f dB, measured %.3f dB" % (true_g, sj["calibration"]["G_db"]))
    errs = []
    for i, mm in enumerate(MIXES[:-1]):
        lv, drr, _ = truth_for_m(irs, mm)
        got = sj["mixcurve"]["metrics"][i]
        errs.append((mm, round(got["tail_level_db"] - lv, 2), round(got["drr_db"] - drr, 2)))
    worst = max(max(abs(e[1]), abs(e[2])) for e in errs)
    check("analyze on the full probe: mixcurve recovers tail level and DRR within 1 dB", worst <= 1.0, "(Mix, tail dB err, DRR dB err) %s; worst %.2f dB" % (errs, worst))
    s1 = sj["steps"][0]
    rt = [b["rt60_s"] for b in s1["room"]["tail_bands"]]
    lin = s1["room"]["linearity"]
    check("analyze, Mix 100 step on the full probe: RT60 within 5% of 1.2 s per band, linearity run and not flagged", max(abs(v - 1.2) / 1.2 for v in rt) <= 0.05 and lin["run"] and lin["nonlinear_or_time_variant"] is False,
          "RT60 %s; linearity worst %s" % (rt, {k: v.get("worst_db") for k, v in lin["comparisons"].items()}))
    check("analyze: Mix 0 sanity says near identity", sj["mix0_sanity"]["identity"], str(sj["mix0_sanity"]))
    return wet, tr


def test_analyze_all(td, wet):
    folder = td / "allrooms"
    folder.mkdir()
    import shutil
    shutil.copy(wet, folder / "synthroom_100-80-60-30-0.wav")
    se.make_export(folder / "emptyroom-100-80-60-30-0.wav", "full", MIXES, irs=se.reverb_irs(rt=0.6, seed=11), silent=(1,))
    p, secs = run_cli(["analyze-all", str(folder)])
    m = re.search(r"all_rooms_summary: (.*all_rooms_summary\.md)", p.stdout)
    txt = Path(m.group(1)).read_text(encoding="utf-8") if m else ""
    lines = len(txt.splitlines())
    check("analyze-all: both rooms processed, room names parsed from file names, the room with an empty pass is listed as failed, summary <= 100 lines",
          m is not None and "synthroom" in txt and "emptyroom" in txt and "Failed or flagged" in txt and "EMPTY" in txt and lines <= 100 and p.returncode == 1,
          "exit %d (1 = something flagged); %d lines; wall %.0f s; stdout %s" % (p.returncode, lines, secs, p.stdout.strip()[-200:]))


def main():
    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        test_split_lite(td)
        test_silent_pass(td)
        test_formats(td)
        test_dirty_mix0(td)
        test_stage()
        r = test_analyze(td)
        if r:
            test_analyze_all(td, r[0])
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n%d checks, %d failed, %.0f s" % (len(RESULTS), n_fail, time.time() - t0))
    Path(__file__).with_name("last_suite_results.txt").write_text("\n".join("%s  %s  %s" % ("PASS" if ok else "FAIL", n, d) for n, ok, d in RESULTS) + "\n", encoding="utf-8")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
