"""Offline multichannel room rendering with measured binaural responses.

Coordinate system: room +X is listener forward, +Y listener left, +Z up.
Source IDs identify the explicitly chosen Windows channel layout.
"""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve, resample_poly

from .render import render_room
from .room import RoomSpec
from .solve import solve_room

LAYOUTS = {
    "stereo": ("FL", "FR"),
    "5.1-back": ("FL", "FR", "FC", "LFE", "BL", "BR"),
    "5.1-side": ("FL", "FR", "FC", "LFE", "SL", "SR"),
    "7.1": ("FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"),
}
DEFAULT_HRTF = Path(__file__).parents[1] / "audio" / "data" / "mit_kemar_normal_pinna.sofa"


def _attr(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


class HrirDataset:
    """A validated SimpleFreeFieldHRIR SOFA file; nearest measured direction."""

    def __init__(self, path: str | Path):
        try:
            import h5py
        except ImportError as exc:
            raise ValueError("SOFA support requires h5py: py -3.14 -m pip install h5py") from exc
        self.path = str(Path(path).resolve())
        with h5py.File(path, "r") as sofa:
            if _attr(sofa.attrs.get("SOFAConventions", "")) != "SimpleFreeFieldHRIR":
                raise ValueError("only SimpleFreeFieldHRIR SOFA files are supported")
            positions = sofa["SourcePosition"]
            if _attr(positions.attrs.get("Type", "")).lower() != "spherical":
                raise ValueError("SOFA source positions must use spherical degrees")
            if "degree" not in _attr(positions.attrs.get("Units", "")).lower():
                raise ValueError("SOFA source angles must be in degrees")
            self.positions = np.asarray(positions, dtype=np.float64)
            self.ir = np.asarray(sofa["Data.IR"], dtype=np.float64)
            rates = np.asarray(sofa["Data.SamplingRate"], dtype=np.float64).reshape(-1)
            self.delay = np.asarray(sofa["Data.Delay"], dtype=np.float64)
            receivers = np.asarray(sofa["ReceiverPosition"], dtype=np.float64)
            self.title = _attr(sofa.attrs.get("Title", "SOFA HRIR"))
        if self.ir.ndim != 3 or self.ir.shape[1] != 2 or self.positions.shape != (self.ir.shape[0], 3):
            raise ValueError("SOFA dimensions must be measurements x two ears x samples")
        if not len(rates) or np.any(~np.isfinite(rates)) or np.any(rates <= 0) or not np.allclose(rates, rates[0]):
            raise ValueError("SOFA requires one constant positive sampling rate")
        if not np.isfinite(self.ir).all() or not np.isfinite(self.positions).all() or not np.isfinite(self.delay).all():
            raise ValueError("SOFA data must be finite")
        if self.delay.shape not in ((1, 2), (self.ir.shape[0], 2)) or np.any(self.delay < 0):
            raise ValueError("SOFA delays must be nonnegative samples with shape 1x2 or Mx2")
        receivers = receivers.reshape((2, -1))
        if receivers.shape[1] < 2 or not (receivers[0, 1] > 0 and receivers[1, 1] < 0):
            raise ValueError("SOFA receiver order must be left ear then right ear")
        self.fs = int(round(float(rates[0])))
        az, el = np.deg2rad(self.positions[:, 0]), np.deg2rad(self.positions[:, 1])
        self.vectors = np.column_stack((np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)))

    def nearest(self, direction: np.ndarray, fs: int) -> tuple[np.ndarray, dict]:
        norm = float(np.linalg.norm(direction))
        if not math.isfinite(norm) or norm <= 1e-9:
            raise ValueError("source direction must have nonzero length")
        direction = np.asarray(direction, dtype=float) / norm
        index = int(np.argmax(self.vectors @ direction))
        original = self.ir[index]
        delays = self.delay[0 if len(self.delay) == 1 else index]
        # Data.Delay is expressed in samples at the dataset sampling rate.
        length = original.shape[1] + int(math.ceil(float(np.max(delays)))) + 1
        delayed = np.zeros((2, length), dtype=np.float64)
        for ear in range(2):
            whole = int(math.floor(delays[ear]))
            frac = float(delays[ear] - whole)
            delayed[ear, whole:whole + original.shape[1]] += original[ear] * (1.0 - frac)
            delayed[ear, whole + 1:whole + 1 + original.shape[1]] += original[ear] * frac
        if self.fs != fs:
            divisor = math.gcd(self.fs, fs)
            delayed = resample_poly(delayed, fs // divisor, self.fs // divisor, axis=1)
        degrees = math.degrees(math.acos(float(np.clip(self.vectors[index] @ direction, -1, 1))))
        return delayed, {"measurement_index": index, "azimuth_deg": float(self.positions[index, 0]),
                         "elevation_deg": float(self.positions[index, 1]), "angular_error_deg": degrees}


def render_binaural(room: RoomSpec, audio: np.ndarray, fs: int, layout: str,
                    hrtf: HrirDataset, receiver_id: str | None = None,
                    wet_percent: float = 100.0) -> dict:
    """Solve each directional room source, then filter it to left/right ears.

    Each channel's entire mono room response uses its direct-source HRIR. This
    is an approximation: image reflections do not yet have individual HRIRs.
    The LFE channel is routed equally to ears, without room or bass management.
    """
    if layout not in LAYOUTS:
        raise ValueError("unknown layout %r" % layout)
    if not math.isfinite(wet_percent) or not 0.0 <= wet_percent <= 100.0:
        raise ValueError("wet percentage must be finite and between 0 and 100")
    x = np.asarray(audio, dtype=np.float64)
    channels = LAYOUTS[layout]
    if x.ndim != 2 or x.shape[1] != len(channels) or not len(x) or not np.isfinite(x).all():
        raise ValueError("%s requires finite non-empty audio with %d channels in Windows order %s" % (layout, len(channels), channels))
    receiver = next((r for r in room.receivers if r.id == receiver_id), None) if receiver_id else room.receivers[0]
    if receiver is None:
        raise ValueError("unknown receiver %r" % receiver_id)
    sources = {source.id.upper(): source for source in room.sources}
    missing = [name for name in channels if name != "LFE" and name not in sources]
    if missing:
        raise ValueError("room requires source IDs: " + ", ".join(missing))
    output = np.zeros((len(x), 2), dtype=np.float64)
    matches = []
    for index, name in enumerate(channels):
        if name == "LFE":
            output[:len(x), 0] += x[:, index] / math.sqrt(2)
            output[:len(x), 1] += x[:, index] / math.sqrt(2)
            continue
        source = sources[name]
        one_room = replace(room, sources=(source,), receivers=(receiver,))
        solution = solve_room(one_room, fs=fs)
        rendered = render_room(one_room, solution, x[:, index:index + 1], fs)["receiver_outputs"][receiver.id]
        direct = rendered["direct_audio"]
        mono = direct + (rendered["audio"] - direct) * (wet_percent / 100.0)
        direction = np.asarray(source.position) - np.asarray(receiver.position)
        filters, match = hrtf.nearest(direction, fs)
        length = len(mono) + filters.shape[1] - 1
        if length > len(output):
            output = np.pad(output, ((0, length - len(output)), (0, 0)))
        for ear in range(2):
            output[:length, ear] += fftconvolve(mono, filters[ear], mode="full")
        matches.append({"channel": name, **match})
    return {"audio": output, "receiver": receiver.id, "layout": layout,
            "channel_order": list(channels), "hrtf_file": hrtf.path, "hrtf_title": hrtf.title,
            "direction_matches": matches,
            "limits": ["Offline reference; not a live Windows system audio route.",
                       "One direct-source HRIR is applied to that source's whole mono room response; individual reflection directions are not binauralized.",
                       "Nearest measured direction, fixed listener facing +X; no head tracking or interpolation.",
                       "LFE is sent equally to both ears without room simulation or bass management.",
                       "Room responses use separate octave bands, not a phase-calibrated full-band RIR; direct levels are normalized per source."]}
