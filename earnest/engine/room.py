"""Validated, versioned room inputs. No filesystem or CLI behavior lives here."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

ROOM_SCHEMA = "earnest.room.v1"
BANDS_HZ = (125, 250, 500, 1000, 2000, 4000, 8000)
WALLS = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")


class RoomValidationError(ValueError):
    """Raised when a room document is incomplete or physically invalid."""


def _number(value: Any, label: str, low: float | None = None, high: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise RoomValidationError("%s must be a number" % label)
    if not math.isfinite(result):
        raise RoomValidationError("%s must be finite" % label)
    if low is not None and result < low:
        raise RoomValidationError("%s must be at least %s" % (label, low))
    if high is not None and result > high:
        raise RoomValidationError("%s must be at most %s" % (label, high))
    return result


@dataclass(frozen=True)
class Material:
    id: str
    absorption: tuple[float, ...]
    scattering: tuple[float, ...]


@dataclass(frozen=True)
class Point:
    id: str
    position: tuple[float, float, float]
    level_db: tuple[float, ...]
    directivity: str = "omni"
    orientation: tuple[float, float, float] = (1.0, 0.0, 0.0)


@dataclass(frozen=True)
class EngineControls:
    """User-visible equation controls; defaults preserve the v1 model."""
    reflection_order: int = 4
    decay_model: str = "eyring"
    absorption_scale: tuple[float, ...] = (1.0,) * len(BANDS_HZ)
    scattering_scale: tuple[float, ...] = (1.0,) * len(BANDS_HZ)
    diffuse_energy_scale: float = 1.0
    tail_duration_scale: float = 1.0
    decay_scale: float = 1.0


@dataclass(frozen=True)
class RoomSpec:
    dimensions: tuple[float, float, float]
    materials: dict[str, Material]
    surfaces: dict[str, Material]
    sources: tuple[Point, ...]
    receivers: tuple[Point, ...]
    temperature_c: float
    controls: EngineControls = EngineControls()
    schema: str = ROOM_SCHEMA
    air_absorption_enabled: bool = False
    humidity_percent: float = 50.0
    pressure_pa: float = 101325.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoomSpec":
        if not isinstance(data, dict):
            raise RoomValidationError("room document must be a JSON object")
        schema = data.get("schema")
        if schema != ROOM_SCHEMA:
            raise RoomValidationError("schema must be %r" % ROOM_SCHEMA)
        if data.get("units") != "m":
            raise RoomValidationError("units must be 'm'")
        geo = data.get("geometry") or {}
        if not isinstance(geo, dict):
            raise RoomValidationError("geometry must be an object")
        if geo.get("type") != "shoebox":
            raise RoomValidationError("geometry.type must be 'shoebox' for the current propagation backend")
        dims = geo.get("dimensions")
        if not isinstance(dims, (list, tuple)) or len(dims) != 3:
            raise RoomValidationError("geometry.dimensions must be [length, width, height] in metres")
        dimensions = tuple(_number(v, "geometry.dimensions[%d]" % i, 0.1) for i, v in enumerate(dims))

        material_rows = data.get("materials")
        if not isinstance(material_rows, list) or not material_rows:
            raise RoomValidationError("materials must be a non-empty list")
        materials: dict[str, Material] = {}
        for row in material_rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                raise RoomValidationError("each material needs a non-empty id")
            if row["id"] in materials:
                raise RoomValidationError("duplicate material id %r" % row["id"])
            bands = row.get("bands_hz", list(BANDS_HZ))
            if not isinstance(bands, (list, tuple)) or tuple(bands) != BANDS_HZ:
                raise RoomValidationError("material %r bands_hz must be %s" % (row["id"], list(BANDS_HZ)))
            alpha, scatter = row.get("absorption"), row.get("scattering", [0.0] * len(BANDS_HZ))
            if not isinstance(alpha, list) or len(alpha) != len(BANDS_HZ):
                raise RoomValidationError("material %r absorption needs seven values for %s Hz" % (row["id"], list(BANDS_HZ)))
            if not isinstance(scatter, list) or len(scatter) != len(BANDS_HZ):
                raise RoomValidationError("material %r scattering needs seven values for %s Hz" % (row["id"], list(BANDS_HZ)))
            materials[row["id"]] = Material(row["id"], tuple(_number(v, "absorption", 0, 1) for v in alpha),
                                             tuple(_number(v, "scattering", 0, 1) for v in scatter))

        surfaces_raw = data.get("surfaces") or {}
        if not isinstance(surfaces_raw, dict) or set(surfaces_raw) != set(WALLS):
            raise RoomValidationError("surfaces must assign a material_id to all six walls: %s" % ", ".join(WALLS))
        surfaces = {}
        for wall in WALLS:
            row = surfaces_raw[wall]
            material_id = row.get("material_id") if isinstance(row, dict) else row
            if not isinstance(material_id, str):
                raise RoomValidationError("surface %s must name a material_id" % wall)
            if material_id not in materials:
                raise RoomValidationError("surface %s refers to unknown material %r" % (wall, material_id))
            surfaces[wall] = materials[material_id]

        def points(key: str) -> tuple[Point, ...]:
            rows = data.get(key)
            if not isinstance(rows, list) or not rows:
                raise RoomValidationError("%s must be a non-empty list" % key)
            out, ids = [], set()
            for index, row in enumerate(rows):
                label = "%s[%d]" % (key, index)
                if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
                    raise RoomValidationError("%s needs a non-empty id" % label)
                if row["id"] in ids:
                    raise RoomValidationError("duplicate %s id %r" % (key, row["id"]))
                ids.add(row["id"])
                pos = row.get("position")
                if not isinstance(pos, (list, tuple)) or len(pos) != 3:
                    raise RoomValidationError("%s.position must have three coordinates" % label)
                xyz = tuple(_number(v, label + ".position", 0) for v in pos)
                if any(v <= 0 or v >= dimensions[i] for i, v in enumerate(xyz)):
                    raise RoomValidationError("%s.position must be inside the room, away from the walls" % label)
                levels = row.get("level_db", [0.0] * len(BANDS_HZ))
                if not isinstance(levels, list) or len(levels) != len(BANDS_HZ):
                    raise RoomValidationError("%s.level_db must have seven values, one per band" % label)
                directivity = row.get("directivity", "omni")
                if directivity not in ("omni", "cardioid", "figure8"):
                    raise RoomValidationError("%s.directivity must be omni, cardioid, or figure8" % label)
                direction = row.get("orientation", [1.0, 0.0, 0.0])
                if not isinstance(direction, (list, tuple)) or len(direction) != 3:
                    raise RoomValidationError("%s.orientation must be a three-component direction" % label)
                orientation = tuple(_number(v, label + ".orientation") for v in direction)
                if math.hypot(*orientation) <= 1e-12:
                    raise RoomValidationError("%s.orientation must be nonzero" % label)
                out.append(Point(row["id"], xyz, tuple(_number(v, label + ".level_db") for v in levels),
                                 directivity, orientation))
            return tuple(out)

        env = data.get("environment") or {}
        if not isinstance(env, dict):
            raise RoomValidationError("environment must be an object")
        temp = _number(env.get("temperature_c", 20), "environment.temperature_c", -50, 100)
        humidity = _number(env.get("humidity_percent", 50), "environment.humidity_percent", 0, 100)
        pressure = _number(env.get("pressure_pa", 101325), "environment.pressure_pa", 10000, 200000)
        air_absorption = env.get("air_absorption_enabled", False)
        if not isinstance(air_absorption, bool):
            raise RoomValidationError("environment.air_absorption_enabled must be a boolean")
        if air_absorption and not -20 <= temp <= 50:
            raise RoomValidationError("air absorption model requires temperature between -20 and 50 C")
        control_raw = data.get("engine_controls") or {}
        if not isinstance(control_raw, dict):
            raise RoomValidationError("engine_controls must be an object")
        order = control_raw.get("reflection_order", 4)
        if isinstance(order, bool) or not isinstance(order, int) or order < 0 or order > 12:
            raise RoomValidationError("engine_controls.reflection_order must be an integer from 0 to 12")
        decay_model = control_raw.get("decay_model", "eyring")
        if decay_model not in ("eyring", "sabine"):
            raise RoomValidationError("engine_controls.decay_model must be 'eyring' or 'sabine'")

        def band_controls(key: str, default: float, low: float, high: float) -> tuple[float, ...]:
            values = control_raw.get(key, [default] * len(BANDS_HZ))
            if not isinstance(values, list) or len(values) != len(BANDS_HZ):
                raise RoomValidationError("engine_controls.%s must have seven values for %s Hz" % (key, list(BANDS_HZ)))
            return tuple(_number(v, "engine_controls." + key, low, high) for v in values)

        controls = EngineControls(
            reflection_order=order, decay_model=decay_model,
            absorption_scale=band_controls("absorption_scale", 1.0, 0.0, 20.0),
            scattering_scale=band_controls("scattering_scale", 1.0, 0.0, 20.0),
            diffuse_energy_scale=_number(control_raw.get("diffuse_energy_scale", 1.0), "engine_controls.diffuse_energy_scale", 0.0, 10.0),
            tail_duration_scale=_number(control_raw.get("tail_duration_scale", 1.0), "engine_controls.tail_duration_scale", 0.1, 4.0),
            decay_scale=_number(control_raw.get("decay_scale", 1.0), "engine_controls.decay_scale", 0.1, 2.5))
        sources, receivers = points("sources"), points("receivers")
        for source in sources:
            for receiver in receivers:
                if math.dist(source.position, receiver.position) <= 1e-9:
                    raise RoomValidationError("source %r and receiver %r must be separated for the point-source model" % (source.id, receiver.id))
        return cls(dimensions, materials, surfaces, sources, receivers, temp, controls,
                   air_absorption_enabled=air_absorption, humidity_percent=humidity, pressure_pa=pressure)

    def absorption(self, wall: str, band: int) -> float:
        return min(1.0, self.surfaces[wall].absorption[band] * self.controls.absorption_scale[band])

    def scattering(self, wall: str, band: int) -> float:
        return min(1.0, self.surfaces[wall].scattering[band] * self.controls.scattering_scale[band])

    @property
    def volume_m3(self) -> float:
        return math.prod(self.dimensions)

    def wall_areas(self) -> dict[str, float]:
        x, y, z = self.dimensions
        return {"x_min": y*z, "x_max": y*z, "y_min": x*z, "y_max": x*z, "z_min": x*y, "z_max": x*y}

    def sound_speed_m_s(self) -> float:
        # Dry-air temperature approximation; humidity and pressure correction are not yet modeled.
        return 331.3 * math.sqrt(1.0 + self.temperature_c / 273.15)

    def air_absorption_area_m2(self, band: int) -> float:
        """Equivalent diffuse-field area 4mV; m is power attenuation in nepers/m."""
        if not self.air_absorption_enabled:
            return 0.0
        from .physics import air_absorption_db_per_m
        alpha_db_m = air_absorption_db_per_m(BANDS_HZ[band], self.temperature_c,
                                            self.humidity_percent, self.pressure_pa)
        return 4.0 * self.volume_m3 * alpha_db_m * math.log(10.0) / 10.0

    def decay_estimates(self) -> list[dict[str, float | int]]:
        areas = self.wall_areas()
        surface_area = sum(areas.values())
        sabine_constant = 24.0 * math.log(10.0) / self.sound_speed_m_s()
        out = []
        for index, band in enumerate(BANDS_HZ):
            absorption_area = sum(areas[w] * self.absorption(w, index) for w in WALLS)
            mean_alpha = absorption_area / surface_area
            air_area = self.air_absorption_area_m2(index)
            total_sabine = absorption_area + air_area
            sabine = sabine_constant * self.volume_m3 / total_sabine if total_sabine > 0 else None
            eyring_den = -surface_area * math.log1p(-mean_alpha) + air_area if mean_alpha < 1 else math.inf
            eyring = sabine_constant * self.volume_m3 / eyring_den if eyring_den > 0 and math.isfinite(eyring_den) else (0.0 if mean_alpha == 1 else None)
            baseline = sabine if self.controls.decay_model == "sabine" else (eyring if eyring is not None else sabine)
            effective = baseline * self.controls.decay_scale if baseline is not None else None
            out.append({"hz": band, "absorption_area_m2": absorption_area, "mean_absorption": mean_alpha,
                        "air_absorption_area_m2": air_area, "sabine_rt60_s": sabine, "eyring_rt60_s": eyring,
                        "effective_rt60_s": effective})
        return out
