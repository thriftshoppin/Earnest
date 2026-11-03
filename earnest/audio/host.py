"""Build and control the small native WASAPI host used by ``earnest route``."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable


class AudioHostError(RuntimeError):
    pass


_NATIVE = Path(__file__).with_name("native")
_SOURCE = _NATIVE / "EarnestAudioHost.cs"
_EXE = _NATIVE / "EarnestAudioHost.exe"
_STATE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Earnest" / "route-state.json"


def _csc() -> Path:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    compiler = windows / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    if not compiler.exists():
        compiler = windows / "Microsoft.NET" / "Framework" / "v4.0.30319" / "csc.exe"
    if not compiler.exists():
        raise AudioHostError(".NET Framework C# compiler not found; install .NET Framework 4.8")
    return compiler


def ensure_host() -> Path:
    required = (_SOURCE, _NATIVE / "NAudio.Core.dll", _NATIVE / "NAudio.Wasapi.dll")
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise AudioHostError("native audio host files missing: " + ", ".join(missing))
    if _EXE.exists() and _EXE.stat().st_mtime >= _SOURCE.stat().st_mtime:
        return _EXE
    netstandard = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "netstandard.dll"
    if not netstandard.exists():
        netstandard = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework" / "v4.0.30319" / "netstandard.dll"
    args = [_csc(), "/nologo", "/target:exe", "/optimize+", "/out:%s" % _EXE,
            "/r:%s" % (_NATIVE / "NAudio.Core.dll"), "/r:%s" % (_NATIVE / "NAudio.Wasapi.dll"),
            "/r:%s" % netstandard, str(_SOURCE)]
    built = subprocess.run(args, cwd=_NATIVE, text=True, capture_output=True)
    if built.returncode:
        detail = (built.stdout + "\n" + built.stderr).strip()
        raise AudioHostError("could not build native audio host:\n" + detail)
    return _EXE


def _run(arguments: Iterable[str], capture: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run([str(ensure_host()), *arguments], cwd=_NATIVE,
                            text=True, capture_output=capture)
    if result.returncode:
        raise AudioHostError((result.stderr or result.stdout or "audio host failed").strip())
    return result


def devices() -> list[dict[str, str]]:
    rows = _run(["--devices"]).stdout.splitlines()
    return [{"id": endpoint, "name": name} for row in rows if "\t" in row
            for endpoint, name in [row.split("\t", 1)]]


def default_endpoint_id() -> str:
    return _run(["--default-id"]).stdout.strip()


def set_default(selector: str) -> None:
    _run(["--set-default", selector])


def save_route_state(previous_default: str, virtual_input: str, physical_output: str,
                     profile: Path) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps({"schema": "earnest.route-state.v1", "previous_default": previous_default,
                                  "virtual_input": virtual_input, "physical_output": physical_output,
                                  "profile": str(profile)}, indent=2) + "\n", encoding="utf-8")


def route_state_exists() -> bool:
    return _STATE.exists()


def restore_route_state() -> bool:
    if not _STATE.exists():
        return False
    state = json.loads(_STATE.read_text(encoding="utf-8"))
    previous = state.get("previous_default")
    if not isinstance(previous, str) or not previous:
        raise AudioHostError("route state has no previous default endpoint")
    set_default(previous)
    _STATE.unlink()
    return True


def route(virtual_input: str, physical_output: str, profile: Path) -> int:
    """Run in the foreground so Ctrl+C remains an obvious, reliable stop control."""
    return subprocess.run([str(ensure_host()), "--route", "--input", virtual_input,
                           "--output", physical_output, "--profile", str(profile)], cwd=_NATIVE).returncode


def bridge(input_endpoint: str, output_endpoint: str, profile: Path, capture_input: bool = False) -> int:
    arguments = [str(ensure_host()), "--bridge", "--input", input_endpoint,
                 "--output", output_endpoint, "--ir-profile", str(profile)]
    if capture_input:
        arguments.append("--capture-input")
    return subprocess.run(arguments, cwd=_NATIVE).returncode
