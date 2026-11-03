"""Input format detection for analysis, room, and audio files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _json_kind(document: Any) -> tuple[str, str]:
    if not isinstance(document, dict):
        return "json", "JSON value is not an object"
    schema = document.get("schema")
    if schema == "earnest.room.v1":
        return "room", "Earnest editable room document"
    if schema == "earnest.measurement.v1":
        return "measurement", "portable third-party measurement"
    if document.get("version") == 1 and isinstance(document.get("tail"), dict):
        return "reverb_formula", "Earnest measured reverb formula"
    if isinstance(document.get("schema"), str) and document["schema"].startswith("earnest."):
        return "earnest_json", "Earnest JSON artifact (%s)" % schema
    return "json", "unrecognized JSON schema"


def detect_input(path: str | Path) -> dict[str, Any]:
    """Identify supported file/container format without inventing room properties."""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError("input does not exist: %s" % source)
    if source.is_dir():
        candidates = [source / name for name in ("formula.json", "measurement.json", "room.json")]
        found = next((item for item in candidates if item.is_file()), None)
        if found is None:
            raise ValueError("directory contains no formula.json, measurement.json, or room.json")
        result = detect_input(found)
        result["container"] = str(source.resolve())
        result["selected_file"] = str(found.resolve())
        return result

    suffix = source.suffix.lower()
    if suffix == ".json":
        try:
            document = json.loads(source.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON input: %s" % exc) from exc
        kind, description = _json_kind(document)
        return {"path": str(source.resolve()), "container_format": "JSON", "kind": kind,
                "description": description, "schema": document.get("schema") if isinstance(document, dict) else None,
                "version": document.get("version") if isinstance(document, dict) else None,
                "normalization": "recognized Earnest schemas are consumed directly; no physical room values inferred"}

    if suffix in (".wav", ".wave", ".flac", ".aif", ".aiff", ".ogg"):
        try:
            import soundfile as sf
            info = sf.info(str(source))
        except Exception as exc:
            raise ValueError("audio header could not be read: %s" % exc) from exc
        return {"path": str(source.resolve()), "container_format": info.format,
                "subtype": info.subtype, "kind": "audio", "description": "audio file; analysis role not inferred",
                "sample_rate_hz": int(info.samplerate), "channels": int(info.channels),
                "frames": int(info.frames), "duration_s": float(info.duration),
                "channel_layout": "unknown; channel count alone does not identify speaker/microphone roles",
                "normalization": "audio metadata detected; dry/wet pairing and room geometry still required"}

    return {"path": str(source.resolve()), "container_format": suffix.lstrip(".").upper() or "unknown",
            "kind": "unknown", "description": "unsupported input format",
            "normalization": "no values inferred"}
