"""Offline frequency focus for investigating a mix."""
from __future__ import annotations
import math
import numpy as np
from scipy.signal import butter, sosfiltfilt


def focus_band(samples, sample_rate_hz: int, low_hz: float, high_hz: float):
    if isinstance(sample_rate_hz, bool) or not isinstance(sample_rate_hz, int) or not 8000 <= sample_rate_hz <= 384000:
        raise ValueError('sample rate must be an integer from 8000 to 384000 Hz')
    low, high = float(low_hz), float(high_hz)
    if not math.isfinite(low) or not math.isfinite(high) or not 0 < low < high < sample_rate_hz / 2:
        raise ValueError('band must satisfy 0 < low < high < Nyquist')
    audio = np.asarray(samples, dtype=np.float64)
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.ndim != 2 or len(audio) < 64 or not 1 <= audio.shape[1] <= 8 or not np.isfinite(audio).all():
        raise ValueError('audio must have at least 64 finite frames and 1–8 channels')
    # Fourth-order Butterworth band-pass, applied forward and backward.
    sos = butter(4, [low, high], btype='bandpass', fs=sample_rate_hz, output='sos')
    return sosfiltfilt(sos, audio, axis=0)
