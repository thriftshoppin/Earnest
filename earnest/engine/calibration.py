"""Fit room-level absorption controls from Earnest's measured reverb formula."""
from __future__ import annotations

import math

from .room import BANDS_HZ, RoomSpec
from .solve import solve_room


def _target_absorption_scale(room: RoomSpec, band: int, target_rt60: float) -> tuple[float, float]:
    """Find the uniform per-band coefficient scale matching the room's selected decay equation."""
    areas = room.wall_areas()
    surface_area = sum(areas.values())
    constant = 24.0 * math.log(10.0) / room.sound_speed_m_s()

    def predict(scale: float) -> float:
        alpha_area = sum(areas[w] * min(1.0, room.surfaces[w].absorption[band] * scale)
                         for w in room.surfaces)
        mean_alpha = alpha_area / surface_area
        if room.controls.decay_model == "sabine":
            denominator = alpha_area
        else:
            denominator = -surface_area * math.log1p(-mean_alpha) if mean_alpha < 1.0 else math.inf
        denominator += room.air_absorption_area_m2(band)
        if math.isinf(denominator):
            return 0.0
        return constant * room.volume_m3 / denominator if denominator > 0 else math.inf

    low, high = 0.0, 20.0
    for _ in range(64):
        middle = (low + high) / 2.0
        if predict(middle) > target_rt60:
            low = middle
        else:
            high = middle
    scale = (low + high) / 2.0
    return scale, predict(scale)


