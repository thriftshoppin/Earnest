"""`earnest ping`: a self-test. Builds known files (the probe written as a 24-bit FLAC with TPDF dither, the way BandLab writes them), pushes them through the real chain and compares
what every hop received with the known truth. Files and results go to runs\\ping\\ (overwritten each time). Never plays audio."""
from __future__ import annotations

import json
import time
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve, resample_poly

from . import analyze, dsp, formula, room, suite
from .io import FS, RUNS, save_json

PING_DIR = RUNS / "ping"
MID = [250, 500, 1000, 2000, 4000]


def tpdf_int(x: np.ndarray, bits: int, rng) -> np.ndarray:
    """Quantise a float signal to `bits` with TPDF dither and proper rounding (what a DAW export does); returns int32 values (24-bit: shifted left by 8, 16-bit: int16)."""
    q = 2.0 ** (bits - 1)
    k = np.rint(x * q + (rng.random(x.shape) - rng.random(x.shape)))
    k = np.clip(k, -q, q - 1)
    return (k.astype(np.int32) << 8) if bits == 24 else k.astype(np.int16)


def write_flac(path, x, bits=24, fs=FS, seed=3):
    rng = np.random.default_rng(seed)
    sf.write(str(path), tpdf_int(x, bits, rng), fs, subtype="PCM_24" if bits == 24 else "PCM_16", format="FLAC")


def reverb_irs(rt=1.2, rho=0.3, seed=7, level_db=-10.0, xtalk=0.1):
    """A known 2x2 reverb: direct at 3 ms (1.0, crosstalk 0.1), diffuse tail from 75 ms, exponential decay, L/R tail correlation rho."""
    rng = np.random.default_rng(seed)
    n = int(4.0 * FS)
    t0 = int(0.003 * FS)
    ts = int(0.075 * FS)
    irs = {}
    for k, side in enumerate(("L", "R")):
        h = np.zeros((n, 2))
        h[t0, k] = 1.0
        h[t0, 1 - k] = xtalk
        tt = np.arange(n - ts) / FS
        env = 10 ** (-3.0 * tt / rt)
        w1, w2 = rng.standard_normal(n - ts), rng.standard_normal(n - ts)
        tl, tr_ = w1 * env, (rho * w1 + np.sqrt(1 - rho ** 2) * w2) * env
        scale = np.sqrt(10 ** (level_db / 10.0) * (1 + xtalk ** 2) / (np.sum(tl ** 2) + np.sum(tr_ ** 2)))
        h[ts:, 0] += scale * tl
        h[ts:, 1] += scale * tr_
        irs[side] = h
    return irs


def crossfade(clip, irs, m):
    wet = np.zeros_like(clip)
    for k, side in enumerate(("L", "R")):
        for c in range(2):
            wet[:, c] += fftconvolve(clip[:, k], irs[side][:, c])[: len(clip)]
    return (1.0 - m) * clip + m * wet


def truth(irs, m):
    """Tail level (mean 250 Hz-4 kHz, dB re direct) and DRR of the exact crossfade, by the room estimators on the exact impulse responses."""
    pre = int(room.PRE_S * FS)
    ir = {}
    for k, side in enumerate(("L", "R")):
        h = m * irs[side].copy()
        h[0, k] += 1.0 - m
        ir[side] = h
    comb = np.sqrt(sum(np.sum(h ** 2, axis=1) for h in ir.values()))
    k0 = int(np.argmax(comb))
    ir = {s: (np.concatenate([np.zeros((pre - k0, 2)), h]) if k0 < pre else h[k0 - pre:]) for s, h in ir.items()}
    return float(np.mean([room.analyze_band(ir, fc)[0]["level_db"] for fc in MID])), room.room_metrics(ir)["drr_db"]


