"""Visible terminal boot sequence for the Earnest command application."""
from __future__ import annotations

import importlib
import os
import platform
import sys
from time import perf_counter


_RESET = "\x1b[0m"
_GREEN = "\x1b[92m"
_DIM_GREEN = "\x1b[32m"
_CYAN = "\x1b[96m"
_AMBER = "\x1b[93m"
_RED = "\x1b[91m"
_BOLD = "\x1b[1m"
_COLOR = False


def _enable_terminal_colors() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    try:
        if not sys.stdout.isatty():
            return False
    except (AttributeError, OSError):
        return False
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt
            handle = msvcrt.get_osfhandle(sys.stdout.fileno())
            mode = ctypes.c_uint()
            kernel = ctypes.windll.kernel32
            if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                return False
            return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
        except (AttributeError, OSError, ValueError):
            return False
    return True


def _paint(text: str, color: str, bold: bool = False) -> str:
    if not _COLOR:
        return text
    return ( _BOLD if bold else "") + color + text + _RESET


def _feather_art() -> tuple[str, ...]:
    # A quill-shaped mark that remains legible in the default CMD code page.
    return (
        "                    .-.",
        "                 .-'   `.",
        "                /  /\\    \\",
        "               /  /  \\    \\",
        "              /__/    \\____\\",
        "              \\  \\    /   /",
        "               `--\\--'   /",
        "                   \\    /",
        "                    `--'",
    )


def _banner() -> None:
    print(_paint("+----------------------------------------------------------------+", _DIM_GREEN))
    for index, line in enumerate(_feather_art()):
        if index == 2:
            line += "      E A R N E S T  //  ROOM ACOUSTICS"
        elif index == 3:
            line += "      PERCEPTION  /  SOLVER  /  AUDIO ENGINE"
        elif index == 4:
            line += "      BUILD 0.1  |  WIN32  |  BOOT SEQUENCE"
        print(_paint("| " + line.ljust(66) + " |", _GREEN, bold=(index == 2)))
    print(_paint("+----------------------------------------------------------------+", _DIM_GREEN))


def _load_stage(number: int, label: str, modules: tuple[str, ...]) -> None:
    print(_paint("\n[0x%02X] INIT // %s" % (number, label.upper()), _CYAN, bold=True))
    width = max(len(module) for module in modules)
    for module in modules:
        sys.stdout.write(_paint("    > %-*s " % (width, module), _DIM_GREEN))
        sys.stdout.flush()
        try:
            importlib.import_module(module)
        except Exception as exc:
            print(_paint("[FAILED]", _RED, bold=True))
            print(_paint("      %s" % exc, _RED))
            raise SystemExit(1)
        print(_paint("[ LOADED ]", _GREEN, bold=True))


def boot() -> None:
    """Load command, analysis, room engine, and audio layers before dispatch."""
    global _COLOR
    _COLOR = _enable_terminal_colors()
    started = perf_counter()
    _banner()
    print(_paint("\nSYS::%s  RUNTIME::PYTHON-%s  MODE::CLI" %
                 (platform.system().upper(), platform.python_version()), _AMBER))

    stages = (
        ("Numerical core", ("numpy",)),
        ("Analysis + signal processing", (
            "earnest.dsp", "earnest.formula", "earnest.gen", "earnest.listen",
            "earnest.room", "earnest.resynth", "earnest.suite")),
        ("Room engine + renderer", (
            "earnest.engine.core", "earnest.engine.room", "earnest.engine.shoebox",
            "earnest.engine.solve", "earnest.engine.render", "earnest.engine.components")),
        ("Reports + audio file I/O", (
            "earnest.plots", "earnest.report", "earnest.io", "soundfile")),
        ("Live audio routing", ("earnest.audio.profile", "earnest.audio.host")),
        ("Command interface", ("earnest.cli",)),
    )
    for number, (label, modules) in enumerate(stages, 1):
        _load_stage(number, label, modules)

    print(_paint("\n[0x07] INIT // COMPONENT REGISTRY", _CYAN, bold=True))
    try:
        from .engine import create_engine
        engine = create_engine()
    except Exception as exc:
        print(_paint("    [FAILED] %s" % exc, _RED, bold=True))
        raise SystemExit(1)
    for component in engine.components:
        print(_paint("    + %s" % component, _GREEN))

    try:
        importlib.import_module("earnest.audio.host")
        audio_status = "LIVE ROUTER MODULE LOADED // DEVICE AND ROUTE NOT VERIFIED"
        audio_color = _GREEN
    except ImportError:
        audio_status = "DEVICE OUTPUT UNAVAILABLE // WAV RENDER ACTIVE"
        audio_color = _AMBER
    print(_paint("\n[AUDIO] " + audio_status, audio_color))
    elapsed_ms = (perf_counter() - started) * 1000.0
    print(_paint("\n+----------------------------------------------------------------+", _GREEN))
    print(_paint("|  ENGINE ONLINE  //  READY  //  BOOT %.0f ms" % elapsed_ms, _GREEN, bold=True))
    print(_paint("+----------------------------------------------------------------+", _GREEN))
    print(_paint("Command accepted. Returning to shell interface.\n", _DIM_GREEN))
