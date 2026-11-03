"""Specular image-source path generation for rectangular rooms."""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import math

from .room import Point, RoomSpec


@dataclass(frozen=True)
class ImagePath:
    delay_s: float
    distance_m: float
    gain_by_band: tuple[float, ...]
    image_index: tuple[int, int, int]


def _axis_images(source: float, receiver: float, size: float, order: int):
    """Return (coordinate, low-wall hits, high-wall hits) in one unfolded axis."""
    out = []
    # A rectangular room has two image families per tile: the normal and mirrored tile.
    # Count actual boundary-plane crossings between receiver and image; even planes are
    # low walls and odd planes are high walls. This keeps material assignment geometric.
    for tile in range(-order - 1, order + 2):
        for mirrored in (False, True):
            coordinate = 2.0 * tile * size + (-source if mirrored else source)
            lo, hi = sorted((receiver, coordinate))
            crossings = [k for k in range(math.floor(lo / size) - 1, math.ceil(hi / size) + 2)
                         if lo + 1e-9 < k * size < hi - 1e-9]
            low_hits = sum(1 for k in crossings if k % 2 == 0)
            high_hits = len(crossings) - low_hits
            if len(crossings) <= order:
                out.append((coordinate, low_hits, high_hits, tile * 2 + int(mirrored)))
    # Same coordinate can arise only at a source on a boundary, which input validation forbids.
    return out


def image_paths(room: RoomSpec, source: Point, receiver: Point, max_order: int = 4) -> list[ImagePath]:
    if max_order < 0 or max_order > 12:
        raise ValueError("max_order must be between 0 and 12")
    dims = room.dimensions
    c = room.sound_speed_m_s()
    paths = []
    axes = [_axis_images(source.position[i], receiver.position[i], dims[i], max_order) for i in range(3)]
    # Filter by total reflection order after combining axes, so max_order means total bounces.
    for candidate in itertools.product(*axes):
        reflection_order = sum(item[1] + item[2] for item in candidate)
        if reflection_order > max_order:
            continue
        image = tuple(item[0] for item in candidate)
        image_index = tuple(item[3] for item in candidate)
        distance = math.sqrt(sum((image[i] - receiver.position[i]) ** 2 for i in range(3)))
        if distance <= 1e-9:
            continue
        hits = [(item[1], item[2]) for item in candidate]
        gains = []
        for band in range(7):
            energy_retention = 1.0
            for axis, pair in enumerate((("x_min", "x_max"), ("y_min", "y_max"), ("z_min", "z_max"))):
                for wall, count in zip(pair, hits[axis]):
                    if count:
                        # The image path retains only the specular share; solve.py places a separate
                        # statistical late-field energy estimate for the non-resolved portion.
                        retention = (1.0 - room.absorption(wall, band)) * (1.0 - room.scattering(wall, band))
                        energy_retention *= retention ** count
            gains.append(math.sqrt(energy_retention) / distance)
        paths.append(ImagePath(distance / c, distance, tuple(gains), image_index))
    return sorted(paths, key=lambda p: p.delay_s)
