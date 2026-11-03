"""User-configurable audio engine session and file-based signal path."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from scipy.signal import sosfilt, resample_poly
import soundfile as sf

from .room import RoomSpec
from .solve import solve_room
from .render import render_room

SCHEMA = "earnest.engine-session.v1"
EQ_FREQUENCIES = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)


def new_session(room_file: str) -> dict:
    path = Path(room_file).resolve()
    room = json.loads(path.read_text(encoding="utf-8-sig"))
    RoomSpec.from_dict(room)
    return {"schema": SCHEMA, "room_file": str(path), "sample_rate_hz": 48000,
            "eq_db": [0.0] * len(EQ_FREQUENCIES), "input_gain_db": 0.0,
            "output_gain_db": -6.0, "wet_percent": 100.0, "receiver": None}


def validate(config: dict) -> None:
    if not isinstance(config, dict) or config.get("schema") != SCHEMA:
        raise ValueError("expected an earnest.engine-session.v1 configuration")
    if not isinstance(config.get("room_file"), str) or not config["room_file"]:
        raise ValueError("room_file is required")
    fs = config.get("sample_rate_hz")
    if isinstance(fs, bool) or not isinstance(fs, int) or not 32000 <= fs <= 192000:
        raise ValueError("sample_rate_hz must be an integer from 32000 to 192000")
    gains = config.get("eq_db")
    if not isinstance(gains, list) or len(gains) != len(EQ_FREQUENCIES):
        raise ValueError("eq_db must contain ten gains")
    def number(value, low, high, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("%s must be between %s and %s" % (name, low, high))
    for frequency, gain in zip(EQ_FREQUENCIES, gains):
        number(gain, -24, 24, "EQ gain in dB")
        if gain != 0 and frequency >= fs / 2:
            raise ValueError("EQ band %d Hz is not below the %d Hz sample rate's Nyquist frequency" % (frequency, fs))
    number(config.get("input_gain_db"), -60, 24, "input_gain_db")
    number(config.get("output_gain_db"), -60, 24, "output_gain_db")
    number(config.get("wet_percent"), 0, 100, "wet_percent")
    if config.get("receiver") is not None and not isinstance(config["receiver"], str):
        raise ValueError("receiver must be a receiver id or null")


def load(path: str | Path) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    validate(config)
    return config


def _eq_sos(fs: int, gains: list[float]) -> np.ndarray:
    """RBJ peaking filters with fixed Q=sqrt(2) and identity at zero dB."""
    rows = []
    for frequency, gain in zip(EQ_FREQUENCIES, gains):
        if abs(gain) < 1e-12 or frequency >= fs / 2:
            continue
        a = 10 ** (gain / 40.0)
        w = 2.0 * math.pi * frequency / fs
        alpha = math.sin(w) / (2.0 * math.sqrt(2.0))
        a0 = 1.0 + alpha / a
        rows.append([(1 + alpha*a)/a0, -2*math.cos(w)/a0, (1-alpha*a)/a0,
                     1.0, -2*math.cos(w)/a0, (1-alpha/a)/a0])
    return np.asarray(rows, dtype=np.float64).reshape((-1, 6))


def render(config: dict, audio_file: str, output: str) -> dict:
    """Apply input gain and EQ, solve and render the room, then write output."""
    validate(config)
    destination = Path(output)
    if destination.exists():
        raise ValueError("refusing to overwrite output file: %s" % destination)
    raw = json.loads(Path(config["room_file"]).read_text(encoding="utf-8-sig"))
    room = RoomSpec.from_dict(raw)
    audio, source_rate = sf.read(audio_file, dtype="float64", always_2d=True)
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError("source audio is empty or contains non-finite samples")
    if audio.shape[1] == 1 and len(room.sources) == 2:
        audio = np.repeat(audio, 2, axis=1)
    if audio.shape[1] != len(room.sources):
        raise ValueError("audio has %d channels; room requires %d sources" % (audio.shape[1], len(room.sources)))
    fs = config["sample_rate_hz"]
    if source_rate != fs:
        divisor = math.gcd(int(source_rate), fs)
        audio = resample_poly(audio, fs // divisor, int(source_rate) // divisor, axis=0)
    audio *= 10 ** (config["input_gain_db"] / 20.0)
    sos = _eq_sos(fs, config["eq_db"])
    if len(sos):
        audio = sosfilt(sos, audio, axis=0)
    solution = solve_room(room, fs=fs)
    result = render_room(room, solution, audio, fs=fs)
    receiver = config.get("receiver") or room.receivers[0].id
    if receiver not in result["receiver_outputs"]:
        raise ValueError("unknown receiver %r; available: %s" % (receiver, ", ".join(result["receiver_outputs"])))
    receiver_output = result["receiver_outputs"][receiver]
    wet = receiver_output["audio"]
    # Both paths use the same source levels and propagation delays. The wet
    # control scales only the difference between the full and direct responses.
    direct = receiver_output["direct_audio"]
    mix = config["wet_percent"] / 100.0
    signal = direct + (wet - direct) * mix
    signal *= 10 ** (config["output_gain_db"] / 20.0)
    peak = float(np.max(np.abs(signal)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destination), signal, fs, subtype="FLOAT")
    return {"output": str(destination.resolve()), "sample_rate_hz": fs, "receiver": receiver,
            "peak_dbfs": 20 * math.log10(max(peak, 1e-15)),
            "samples_over_full_scale": int(np.count_nonzero(np.abs(signal) > 1.0)),
            "model_limits": result["render_limits"] + solution["model_limits"]}
