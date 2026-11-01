"""Command line: python -m earnest gen | listen | room | resynth | zoom | crosscheck"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import formula, gen, listen, plots, report, resynth, room, suite
from .io import FS, new_run, read_wav, save_json


def cmd_gen(a):
    out = Path(a.out) if a.out else new_run("gen")
    out.mkdir(parents=True, exist_ok=True)
    if a.suite:
        x, m = suite.write(a.suite, out)
        save_json(out / ("probe_suite_%s.json" % a.suite), m)
        plots.suite_png(out / ("probe_suite_%s.png" % a.suite), x, m["blocks"], "earnest gen --suite %s" % a.suite)
        n = report.suite_report(m, out / "report.md", out)
        print("gen --suite %s: %s (%.3f s; report %d lines)" % (a.suite, out / ("probe_suite_%s.wav" % a.suite), m["length_s"], n))
        return 0
    sigs, manifest = gen.run(out)
    save_json(out / "gen.json", manifest)
    plots.gen_png(out / "gen.png", sigs, "earnest gen")
    n = report.gen_report(manifest, out / "report.md", out)
    print("gen: wrote %d files to %s (report %d lines)" % (len(sigs), out, n))
    return 0


def _listen(path, t0=None, t1=None, hires=False, cmd="listen"):
    x, notes = read_wav(path)
    title = Path(path).name
    if t0 is not None or t1 is not None:
        a, b = int((t0 or 0) * FS), int((t1 or len(x) / FS) * FS)
        x = x[a:b]
        title += " [%.3f-%.3f s]" % (a / FS, b / FS)
        notes.append("slice %.3f-%.3f s (times in this run are relative to the slice start)" % (a / FS, b / FS))
    if len(x) < FS // 10:
        raise SystemExit("%s: fewer than 0.1 s of audio" % cmd)
    out = new_run(cmd)
    res, pg = listen.analyze(x, FS, hires)
    res["source"], res["notes"] = str(path), notes
    save_json(out / (cmd + ".json"), res)
    plots.listen_png(out / (cmd + ".png"), x, res, pg, "earnest %s: %s" % (cmd, title))
    n = report.listen_report(res, out / "report.md", title, notes)
    print("%s: %s (report %d lines)" % (cmd, out, n))
    return 0


def cmd_listen(a):
    return _listen(a.file)


def cmd_split(a):
    man = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dry_out = Path(a.dry_out) if a.dry_out else None
    if dry_out:
        dry_out.mkdir(parents=True, exist_ok=True)
    r = suite.split(a.wet, man, out, dry_out)
    save_json(out / "split.json", r)
    wet, _ = read_wav(a.wet)
    plots.suite_png(out / "split.png", wet, man["blocks"], "earnest split: %s (offset %.3f ms)" % (Path(a.wet).name, r["offset_ms"]), r["offset_samples"] / FS)
    n = report.split_report(r, out / "report.md", a.wet)
    print("split: %d blocks written to %s, offset %.3f ms (report %d lines)" % (len(r["blocks"]), out, r["offset_ms"], n))
    return 0


def cmd_zoom(a):
    return _listen(a.file, getattr(a, "from"), a.to, True, "zoom")


def cmd_room(a):
    res, plot = room.run_room(a.dry, a.wet)
    out = new_run("room")
    f = formula.build(res, "dry=%s wet=%s" % (a.dry, a.wet))
    save_json(out / "formula.json", f)
    res2 = dict(res)
    save_json(out / "room.json", res2)
    plots.room_png(out / "room.png", res, plot, "earnest room: %s vs %s" % (Path(a.dry).name, Path(a.wet).name))
    n = report.room_report(res, out / "report.md", "%s vs %s" % (Path(a.dry).name, Path(a.wet).name))
    print("room: %s (report %d lines)" % (out, n))
    return 0


def cmd_resynth(a):
    f = json.loads(Path(a.formula).read_text(encoding="utf-8"))
    s = resynth.run(f, a.dry, a.compare, a.seeds)
    out = new_run("resynth")
    save_json(out / "resynth.json", s)
    plots.resynth_png(out / "resynth.png", s, "earnest resynth: %s" % Path(a.formula).name)
    n = report.resynth_report(s, out / "report.md", Path(a.formula).name)
    print("resynth: %s (report %d lines)" % (out, n))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="earnest", description="Turns stereo audio into things Claude can read. Never plays audio.")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="write test-signal WAV files")
    g.add_argument("--out", help="output folder (default: a new run folder)")
    g.add_argument("--suite", choices=["lite", "full"], help="write ONE probe-suite WAV with every stimulus joined (plus its manifest) instead of the separate files")
    g.set_defaults(fn=cmd_gen)
    sp = sub.add_parser("split", help="cut a wet suite export back into the named block files")
    sp.add_argument("wet")
    sp.add_argument("manifest")
    sp.add_argument("out_dir")
    sp.add_argument("--dry-out", help="also write the matching dry blocks here")
    sp.set_defaults(fn=cmd_split)
    l = sub.add_parser("listen", help="stereo scene sheet of a file")
    l.add_argument("file")
    l.set_defaults(fn=cmd_listen)
    z = sub.add_parser("zoom", help="listen at high resolution on a slice")
    z.add_argument("file")
    z.add_argument("--from", dest="from", type=float, required=True)
    z.add_argument("--to", type=float, required=True)
    z.set_defaults(fn=cmd_zoom)
    r = sub.add_parser("room", help="fit a reverb formula from dry and wet renders (two folders, or two sweep WAV files)")
    r.add_argument("dry")
    r.add_argument("wet")
    r.set_defaults(fn=cmd_room)
    s = sub.add_parser("resynth", help="render a formula and report statistical error")
    s.add_argument("formula")
    s.add_argument("dry")
    s.add_argument("--compare", help="real wet render of the same dry file")
    s.add_argument("--seeds", type=int, default=5)
    s.set_defaults(fn=cmd_resynth)
    from . import crosscheck
    c = sub.add_parser("crosscheck", help="compare room fits of the eight Univerb renders with univerb_results.csv")
    c.add_argument("--dry", default=str(crosscheck.DRY))
    c.add_argument("--wet-dir", default=str(crosscheck.WET_DIR))
    c.add_argument("--csv", default=str(crosscheck.CSV))
    c.set_defaults(fn=crosscheck.run_cmd)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
