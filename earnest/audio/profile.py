"""Translate a solved Earnest room into the live-router profile contract."""
from __future__ import annotations

import math
from typing import Any


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_live_profile(solution: dict[str, Any], dry_mix: float = 0.78,
                       wet_mix: float = 0.55) -> dict[str, Any]:
    """Make a deterministic live profile without pretending the band IRs are phase coherent.

    The full solved octave-band response stays in ``source_solution``. The current
    real-time host consumes the median RT60 as its FDN feedback target and preserves
    early reflection timing/gain data for the multiband convolution component.
    """
    if solution.get("schema") != "earnest.room-solution.v1":
        raise ValueError("expected earnest.room-solution.v1")
    controls = solution.get("engine_controls") or {}
    decay_key = "%s_rt60_s" % controls.get("decay_model", "eyring")
    rt60 = []
    for row in solution.get("decay_estimates", []):
        value = _finite(row.get(decay_key))
        if value is None and decay_key != "sabine_rt60_s":
            value = _finite(row.get("sabine_rt60_s"))
        if value is not None and 0.02 < value < 30:
            rt60.append(value)
    if not rt60:
        raise ValueError("room solution has no finite RT60 estimate")

    pair = (solution.get("source_receiver_pairs") or [None])[0]
    if not isinstance(pair, dict):
        raise ValueError("room solution has no source/receiver pair")
    path_group = next((entry for entry in solution.get("paths", [])
                       if entry.get("source_id") == pair.get("source_id")
                       and entry.get("receiver_id") == pair.get("receiver_id")), {})
    paths = list(path_group.get("paths") or [])
    direct = paths[0] if paths else None
    direct_gains = (direct or {}).get("gain_by_band") or [1.0] * 7
    early = []
    for path in paths[1:]:
        delay_s = _finite(path.get("delay_s"))
        gains = path.get("gain_by_band") or []
        if delay_s is None or delay_s > 0.120 or len(gains) != len(direct_gains):
            continue
        ratios = [abs(float(gain)) / max(abs(float(reference)), 1e-20)
                  for gain, reference in zip(gains, direct_gains)]
        # RMS across octave bands is a broadband pressure approximation only.
        gain = math.sqrt(sum(value * value for value in ratios) / len(ratios))
        early.append({"delay_ms": round(delay_s * 1000.0, 4),
                      "broadband_gain": round(min(gain, 2.0), 6),
                      "gain_by_band_relative": [round(value, 6) for value in ratios]})
    early.sort(key=lambda item: item["delay_ms"])

    return {
        "schema": "earnest.live-room-profile.v1",
        "sample_rate_hz": int(solution.get("sample_rate_hz", 48000)),
        "dry_mix": max(0.0, min(1.0, float(dry_mix))),
        "wet_mix": max(0.0, min(1.0, float(wet_mix))),
        "rt60_s": [round(value, 6) for value in rt60],
        "bands_hz": list(solution.get("bands_hz") or []),
        "early_reflections": early[:32],
        "source_solution": {
            "source_id": pair.get("source_id"), "receiver_id": pair.get("receiver_id"),
            "direct_delay_ms": pair.get("direct_delay_ms"),
            "reflection_density_per_s": pair.get("reflection_density_per_s"),
            "engine_controls": controls,
        },
        "host_contract": {
            "processor": "fdn-rt60-adapter-v1",
            "uses_now": ["median octave-band RT60", "dry/wet controls"],
            "reserved_for_multiband_convolution": ["per-band RT60", "early_reflections"],
            "limit": "The live FDN is a real-time room adapter, not a phase-coherent convolution of the separate octave-band solver IRs."
        },
    }