def run(quick: bool = False, base=None) -> int:
    t0 = time.time()
    pdir = Path(base) if base else PING_DIR
    pdir.mkdir(parents=True, exist_ok=True)
    inbox = pdir / "inbox"
    inbox.mkdir(exist_ok=True)
    mode = "lite" if quick else "full"
    clip, man = suite.build(mode)
    mpath = pdir / "ping_manifest.json"
    mpath.write_text(json.dumps(man), encoding="utf-8")
    irs = reverb_irs()
    wet100, wet60 = crossfade(clip, irs, 1.0), crossfade(clip, irs, 0.6)
    muted = clip.copy()
    muted[:, 1] = 0.0
    noise = np.random.default_rng(9).standard_normal(clip.shape) * 10 ** (-60 / 20.0)
    write_flac(inbox / "dry.flac", clip)
    write_flac(inbox / "pingroom100.flac", wet100)
    write_flac(inbox / "pingroom60.flac", wet60)
    g = gcd(FS, 44100)
    write_flac(inbox / "lofi100.flac", resample_poly(wet100, 44100 // g, FS // g, axis=0), bits=16, fs=44100)
    write_flac(inbox / "mutedR.flac", muted)
    write_flac(inbox / "noiseonly.flac", noise)
    print("ping: 6 files written to %s (%s probe); running the real chain ..." % (inbox, mode))
    plan = analyze.plan_folder(inbox)
    results, plan, out_root = analyze.process_folder(inbox, manifest_path=str(mpath), out_root=pdir / "results", quiet=True, plan=plan)
    by = {r["room"]: r for r in results}
    checks = []

    def chk(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    def file_info(room_name, fname):
        d = (by.get(room_name) or {}).get("data") or {}
        return next((f for f in d.get("files", []) if f.get("file") == fname), {}), d

    def hop(info, name):
        return next((h for h in info.get("hops", []) if h["hop"] == name), None)

    # --- the clean dry file
    f, d = file_info("pingroom", "dry.flac")
    if not f:
        f = next((x for r in results for x in (r["data"] or {}).get("files", []) if x.get("file") == "dry.flac"), {})
    chk("dry.flac: every hop OK", f.get("status") == "OK" and all(h["status"] == "OK" for h in f.get("hops", [])), [(h["hop"], h["status"]) for h in f.get("hops", [])])
    chk("dry.flac: per-channel peak -18 dBFS (+-0.3)", all(abs(p + 18.0) <= 0.3 for p in f.get("peak_dbfs", [0, 0])), "peaks %s" % f.get("peak_dbfs"))
    chk("dry.flac: both channels match their sweep", sum(1 for s in f.get("match", []) if s["detected"]) == 4, [(s["sweep"], "LR"[s["channel"]], s["peak_to_noise_db"]) for s in f.get("match", [])])
    cal = ((by.get("pingroom") or {}).get("data") or {}).get("calibration", {})
    chk("dry.flac: calibration gain 0 dB (+-0.3)", cal.get("ok") and abs(cal.get("G_db", 99)) <= 0.3, "G = %s dB" % cal.get("G_db"))
    # --- effect files through the crossfade
    for room_name, fname, label, m in (("pingroom", "pingroom100.flac", 100, 1.0), ("pingroom", "pingroom60.flac", 60, 0.6), ("lofi", "lofi100.flac", 100, 1.0)):
        f, d = file_info(room_name, fname)
        lv, drr = truth(irs, m)
        st = next((s for s in d.get("steps", []) if s.get("label") == label and s.get("status") == "ok"), None)
        from .mixcurve import metrics
        got = metrics(st["room"]) if st else None
        chk("%s: no FAIL hop, both channels read and matched" % fname, f.get("status") in ("OK", "WARN") and sum(1 for s in f.get("match", []) if s["detected"]) == 4,
            {"status": f.get("status"), "hops": [(h["hop"], h["status"]) for h in f.get("hops", [])]})
        chk("%s: tail level and DRR within 1 dB of the known crossfade" % fname, got is not None and abs(got["tail_level_db"] - lv) <= 1.0 and abs(got["drr_db"] - drr) <= 1.0,
            "tail %s dB (truth %.2f), DRR %s dB (truth %.2f)" % (None if not got else round(got["tail_level_db"], 2), lv, None if not got else round(got["drr_db"], 2), drr))
        if fname == "lofi100.flac":
            ch = hop(f, "CONVERT")
            chk("lofi100.flac: CONVERT reports 44100 -> 48000 Hz with per-channel peaks", ch is not None and "44100" in ch["msg"] and "per-channel peak" in ch["msg"], ch["msg"] if ch else None)
    # --- deliberately broken files
    f, d = file_info("mutedR", "mutedR.flac")
    mt = hop(f, "MATCH")
    rd = hop(f, "READ")
    chk("mutedR.flac: READ warns that channel R is only dither noise, then FAILS at MATCH with 'channel R lost'", rd is not None and rd["status"] == "WARN" and mt is not None and mt["status"] == "FAIL" and "channel R lost" in mt["msg"],
        (rd["status"] if rd else None, mt["msg"][:170] if mt else None))
    f, d = file_info("noiseonly", "noiseonly.flac")
    mt = hop(f, "MATCH")
    chk("noiseonly.flac: FAILS at MATCH with 'no probe found'", mt is not None and mt["status"] == "FAIL" and mt["msg"].startswith("no probe found"), mt["msg"][:200] if mt else None)
    chk("noiseonly.flac: no later hop ran after the failure (stop function)", mt is not None and f.get("hops", [{}])[-1]["hop"] == "MATCH", [h["hop"] for h in f.get("hops", [])])
    n_hops = sum(len(f.get("hops", [])) for r in results for f in (r["data"] or {}).get("files", []))
    lost = [c for c in checks if not c["ok"]]
    L = ["# earnest ping (%s probe)" % mode, ""]
    for c in checks:
        L.append("%s  %s  %s" % ("OK  " if c["ok"] else "LOST", c["check"], c["detail"]))
    verdict = ("PING OK: %d checks over %d hops, 0 lost" % (len(checks), n_hops)) if not lost else ("PING FAILED: %d of %d checks lost: %s" % (len(lost), len(checks), "; ".join(c["check"] for c in lost)))
    L += ["", verdict, "seconds: %.0f" % (time.time() - t0)]
    (pdir / "ping.txt").write_text("\n".join(L) + "\n", encoding="utf-8")
    save_json(pdir / "ping.json", {"verdict": verdict, "checks": checks, "mode": mode, "seconds": round(time.time() - t0, 1)})
    print("\n".join(L[2:]))
    print("details: %s" % (pdir / "ping.txt"))
    return 0 if not lost else 1
