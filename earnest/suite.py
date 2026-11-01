"""Probe suite: every stimulus joined in ONE file so a single DAW export per effect setting gives everything `room` needs, plus `split` to cut the wet export back
into the named files. Everything downstream is manifest-driven (names, start_s, length_s); the dry signal is read from the file next to the manifest when there is one.

`full` reproduces earnest_probe_v1 (190.5 s): the nine gen blocks are generated, the three noise-width blocks are copied from the bundled reference (probe\\), because their
noise realisation cannot be regenerated from a seed. Large wet files are never loaded whole: `Source` reads and resamples segments from disk."""
from __future__ import annotations

import json
from math import gcd
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import find_peaks, resample_poly

from . import gen
from .dsp import db
from .io import FS, ROOT, read_wav, write_wav

PROBE_DIR = ROOT / "probe"
PROBE_JSON = PROBE_DIR / "earnest_probe_v1.json"
LEAD_S, END_S, BLOCK_TAIL_S = 2.0, 1.0, 6.0
MAX_OFFSET_S = 0.5
EMPTY_DB = -90.0
NOISE_REF = ("noise_mid", "noise_side", "noise_wide")
ORDER = {
    "lite": ["sweep_L", "sweep_R", "clicks_panned", "clicks_mono", "noise_bursts_panned"],
    "full": ["sweep_L", "sweep_R", "sweep_L_m30", "sweep_R_m30", "sweep_L_rep", "sweep_R_rep", "clicks_panned", "clicks_mono", "noise_bursts_panned",
             "noise_mid", "noise_side", "noise_wide"],
}
DESC = {
    "sweep_L": "exp sweep 20 Hz-16 kHz, 8 s, left only", "sweep_R": "exp sweep 20 Hz-16 kHz, 8 s, right only",
    "sweep_L_m30": "same sweep, 12 dB lower, left only (linearity)", "sweep_R_m30": "same sweep, 12 dB lower, right only (linearity)",
    "sweep_L_rep": "repeat of sweep_L (time-variance check)", "sweep_R_rep": "repeat of sweep_R (time-variance check)",
    "clicks_panned": "one-sample clicks, constant-power pans -1,-0.5,0,0.5,1, 2 s apart", "clicks_mono": "same one-sample click in both channels, 5 times, 2 s apart",
    "noise_bursts_panned": "0.5 s pink-noise bursts at pans -1,-0.5,0,0.5,1, 2 s apart",
    "noise_mid": "3 pink bursts, left = right (input correlation +1), 5 s apart", "noise_side": "3 pink bursts, left = -right (input correlation -1), 5 s apart",
    "noise_wide": "3 pink bursts, left and right independent (input correlation 0), 5 s apart",
}


def _ref_block(name: str) -> np.ndarray:
    m = json.loads(PROBE_JSON.read_text(encoding="utf-8"))
    b = next(b for b in m["blocks"] if b["name"] == name)
    x, fs = sf.read(str(PROBE_DIR / "earnest_probe_v1.flac"), start=int(round(b["start_s"] * 48000)), frames=int(round(b["length_s"] * 48000)), dtype="float64")
    return x


def block_signal(name: str, fs: int = FS) -> np.ndarray:
    t = BLOCK_TAIL_S
    if name in NOISE_REF:
        return _ref_block(name)
    if name.startswith("sweep_"):
        return gen.sweep_stereo(name[6], -30.0 if name.endswith("_m30") else gen.PEAK_DB, fs, t)   # _rep is an identical copy of the -18 dBFS sweep
    return {"clicks_panned": gen.clicks_panned, "clicks_mono": gen.clicks_mono, "noise_bursts_panned": gen.noise_bursts}[name](fs, t)


