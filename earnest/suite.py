"""Probe suite: every stimulus joined in ONE WAV so a single DAW export per effect setting gives everything `room` needs, and `split` to cut the wet export back
into the named files. Same signal code and names as `gen`; each block has a 6 s silent tail so long reverb tails die out before the next block."""
from __future__ import annotations

import numpy as np

from . import dsp, gen
from .dsp import db
from .io import FS, read_wav, write_wav

LEAD_S, END_S, BLOCK_TAIL_S = 2.0, 1.0, 6.0
MAX_OFFSET_S = 0.5
EMPTY_DB = -90.0
ORDER = {
    "lite": ["sweep_L", "sweep_R", "clicks_panned", "clicks_mono", "noise_bursts_panned"],
    "full": ["sweep_L", "sweep_R", "sweep_L_m30", "sweep_R_m30", "sweep_L_rep", "sweep_R_rep", "clicks_panned", "clicks_mono", "noise_bursts_panned"],
}


def block_signal(name: str, fs: int = FS) -> np.ndarray:
    t = BLOCK_TAIL_S
    if name.startswith("sweep_"):
        side = name[6]
        return gen.sweep_stereo(side, -30.0 if name.endswith("_m30") else gen.PEAK_DB, fs, t)   # _rep is an identical copy of the -18 dBFS sweep
    return {"clicks_panned": gen.clicks_panned, "clicks_mono": gen.clicks_mono, "noise_bursts_panned": gen.noise_bursts}[name](fs, t)


def build(mode: str, fs: int = FS):
    if mode not in ORDER:
        raise SystemExit("suite mode must be lite or full")
    blocks, pos = [], int(round(LEAD_S * fs))
    sigs = []
    for name in ORDER[mode]:
        x = block_signal(name, fs)
        blocks.append({"name": name, "start_sample": pos, "start_s": round(pos / fs, 6), "length_samples": len(x), "length_s": round(len(x) / fs, 6),
                       "peak_dbfs": round(db(np.abs(x).max()), 2)})
        if name.startswith(("clicks_panned", "noise_bursts")):
            blocks[-1]["pans"] = gen.PANS
        sigs.append((pos, x))
        pos += len(x)
    total = pos + int(round(END_S * fs))
    out = np.zeros((total, 2))
    for p, x in sigs:
        out[p:p + len(x)] = x
    manifest = {"mode": mode, "fs": fs, "format": "WAV 32-bit float stereo", "lead_s": LEAD_S, "end_s": END_S, "block_tail_s": BLOCK_TAIL_S,
                "length_s": round(total / fs, 6), "total_samples": total, "sweep": gen.SWEEP, "pan_law": "constant power: gL=cos((p+1)pi/4), gR=sin((p+1)pi/4)",
                "blocks": blocks, "note": "_rep is an identical copy of the -18 dBFS sweep; noise bursts use a fixed seed"}
    return out, manifest


def write(mode: str, outdir):
    x, m = build(mode)
    write_wav(outdir / ("probe_suite_%s.wav" % mode), x)
    return x, m


def find_offset(wet: np.ndarray, dry: np.ndarray, manifest: dict, fs: int = FS) -> int:
    """Samples by which the wet suite lags the dry one: cross-correlation of the wet file with the dry sweep_L block."""
    b = next(b for b in manifest["blocks"] if b["name"] == "sweep_L")
    blk = dry[b["start_sample"]: b["start_sample"] + b["length_samples"], 0]
    n = len(wet) + len(blk)
    N = 1 << (n - 1).bit_length()
    B = np.conj(np.fft.rfft(blk, N))
    best, best_lag = -1.0, 0
    for c in range(2):
        r = np.fft.irfft(np.fft.rfft(wet[:, c], N) * B, N)
        lo, hi = max(b["start_sample"] - 5 * fs, 0), min(b["start_sample"] + 5 * fs, len(wet))
        seg = np.abs(r[lo:hi])
        k = int(np.argmax(seg))
        if seg[k] > best:
            best, best_lag = float(seg[k]), lo + k
    return best_lag - b["start_sample"]


def split(wet_path, manifest: dict, out_dir, dry_out=None, fs: int = FS):
    """Cuts the wet suite into named block files. Returns a result dict (also used for the report)."""
    wet, notes = read_wav(wet_path)
    dry, m2 = build(manifest["mode"], fs)
    off = find_offset(wet, dry, manifest, fs)
    if abs(off) > MAX_OFFSET_S * fs:
        raise SystemExit("split: the wet file is %.3f s off the dry suite (limit %.1f s). Is it an export of the right suite, with the right start point?" % (off / fs, MAX_OFFSET_S))
    rows = []
    for b in manifest["blocks"]:
        a, e = b["start_sample"] + off, b["start_sample"] + off + b["length_samples"]
        a, e = max(a, 0), min(e, len(wet))
        seg = wet[a:e]
        write_wav(out_dir / (b["name"] + ".wav"), seg)
        pk = db(np.abs(seg).max()) if len(seg) else -999.0
        rms = db(np.sqrt(np.mean(seg ** 2))) if len(seg) else -999.0
        rows.append({"name": b["name"], "start_s": round(a / fs, 3), "length_s": round(len(seg) / fs, 3), "expected_length_s": b["length_s"], "peak_dbfs": round(pk, 2),
                     "rms_dbfs": round(rms, 2), "empty": bool(pk < EMPTY_DB), "clipped_at_file_end": bool(len(seg) < b["length_samples"])})
        if dry_out is not None:
            write_wav(dry_out / (b["name"] + ".wav"), dry[b["start_sample"]: b["start_sample"] + b["length_samples"]])
    return {"mode": manifest["mode"], "offset_samples": off, "offset_ms": round(off / fs * 1000.0, 3), "notes": notes, "blocks": rows, "wet_seconds": round(len(wet) / fs, 3)}
