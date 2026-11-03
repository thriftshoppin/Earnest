"""Create and inspect repeatable dry/wet black-box capture sets."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf

from . import suite
from .io import FS, write_wav


def create_kit(out: str | Path, room_name: str = "Union Stairs", gain_db: float = -6.0) -> Path:
    if not math.isfinite(gain_db) or not -48 <= gain_db <= 0:
        raise ValueError("probe gain must be finite and between -48 and 0 dB")
    target = Path(out)
    if target.exists() and any(target.iterdir()):
        raise ValueError("capture kit folder must be new or empty: %s" % target)
    target.mkdir(parents=True, exist_ok=True)
    (target / "captures").mkdir()
    print("capture-kit: generating full stereo probe at %+.1f dB relative to the original" % gain_db, flush=True)
    signal, manifest = suite.build("full")
    signal *= 10 ** (gain_db / 20.0)
    manifest["reference_gain_db"] = gain_db
    for block in manifest["blocks"]:
        block["peak_dbfs"] = round(block["peak_dbfs"] + gain_db, 2)
    manifest["note"] += "; all blocks scaled by %+.1f dB; use the probe file as the dry stimulus" % gain_db
    write_wav(target / "probe_suite_full.wav", signal)
    (target / "probe_suite_full.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    plan = {"schema": "earnest.capture-kit.v1", "room_name": room_name,
            "sample_rate_hz": FS, "channels": 2, "probe_file": "probe_suite_full.wav",
            "probe_manifest": "probe_suite_full.json", "probe_gain_db": gain_db,
            "takes": [
                {"file": "dry.wav", "role": "dry", "notes": "same source, effect bypassed"},
                *[{"file": "union100_rep%d.wav" % i, "role": "wet_repeat", "mix_percent": 100,
                   "repeat": i} for i in range(1, 4)]],
            "limitation": "Raw captures are evidence, not a trained model; the plugin's internal state is not observed."}
    (target / "capture-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    guide = f"""# {room_name}: first black-box capture

## What to do in the DAW

1. Import `probe_suite_full.wav` onto one stereo track at 48 kHz. Keep it at unity gain; leave pan centered.
2. Export it with the reverb bypassed as 32-bit float stereo WAV: `captures/dry.wav`.
3. Choose the {room_name} preset, set its mix to 100% wet, and keep every other control fixed.
4. Export three separate passes named `captures/union100_rep1.wav`, `union100_rep2.wav`, and `union100_rep3.wav`.
5. Use the same sample rate, start position, routing, output gain, and export length for every pass. Include the probe's full ending. Disable normalization and unrelated processing.
6. Check that no stage, including the plugin itself, clips. If it clips internally, lower the source before the effect and export a new matching dry reference at that same source level. If only the export clips, reduce output after the effect for all takes and document that gain.
7. Run `python -m earnest capture-check "{target.resolve()}"` from the Earnest folder.

The suite already contains separate left/right sweeps, repeats, two sweep levels, clicks, and stereo noise. Do not split or change its channels in the DAW. The checked-in manifest describes their positions.

Keep a note of plugin version, preset, all visible controls, sample rate, source gain, output gain, and export format. Never overwrite these captures with normalized files. `capture-check` checks file format, approximate duration and near-full-scale samples; it does not prove that the correct preset, routing, alignment, or unclipped internal processing was used.

## After capture

From the Earnest folder, run the following for the first repeat; change `rep1` to `rep2` and `rep3` for the other two:

```powershell
python -m earnest analyze "{target.resolve()}\\captures\\union100_rep1.wav" --room "{room_name}" --mix 100 --manifest "{target.resolve()}\\probe_suite_full.json" --probe "{target.resolve()}\\probe_suite_full.wav" --dry "{target.resolve()}\\captures\\dry.wav" --out "{target.resolve()}\\analysis\\rep1"
```

These are measurement inputs; no neural training or blind test is performed by creating this kit.
"""
    (target / "README.md").write_text(guide, encoding="utf-8")
    return target.resolve()


def check_kit(folder: str | Path) -> dict:
    root = Path(folder)
    plan = json.loads((root / "capture-plan.json").read_text(encoding="utf-8"))
    if plan.get("schema") != "earnest.capture-kit.v1":
        raise ValueError("unsupported capture plan schema")
    manifest = json.loads((root / plan["probe_manifest"]).read_text(encoding="utf-8"))
    expected_s = float(manifest["total_s"])
    rows = []
    for take in plan["takes"]:
        path = root / "captures" / take["file"]
        row = {"file": take["file"], "role": take["role"], "exists": path.is_file(), "warnings": []}
        if path.is_file():
            with sf.SoundFile(str(path)) as stream:
                row.update(sample_rate_hz=stream.samplerate, channels=stream.channels,
                           duration_s=round(len(stream) / stream.samplerate, 4), subtype=stream.subtype)
                peak, full_scale = 0., 0
                for block in stream.blocks(blocksize=262144, dtype="float32", always_2d=True):
                    if not np.isfinite(block).all():
                        row["warnings"].append("non-finite samples found")
                        break
                    peak = max(peak, float(np.max(np.abs(block))))
                    full_scale += int(np.count_nonzero(np.abs(block) >= 0.999969))
                row.update(peak=round(peak, 7), samples_at_or_near_full_scale=full_scale)
                if stream.samplerate != FS or stream.channels != 2:
                    row["warnings"].append("expected 48 kHz stereo")
                if abs(row["duration_s"] - expected_s) > 0.1:
                    row["warnings"].append("duration differs from probe; check export boundaries and tail")
                if peak == 0:
                    row["warnings"].append("file is silent")
                if full_scale:
                    row["warnings"].append("samples at or near full scale; inspect for clipping")
        else:
            row["warnings"].append("capture not yet present")
        rows.append(row)
    return {"schema": "earnest.capture-check.v1", "room_name": plan["room_name"],
            "expected_duration_s": expected_s, "takes": rows,
            "limits": ["No alignment, preset, internal clipping, audio quality, or model fit verification."]}
