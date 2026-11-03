"""Time-stamped spectral peak observations, not source-separated notes."""
from __future__ import annotations

import math
import numpy as np
from scipy.signal import find_peaks


def trace_frequencies(audio, sample_rate_hz: int, *, window_size: int = 4096,
                      hop_size: int = 512, min_hz: float = 40.0, max_hz: float | None = None,
                      min_level_dbfs: float = -80.0, relative_threshold_db: float = -45.0,
                      max_peaks: int = 24) -> dict:
    """Analyze independent channels with Hann-windowed, interpolated FFT peaks.

    Peak magnitude is coherent-gain calibrated for an isolated sinusoid. Noise,
    overlapping sinusoids and off-bin leakage affect both amplitude and frequency.
    """
    if isinstance(sample_rate_hz, bool) or not isinstance(sample_rate_hz, int) or not 8000 <= sample_rate_hz <= 384000:
        raise ValueError("sample rate must be an integer from 8000 to 384000 Hz")
    if isinstance(window_size, bool) or not isinstance(window_size, int) or not 256 <= window_size <= 65536:
        raise ValueError("window_size must be an integer from 256 to 65536")
    if isinstance(hop_size, bool) or not isinstance(hop_size, int) or not 1 <= hop_size <= window_size:
        raise ValueError("hop_size must be an integer between 1 and window_size")
    if isinstance(max_peaks, bool) or not isinstance(max_peaks, int) or not 1 <= max_peaks <= 256:
        raise ValueError("max_peaks must be an integer from 1 to 256")
    maximum = float(sample_rate_hz / 2 if max_hz is None else max_hz)
    minimum = float(min_hz)
    threshold, relative = float(min_level_dbfs), float(relative_threshold_db)
    if not all(math.isfinite(x) for x in (minimum, maximum, threshold, relative)):
        raise ValueError("frequency bounds and thresholds must be finite")
    if not 0 <= minimum < maximum <= sample_rate_hz / 2 or not -200 <= threshold <= 0 or not -200 <= relative <= 0:
        raise ValueError("invalid frequency range or thresholds")
    samples = np.asarray(audio, dtype=np.float64)
    if samples.ndim == 1:
        samples = samples[:, None]
    if samples.ndim != 2 or samples.shape[0] == 0 or not 1 <= samples.shape[1] <= 8 or not np.isfinite(samples).all():
        raise ValueError("audio must contain finite samples and one to eight channels")
    # Include the final partial frame; zero-padding does not improve frequency resolution.
    starts = range(0, samples.shape[0], hop_size)
    window = np.hanning(window_size)
    window_sum = float(window.sum())
    frequencies = np.fft.rfftfreq(window_size, 1.0 / sample_rate_hz)
    frames = []
    for start in starts:
        valid = min(window_size, samples.shape[0] - start)
        chunk = np.zeros((window_size, samples.shape[1]), dtype=np.float64)
        chunk[:valid] = samples[start:start + valid]
        spectrum = np.fft.rfft(chunk * window[:, None], axis=0)
        magnitude = np.abs(spectrum) * (2.0 / window_sum)
        channels = []
        for channel in range(samples.shape[1]):
            m = magnitude[:, channel]
            indices, _ = find_peaks(m)
            indices = indices[(frequencies[indices] >= minimum) & (frequencies[indices] <= maximum)]
            if len(indices):
                levels = 20 * np.log10(np.maximum(m[indices], 1e-15))
                keep = levels >= max(threshold, float(levels.max()) + relative)
                indices, levels = indices[keep], levels[keep]
                order = np.argsort(levels)[::-1][:max_peaks]
                indices = indices[order]
            peaks = []
            for index in indices:
                left, mid, right = np.log(np.maximum(m[index - 1:index + 2], 1e-15))
                denominator = left - 2 * mid + right
                offset = 0.5 * (left - right) / denominator if abs(denominator) > 1e-15 else 0.0
                offset = float(np.clip(offset, -0.5, 0.5))
                hz = (float(index) + offset) * sample_rate_hz / window_size
                if minimum <= hz <= maximum:
                    # Evaluate at the interpolated frequency to reduce scalloping
                    # and interpolation bias in the amplitude estimate.
                    phase = np.exp(-2j * np.pi * hz * np.arange(window_size) / sample_rate_hz)
                    amplitude = 2.0 * abs(np.dot(chunk[:, channel] * window, phase)) / window_sum
                    peaks.append({"hz": hz,
                                  "level_dbfs": 20.0 * math.log10(max(float(amplitude), 1e-15))})
            channels.append({"channel": channel, "peaks": peaks})
        frames.append({"start_s": start / sample_rate_hz,
                       "center_s": (start + valid / 2.0) / sample_rate_hz,
                       "valid_samples": valid, "channels": channels})
    return {"schema": "earnest.frequency-trace.v1", "sample_rate_hz": sample_rate_hz,
            "channels": samples.shape[1], "window_size": window_size, "hop_size": hop_size,
            "bin_spacing_hz": sample_rate_hz / window_size, "frames": frames,
            "limits": ["Spectral peaks are observations, not isolated instruments, notes, or MIDI events.",
                       "The final partial frame is zero-padded; its amplitude is not fully calibrated.",
                       "Nearby or overlapping partials and noise can bias interpolated peaks.",
                       "Levels are digital full-scale estimates, not sound pressure levels.",
                       "DC and the Nyquist bin are not reported as peaks."]}