def build(mode: str, fs: int = FS):
    if mode not in ORDER:
        raise SystemExit("suite mode must be lite or full")
    blocks, pos, sigs = [], int(round(LEAD_S * fs)), []
    for name in ORDER[mode]:
        x = block_signal(name, fs)
        blocks.append({"name": name, "start_s": round(pos / fs, 6), "length_s": round(len(x) / fs, 6), "peak_dbfs": round(db(np.abs(x).max()), 2),
                       "description": DESC[name], "start_sample": pos, "length_samples": len(x)})
        sigs.append((pos, x))
        pos += len(x)
    total = pos + int(round(END_S * fs))
    out = np.zeros((total, 2))
    for p, x in sigs:
        out[p:p + len(x)] = x
    manifest = {"name": "earnest_probe_v1" if mode == "full" else "earnest_probe_lite", "mode": mode, "fs": fs, "channels": 2, "head_s": LEAD_S, "end_s": END_S,
                "tail_s": BLOCK_TAIL_S, "blocks": blocks, "total_s": round(total / fs, 6), "total_samples": total, "pan_law": "constant power: gL=cos((p+1)pi/4), gR=sin((p+1)pi/4)",
                "sweep": gen.SWEEP, "note": "_rep is an identical copy of the -18 dBFS sweep; noise_mid/side/wide are copied from the bundled reference probe"}
    return out, manifest


def write(mode: str, outdir):
    x, m = build(mode)
    write_wav(outdir / ("probe_suite_%s.wav" % mode), x)
    return x, m


# ----------------------------------------------------------------------------- manifests and dry signal

def load_manifest(path) -> dict:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    fs = int(m.get("fs", FS))
    for b in m["blocks"]:
        b.setdefault("start_sample", int(round(b["start_s"] * fs)))
        b.setdefault("length_samples", int(round(b["length_s"] * fs)))
    m.setdefault("total_samples", int(round(m["total_s"] * fs)))
    m["_path"] = str(path)
    return m


def dry_signal(manifest: dict, dry_path=None) -> np.ndarray:
    """The dry suite at 48 kHz: an explicit file, else the file next to the manifest named like it, else regenerated from the block names."""
    cands = [Path(dry_path)] if dry_path else []
    if manifest.get("_path"):
        d = Path(manifest["_path"]).parent
        cands += [d / (manifest["name"] + e) for e in (".flac", ".wav")] + [d / ("probe_suite_%s.wav" % manifest.get("mode", "full"))]
    for c in cands:
        if c.exists():
            x, _ = read_wav(c)
            if abs(len(x) - manifest["total_samples"]) <= 1:
                return x
    out = np.zeros((manifest["total_samples"], 2))
    for b in manifest["blocks"]:
        s = block_signal(b["name"])
        out[b["start_sample"]: b["start_sample"] + len(s)] = s[: manifest["total_samples"] - b["start_sample"]]
    return out


# ----------------------------------------------------------------------------- lazy source (never loads a big file whole)

