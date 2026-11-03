"""Room solve orchestration: paths, band impulse responses, sound-field spectra, and provenance."""
from __future__ import annotations

import math
import itertools

import numpy as np

from .room import BANDS_HZ, RoomSpec
from .shoebox import image_paths
from .physics import air_absorption_db_per_m
from .energy_metrics import energy_time_metrics
from ..dsp import bandpass_fft


def _add_fractional_impulse(signal: np.ndarray, position: float, amplitude: float) -> None:
    i = int(math.floor(position))
    frac = position - i
    if 0 <= i < len(signal):
        signal[i] += amplitude * (1.0 - frac)
    if 0 <= i + 1 < len(signal):
        signal[i + 1] += amplitude * frac


def _modal_diagnostics(dimensions: tuple[float, float, float], sound_speed: float) -> list[dict]:
    modes = []
    for index in itertools.product(range(5), repeat=3):
        if index == (0, 0, 0):
            continue
        frequency = sound_speed / 2.0 * math.sqrt(sum((index[i] / dimensions[i]) ** 2 for i in range(3)))
        modes.append({"indices": list(index), "hz": frequency})
    return sorted(modes, key=lambda mode: mode["hz"])


def _late_field(room: RoomSpec, band_index: int, direct_distance: float, reflection_energy: float,
                rt60: float | None, fs: int, seed: int) -> tuple[np.ndarray, dict]:
    areas = room.wall_areas()
    absorption_area = sum(areas[w] * room.absorption(w, band_index)
                          for w in room.surfaces)
    absorption_area += room.air_absorption_area_m2(band_index)
    if absorption_area <= 0 or rt60 is None or rt60 <= 0:
        return np.zeros(0, dtype=np.float64), {"start_s": None, "rt60_s": rt60,
                                               "target_reverb_to_direct_energy": None,
                                               "late_energy": 0.0, "reason": "no finite diffuse-field target"}
    # Diffuse-field approximation for an omnidirectional source: R/D = 16*pi*r^2/A.
    target = 16.0 * math.pi * direct_distance ** 2 / absorption_area * room.controls.diffuse_energy_scale
    late_energy = max(target - reflection_energy, 0.0)
    if late_energy == 0:
        return np.zeros(0, dtype=np.float64), {"start_s": None, "rt60_s": rt60,
                                               "target_reverb_to_direct_energy": target,
                                               "late_energy": 0.0, "reason": "explicit reflections meet or exceed diffuse-field energy estimate"}
    seconds = min(max(rt60 * 1.25 * room.controls.tail_duration_scale, 0.25), 8.0)
    t = np.arange(max(1, int(seconds * fs)), dtype=np.float64) / fs
    envelope = np.power(10.0, -3.0 * t / rt60)  # pressure envelope for a -60 dB energy decay in RT60
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(len(t)) * envelope
    noise = bandpass_fft(noise, fs, BANDS_HZ[band_index], 1)
    noise *= math.sqrt(late_energy / max(float(np.sum(noise * noise)), 1e-30))
    return noise, {"start_s": None, "rt60_s": rt60,
                   "target_reverb_to_direct_energy": target, "late_energy": late_energy,
                   "reason": "statistical diffuse tail; room-wide energy estimate"}


