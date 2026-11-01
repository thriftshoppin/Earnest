"""`run`: the one command. Processes every export in the inbox folder (new or changed files only), mirrors the newest results into runs\\latest\\ and opens that folder.
Never moves, renames or deletes the user's files; never plays audio."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import analyze
from .io import ROOT, RUNS, save_json

INBOX = ROOT / "inbox"
LATEST = RUNS / "latest"
STATE = "processed.json"


def _sig(p: Path) -> dict:
    st = p.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def _load_state(inbox: Path) -> dict:
    f = inbox / STATE
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "files": {}}


def _status_line(room: str, data: dict) -> str:
    probs = data.get("problems") or []
    if not probs:
        return "%s: OK" % room
    kind = "EMPTY" if any(("EMPTY" in p or "empty" in p) for p in probs) else ("not clean dry" if any("Mix 0" in p for p in probs) else "flagged")
    return "%s: %s - %s" % (room, kind, "; ".join(probs)[:300])


def run(inbox=None, force: bool = False, latest=None, manifest=None, labels=None, open_explorer: bool = True) -> int:
    inbox = Path(inbox) if inbox else INBOX
    latest = Path(latest) if latest else LATEST
    inbox.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in inbox.iterdir() if p.suffix.lower() in (".wav", ".flac"))
    state = _load_state(inbox)
    if not files:
        print("inbox is empty: put the Cakewalk exports (.wav or .flac, one per room) in %s and run again" % inbox)
        return 0
    lines, done, skipped = [], [], []
    for f in files:
        room = analyze.room_from_filename(f)
        sig = _sig(f)
        old = state["files"].get(f.name)
        if (not force and old and old.get("size") == sig["size"] and old.get("mtime_ns") == sig["mtime_ns"]
                and (Path(old.get("run_folder", "")) / "summary.json").exists()):
            skipped.append(f.name)
            print("skipping %s (unchanged since the last run)" % f.name)
            continue
        print("analyzing %s as room '%s' ..." % (f.name, room))
        t0 = time.time()
        try:
            code, sp, s = analyze.analyze(f, room, manifest, labels, quiet=True)
        except Exception as e:      # one bad file must not stop the others; it is retried next time
            lines.append("%s: FAILED - %s: %s" % (room, type(e).__name__, e))
            state["files"].pop(f.name, None)
            continue
        state["files"][f.name] = {**sig, "room": room, "run_folder": str(sp.parent), "exit_code": code, "problems": s["problems"], "seconds": round(time.time() - t0, 1),
                                  "done_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        done.append(f.name)
        save_json(inbox / STATE, state)           # saved after every file so an interrupted run keeps its progress
    save_json(inbox / STATE, state)
    # mirror the newest result of every room in the inbox into latest\
    latest.mkdir(parents=True, exist_ok=True)
    results, used = [], set()
    for f in files:
        ent = state["files"].get(f.name)
        if not ent:
            continue
        rf = Path(ent["run_folder"])
        try:
            data = json.loads((rf / "summary.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        room = ent["room"]
        tag = analyze.slug(room)
        if tag in used:
            tag = analyze.slug(Path(f.name).stem)
        used.add(tag)
        for src_name, dst in (("summary.md", "%s_summary.md" % tag), ("mixcurve.png", "%s_mixcurve.png" % tag)):
            if (rf / src_name).exists():
                shutil.copy2(rf / src_name, latest / dst)
        m100 = sorted(rf.glob("step1*/room.png"))
        if m100:
            shutil.copy2(m100[0], latest / ("%s_room.png" % tag))
        results.append({"file": f.name, "room": room, "code": ent["exit_code"], "summary": str(rf / "summary.md"), "data": data})
        lines.append(_status_line(room, data) + ("  (not re-run: unchanged)" if f.name in skipped else ""))
    bad = analyze.all_rooms_report(results, latest / "all_rooms_summary.md", "Inbox: %s" % inbox)
    print()
    print("Results:")
    for ln in lines:
        print("  " + ln)
    print()
    print("all_rooms_summary: %s" % (latest / "all_rooms_summary.md"))
    print("analyzed %d, skipped %d unchanged" % (len(done), len(skipped)))
    if open_explorer and sys.platform == "win32":
        try:
            os.startfile(str(latest))           # a normal, visible File Explorer window
        except OSError as e:
            print("could not open %s: %s" % (latest, e))
    return 1 if (bad or any("FAILED" in ln for ln in lines)) else 0