class Source:
    def __init__(self, path):
        self.path = str(path)
        self.info = sf.info(self.path)
        self.fs_in, self.n_in = self.info.samplerate, self.info.frames
        g = gcd(self.fs_in, FS)
        self.up, self.down = FS // g, self.fs_in // g
        self.n = int(self.n_in * self.up // self.down)

    def read(self, a: int, b: int) -> np.ndarray:
        """48 kHz samples [a, b) as float64 (n, 2), zero-padded outside the file. Reads only the needed source range, plus a margin for the resampler."""
        a0, b0 = max(a, 0), min(b, self.n)
        out = np.zeros((b - a, 2))
        if b0 <= a0:
            return out
        m = 2000 // self.down + 2
        al = (a0 // self.up - m) * self.up              # 48k index aligned to a whole source sample
        s0 = max(al // self.up * self.down, 0)
        al = s0 // self.down * self.up
        s1 = min(-(-b0 * self.down // self.up) + 2000, self.n_in)
        x, _ = sf.read(self.path, start=s0, frames=s1 - s0, dtype="float64", always_2d=True)
        x = x[:, :2] if x.shape[1] >= 2 else np.repeat(x, 2, axis=1)
        if self.up != self.down:
            x = resample_poly(x, self.up, self.down, axis=0)
        seg = x[a0 - al: b0 - al]
        out[a0 - a: a0 - a + len(seg)] = seg
        return out

    def chunks(self, size: int, overlap: int):
        a = 0
        while a < self.n:
            yield a, self.read(a, min(a + size, self.n))
            if a + size >= self.n:
                break
            a += size - overlap


def find_copies(src: Source, dry: np.ndarray, manifest: dict, n: int):
    """Positions (48 kHz samples) of the start of each of n copies of the suite, in time order, found independently by cross-correlating the dry sweep_L block with the
    wet file in chunks. Returns (positions, info). Copies that left no trace (silent passes) are placed from the gaps between the found ones and listed in info['inferred']."""
    b = next(b for b in manifest["blocks"] if b["name"] == "sweep_L")
    blk = dry[b["start_sample"]: b["start_sample"] + b["length_samples"], 0]
    total = manifest["total_samples"]
    size, overlap = 40 * FS, len(blk) + FS
    N = 1 << (size + len(blk) - 1).bit_length()
    B = np.conj(np.fft.rfft(blk, N))
    cands = []
    for a, x in src.chunks(size, overlap):
        best = None
        for c in range(2):
            r = np.abs(np.fft.irfft(np.fft.rfft(x[:, c], N) * B, N)[: max(len(x) - len(blk) + 1, 1)])
            best = r if best is None else np.maximum(best, r)
        pk, _ = find_peaks(best, distance=FS)
        top = pk[np.argsort(best[pk])[::-1][:60]]
        cands += [(a + int(p) - b["start_sample"], float(best[p])) for p in top]
    if not cands:
        return [], {"inferred": [], "strengths": []}
    cands.sort(key=lambda t: -t[1])
    top_v = cands[0][1]
    minsep = total // 2
    acc = []
    for p, v in cands:
        if v < 0.03 * top_v or len(acc) >= n:
            break
        if all(abs(p - q) >= minsep for q, _ in acc):
            acc.append((p, v))
    fixed = []
    for p, v in acc:           # a repeat of sweep_L inside the same copy correlates just as strongly: take the earliest comparable peak
        early = [q for q, w in cands if p - minsep < q < p and w >= 0.6 * v and all(abs(q - r) >= minsep for r, _ in acc if r != p)]
        fixed.append((min(early + [p]), v))
    fixed.sort()
    pos = [p for p, _ in fixed]
    inferred = []
    if len(pos) < n:
        slot = total
        for _ in range(n - len(pos)):
            gaps = [(pos[i + 1] - pos[i], i) for i in range(len(pos) - 1)]
            lead, trail = (pos[0] if pos else 0), (src.n - (pos[-1] + slot) if pos else src.n)
            # a missing (silent) copy is only placed where a whole copy fits: in a gap of two slots or more, before the first copy, or after the last
            opts = [(g - slot, "gap", i) for g, i in gaps if g >= 1.8 * slot] + ([(lead - slot, "lead", -1)] if lead >= 1.8 * slot else []) +                    ([(trail, "trail", len(pos) - 1)] if trail >= 0.8 * slot else [])
            if not opts:
                break
            ex, kind, i = max(opts)
            if kind == "gap":
                new = pos[i] + (pos[i + 1] - pos[i]) // 2
                new = max(pos[i] + slot, min(new, pos[i + 1] - slot))
            elif kind == "lead":
                new = max(pos[0] - slot - (ex // 2), 0)
            else:
                new = pos[-1] + slot + (ex // 2)
            pos.append(new)
            pos.sort()
            inferred.append(new)
    return pos, {"inferred": inferred, "strengths": [round(v / top_v, 3) for _, v in fixed]}


def _band_gain(dry_blk: np.ndarray, wet_blk: np.ndarray, lo=200.0, hi=8000.0) -> float:
    n = max(len(dry_blk), len(wet_blk))
    N = 1 << (n - 1).bit_length()
    f = np.fft.rfftfreq(N, 1.0 / FS)
    sel = (f >= lo) & (f <= hi)
    X, Y = np.fft.rfft(dry_blk, N), np.fft.rfft(wet_blk, N)
    return float(np.sqrt(np.sum(np.abs(Y[sel]) ** 2) / max(np.sum(np.abs(X[sel]) ** 2), 1e-30)))


def calibrate(blocks_of, dry: np.ndarray, manifest: dict) -> dict:
    """One gain factor G from the Mix 0 pass: its sweep_L block against the generated dry block over 200 Hz-8 kHz, if that pass is clean dry.
    `blocks_of(name)` returns that pass's wet block (48 kHz). Returns dict(G, G_db, ok, warnings)."""
    by = {b["name"]: b for b in manifest["blocks"]}
    out = {"G": 1.0, "G_db": 0.0, "ok": False, "warnings": [], "checks": {}}
    sw = by["sweep_L"]
    dry_sw = dry[sw["start_sample"]: sw["start_sample"] + sw["length_samples"], 0]
    w = blocks_of("sweep_L")
    if len(w) == 0 or db(np.abs(w).max()) < EMPTY_DB:
        out["warnings"].append("the Mix 0 pass is empty (peak under -90 dBFS): no calibration")
        return out
    # offset inside the block is already removed by the cut; use the L channel (the dry sweep is left only)
    n = min(len(dry_sw), len(w))
    G = _band_gain(dry_sw[:n], w[:n, 0])
    ok = True
    if "clicks_mono" in by:
        c = blocks_of("clicks_mono")
        corr = float(np.corrcoef(c[:, 0], c[:, 1])[0, 1]) if len(c) and c[:, 0].std() > 0 and c[:, 1].std() > 0 else 0.0
        out["checks"]["clicks_mono_LR_corr"] = round(corr, 4)
        if corr < 0.99:
            ok = False
            out["warnings"].append("the Mix 0 pass is not clean dry: L/R correlation of its clicks_mono block is %.3f (needs 0.99 or more)" % corr)
    t0 = int((gen.SWEEP["lead_s"] + gen.SWEEP["seconds"] + 0.5) * FS)
    tail = w[t0:, 0]
    peak = float(np.abs(w[:, 0]).max())
    if len(tail) and peak > 0:
        tdb = db(np.abs(tail).max() / peak)
        out["checks"]["tail_after_sweep_db_re_peak"] = round(tdb, 1)
        if tdb > -80:
            ok = False
            out["warnings"].append("the Mix 0 pass is not clean dry: a tail at %.1f dB re peak follows its sweep (needs below -80 dB)" % tdb)
    if ok:
        out.update({"G": G, "G_db": round(db(G), 3), "ok": True})
    else:
        out["warnings"].append("continuing WITHOUT level calibration (levels stay as exported; measured band gain would have been %.2f dB)" % db(G))
    out["measured_G_db"] = round(db(G), 3)
    return out


def plan_steps(wet_path, manifest: dict, repeats: int = 1, labels=None, dry_path=None):
    """Finds the copies. Returns (source, dry, steps, info); each step is {index, label, start (48 kHz samples), inferred}."""
    src = Source(wet_path)
    dry = dry_signal(manifest, dry_path)
    pos, info = find_copies(src, dry, manifest, repeats)
    if len(pos) < repeats:
        raise SystemExit("split: found %d of %d copies of the suite in %s (the others could not be placed)" % (len(pos), repeats, wet_path))
    steps = [{"index": i + 1, "label": (labels[i] if labels else None), "start": p, "inferred": p in info["inferred"]} for i, p in enumerate(pos)]
    return src, dry, steps, info


def cut_blocks(src: Source, manifest: dict, start: int, names=None):
    """Every block (or the named ones) of one copy that starts at `start`, as {name: (n, 2)}; short when the file ends early."""
    out = {}
    for b in manifest["blocks"]:
        if names and b["name"] not in names:
            continue
        a = start + b["start_sample"]
        out[b["name"]] = src.read(a, a + b["length_samples"])
    return out


def block_stats(x: np.ndarray):
    pk = db(np.abs(x).max()) if len(x) else -999.0
    rms = db(np.sqrt(np.mean(x ** 2))) if len(x) else -999.0
    return round(pk, 2), round(rms, 2)


def step_dirname(st) -> str:
    return "step%d_mix%s" % (st["index"], st["label"]) if st["label"] is not None else "step%d" % st["index"]


def run_split(wet_path, manifest_path, out_dir, dry_out=None, repeats: int = 1, labels=None, dry_path=None, calibrate_last: bool = True, write_files: bool = True):
    """The `split` command. One copy (repeats=1, no labels) writes <name>.wav into out_dir; several copies write step folders. Returns the result dict used by the report."""
    manifest = load_manifest(manifest_path)
    if labels and len(labels) != repeats:
        raise SystemExit("split: %d labels for %d repeats" % (len(labels), repeats))
    src, dry, steps, info = plan_steps(wet_path, manifest, repeats, labels, dry_path)
    notes = []
    if src.fs_in != FS:
        notes.append("wet file resampled from %d Hz to %d Hz" % (src.fs_in, FS))
    notes.append("wet file format: %s, %d Hz, %d channels" % (src.info.subtype, src.fs_in, src.info.channels))
    if src.info.subtype in ("PCM_16", "PCM_U8"):
        notes.append("16-bit file: quantisation floor near -90 dBFS; long tails will be cut by it (see the decay range per band in the room reports)")
    cal = {"G": 1.0, "G_db": 0.0, "ok": False, "warnings": [], "checks": {}, "applied": False}
    if calibrate_last and labels and labels[-1] in (0, "0"):
        last = steps[-1]
        names = ("sweep_L", "clicks_mono")
        raw = cut_blocks(src, manifest, last["start"], names)
        cal = calibrate(lambda n: raw[n], dry, manifest)
        cal["applied"] = bool(cal["ok"])
    elif calibrate_last and labels:
        cal["warnings"].append("the last label is %s, not 0: no Mix 0 pass to calibrate from" % labels[-1])
    G = cal["G"] if cal["ok"] else 1.0
    result = {"mode": manifest.get("mode"), "manifest": manifest.get("name"), "notes": notes, "calibration": cal, "wet_seconds": round(src.n / FS, 3), "steps": []}
    out_dir = Path(out_dir)
    for st in steps:
        blocks = cut_blocks(src, manifest, st["start"])
        rows = []
        folder = out_dir / step_dirname(st) if (repeats > 1 or labels) else out_dir
        if write_files:
            folder.mkdir(parents=True, exist_ok=True)
        for b in manifest["blocks"]:
            x = blocks[b["name"]]
            pk, rms = block_stats(x)
            short = len(x) and False
            rows.append({"name": b["name"], "peak_dbfs": pk, "rms_dbfs": rms, "empty": bool(pk < EMPTY_DB), "length_s": round(len(x) / FS, 3)})
            if write_files:
                write_wav(folder / (b["name"] + ".wav"), x / G)
                if dry_out is not None:
                    dd = Path(dry_out) / (step_dirname(st) if (repeats > 1 or labels) else "")
                    dd.mkdir(parents=True, exist_ok=True)
                    write_wav(dd / (b["name"] + ".wav"), dry[b["start_sample"]: b["start_sample"] + b["length_samples"]])
        cut_short = (st["start"] + manifest["total_samples"]) > src.n + FS
        result["steps"].append({"index": st["index"], "label": st["label"], "start_s": round(st["start"] / FS, 3), "offset_ms": round(st["start"] / FS * 1000.0, 3),
                                "start_sample": int(st["start"]), "inferred": st["inferred"], "folder": str(folder), "blocks": rows,
                                "empty_blocks": [r["name"] for r in rows if r["empty"]], "cut_short": bool(cut_short),
                                "all_empty": all(r["empty"] for r in rows if r["name"].startswith("sweep_"))})
    return result
