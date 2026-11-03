"""Deterministic comparison for aligned recordings and model hypotheses."""
from __future__ import annotations

import numpy as np
import math


def compare_audio(reference, candidate, sample_rate_hz: int) -> tuple[dict, np.ndarray]:
    """Return an explicit reference-minus-candidate residual and its band energies.

    Inputs must already be aligned, at the same sample rate and with matching
    channels and duration; no hidden gain normalization or shifting is done.
    """
    if isinstance(sample_rate_hz, bool) or not isinstance(sample_rate_hz, int) or not 8000 <= sample_rate_hz <= 384000:
        raise ValueError("sample rate must be an integer from 8000 to 384000 Hz")
    ref, pred = np.asarray(reference, dtype=np.float64), np.asarray(candidate, dtype=np.float64)
    if ref.ndim == 1:
        ref = ref[:, None]
    if pred.ndim == 1:
        pred = pred[:, None]
    if ref.ndim != 2 or ref.shape != pred.shape or not ref.size or not 1 <= ref.shape[1] <= 8:
        raise ValueError("recordings must have matching nonempty frame and channel counts (1–8 channels)")
    if not np.isfinite(ref).all() or not np.isfinite(pred).all():
        raise ValueError("recordings must contain finite samples")
    residual = ref - pred
    # Parseval energy for real FFT: double bins with distinct negative partners.
    bins = np.fft.rfftfreq(len(ref), 1.0 / sample_rate_hz)
    spectrum = np.abs(np.fft.rfft(residual, axis=0)) ** 2
    weights = np.full(len(bins), 2.0)
    weights[0] = 1.0
    if len(ref) % 2 == 0:
        weights[-1] = 1.0
    spectrum *= weights[:, None] / len(ref) ** 2
    nyquist = sample_rate_hz / 2.0
    edges = [0., 125., 250., 500., 1000., 2000., 4000., 8000., 16000., nyquist]
    edges = sorted(set(min(edge, nyquist) for edge in edges))
    channels = []
    for c in range(ref.shape[1]):
        ref_power = float(np.mean(ref[:, c] ** 2))
        error_power = float(np.mean(residual[:, c] ** 2))
        bands = []
        for i, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
            selected = (bins >= lo) & ((bins <= hi) if i == len(edges)-2 else (bins < hi))
            bands.append({"low_hz": lo, "high_hz": hi, "mean_square": float(spectrum[selected, c].sum())})
        channels.append({"channel": c, "reference_mean_square": ref_power,
                         "residual_mean_square": error_power,
                         "residual_to_reference_db": 10 * np.log10(error_power / ref_power) if ref_power > 0 and error_power > 0 else None,
                         "bands": bands})
    return {"schema": "earnest.audio-comparison.v1", "sample_rate_hz": sample_rate_hz,
            "frames": len(ref), "channels": channels,
            "limits": ["Inputs must already be sample-aligned; delay and gain are not adjusted.",
                       "Band energy is an analysis of the residual, not proof of which sources are missing.",
                       "Exact reconstruction does not establish a unique source or room explanation."]}, residual


def compare_audio_segments(reference, candidate, sample_rate_hz: int, segment_seconds: float) -> list[dict]:
    """Measure disjoint intervals, including an explicitly shorter last interval."""
    if isinstance(segment_seconds, bool) or not isinstance(segment_seconds, (int, float)) or not math.isfinite(segment_seconds) or not .01 <= segment_seconds <= 60:
        raise ValueError("segment duration must be finite and between 0.01 and 60 seconds")
    # Validate the full pair once, including rate and channel constraints.
    compare_audio(reference, candidate, sample_rate_hz)
    ref, pred = np.asarray(reference), np.asarray(candidate)
    step = max(1, round(segment_seconds * sample_rate_hz))
    if (len(ref) + step - 1) // step > 10000:
        raise ValueError("more than 10000 intervals; choose a longer segment duration")
    result = []
    for start in range(0, len(ref), step):
        end = min(start + step, len(ref))
        report, _ = compare_audio(ref[start:end], pred[start:end], sample_rate_hz)
        result.append({"start_sample": start, "end_sample_exclusive": end,
                       "start_s": start / sample_rate_hz, "end_s": end / sample_rate_hz,
                       "channels": report["channels"]})
    return result
