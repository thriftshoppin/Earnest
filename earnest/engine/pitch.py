"""Pitch-coordinate conversion; this is not fundamental estimation."""
from __future__ import annotations
import math


def frequency_to_pitch(frequency_hz: float, a4_hz: float = 440.0) -> dict:
    frequency, a4 = float(frequency_hz), float(a4_hz)
    if not math.isfinite(frequency) or not math.isfinite(a4) or frequency <= 0 or a4 <= 0:
        raise ValueError('frequencies must be finite and positive')
    midi_float = 69.0 + 12.0 * math.log2(frequency / a4)
    # Half-semitone ties are resolved upward, not by Python's round-to-even.
    nearest = math.floor(midi_float + .5)
    names = ('C','C#','D','D#','E','F','F#','G','G#','A','A#','B')
    return {'midi_pitch': midi_float, 'nearest_equal_tempered_note': names[nearest % 12] + str(nearest // 12 - 1),
            'nearest_note_number': nearest, 'midi_note_in_range': 0 <= nearest <= 127,
            'cents_from_nearest': 100 * (midi_float - nearest), 'reference_a4_hz': a4}
