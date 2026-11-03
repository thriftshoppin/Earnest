"""Generate a standalone, interactive room-analysis report from engine artifacts."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .engine.room import RoomSpec
from .engine.solve import solve_room


def _formula(path):
    if path is None:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    tail = data.get("tail", {})
    bands, decay = tail.get("bands_hz"), tail.get("rt60_s")
    if not isinstance(bands, list) or not isinstance(decay, list) or len(bands) != len(decay):
        raise ValueError("%s is not an Earnest formula with matching tail bands and RT60 values" % path)
    return {"label": str(data.get("source") or Path(path).stem), "bands_hz": bands,
            "rt60_s": decay, "tail_level_db": tail.get("level_db"),
            "iacc": tail.get("iacc"), "path": str(Path(path).resolve())}


def build(room_path, reference=None, comparison=None, output=None, sample_rate=24000, order=None):
    room_path = Path(room_path)
    doc = json.loads(room_path.read_text(encoding="utf-8-sig"))
    room = RoomSpec.from_dict(doc)
    print("visualize: solving room; this may take a moment", flush=True)
    solution = solve_room(room, fs=sample_rate, max_order=order)
    pairs = []
    for pair in solution["source_receiver_pairs"]:
        curves = {}
        for band, values in pair["band_ir"].items():
            signal = np.asarray(values, dtype=np.float64)
            energy = np.cumsum((signal * signal)[::-1])[::-1]
            indices = np.unique(np.linspace(0, max(len(energy) - 1, 0), min(320, len(energy)), dtype=int))
            peak = max(float(energy[0]), 1e-30)
            curves[band] = [[round(int(i) / sample_rate, 4), round(float(10 * np.log10(max(energy[i] / peak, 1e-12))), 2)] for i in indices]
        pairs.append({key: value for key, value in pair.items() if key != "band_ir"} | {"energy_decay_db": curves})
    model = {key: value for key, value in solution.items() if key not in ("source_receiver_pairs",)}
    model["source_receiver_pairs"] = pairs
    payload = {"room": {"path": str(room_path.resolve()), "sources": doc["sources"], "receivers": doc["receivers"]},
               "solution": model, "reference": _formula(reference), "comparison": _formula(comparison)}
    template = (Path(__file__).parent / "visualizer" / "index.html").read_text(encoding="utf-8")
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")).replace("</", "<\\/")
    html = template.replace("/*EARNEST_DATA*/", encoded)
    target = Path(output) if output else Path.cwd() / "results" / "visualizer" / "room.html"
    if target.exists():
        raise ValueError("output already exists; choose a new path: %s" % target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    print("visualize: interactive room report -> %s" % target.resolve(), flush=True)
    print("visualize: simulated paths and energy decay are model estimates; reference and comparison are supplied measurements", flush=True)
    return target.resolve()