def fit_formula(room_document: dict, formula: dict, reverb_type: str | None = None) -> dict:
    """Return a copied room document with calibrated absorption scales and provenance."""
    input_schema = formula.get("schema") if isinstance(formula, dict) else None
    if isinstance(formula, dict) and formula.get("schema") == "earnest.measurement.v1":
        rows = formula.get("bands")
        if not isinstance(rows, list):
            raise ValueError("earnest.measurement.v1 requires a bands array")
        fields = ("rt60_s", "edt_s", "level_db", "pre_delay_ms", "buildup_ms", "iacc", "modulation")
        normalized = {"version": 1, "source": formula.get("source", "third-party measurement"),
                      "reverb_type": formula.get("reverb_type"),
                      "plugin_metadata": formula.get("plugin_metadata", {}),
                      "early_taps": formula.get("early_taps", {"taps": []}), "tail": {"bands_hz": [], **{key: [] for key in fields}}}
        for row in rows:
            if not isinstance(row, dict) or "hz" not in row:
                raise ValueError("each measurement band needs an hz value")
            normalized["tail"]["bands_hz"].append(int(row["hz"]))
            for key in fields:
                normalized["tail"][key].append(row.get(key, row.get("tail_level_db") if key == "level_db" else None))
        formula = normalized
    if not isinstance(formula, dict) or formula.get("version") != 1 or not isinstance(formula.get("tail"), dict):
        raise ValueError("analysis must be an Earnest formula.json or earnest.measurement.v1 JSON")
    tail = formula["tail"]
    bands = tail.get("bands_hz")
    times = tail.get("rt60_s")
    if not isinstance(bands, list) or not isinstance(times, list) or len(bands) != len(times):
        raise ValueError("formula tail must contain matching bands_hz and rt60_s arrays")
    measured = {int(hz): value for hz, value in zip(bands, times)}
    room = RoomSpec.from_dict(room_document)
    prior_controls = room_document.get("engine_controls") or {}
    scales = list(prior_controls.get("absorption_scale", [1.0] * len(BANDS_HZ)))
    fit = []
    for index, hz in enumerate(BANDS_HZ):
        value = measured.get(hz)
        if value is None or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            fit.append({"hz": hz, "measured_rt60_s": value, "status": "no usable measured decay; previous scale kept"})
            continue
        scale, predicted = _target_absorption_scale(room, index, float(value))
        scales[index] = scale
        finite_prediction = predicted if math.isfinite(predicted) else None
        matched = finite_prediction is not None and math.isclose(finite_prediction, float(value), rel_tol=1e-5, abs_tol=1e-8)
        fit.append({"hz": hz, "measured_rt60_s": float(value), "predicted_rt60_s": finite_prediction,
                    "absorption_scale": scale, "status": "fit" if matched else "boundary"})
    usable_rt = [float(v) for v in times if isinstance(v, (int, float)) and math.isfinite(v) and v > 0]
    modulation = tail.get("modulation") or []
    modulated_bands = [int(bands[i]) for i, item in enumerate(modulation)
                       if i < len(bands) and item is not None]
    tap_data = formula.get("early_taps") or {}
    tap_count = len(tap_data.get("taps", [])) if isinstance(tap_data, dict) else 0
    median_rt = sorted(usable_rt)[len(usable_rt) // 2] if usable_rt else None
    if len(modulated_bands) >= 2:
        character = "modulated-tail evidence"
    elif median_rt is not None and median_rt <= 0.35 and tap_count >= 3:
        character = "short, reflection-rich room-like response"
    elif median_rt is not None and median_rt >= 1.2 and tap_count >= 3:
        character = "long, diffuse hall-like response"
    elif tap_count == 0:
        character = "decay measured; early geometry unresolved"
    else:
        character = "mixed or ambiguous reverb evidence"
    plugin_metadata = formula.get("plugin_metadata") or {}
    if not isinstance(plugin_metadata, dict):
        plugin_metadata = {"raw": plugin_metadata}
    source_label = reverb_type or formula.get("reverb_type") or plugin_metadata.get("reverb_type")
    updated = dict(room_document)
    updated["engine_controls"] = dict(prior_controls)
    updated["engine_controls"]["absorption_scale"] = scales
    updated["analysis_evidence"] = {
        "schema": "earnest.room-analysis.v1",
        "source_type": "third_party_measurement" if input_schema == "earnest.measurement.v1" else "measured_reverb_formula",
        "input_schema": input_schema or "earnest.reverb-formula.v1",
        "source": formula.get("source", ""), "reverb_class": source_label or "unclassified",
        "fit_decay_model": room.controls.decay_model,
        "plugin_metadata": plugin_metadata, "inferred_character": character,
        "modulation_detected_bands_hz": modulated_bands,
        "median_measured_rt60_s": median_rt, "early_tap_count": tap_count,
        "measured_tail": {key: tail.get(key) for key in
                          ("bands_hz", "level_db", "rt60_s", "edt_s", "pre_delay_ms", "buildup_ms", "iacc", "modulation")},
        "early_taps": formula.get("early_taps"),
        "fit": fit,
        "interpretation": "Character is a heuristic description of measured decay and reflections, not a plugin-family identification. Measured decay seeds editable room controls but cannot uniquely identify geometry or per-wall materials."
    }
    return updated


def solve_room_from_analysis(room_document: dict, formula: dict,
                             reverb_type: str | None = None,
                             sample_rate: int = 48000,
                             reflection_order: int | None = None) -> dict:
    """Translate measured acoustic evidence into room controls, then solve that room.

    User-authored geometry, surface assignments, source positions and receiver
    positions are retained. The fit only adjusts per-band absorption scales.
    The returned hypothesis is an equivalent acoustic fit, not a unique room
    reconstruction.
    """
    calibrated = fit_formula(room_document, formula, reverb_type)
    room = RoomSpec.from_dict(calibrated)
    solution = solve_room(room, fs=sample_rate, max_order=reflection_order)
    solution["analysis_translation"] = {
        "schema": "earnest.analysis-room-translation.v1",
        "input_schema": calibrated["analysis_evidence"]["input_schema"],
        "fit_decay_model": room.controls.decay_model,
        "fitted_controls": "per-band absorption scales",
        "fixed_room_inputs": ["geometry.dimensions", "surfaces", "sources", "receivers"],
        "interpretation": "Measured decay constrains an equivalent acoustic fit; it does not uniquely recover room geometry or materials."
    }
    return {"calibrated_room": calibrated, "room_solution": solution,
            "fit": calibrated["analysis_evidence"]}
