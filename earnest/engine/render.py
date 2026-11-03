"""Offline audio driving through a solved room response."""
from __future__ import annotations

import math
from contextlib import nullcontext

import numpy as np
from scipy.signal import fftconvolve

from .room import BANDS_HZ, RoomSpec
from ..dsp import edges


def _partition_audio(x: np.ndarray, fs: int, xp=np) -> tuple[list[np.ndarray], np.ndarray]:
    """Split with a unity-sum, zero-phase bank and zero-extended boundaries."""
    from scipy.fft import next_fast_len
    n = len(x)
    if n == 0:
        return [np.array([], dtype=float) for _ in BANDS_HZ], np.array([], dtype=float)
    guard = max(int(0.5 * fs), 1)
    N = next_fast_len(n + 2 * guard)
    padded = xp.zeros(N, dtype=xp.float64)
    padded[guard:guard + n] = x
    spectrum = xp.fft.rfft(padded)
    frequencies = xp.fft.rfftfreq(N, 1.0 / fs)
    responses = []
    for center in BANDS_HZ:
        lo, hi = edges(center, 1)
        with np.errstate(divide="ignore", over="ignore") if xp is np else nullcontext():
            lp = 1.0 / xp.sqrt(1.0 + (frequencies / hi) ** 12)
            hp = xp.where(frequencies > 0, 1.0 / xp.sqrt(1.0 + (lo / xp.maximum(frequencies, 1e-9)) ** 12), 0.0)
        responses.append(lp * hp)
    total = xp.sum(xp.stack(responses), axis=0)
    scale = xp.maximum(total, 1.0)
    band_signals = [xp.fft.irfft(spectrum * response / scale, N)[guard:guard + n] for response in responses]
    residual_response = xp.maximum(1.0 - total, 0.0)
    residual = xp.fft.irfft(spectrum * residual_response, N)[guard:guard + n]
    return band_signals, residual


def _direct_kernel(delay_s: float, fs: int) -> np.ndarray:
    position = max(delay_s, 0.0) * fs
    index = int(math.floor(position))
    fraction = position - index
    kernel = np.zeros(index + 2, dtype=np.float64)
    kernel[index] = 1.0 - fraction
    kernel[index + 1] = fraction
    return kernel


