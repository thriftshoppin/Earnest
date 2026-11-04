"""Visible terminal boot sequence for the Earnest command application."""
from __future__ import annotations

import importlib
import os
import platform
import sys
from time import perf_counter
from .version import SHELL_VERSION


_RESET = "\x1b[0m"
_PINK = "\x1b[38;2;255;46;136m"       # StageJack accent
_BLUE = "\x1b[38;2;0;190;255m"        # StageJack electric blue
_WHITE = "\x1b[38;2;238;242;240m"     # StageJack text
_MUTED = "\x1b[38;2;160;170;166m"
_FRAME = "\x1b[38;2;76;91;86m"
_AMBER = "\x1b[38;2;255;176;0m"
_RED = "\x1b[38;2;255;95;95m"
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
    return (
        r"       .-''''-.",
        r"     .'   /  .'",
        r"    /   /  .'/",
        r"   /  /  .' /",
        r"  / /  .'  /",
        r" /.' .'  .'",
        r" ' ./_.-'",
        r"   /",
        r"  /",
    )


def _banner() -> None:
    logo = (
        r" _____    _    ____  _   _ _____ ____ _____",
        r"| ____|  / \  |  _ \| \ | | ____/ ___|_   _|",
        r"|  _|   / _ \ | |_) |  \| |  _| \___ \ | |",
        r"| |___ / ___ \|  _ <| |\  | |___ ___) || |",
        r"|_____/_/   \_\_| \_\_| \_|_____|____/ |_|",
        r"",
        r"  P E R C E P T I O N  /  R O O M  /  A U D I O",
        "  COMMAND DECK  ::  v" + SHELL_VERSION,
        r"",
    )
    print(_paint("+" + "-" * 73 + "+", _FRAME))
    for feather, word in zip(_feather_art(), logo):
        print(_paint("| ", _FRAME) + _paint(feather.ljust(18), _PINK) +
              _paint(word.ljust(53), _WHITE if "COMMAND DECK" not in word else _BLUE) + _paint(" |", _FRAME))
    print(_paint("+" + "-" * 73 + "+", _FRAME))


def _load_stage(number: int, label: str, modules: tuple[str, ...]) -> None:
    print(_paint("\n[0x%02X] INIT // %s" % (number, label.upper()), _BLUE, bold=True))
    width = max(len(module) for module in modules)
    for module in modules:
        sys.stdout.write(_paint("    > %-*s " % (width, module), _MUTED))
        sys.stdout.flush()
        try:
            importlib.import_module(module)
        except Exception as exc:
            print(_paint("[FAILED]", _RED, bold=True))
            print(_paint("      %s" % exc, _RED))
            raise SystemExit(1)
        print(_paint("[ LOADED ]", _PINK, bold=True))


def boot(interactive: bool = False) -> None:
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

    print(_paint("\n[0x07] INIT // COMPONENT REGISTRY", _BLUE, bold=True))
    try:
        from .engine import create_engine
        engine = create_engine()
    except Exception as exc:
        print(_paint("    [FAILED] %s" % exc, _RED, bold=True))
        raise SystemExit(1)
    for component in engine.components:
        print(_paint("    + %s" % component, _MUTED))

    try:
        importlib.import_module("earnest.audio.host")
        audio_status = "LIVE ROUTER MODULE LOADED // DEVICE AND ROUTE NOT VERIFIED"
        audio_color = _BLUE
    except ImportError:
        audio_status = "DEVICE OUTPUT UNAVAILABLE // WAV RENDER ACTIVE"
        audio_color = _AMBER
    print(_paint("\n[AUDIO] " + audio_status, audio_color))
    elapsed_ms = (perf_counter() - started) * 1000.0
    print(_paint("\n+----------------------------------------------------------------+", _FRAME))
    print(_paint("|  ENGINE ONLINE  //  READY  //  BOOT %.0f ms" % elapsed_ms, _PINK, bold=True))
    print(_paint("+----------------------------------------------------------------+", _FRAME))
    print(_paint("Command deck ready.\n" if interactive else "Command accepted. Returning to shell interface.\n", _MUTED))
