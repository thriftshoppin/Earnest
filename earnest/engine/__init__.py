"""Composable acoustic engine and its built-in physical-room components."""

from .core import (Artifact, ComponentContext, ControlParameter, Engine, EngineError,
                   EngineComponent, EngineResult, RealtimeAudioComponent)
from .room import RoomSpec, RoomValidationError
from .render import render_room
from .solve import solve_room
from .calibration import fit_formula, solve_room_from_analysis
from .detection import detect_input
from .components import create_engine

__all__ = ["Artifact", "ComponentContext", "ControlParameter", "Engine", "EngineError",
           "EngineComponent", "EngineResult", "RealtimeAudioComponent",
           "RoomSpec", "RoomValidationError", "render_room", "solve_room", "fit_formula",
           "solve_room_from_analysis", "detect_input", "create_engine"]
