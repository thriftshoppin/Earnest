"""Compile a StageJack control session with the authoritative room solver."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .convolution import compile_room


def main():
    p = argparse.ArgumentParser()
    p.add_argument("room")
    p.add_argument("profile")
    p.add_argument("--wet", type=int, default=100)
    p.add_argument("--tail", type=int, default=100)
    p.add_argument("--decay", type=int, default=100)
    p.add_argument("--absorption", type=int, default=100)
    p.add_argument("--scattering", type=int, default=100)
    p.add_argument("--diffusion", type=int, default=100)
    a = p.parse_args()
    for value in (a.wet, a.tail, a.decay, a.absorption, a.scattering, a.diffusion):
        if not 0 <= value <= 250:
            p.error("control values must be between 0 and 250")
    if a.tail < 10 or a.decay < 10:
        p.error("tail and decay must be at least 10 percent")
    room = json.loads(Path(a.room).read_text(encoding="utf-8-sig"))
    controls = room.setdefault("engine_controls", {})
    controls["decay_scale"] = max(0.1, min(2.5, controls.get("decay_scale", 1.0) * a.decay / 100))
    controls["tail_duration_scale"] = max(0.1, min(4.0, controls.get("tail_duration_scale", 1.0) * a.tail / 100))
    for key, percent in (("absorption_scale", a.absorption), ("scattering_scale", a.scattering)):
        controls[key] = [min(20.0, x * percent / 100) for x in controls.get(key, [1.0] * 7)]
    controls["diffuse_energy_scale"] = min(10.0, controls.get("diffuse_energy_scale", 1.0) * a.diffusion / 100)
    profile = Path(a.profile)
    profile.parent.mkdir(parents=True, exist_ok=True)
    configured = profile.with_suffix(".room.json")
    configured.write_text(json.dumps(room, indent=2) + "\n", encoding="utf-8")
    # The present route returns only the wet field. 0.0001 is a conservative
    # experimental gain because the selected endpoints may form a feedback loop.
    print("STAGEJACK // compiling %s at %s%% wet" % (a.room, a.wet), flush=True)
    result = compile_room(configured, profile, dry=0, wet=0.0001 * a.wet / 100)
    print("STAGEJACK // profile ready: " + result["profile"], flush=True)


if __name__ == "__main__":
    main()
