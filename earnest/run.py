"""`run`: the one command. Processes the exports in the inbox folder (new or changed ones only), mirrors the newest results into runs\\latest\\ and opens that folder.
Never moves, renames or deletes the user's files; never plays audio. Single-pass files are grouped into rooms by name (`union100.flac` = room union, Mix 100; `dry*.flac` = the
dry reference), several-pass files are one room each (see pipeline.py)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import analyze, pipeline
from .io import ROOT, RUNS, save_json

INBOX = ROOT / "inbox"
LATEST = RUNS / "latest"
STATE = "processed.json"


def _sig(p: Path) -> list:
    st = Path(p).stat()
    return [Path(p).name, st.st_size, st.st_mtime_ns]


def _load_state(inbox: Path) -> dict:
    f = inbox / STATE
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("version") == 2:
                return d
        except Exception:
            pass
    return {"version": 2, "rooms": {}}


def _room_sig(members, dry_member) -> list:
    return sorted([_sig(m["path"]) for m in members]) + ([["dry"] + _sig(dry_member["path"])] if dry_member else [])


def _room_lines(room: str, data: dict) -> list:
    out = []
    probs = data.get("problems") or []
    kind = "OK" if not probs else ("EMPTY" if any(("EMPTY" in p or "empty" in p) for p in probs) else ("not clean dry" if any("Mix 0" in p or "dry" in p for p in probs) else "flagged"))
    out.append("%s: %s%s" % (room, kind, (" - " + "; ".join(probs)[:400]) if probs else ""))
    for f in data.get("files", []):
        hop = f.get("failed_hop")
        out.append("    %s: %s%s" % (f.get("file", "?"), f.get("status", "?"), (" at hop %s: %s" % (hop, f.get("reason", ""))) if hop else ""))
    return out


def run(inbox=None, force: bool = False, latest=None, manifest=None, labels=None, open_explorer: bool = True, stop_on_fail: bool = False) -> int:
    inbox = Path(inbox) if inbox else INBOX
    latest = Path(latest) if latest else LATEST
    inbox.mkdir(parents=True, exist_ok=True)
    state = _load_state(inbox)
    plan = analyze.plan_folder(inbox)
    if not plan["all"]:
        print("inbox is empty: put the Cakewalk exports (.wav or .flac) in %s and run again" % inbox)
        return 0
    print("inbox: %d file(s), %d room(s)%s" % (len(plan["all"]), len(plan["rooms"]), (", dry reference: %s" % Path(plan["dry"]["path"]).name) if plan["dry"] else ", no dry reference"))
    for n in plan["notes"]:
        print("NOTE: " + n)
    for d in plan["duplicates"]:
        print("DUPLICATE: %s has the same content as %s and is skipped" % (d["file"], d["duplicate_of"]))
    done, skipped, failed = [], [], []
    cache = {}
    for room_name, members in plan["rooms"].items():
        sig = _room_sig(members, plan["dry"])
        old = state["rooms"].get(room_name)
        if not force and old and old.get("sig") == sig and (Path(old.get("run_folder", "")) / "summary.json").exists():
            skipped.append(room_name)
            print("skipping room %s (its files are unchanged since the last run)" % room_name)
            continue
        print("analyzing room '%s': %s ..." % (room_name, ", ".join(Path(m["path"]).name for m in members)))
        t0 = time.time()
        try:
            results, _, out_root = analyze.process_folder(inbox, labels, manifest, stop_on_fail=stop_on_fail, quiet=False, plan=plan, only_rooms=[room_name], out_root=RUNS / time.strftime("%Y%m%d-%H%M%S-run"), cache=cache)
        except Exception as e:
            failed.append("%s: FAILED - %s: %s" % (room_name, type(e).__name__, e))
            continue
        r = results[0]
        if r.get("data") is None:
            failed.append("%s: FAILED - %s" % (room_name, r.get("error")))
            continue
        state["rooms"][room_name] = {"sig": sig, "run_folder": str(Path(r["summary"]).parent), "exit_code": r["code"], "problems": r["data"]["problems"],
                                     "seconds": round(time.time() - t0, 1), "done_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        done.append(room_name)
        save_json(inbox / STATE, state)
        if stop_on_fail and r["code"] != 0:
            print("stopping at the first failure (--stop-on-fail)")
            break
    save_json(inbox / STATE, state)
    # mirror the newest result of every room into latest\
    latest.mkdir(parents=True, exist_ok=True)
    results, lines = [], []
    for room_name in plan["rooms"]:
        ent = state["rooms"].get(room_name)
        if not ent:
            continue
        rf = Path(ent["run_folder"])
        try:
            data = json.loads((rf / "summary.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        tag = analyze.slug(room_name)
        for src_name, dst in (("summary.md", "%s_summary.md" % tag), ("mixcurve.png", "%s_mixcurve.png" % tag)):
            if (rf / src_name).exists():
                shutil.copy2(rf / src_name, latest / dst)
        steps = sorted(rf.glob("step*_mix*"), key=lambda p: -int(p.name.split("mix")[-1]) if p.name.split("mix")[-1].isdigit() else 0)
        top = [s for s in steps if (s / "room.png").exists()]
        if top:
            shutil.copy2(top[0] / "room.png", latest / ("%s_room.png" % tag))
        for t in sorted((rf / "trace").glob("*/trace.txt")) if (rf / "trace").exists() else []:
            shutil.copy2(t, latest / ("%s_trace.txt" % t.parent.name))
        results.append({"file": ", ".join(f.get("file", "?") for f in data.get("files", [])), "room": room_name, "code": ent["exit_code"], "summary": str(rf / "summary.md"), "data": data})
        lines += _room_lines(room_name, data) if room_name not in skipped else [l + ("  (not re-run: unchanged)" if i == 0 else "") for i, l in enumerate(_room_lines(room_name, data))]
    bad = analyze.all_rooms_report(results, latest / "all_rooms_summary.md", "Inbox: %s" % inbox, plan)
    print()
    print("Results:")
    for ln in lines + ["%s" % f for f in failed]:
        print("  " + ln)
    print()
    print("all_rooms_summary: %s" % (latest / "all_rooms_summary.md"))
    print("analyzed %d, skipped %d unchanged" % (len(done), len(skipped)))
    if open_explorer and sys.platform == "win32":
        try:
            os.startfile(str(latest))           # a normal, visible File Explorer window
        except OSError as e:
            print("could not open %s: %s" % (latest, e))
    return 1 if (bad or failed) else 0
