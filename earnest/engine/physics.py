"""Explicit physical models for homogeneous air and ideal instrument resonators.

These functions are a foundation for analysis, not complete instrument models.
Sources and validity limits are documented in docs/PHYSICS_NOTES.md.
"""
from __future__ import annotations

import math


def _finite(value: float, name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def air_absorption_db_per_m(frequency_hz: float, temperature_c: float,
                            relative_humidity_percent: float, pressure_pa: float = 101325.0) -> float:
    """ISO 9613-1 pure-tone attenuation in dB/m, with humidity in percent.

    The modeled atmosphere is homogeneous; saturation is over liquid water.
    Its standard gives uncertainty ranges that depend on all input conditions.
    """
    f = _finite(frequency_hz, "frequency_hz")
    t_c = _finite(temperature_c, "temperature_c")
    rh = _finite(relative_humidity_percent, "relative_humidity_percent")
    pressure = _finite(pressure_pa, "pressure_pa")
    if f < 0 or not -20 <= t_c <= 50 or not 0 <= rh <= 100 or not 10000 <= pressure <= 200000:
        raise ValueError("air model requires nonnegative frequency, -20..50 C, 0..100% RH and 10..200 kPa")
    if f == 0:
        return 0.0
    t = t_c + 273.15
    t_ratio, p_ratio = t / 293.15, pressure / 101325.0
    # Saturation pressure ratio p_sat/p_ref, and water-vapour molar concentration (%).
    saturation_ratio = 10.0 ** (-6.8346 * (273.16 / t) ** 1.261 + 4.6151)
    h = rh * saturation_ratio / p_ratio
    if h > 100.0:
        raise ValueError("water vapour partial pressure cannot exceed total atmospheric pressure")
    oxygen = p_ratio * (24.0 + 4.04e4 * h * (0.02 + h) / (0.391 + h))
    nitrogen = p_ratio * t_ratio ** -0.5 * (9.0 + 280.0 * h * math.exp(-4.17 * (t_ratio ** (-1.0 / 3.0) - 1.0)))
    classical = 1.84e-11 * (1.0 / p_ratio) * math.sqrt(t_ratio)
    molecular = t_ratio ** -2.5 * (
        0.01275 * math.exp(-2239.1 / t) / (oxygen + f * f / oxygen)
        + 0.1068 * math.exp(-3352.0 / t) / (nitrogen + f * f / nitrogen))
    return 8.686 * f * f * (classical + molecular)


def ideal_string_modes(length_m: float, tension_n: float, linear_density_kg_m: float,
                       count: int = 12) -> list[float]:
    """Frequencies of an ideal flexible string fixed at both ends, in Hz."""
    length = _finite(length_m, "length_m")
    tension = _finite(tension_n, "tension_n")
    density = _finite(linear_density_kg_m, "linear_density_kg_m")
    if length <= 0 or tension <= 0 or density <= 0 or isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 256:
        raise ValueError("length, tension and linear density must be positive; count must be an integer from 1 to 256")
    fundamental = math.sqrt(tension / density) / (2.0 * length)
    return [n * fundamental for n in range(1, count + 1)]


def directivity_pressure(pattern: str, orientation: tuple[float, float, float],
                         direction: tuple[float, float, float]) -> float:
    """Frequency-independent first-order polar pattern with signed pressure."""
    if pattern == "omni":
        return 1.0
    if pattern not in ("cardioid", "figure8"):
        raise ValueError("directivity pattern must be omni, cardioid, or figure8")
    if len(orientation) != 3 or len(direction) != 3:
        raise ValueError("orientation and direction need three components")
    axis = tuple(_finite(v, "orientation") for v in orientation)
    ray = tuple(_finite(v, "direction") for v in direction)
    axis_length, ray_length = math.hypot(*axis), math.hypot(*ray)
    if axis_length <= 1e-12 or ray_length <= 1e-12:
        raise ValueError("orientation and direction must be nonzero")
    cosine = max(-1.0, min(1.0, sum(a * b for a, b in zip(axis, ray)) / (axis_length * ray_length)))
    return (1.0 + cosine) / 2.0 if pattern == "cardioid" else cosine


def ideal_pipe_modes(length_m: float, sound_speed_m_s: float, boundary: str,
                     count: int = 12) -> list[float]:
    """Ideal uniform tube modes; effective length must include any end correction."""
    length = _finite(length_m, "length_m")
    speed = _finite(sound_speed_m_s, "sound_speed_m_s")
    if length <= 0 or speed <= 0 or isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 256:
        raise ValueError("length and sound speed must be positive; count must be an integer from 1 to 256")
    if boundary == "open-open":
        return [n * speed / (2.0 * length) for n in range(1, count + 1)]
    if boundary == "open-closed":
        return [(2 * n - 1) * speed / (4.0 * length) for n in range(1, count + 1)]
    raise ValueError("boundary must be 'open-open' or 'open-closed'")


def stiff_string_modes(length_m: float, tension_n: float, linear_density_kg_m: float,
                       inharmonicity: float, count: int = 12) -> list[float]:
    """Pinned stiff-string approximation using the dimensionless B coefficient."""
    base = ideal_string_modes(length_m, tension_n, linear_density_kg_m, count)
    b = _finite(inharmonicity, "inharmonicity")
    if b < 0:
        raise ValueError("inharmonicity must be nonnegative")
    return [f * math.sqrt(1.0 + b * n * n) for n, f in enumerate(base, 1)]


def circular_membrane_modes(radius_m: float, tension_n_m: float, surface_density_kg_m2: float,
                            count: int = 12) -> list[dict[str, float | int]]:
    """Fixed-edge circular membrane modal frequencies (without angular degeneracy)."""
    from scipy.special import jn_zeros
    radius = _finite(radius_m, "radius_m")
    tension = _finite(tension_n_m, "tension_n_m")
    density = _finite(surface_density_kg_m2, "surface_density_kg_m2")
    if radius <= 0 or tension <= 0 or density <= 0 or isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 24:
        raise ValueError("radius, tension and surface density must be positive; count must be an integer from 1 to 24")
    scale = math.sqrt(tension / density) / (2.0 * math.pi * radius)
    modes = [{"angular_order": angular, "radial_index": radial, "frequency_hz": float(zero) * scale}
             for angular in range(count) for radial, zero in enumerate(jn_zeros(angular, count), 1)]
    return sorted(modes, key=lambda mode: mode["frequency_hz"])[:count]
