"""`reset`: archive the old results and start clean, then self-test. Nothing is deleted: folders in runs\\ and inbox\\processed.json are MOVED into archive\\<timestamp>\\.
Never touches the user's files in inbox\\, nor data\\, probe\\, the source, tests, README or requirements-lock.txt. `--purge-archive <days>` sends old archive folders to the Recycle Bin."""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .io import ROOT

DEPS = [("numpy", "numpy"), ("scipy", "scipy"), ("soundfile", "soundfile"), ("matplotlib", "matplotlib"), ("pyloudnorm", "pyloudnorm")]


def _version(dist):
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:
        return None


def check_dependencies() -> bool:
    ok = True
    print("python %s" % sys.version.split()[0])
    for mod, dist in DEPS:
        try:
            importlib.import_module(mod)
            print("  %-11s %s" % (mod, _version(dist) or "?"))
        except Exception as e:
            print("  %-11s MISSING (%s)" % (mod, e))
            ok = False
    if not ok:
        print("A dependency is missing. Nothing was installed; install it yourself and run reset again.")
    return ok


def to_recycle_bin(path: Path) -> bool:
    """Visible PowerShell call: Microsoft.VisualBasic FileSystem.DeleteDirectory with SendToRecycleBin (never a hard delete)."""
    ps = ("Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory('%s', "
          "[Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs, [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)" % str(path).replace("'", "''"))
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    return r.returncode == 0 and not path.exists()


def run(yes: bool = False, purge_days=None, root=None, no_ping: bool = False) -> int:
    root = Path(root) if root else ROOT
    runs, inbox, archive = root / "runs", root / "inbox", root / "archive"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = archive / stamp
    folders = sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []
    state = inbox / "processed.json"
    print("earnest reset (%s)" % root)
    print("This will:")
    print("  1. MOVE %d folder(s) from %s into %s (nothing is deleted):" % (len(folders), runs, dest))
    for f in folders:
        print("       %s" % f.name)
    print("  2. MOVE %s into the same archive and create an empty one" % state)
    print("  3. leave your files in %s, and data\\, probe\\, the source, tests, README and requirements-lock.txt, untouched" % inbox)
    if purge_days is not None:
        print("  4. send archive folders older than %s day(s) to the Recycle Bin" % purge_days)
    print("  5. check the dependencies, then run `earnest ping`")
    if not yes:
        print("\nPress any key to go ahead, or close this window to cancel ...")
        try:
            import msvcrt
            msvcrt.getwch()
        except ImportError:
            input()
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    (dest / "runs").mkdir(exist_ok=True)
    for f in folders:
        shutil.move(str(f), str(dest / "runs" / f.name))
        moved.append(f.name)
    runs.mkdir(exist_ok=True)
    if state.exists():
        shutil.move(str(state), str(dest / "processed.json"))
    inbox.mkdir(exist_ok=True)
    state.write_text(json.dumps({"version": 2, "rooms": {}}), encoding="utf-8")
    print("\narchived %d folder(s) and processed.json to %s" % (len(moved), dest))
    if purge_days is not None and archive.exists():
        cutoff = datetime.now() - timedelta(days=float(purge_days))
        for d in sorted(archive.iterdir()):
            if not d.is_dir() or d == dest:
                continue
            try:
                when = datetime.strptime(d.name[:15], "%Y%m%d-%H%M%S")
            except ValueError:
                when = datetime.fromtimestamp(d.stat().st_mtime)
            if when < cutoff:
                print("  to the Recycle Bin: %s -> %s" % (d.name, "ok" if to_recycle_bin(d) else "FAILED"))
    print()
    if not check_dependencies():
        return 3
    if no_ping:
        print("\n(ping skipped)")
        return 0
    from . import ping
    code = ping.run(False, runs / "ping")
    print("\n" + ("READY" if code == 0 else "NOT READY: ping failed (see above)"))
    return code
