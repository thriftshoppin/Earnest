"""Approximate 2D, point-sampled sound-field slice from image paths."""
from __future__ import annotations
import cmath
import math
from .room import BANDS_HZ, Point, RoomSpec
from .shoebox import image_paths


def sample_room_field(room: RoomSpec, *, frequency_hz: int = 1000, grid_size: int = 13,
                      height_m: float | None = None, reflection_order: int = 1) -> dict:
    if not isinstance(room, RoomSpec):
        raise ValueError('room must be a validated RoomSpec')
    if frequency_hz not in BANDS_HZ:
        raise ValueError('frequency_hz must be one of the room octave band centers')
    if isinstance(grid_size, bool) or not isinstance(grid_size, int) or not 3 <= grid_size <= 21:
        raise ValueError('grid_size must be an integer from 3 to 21')
    if isinstance(reflection_order, bool) or not isinstance(reflection_order, int) or not 0 <= reflection_order <= 1:
        raise ValueError('field reflection_order must be 0 or 1')
    if len(room.sources) > 4 or max(room.dimensions) > 100:
        raise ValueError('field preview supports at most 4 sources and 100 m per dimension')
    height = room.receivers[0].position[2] if height_m is None else float(height_m)
    if not math.isfinite(height) or not 0 < height < room.dimensions[2]:
        raise ValueError('height_m must be strictly inside the room')
    index = BANDS_HZ.index(frequency_hz)
    if any(abs(s.level_db[index]) > 120 for s in room.sources):
        raise ValueError('source levels for field preview must be between -120 and 120 dB')
    cells = []
    for j in range(grid_size):
        row = []
        y = room.dimensions[1] * (j + .5) / grid_size
        for i in range(grid_size):
            x = room.dimensions[0] * (i + .5) / grid_size
            position = (x, y, height)
            if any(math.dist(position, source.position) < .1 for source in room.sources):
                row.append(None)  # point-source singularity; no arbitrary near-field extrapolation
                continue
            receiver = Point('grid', position, (0.,)*7)
            power = 0.0
            for source in room.sources:
                paths = image_paths(room, source, receiver, reflection_order)
                transfer = sum(path.gain_by_band[index] * cmath.exp(-2j * math.pi * frequency_hz * path.delay_s) for path in paths)
                power += abs(transfer) ** 2 * 10 ** (source.level_db[index] / 10)
            row.append(power)
        cells.append(row)
    finite = [v for row in cells for v in row if v is not None]
    peak = max(finite, default=0.0)
    levels = [[None if v is None or v <= 0 or peak <= 0 else 10 * math.log10(v / peak)
               for v in row] for row in cells]
    return {'schema':'earnest.room-field-slice.v1', 'frequency_hz':frequency_hz,
            'height_m':height, 'grid_size':grid_size, 'dimensions_m':list(room.dimensions),
            'cell_spacing_m':[room.dimensions[0]/grid_size, room.dimensions[1]/grid_size],
            'reflection_order':reflection_order, 'relative_level_db':levels,
            'reference':'maximum sampled power',
            'limits':['Point samples at one frequency, not volume-averaged acoustic energy density.',
                      'Coherent explicit paths per source; different sources are independent.',
                      'Omnidirectional virtual receiver; room source directivity is included.',
                      'Statistical diffuse tail, diffraction, calibrated SPL and near-field source size are not modeled.',
                      'Grid points within 0.1 m of a source and zero-power points are shown as unavailable.']}
