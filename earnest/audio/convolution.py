"""Compile a room into causal filters for the Windows block convolver.

The offline renderer uses a zero-phase band bank. We retain a finite amount of
its pre-response as deliberate lookahead; this is an approximation, not a
sample-exact replacement for the offline renderer.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import struct

import numpy as np

from ..engine.room import RoomSpec
from ..engine.solve import solve_room
from ..engine.render import render_room
from ..engine.spatial import LAYOUTS


def compile_room(room_file, output, sample_rate=48000, layout="stereo", receiver_id=None,
                 order=None, dry=0.78, wet=0.55, lookahead_ms=85.0):
    if layout not in LAYOUTS:
        raise ValueError("unsupported channel layout: " + layout)
    if not all(np.isfinite(v) and 0 <= v <= 2.5 for v in (dry, wet)):
        raise ValueError("dry and wet gains must be finite and between 0 and 2.5")
    if not np.isfinite(lookahead_ms) or not 10 <= lookahead_ms <= 500:
        raise ValueError("lookahead must be between 10 and 500 ms")
    path = Path(room_file)
    room = RoomSpec.from_dict(json.loads(path.read_text(encoding="utf-8-sig")))
    receiver = next((r for r in room.receivers if r.id == receiver_id), None) if receiver_id else room.receivers[0]
    if receiver is None:
        raise ValueError("unknown receiver: " + str(receiver_id))
    channels = LAYOUTS[layout]
    sources = {s.id.upper(): s for s in room.sources}
    fallback = room.sources[0]
    lead = int(round(sample_rate * lookahead_ms / 1000))
    impulse = np.zeros((lead * 2 + 1, 1))
    impulse[lead, 0] = 1.0
    filters = []
    mapping = []
    for channel in channels:
        if channel == "LFE":
            kernel = np.zeros(len(impulse), dtype=np.float32)
            kernel[lead] = dry
            mapping.append("LFE: direct only")
        else:
            source = sources.get(channel, fallback)
            mapping.append(channel + ": " + source.id + (" (fallback)" if source is fallback and channel not in sources else ""))
            one = replace(room, sources=(source,), receivers=(receiver,))
            print("bridge: solving %s using source %s" % (channel, source.id), flush=True)
            solution = solve_room(one, fs=sample_rate, max_order=order)
            result = render_room(one, solution, impulse, sample_rate)["receiver_outputs"][receiver.id]
            direct = result["direct_audio"]
            kernel = np.asarray(dry * direct + wet * (result["audio"] - direct), dtype=np.float32)
        if not np.isfinite(kernel).all():
            raise ValueError("room produced non-finite filter samples")
        filters.append(kernel)
    length = max(map(len, filters))
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        handle.write(struct.pack("<4sIIII", b"ERIR", 1, sample_rate, len(channels), length))
        for kernel in filters:
            padded = np.zeros(length, dtype="<f4")
            padded[:len(kernel)] = kernel
            handle.write(padded.tobytes())
    return {"room": str(path.resolve()), "receiver": receiver.id, "layout": layout,
            "mapping": mapping, "sample_rate": sample_rate, "lookahead_ms": lookahead_ms,
            "filter_frames": length, "profile": str(target.resolve())}