def solve_room(room: RoomSpec, fs: int = 48000, max_order: int | None = None) -> dict:
    """Compute per-pair, per-octave specular IRs and source-weighted band energy.

    The late field is a statistical energy-matched tail, not directional ray tracing.
    Modal frequencies are diagnostics only; no modal pressure response is synthesized.
    """
    if fs < 24000 or fs > 192000:
        raise ValueError("fs must be between 24000 and 192000 Hz for Earnest's 125 Hz-8 kHz bands")
    max_order = room.controls.reflection_order if max_order is None else max_order
    all_paths, pair_results = [], []
    c = room.sound_speed_m_s()
    for source in room.sources:
        for receiver in room.receivers:
            paths = image_paths(room, source, receiver, max_order)
            if not paths:
                raise ValueError("source %r and receiver %r have no valid direct path; check their separation" % (source.id, receiver.id))
            direct = paths[0]
            # Normalize against an omnidirectional direct path, so a directional
            # null or negative polarity remains observable and never divides by zero.
            normalization = [(10.0 ** (-air_absorption_db_per_m(f, room.temperature_c, room.humidity_percent, room.pressure_pa)
                                        * direct.distance_m / 20.0) if room.air_absorption_enabled else 1.0)
                             / direct.distance_m for f in BANDS_HZ]
            last_path_s = max((p.delay_s for p in paths), default=0.0)
            tail_start_s = last_path_s + 0.02
            decay_rows = room.decay_estimates()
            rt_by_band = [row["effective_rt60_s"] for row in decay_rows]
            tail_seconds = [min(max(rt * 1.25, 0.25), 8.0) if rt is not None and rt > 0 else 0.0 for rt in rt_by_band]
            n = max(64, int(math.ceil((tail_start_s + max(tail_seconds, default=0.05)) * fs)))
            band_ir = np.zeros((7, n), dtype=np.float64)
            for path in paths:
                sample = path.delay_s * fs
                for band, gain in enumerate(path.gain_by_band):
                    # Normalize path pressure to the direct path so outputs express room response
                    # independently of arbitrary source calibration.
                    relative_gain = gain / max(normalization[band], 1e-30)
                    _add_fractional_impulse(band_ir[band], sample, relative_gain)
            late_fields = []
            for band in range(7):
                reflection_energy = sum((path.gain_by_band[band] / max(normalization[band], 1e-30)) ** 2
                                        for path in paths if path is not direct)
                seed = sum((i + 1) * ord(ch) for i, ch in enumerate(source.id + ":" + receiver.id)) + band * 7919
                tail, tail_meta = _late_field(room, band, direct.distance_m, reflection_energy,
                                             rt_by_band[band], fs, seed)
                start_sample = int(math.ceil(tail_start_s * fs))
                if len(tail):
                    end_sample = start_sample + len(tail)
                    if end_sample > len(band_ir[band]):
                        band_ir = np.pad(band_ir, ((0, 0), (0, end_sample - band_ir.shape[1])))
                    band_ir[band, start_sample:end_sample] += tail
                    tail_meta["start_s"] = tail_start_s
                late_fields.append(tail_meta)
            spectrum_db = []
            for band in range(7):
                # Energy transfer per band, normalized to direct-path gain. Source level is an
                # optional source spectrum in dB; independent sources add in power.
                power = float(np.sum(band_ir[band] ** 2))
                spectrum_db.append(10.0 * math.log10(max(power, 1e-30)) + source.level_db[band])
            # Include the fractional direct impulse beginning at floor(delay * fs).
            arrival_index = min(int(math.floor(direct.delay_s * fs)), band_ir.shape[1] - 1)
            energy_diagnostics = [{"hz": center, **energy_time_metrics(band_ir[i], int(fs), arrival_index)}
                                  for i, center in enumerate(BANDS_HZ)]
            first = paths[0]
            reflections = [p for p in paths if p is not first]
            all_paths.append({"source_id": source.id, "receiver_id": receiver.id,
                              "paths": [{"delay_s": p.delay_s, "distance_m": p.distance_m,
                                         "image_index": list(p.image_index), "gain_by_band": list(p.gain_by_band),
                                         "directivity_gain": p.directivity_gain} for p in paths]})
            pair_results.append({"source_id": source.id, "receiver_id": receiver.id,
                                 "direct_distance_m": direct.distance_m, "direct_delay_ms": direct.delay_s * 1000,
                                 "directivity_gain": direct.directivity_gain,
                                 "path_count": len(paths),
                                 "reflection_density_per_s": len(reflections) / max(last_path_s, 1e-12),
                                 "band_energy_db": spectrum_db,
                                 "diffuse_tail_by_band": late_fields,
                                 "energy_time_metrics_by_band": energy_diagnostics,
                                 "band_ir": {str(b): band_ir[i].tolist() for i, b in enumerate(BANDS_HZ)}})

    # Independent sources add as power at each receiver. Source correlation is deliberately
    # absent from v1 and is surfaced in metadata instead of silently assuming phase coherence.
    receiver_spectra = []
    for receiver in room.receivers:
        rows = [r for r in pair_results if r["receiver_id"] == receiver.id]
        power = [sum(10 ** (row["band_energy_db"][b] / 10.0) for row in rows) for b in range(7)]
        receiver_spectra.append({"receiver_id": receiver.id,
                                 "source_weighted_energy_db": [10 * math.log10(max(v, 1e-30)) for v in power]})
    return {
        "schema": "earnest.room-solution.v1", "engine": "shoebox-image-source-v1",
        "room_schema": room.schema, "sample_rate_hz": fs,
        "bands_hz": list(BANDS_HZ), "temperature_c": room.temperature_c,
        "air_absorption_enabled": room.air_absorption_enabled,
        "humidity_percent": room.humidity_percent,
        "pressure_pa": room.pressure_pa,
        "sound_speed_m_s": c, "dimensions_m": list(room.dimensions), "volume_m3": room.volume_m3,
        "max_total_reflection_order": max_order,
        "engine_controls": {"reflection_order": max_order,
                            "decay_model": room.controls.decay_model,
                            "absorption_scale": list(room.controls.absorption_scale),
                            "scattering_scale": list(room.controls.scattering_scale),
                            "diffuse_energy_scale": room.controls.diffuse_energy_scale,
                            "tail_duration_scale": room.controls.tail_duration_scale,
                            "decay_scale": room.controls.decay_scale},
        "decay_estimates": room.decay_estimates(),
        "low_frequency_modes_hz": _modal_diagnostics(room.dimensions, c),
        "source_receiver_pairs": pair_results,
        "receiver_sound_field": receiver_spectra,
        "paths": all_paths,
        "model_limits": [
            "Rectangular shoebox geometry only; no imported mesh, occlusion, diffraction, or edge scattering.",
            "Diffuse late tail uses a statistical reverberant-energy estimate, not directional ray tracing or a measured decay fit.",
            "Band impulse responses are separate and are not phase-calibrated into a full-band waveform; energy-time diagnostics are modeled finite-window estimates, not standards-compliant measured values.",
            "Low-frequency modal frequencies are not synthesized; correlated-source cross terms are not included.",
            "Pressure gains are normalized to each source-receiver direct path; absolute SPL needs source and calibration data.",
            "When enabled, air absorption affects explicit paths and diffuse-field decay estimates; ideal frequency-independent directivity affects explicit paths only. Humidity effects on sound speed are not modeled. Measured RT60 fitting does not recover unique geometry or materials."
        ]
    }