def render_room(room: RoomSpec, solution: dict, source_audio: np.ndarray, fs: int = 48000,
                direct_gain: float = 1.0, reflection_gain_db: tuple[float, ...] | None = None,
                backend: str = "cpu", cuda_device: int = 0) -> dict:
    """Render one source signal per configured source through the solved room.

    Input shape is frames x sources in RoomSpec.sources order. Each receiver produces
    a mono pressure signal. Direct pressure and reflected pressure have independent
    gains; reflection gains correspond to the seven solver bands. No normalization
    or clipping is applied. Defaults reproduce the original response.
    """
    x = np.asarray(source_audio, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != len(room.sources):
        raise ValueError("source_audio must have one column for each room source (%d)" % len(room.sources))
    if len(x) == 0 or not np.isfinite(x).all():
        raise ValueError("source_audio must contain finite, non-empty samples")
    if int(solution.get("sample_rate_hz", -1)) != fs:
        raise ValueError("render sample rate must match the room solution sample rate")
    if not math.isfinite(direct_gain) or not 0 <= direct_gain <= 2.5:
        raise ValueError("direct_gain must be finite and between 0 and 2.5")
    if reflection_gain_db is None:
        reflection_gain_db = (0.0,) * len(BANDS_HZ)
    if len(reflection_gain_db) != len(BANDS_HZ) or any(not math.isfinite(v) or v < -60 or v > 24 for v in reflection_gain_db):
        raise ValueError("reflection_gain_db must contain seven finite values between -60 and +24 dB")
    if backend not in ("cpu", "cuda"):
        raise ValueError("render backend must be cpu or cuda")
    if isinstance(cuda_device, bool) or not isinstance(cuda_device, int) or cuda_device < 0:
        raise ValueError("CUDA device must be a nonnegative integer")
    xp = np
    convolve = fftconvolve
    device_info = None
    if backend == "cuda":
        try:
            import cupy as cp
            from cupyx.scipy.signal import fftconvolve as gpu_fftconvolve
            cp.cuda.Device(cuda_device).use()
            props = cp.cuda.runtime.getDeviceProperties(cuda_device)
            device_info = props['name'].decode('utf-8') if isinstance(props['name'], bytes) else props['name']
            xp, convolve = cp, gpu_fftconvolve
        except Exception as exc:
            raise ValueError("CUDA backend unavailable on device %s: %s" % (cuda_device, exc)) from exc
    x = xp.asarray(x)
    source_columns = {}
    for index, source in enumerate(room.sources):
        source_columns[source.id] = _partition_audio(x[:, index], fs, xp)

    outputs = {}
    for receiver in room.receivers:
        pair_rows = {row["source_id"]: row for row in solution["source_receiver_pairs"]
                     if row["receiver_id"] == receiver.id}
        total_length = max(len(x) + len(pair_rows[source.id]["band_ir"][str(BANDS_HZ[0])]) - 1
                           for source in room.sources)
        output = xp.zeros(total_length, dtype=xp.float64)
        direct_output = xp.zeros(total_length, dtype=xp.float64)
        for source in room.sources:
            pair = pair_rows[source.id]
            bands, residual = source_columns[source.id]
            direct = xp.asarray(_direct_kernel(pair["direct_delay_ms"] / 1000.0, fs)) * float(pair.get("directivity_gain", 1.0))
            for band_index, center in enumerate(BANDS_HZ):
                level = 10.0 ** (source.level_db[band_index] / 20.0)
                impulse = xp.asarray(pair["band_ir"][str(center)], dtype=xp.float64)
                reflected_gain = 10.0 ** (reflection_gain_db[band_index] / 20.0)
                if reflected_gain == 1.0 and direct_gain == 1.0:
                    mixed_impulse = impulse
                else:
                    mixed_impulse = impulse * reflected_gain
                    mixed_impulse[:len(direct)] += direct * (direct_gain - reflected_gain)
                convolved = convolve(bands[band_index] * level, mixed_impulse, mode="full")
                output[:len(convolved)] += convolved
                direct_band = convolve(bands[band_index] * level * direct_gain, direct, mode="full")
                direct_output[:len(direct_band)] += direct_band
            # Outside Earnest's modeled bands, preserve the direct path and its propagation delay.
            unmodeled = convolve(residual * direct_gain, direct, mode="full")
            output[:len(unmodeled)] += unmodeled
            direct_output[:len(unmodeled)] += unmodeled
        if backend == "cuda":
            output, direct_output = xp.asnumpy(output), xp.asnumpy(direct_output)
        band_levels = []
        for center in BANDS_HZ:
            lo, hi = edges(center, 1)
            N = 1 << (max(len(output), 1) - 1).bit_length()
            spectrum = np.fft.rfft(output, N)
            frequencies = np.fft.rfftfreq(N, 1.0 / fs)
            select = (frequencies >= lo) & (frequencies < hi)
            power = float(np.sum(np.abs(spectrum[select]) ** 2) * 2.0) / max(N * len(output), 1)
            band_levels.append({"hz": center, "rms_dbfs": 10.0 * math.log10(max(power, 1e-30))})
        outputs[receiver.id] = {
            "audio": output,
            "direct_audio": direct_output,
            "analysis": {
                "frames": len(output), "duration_s": len(output) / fs,
                "peak_dbfs": 20.0 * math.log10(max(float(np.max(np.abs(output))), 1e-15)),
                "rms_dbfs": 20.0 * math.log10(max(float(np.sqrt(np.mean(output * output))), 1e-15)),
                "band_rms_dbfs": band_levels,
                "clipped_samples_at_0dbfs": int(np.count_nonzero(np.abs(output) >= 1.0)),
                "normalization_applied": False
            }
        }
    return {"sample_rate_hz": fs, "compute_backend": backend, "cuda_device": cuda_device if backend == "cuda" else None, "cuda_device_name": device_info, "source_ids": [source.id for source in room.sources],
            "receiver_outputs": outputs,
            "mix_controls": {"direct_gain": direct_gain, "reflection_gain_db": list(reflection_gain_db)},
            "render_limits": ["Mono pressure output per receiver; ideal frequency-independent directivity is used only for explicit paths.",
                              "Below 125 Hz and above 8 kHz only the delayed direct signal is rendered.",
                              "The rendered signal is an offline approximation using separate octave-band responses."]}
