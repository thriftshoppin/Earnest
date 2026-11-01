"""Synthetic-IR tests with known answers. Plain script (pytest is not installed): python tests/run_tests.py
Each limit prints PASS/FAIL with the raw numbers. Exit code 1 if any FAIL."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from earnest import dsp, formula, gen, resynth, room, suite  # noqa: E402
from earnest.io import FS, read_wav, write_wav  # noqa: E402

RESULTS = []


def check(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print("%s  %s  %s" % ("PASS" if ok else "FAIL", name, detail))


def synth_system(rt60, rho=0.3, seed=1, tail_start_ms=75.0, level_db=-10.0, taps=None, direct_xtalk=0.1):
    """Known 2x2 impulse responses: direct (arrival 3 ms), discrete taps, then an exponentially decaying noise tail with L/R correlation rho."""
    rng = np.random.default_rng(seed)
    n = int(4.0 * FS)
    irs = {}
    t0 = int(0.003 * FS)
    taps = taps if taps is not None else []
    for k, side in enumerate(("L", "R")):
        h = np.zeros((n, 2))
        h[t0, k] = 1.0
        h[t0, 1 - k] = direct_xtalk
        for tp in taps:
            if tp["source"] != side:
                continue
            i = int(round(t0 + tp["delay_ms"] * FS / 1000.0))
            gl, gr = dsp.pan_gains(tp["pan"])
            a = 10 ** (tp["gain_db"] / 20.0) * np.hypot(1.0, direct_xtalk)
            h[i, 0] += a * gl
            h[i, 1] += a * gr
        ts = int(tail_start_ms * FS / 1000.0)
        tt = np.arange(n - ts) / FS
        env = 10 ** (-3.0 * tt / rt60)
        w1, w2 = rng.standard_normal(n - ts), rng.standard_normal(n - ts)
        tl, tr = w1 * env, (rho * w1 + np.sqrt(1 - rho ** 2) * w2) * env
        # level: tail energy = level_db re direct energy
        scale = np.sqrt(10 ** (level_db / 10.0) * (1 + direct_xtalk ** 2) / (np.sum(tl ** 2) + np.sum(tr ** 2)))
        h[ts:, 0] += scale * tl
        h[ts:, 1] += scale * tr
        irs[side] = h
    return irs


def run_sweeps(irs, nonlin=0.0, level_db=-18.0):
    dry_l = gen.sweep_stereo("L", level_db)
    dry_r = gen.sweep_stereo("R", level_db)
    out = {}
    for side, dry in (("L", dry_l), ("R", dry_r)):
        h = irs[side]
        wet = np.stack([fftconvolve(dry[:, 0 if side == "L" else 1], h[:, c])[: len(dry)] for c in range(2)], axis=1)
        if nonlin:
            wet = np.tanh(nonlin * wet) / nonlin
        out[side] = (dry, wet)
    return out


def main():
    t_start = time.time()
    taps = [{"delay_ms": 7.3, "gain_db": -6.0, "pan": -0.6, "source": "L"}, {"delay_ms": 13.1, "gain_db": -9.0, "pan": 0.4, "source": "R"},
            {"delay_ms": 21.7, "gain_db": -12.0, "pan": -0.2, "source": "L"}, {"delay_ms": 34.9, "gain_db": -14.0, "pan": 0.8, "source": "R"},
            {"delay_ms": 52.3, "gain_db": -17.0, "pan": 0.0, "source": "L"}]
    # --- RT60, IACC
    for rt in (0.3, 1.2, 2.5):
        irs = synth_system(rt, rho=0.3, seed=int(rt * 10), taps=taps)
        res, _ = room.analyze_sweeps(run_sweeps(irs))
        errs, ia = [], []
        for b in res["tail_bands"]:
            e = (b["rt60_s"] - rt) / rt * 100.0 if b["rt60_s"] else float("nan")
            errs.append(e)
            ia.append(b["iacc"])
        worst = max(abs(e) for e in errs)
        check("RT60 %.1f s within 5%% in every band 125 Hz-8 kHz" % rt, worst <= 5.0, "errors %% per band %s; worst %.2f%%" % (["%.2f" % e for e in errs], worst))
        # truth = IACC of the actual synthetic tails (same estimator, band-filtered, from the tail start); a random-noise sample never has exactly the nominal rho
        truth = []
        for fc in dsp.EDC_BANDS:
            v = []
            for s in ("L", "R"):
                hh = irs[s][int(0.075 * FS):]
                v.append(dsp.iacc(dsp.bandpass_fft(hh[:, 0], FS, fc, 1), dsp.bandpass_fft(hh[:, 1], FS, fc, 1), FS))
            truth.append(float(np.mean(v)))
        d = [abs(v - t_) for v, t_ in zip(ia, truth)]
        check("IACC %.1f s tail within +-0.05 of the true IACC in every band" % rt, max(d) <= 0.05,
              "measured %s; true %s; worst |diff| %.3f" % (ia, ["%.3f" % x for x in truth], max(d)))
    # --- taps, pan
    irs = synth_system(1.2, rho=0.3, seed=5, taps=taps)
    res, _ = room.analyze_sweeps(run_sweeps(irs))
    et = res["early_taps"]
    dly, pan, miss = [], [], 0
    for tp in taps:
        near = [t for t in et["taps"] if t["source"] == tp["source"] and abs(t["delay_ms"] - tp["delay_ms"]) < 1.0]
        if not near:
            miss += 1
            continue
        t = min(near, key=lambda t: abs(t["delay_ms"] - tp["delay_ms"]))
        dly.append(t["delay_ms"] - tp["delay_ms"])
        pan.append(t["pan"] - tp["pan"])
    check("tap delays within +-0.2 ms", miss == 0 and max(abs(d) for d in dly) <= 0.2, "taps found %d (status %s), missed %d, delay errors ms %s" % (et["count_found"], et["status"], miss, ["%.3f" % d for d in dly]))
    check("tap pans within +-0.05", miss == 0 and max(abs(p) for p in pan) <= 0.05, "pan errors %s" % ["%.3f" % p for p in pan])
    check("no spurious taps (found == true count)", et["count_found"] == len(taps), "found %d, true %d" % (et["count_found"], len(taps)))
    # --- unresolved case: no taps
    irs0 = synth_system(1.2, rho=0.3, seed=6, taps=[], tail_start_ms=5.0)
    res0, _ = room.analyze_sweeps(run_sweeps(irs0))
    check("dense tail with no taps reports 'unresolved' (never padded to 24)", res0["early_taps"]["status"] == "unresolved" and len(res0["early_taps"]["taps"]) == 0,
          "status %s, count_found %d" % (res0["early_taps"]["status"], res0["early_taps"]["count_found"]))
    # --- direct matrix
    M = res["direct_matrix"]
    check("direct matrix recovered (1.0 / 0.1)", abs(M["L"][0] - 1) < 0.05 and abs(M["L"][1] - 0.1) < 0.05 and abs(M["R"][1] - 1) < 0.05, "M = %s" % {k: [round(x, 3) for x in v] for k, v in M.items()})
    # --- linearity
    sets = {"a": run_sweeps(irs, level_db=-18.0), "b": run_sweeps(irs, level_db=-30.0), "rep": run_sweeps(irs, level_db=-18.0)}
    lin = room.linearity(sets)
    check("linearity: linear system passes (flag false)", lin["nonlinear_or_time_variant"] is False,
          "; ".join("%s worst %.3f dB" % (k, c["worst_db"]) for k, c in lin["comparisons"].items()))
    setsn = {"a": run_sweeps(irs, nonlin=8.0, level_db=-18.0), "b": run_sweeps(irs, nonlin=8.0, level_db=-30.0), "rep": {}}
    linn = room.linearity(setsn)
    check("linearity: soft-clipped system is flagged", linn["nonlinear_or_time_variant"] is True,
          "; ".join("%s worst %.3f dB" % (k, c["worst_db"]) for k, c in linn["comparisons"].items() if c.get("run")))
    # --- pan transfer map on a known stereo system (identity direct path)
    dry = gen.clicks_panned()
    ident = np.zeros((int(0.5 * FS), 2, 2))
    d0 = int(0.003 * FS)
    wetc = np.zeros_like(dry)
    wetc[d0:] = dry[:-d0]
    rows = room.pan_map(dry, wetc, d0)
    err = [abs(r["pan_out_direct"] - r["pan_in"]) for r in rows]
    check("pan transfer map: identity system returns the input pan (+-0.05)", len(rows) == 5 and max(err) <= 0.05, "in %s -> out %s" % ([r["pan_in"] for r in rows], [r["pan_out_direct"] for r in rows]))
    # --- formula round trip: fit, then resynth against the formula's own numbers (self-consistency, not real audio)
    res3, _ = room.analyze_sweeps(run_sweeps(synth_system(1.2, rho=0.3, seed=9, taps=taps)))
    res3["input_mode"] = "stereo"
    res3["nonlinear_or_time_variant"] = False
    f = formula.build(res3, "synthetic")
    dry_l = gen.sweep_stereo("L")
    import tempfile
    from earnest.io import write_wav
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "dry.wav"
        write_wav(p, dry_l)
        st = resynth.run(f, p, None, 5)
    print("resynth self-consistency (info only):")
    for k in ("edc_err_db", "rt60_err_pct", "iacc_diff", "spectral_err_db"):
        print("  %-16s mean %s" % (k, st[k]["mean"]))
        print("  %-16s sd   %s" % ("", st[k]["sd"]))
    ok = all(v is not None and abs(v) < 15 for v in st["rt60_err_pct"]["mean"])
    check("resynth smoke: RT60 error mean within 15% per band (info limit)", ok, "means %s" % st["rt60_err_pct"]["mean"])
    suite_tests()
    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print("\n%d checks, %d failed, %.0f s" % (len(RESULTS), n_fail, time.time() - t_start))
    out = Path(__file__).parent / "last_results.txt"
    out.write_text("\n".join("%s  %s  %s" % ("PASS" if ok else "FAIL", n, d) for n, ok, d in RESULTS) + "\n", encoding="utf-8")
    return 1 if n_fail else 0


def suite_tests():
    import json
    import tempfile
    from earnest.cli import main as cli_main
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # 1. identity: suite -> split (offset 0) equals the gen signals
        dry, man = suite.build("full")
        write_wav(td / "dry_full.wav", dry)
        (td / "man.json").write_text(json.dumps(man), encoding="utf-8")
        (td / "id").mkdir()
        res = suite.split(td / "dry_full.wav", man, td / "id", None)
        worst, names = 0.0, []
        gen_files = gen.make_all()
        for b in man["blocks"]:
            seg, _ = read_wav(td / "id" / (b["name"] + ".wav"))
            ref = suite.block_signal(b["name"])
            d = float(np.abs(seg - ref).max())
            g = gen_files.get(b["name"] + ".wav")
            if g is not None:   # the gen file (4 s tail) must equal the start of the block, the rest of the block must be silent
                d = max(d, float(np.abs(seg[: len(g)] - g).max()), float(np.abs(seg[len(g):]).max()))
            worst = max(worst, d)
            names.append(b["name"])
        check("suite identity (full): every block equals its gen signal within 1e-6", worst <= 1e-6 and res["offset_samples"] == 0,
              "%d blocks, worst |diff| %.2e, offset %d samples" % (len(names), worst, res["offset_samples"]))
        # 2. synthetic effect: 7 ms delay and a gain change
        d7 = int(round(0.007 * FS))
        wet = np.zeros((len(dry) + d7, 2))
        wet[d7:] = 0.5 * dry
        write_wav(td / "wet7.wav", wet)
        (td / "w7").mkdir()
        r7 = suite.split(td / "wet7.wav", man, td / "w7", None)
        worst = 0.0
        for b in man["blocks"]:
            seg, _ = read_wav(td / "w7" / (b["name"] + ".wav"))
            worst = max(worst, float(np.abs(seg - 0.5 * suite.block_signal(b["name"])).max()))
        check("suite effect (7 ms delay, gain 0.5): offset found within +-1 sample", abs(r7["offset_samples"] - d7) <= 1,
              "true %d samples (7.000 ms), found %d samples (%.3f ms)" % (d7, r7["offset_samples"], r7["offset_ms"]))
        check("suite effect: blocks equal 0.5 x dry within 1e-6", worst <= 1e-6, "worst |diff| %.2e" % worst)
        # 3. known reverb through the lite suite -> split -> room; RT60 within 5 %
        taps = [{"delay_ms": 7.3, "gain_db": -6.0, "pan": -0.6, "source": "L"}, {"delay_ms": 13.1, "gain_db": -9.0, "pan": 0.4, "source": "R"},
                {"delay_ms": 21.7, "gain_db": -12.0, "pan": -0.2, "source": "L"}, {"delay_ms": 34.9, "gain_db": -14.0, "pan": 0.8, "source": "R"},
                {"delay_ms": 52.3, "gain_db": -17.0, "pan": 0.0, "source": "L"}]
        dl, ml = suite.build("lite")
        (td / "manl.json").write_text(json.dumps(ml), encoding="utf-8")
        for rt in (0.3, 1.2, 2.5):
            irs = synth_system(rt, rho=0.3, seed=int(rt * 10) + 100, taps=taps)
            wl = np.zeros((len(dl), 2))
            for k, side in enumerate(("L", "R")):
                for c in range(2):
                    wl[:, c] += fftconvolve(dl[:, k], irs[side][:, c])[: len(dl)]
            tag = "rt%d" % int(rt * 10)
            write_wav(td / (tag + ".wav"), wl)
            wd, dd = td / (tag + "_wet"), td / (tag + "_dry")
            wd.mkdir()
            dd.mkdir()
            rs = suite.split(td / (tag + ".wav"), ml, wd, dd)
            out, _ = room.run_room(dd, wd)
            errs = [(b["rt60_s"] - rt) / rt * 100.0 for b in out["tail_bands"]]
            ia_ok = all(b["iacc"] is not None for b in out["tail_bands"])
            check("suite lite -> split -> room: RT60 %.1f s within 5%% in every band" % rt, max(abs(e) for e in errs) <= 5.0 and abs(rs["offset_samples"] - 144) <= 1,   # 144 samples = the synthetic reverb's own 3 ms direct delay

                  "offset %d samples (true 144); errors %% %s; worst %.2f%%; taps %s (%d); pan map blocks %s" % (
                      rs["offset_samples"], ["%.2f" % e for e in errs], max(abs(e) for e in errs), out["early_taps"]["status"], out["early_taps"]["count_found"],
                      {k: len(v) for k, v in out["pan_map"].items()}))


if __name__ == "__main__":
    sys.exit(main())
