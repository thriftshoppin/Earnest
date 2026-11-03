"""Command line: python -m earnest gen | listen | room | resynth | zoom | crosscheck"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import formula, gen, listen, plots, report, resynth, room, suite
from .io import FS, new_run, read_wav, save_json


def cmd_visualize(a):
    from .visualize import build
    try:
        path = build(a.room_file, a.reference, a.comparison, a.out, a.sample_rate, a.order)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit("visualize: %s" % exc)
    if a.open:
        import webbrowser
        webbrowser.open(path.as_uri())
    return 0


def cmd_live_view(a):
    import os
    import subprocess
    import threading
    import webbrowser
    from .io import ROOT
    from .room_editor import create_server
    server = ROOT / "live" / "server.js"
    if not server.is_file():
        raise SystemExit("live-view: viewer is not installed: %s" % server)
    try:
        editor = create_server(a.editor_port)
    except OSError as exc:
        raise SystemExit("live-view: unable to start Room Studio: %s; choose --editor-port" % exc)
    threading.Thread(target=editor.serve_forever, daemon=True).start()
    editor_port = editor.server_address[1]
    print("live-view: read-only playback monitoring; this does not create an audio output", flush=True)
    print("live-view: Room Studio available on http://127.0.0.1:%s/" % editor_port, flush=True)
    if a.open:
        threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:%d/" % a.port)).start()
    try:
        env = os.environ.copy()
        env["EARNEST_EDITOR_PORT"] = str(editor_port)
        return subprocess.call(["node", str(server), a.endpoint, str(a.port)], cwd=str(ROOT), env=env)
    except OSError as exc:
        raise SystemExit("live-view: %s" % exc)
    finally:
        editor.shutdown()
        editor.server_close()


def cmd_gen(a):
    out = Path(a.out) if a.out else new_run("gen")
    out.mkdir(parents=True, exist_ok=True)
    if a.suite:
        x, m = suite.write(a.suite, out)
        save_json(out / ("probe_suite_%s.json" % a.suite), m)
        plots.suite_png(out / ("probe_suite_%s.png" % a.suite), x, m["blocks"], "earnest gen --suite %s" % a.suite)
        n = report.suite_report(m, out / "report.md", out)
        print("gen --suite %s: %s (%.3f s; report %d lines)" % (a.suite, out / ("probe_suite_%s.wav" % a.suite), m["total_s"], n))
        return 0
    sigs, manifest = gen.run(out)
    save_json(out / "gen.json", manifest)
    plots.gen_png(out / "gen.png", sigs, "earnest gen")
    n = report.gen_report(manifest, out / "report.md", out)
    print("gen: wrote %d files to %s (report %d lines)" % (len(sigs), out, n))
    return 0


def cmd_capture_kit(a):
    from .capture import create_kit
    try:
        result = create_kit(a.out, room_name=a.room, gain_db=a.gain_db)
    except (OSError, ValueError) as exc:
        raise SystemExit("capture-kit: %s" % exc)
    print("capture-kit: ready at %s" % result)
    return 0


def cmd_capture_check(a):
    from .capture import check_kit
    try:
        result = check_kit(a.folder)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit("capture-check: %s" % exc)
    print(json.dumps(result, indent=2))
    return 1 if any(row["warnings"] for row in result["takes"]) else 0


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


def _labels(a):
    return [int(x) if x.strip().lstrip("-").isdigit() else x.strip() for x in a.labels.split(",")] if a.labels else None


def cmd_split(a):
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    labels = _labels(a)
    reps = a.repeats if a.repeats else (len(labels) if labels else 1)
    from . import pipeline, trace
    tr = trace.Trace(Path(a.wet).name)
    tr.out_dir = out
    man = suite.load_manifest(a.manifest)
    try:
        pipeline.ingest(a.wet, man, suite.dry_signal(man, a.dry), labels or [None] * reps, tr, {})
    except trace.HopFail as e:
        tr.finish(out)
        print("split stopped at hop %s: %s (most likely: %s)" % (e.hop, e.reason, e.cause))
        return 2
    r = suite.run_split(a.wet, a.manifest, out, Path(a.dry_out) if a.dry_out else None, reps, labels, a.dry)
    cal = r["calibration"]
    tr.add("LEVEL", "OK" if cal.get("applied") else "WARN", ("G = %.3f dB divided out of every cut file; checks %s" % (cal["G_db"], cal["checks"])) if cal.get("applied") else
           ("no calibration: " + "; ".join(cal.get("warnings") or ["no Mix 0 label"])))
    tr.add("WRITE", "OK", "%d cop%s cut into %s; empty blocks per step: %s" % (len(r["steps"]), "y" if len(r["steps"]) == 1 else "ies", out, [len(s["empty_blocks"]) for s in r["steps"]]))
    tr.finish(out)
    save_json(out / "split.json", r)
    n = report.split_report(r, out / "report.md", a.wet)
    empties = [(s["index"], s["empty_blocks"]) for s in r["steps"] if s["empty_blocks"]]
    print("split: %d copy(ies) cut into %s (report %d lines)%s" % (len(r["steps"]), out, n, ("; EMPTY blocks in steps %s" % [e[0] for e in empties]) if empties else ""))
    return 2 if any(s["inferred"] or s["all_empty"] for s in r["steps"]) else 0


def cmd_analyze(a):
    from . import analyze
    code, p, s = analyze.analyze(a.export, a.room, a.manifest, _labels(a), a.out, a.dry, stop_on_fail=a.stop_on_fail, probe_path=a.probe, mix=a.mix)
    print("run time %.0f s, peak memory %.0f MB" % (s["seconds"], s["peak_memory_mb"]))
    return code


def cmd_analyze_all(a):
    from . import analyze
    code, p = analyze.analyze_all(a.folder, _labels(a), a.manifest, a.stop_on_fail)
    return code


def cmd_run(a):
    from . import run
    return run.run(a.inbox, a.force, a.latest, a.manifest, _labels(a), not a.no_open, a.stop_on_fail)


def cmd_reset(a):
    from . import reset
    return reset.run(a.yes, a.purge_archive, a.root, a.no_ping)


def cmd_ping(a):
    from . import ping
    return ping.run(a.quick)


def cmd_mixcurve(a):
    from . import mixcurve
    labels = _labels(a) or [Path(f).name for f in a.runs]
    if len(labels) != len(a.runs):
        raise SystemExit("mixcurve: %d labels for %d run folders" % (len(labels), len(a.runs)))
    out = new_run("mixcurve")
    c, n = mixcurve.write([(lb, mixcurve.load_run(f)) for lb, f in zip(labels, a.runs)], out, a.title or "mixcurve")
    save_json(out / "mixcurve.json", c)
    print("mixcurve: %s (report %d lines)" % (out, n))
    return 0


def cmd_zoom(a):
    return _listen(a.file, getattr(a, "from"), a.to, True, "zoom")


def cmd_room(a):
    from .engine import Artifact, EngineError, create_engine
    sets, clicks, notes = room.load_sets(a.dry, a.wet)
    if not sets["a"]:
        raise SystemExit("room: no sweep pairs found (need sweep_L.wav / sweep_R.wav in both folders, or two WAV files)")
    run = create_engine().execute(
        ("reverb.analyze", "acoustic.infer_character"),
        {"reverb.sweeps": Artifact("earnest.reverb-sweeps.v1",
                                    {"sets": sets, "clicks": clicks, "notes": notes},
                                    source="dry=%s wet=%s" % (a.dry, a.wet))},
        {"reverb.analyze": {"source": "dry=%s wet=%s" % (a.dry, a.wet)}})
    res = run.artifacts["reverb.observations"].value
    f = run.artifacts["reverb.measurement"].value
    plot = run.artifacts["reverb.plot_data"].value
    hypotheses = run.artifacts["acoustic.hypotheses"].value
    out = new_run("room")
    save_json(out / "formula.json", f)
    save_json(out / "inference.json", hypotheses)
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


def _room_template():
    return {
        "schema": "earnest.room.v1", "units": "m",
        "geometry": {"type": "shoebox", "dimensions": [8.0, 5.0, 2.8]},
        "materials": [{"id": "painted_plaster", "bands_hz": [125, 250, 500, 1000, 2000, 4000, 8000],
                        "absorption": [0.08, 0.07, 0.06, 0.05, 0.04, 0.04, 0.04],
                        "scattering": [0.05, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18]}],
        "surfaces": {wall: {"material_id": "painted_plaster"} for wall in
                     ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")},
        "sources": [
            {"id": "speaker_left", "position": [2.0, 2.0, 1.4], "level_db": [0, 0, 0, 0, 0, 0, 0], "directivity": "omni", "orientation": [1, 0, 0]},
            {"id": "speaker_right", "position": [2.0, 3.0, 1.4], "level_db": [0, 0, 0, 0, 0, 0, 0], "directivity": "omni", "orientation": [1, 0, 0]}
        ],
        "receivers": [{"id": "seat_1", "position": [5.5, 2.5, 1.2], "directivity": "omni", "orientation": [-1, 0, 0]}],
        "environment": {"temperature_c": 20.0, "humidity_percent": 50.0,
                        "pressure_pa": 101325.0, "air_absorption_enabled": False},
        "engine_controls": {
            "reflection_order": 4, "decay_model": "eyring",
            "absorption_scale": [1, 1, 1, 1, 1, 1, 1],
            "scattering_scale": [1, 1, 1, 1, 1, 1, 1],
            "diffuse_energy_scale": 1.0, "tail_duration_scale": 1.0
        }
    }


def cmd_room_template(a):
    path = Path(a.file)
    if path.exists():
        raise SystemExit("room-template: refusing to overwrite existing file: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_room_template(), indent=2) + "\n", encoding="utf-8")
    print("room-template: wrote %s; edit dimensions, six surface assignments, sources and receivers" % path)
    return 0


def cmd_room_field(a):
    from .engine import Artifact, EngineError, create_engine
    try:
        path = Path(a.room_file)
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        run = create_engine().execute(("room.parse", "room.field_slice"),
            {"room.document": Artifact("earnest.room.v1", document, source=str(path.resolve()))},
            {"room.field_slice": {"frequency_hz": a.frequency, "grid_size": a.grid,
                                  "height_m": a.height, "reflection_order": a.order}})
        result = run.artifacts["room.field_slice"].value
        if a.out:
            target = Path(a.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as f:
                json.dump(result, f, indent=2, allow_nan=False)
                f.write("\n")
            print("room-field: wrote %s" % target)
        else:
            print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, EngineError) as exc:
        raise SystemExit("room-field: %s" % exc)
    return 0


def cmd_soundfield_spectrum(a):
    from .engine import Artifact, EngineError, create_engine
    try:
        path = Path(a.input)
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        if a.room_solution:
            solution_path = Path(a.room_solution)
            solution = json.loads(solution_path.read_text(encoding="utf-8-sig"))
            workflow = ("soundfield.from_room_paths",)
            inputs = {"room.solution": Artifact("earnest.room-solution.v1", solution, source=str(solution_path.resolve())),
                      "soundfield.source_spectra": Artifact("earnest.source-spectra.v1", document, source=str(path.resolve()))}
        else:
            workflow = ("soundfield.propagate",)
            inputs = {"soundfield.input": Artifact("earnest.soundfield-input.v1", document, source=str(path.resolve()))}
        result = create_engine().execute(workflow, inputs).artifacts["soundfield.spectrum"].value
        if a.out:
            target = Path(a.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, allow_nan=False)
                stream.write("\n")
            print("soundfield-spectrum: wrote %s" % target)
        else:
            print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, EngineError) as exc:
        raise SystemExit("soundfield-spectrum: %s" % exc)
    return 0


def cmd_room_from_instructions(a):
    from .room_instructions import apply_instructions
    try:
        plan = json.loads(Path(a.instructions).read_text(encoding="utf-8-sig"))
        document = apply_instructions(plan)
        path = Path(a.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as f:
            json.dump(document, f, indent=2, allow_nan=False)
            f.write("\n")
        print("room-from-instructions: wrote %s" % path)
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit("room-from-instructions: %s" % exc)
    return 0


def cmd_room_editor(a):
    from .room_editor import serve
    try:
        serve(a.port, open_browser=a.open)
    except (OSError, ValueError) as exc:
        raise SystemExit("room-editor: %s" % exc)
    return 0


def cmd_instrument_modes(a):
    from .engine import Artifact, EngineError, create_engine
    try:
        path = Path(a.model)
        model = json.loads(path.read_text(encoding="utf-8-sig"))
        run = create_engine().execute(("instrument.modes",),
            {"instrument.model": Artifact("earnest.instrument-model.v1", model, source=str(path.resolve()))})
        print(json.dumps(run.artifacts["instrument.modes"].value, indent=2))
    except (OSError, ValueError, TypeError, EngineError) as exc:
        raise SystemExit("instrument-modes: %s" % exc)
    return 0


def cmd_instrument_train(a):
    from .engine.instrument_id import train
    try:
        out = Path(a.out)
        if out.exists():
            raise ValueError("output already exists; choose a new path")
        model = train(a.examples)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8") as f:
            json.dump(model, f, indent=2, allow_nan=False)
        print("trained on %d labeled recordings -> %s" % (len(model["samples"]), out))
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit("instrument-train: %s" % exc)
    return 0


def cmd_instrument_identify(a):
    import soundfile as sf
    from .engine import Artifact, EngineError, create_engine
    try:
        model = json.loads(Path(a.model).read_text(encoding="utf-8-sig"))
        with sf.SoundFile(a.audio) as source:
            fs = source.samplerate
            samples = source.read(frames=fs * 15, dtype="float64", always_2d=True)
        result = create_engine().execute(("instrument.identify",), {
            "audio.samples": Artifact("earnest.audio-samples.v1", {"samples": samples, "sample_rate_hz": int(fs)}, source=str(Path(a.audio).resolve())),
            "instrument.reference_model": Artifact("earnest.instrument-reference-model.v1", model, source=str(Path(a.model).resolve()))
        }).artifacts["instrument.identification"].value
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, EngineError, RuntimeError) as exc:
        raise SystemExit("instrument-identify: %s" % exc)
    return 0


def cmd_frequency_trace(a):
    import soundfile as sf
    from .engine import Artifact, EngineError, create_engine
    try:
        path = Path(a.audio)
        samples, fs = sf.read(str(path), dtype="float64", always_2d=True)
        run = create_engine().execute(("audio.frequency_trace",),
            {"audio.samples": Artifact("earnest.audio-samples.v1", {"samples": samples, "sample_rate_hz": int(fs)}, source=str(path.resolve()))},
            {"audio.frequency_trace": {"window_size": a.window, "hop_size": a.hop,
                                       "min_hz": a.min_hz, "max_hz": a.max_hz, "max_peaks": a.max_peaks,
                                       "min_level_dbfs": a.min_level_dbfs, "relative_threshold_db": a.relative_threshold_db}})
        result = run.artifacts["audio.frequency_trace"].value
        result["source_file"] = str(path.resolve())
        out = Path(a.out) if a.out else new_run("frequency-trace") / "frequency-trace.json"
        if out.exists():
            raise ValueError("output already exists; choose a new path")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print("frequency-trace: %d frames, %d channel(s) -> %s" % (len(result["frames"]), result["channels"], out))
    except (OSError, ValueError, TypeError, EngineError, RuntimeError) as exc:
        raise SystemExit("frequency-trace: %s" % exc)
    return 0


def cmd_room_solve(a):
    import re
    import soundfile as sf
    from .engine import Artifact, EngineError, RoomValidationError, create_engine
    try:
        room_path = Path(a.room_file)
        raw = json.loads(room_path.read_text(encoding="utf-8"))
        run = create_engine().execute(
            ("room.parse", "room.solve"),
            {"room.document": Artifact("earnest.room.v1", raw, source=str(room_path.resolve()))},
            {"room.solve": {"sample_rate": a.sample_rate, "reflection_order": a.order}})
        spec, result = run.artifacts["room.model"].value, run.artifacts["room.solution"].value
    except (OSError, json.JSONDecodeError, EngineError, RoomValidationError, ValueError) as exc:
        raise SystemExit("room-solve: %s" % exc)
    out = Path(a.out) if a.out else new_run("room-solve")
    out.mkdir(parents=True, exist_ok=True)
    metadata = dict(result)
    metadata["source_file"] = str(Path(a.room_file).resolve())
    metadata["ir_files"] = []
    metadata["source_receiver_pairs"] = []
    for index, pair in enumerate(result["source_receiver_pairs"]):
        safe = lambda value: re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
        base = "%s__%s" % (safe(pair["source_id"]), safe(pair["receiver_id"]))
        pair_meta = {key: value for key, value in pair.items() if key != "band_ir"}
        pair_meta["ir_files"] = {}
        for band, samples in pair["band_ir"].items():
            name = "%s_%sHz.wav" % (base, band)
            sf.write(str(out / name), np.asarray(samples, dtype=np.float32), a.sample_rate, subtype="FLOAT")
            pair_meta["ir_files"][band] = name
            metadata["ir_files"].append(name)
        metadata["source_receiver_pairs"].append(pair_meta)
    save_json(out / "solution.json", metadata)
    print("room-solve: %d source-receiver pair(s), %d band IRs -> %s" %
          (len(result["source_receiver_pairs"]), len(metadata["ir_files"]), out))
    for warning in result["model_limits"]:
        print("LIMIT: " + warning)
    return 0


def cmd_simulate(a):
    import math
    import re
    import soundfile as sf
    from scipy.signal import resample_poly
    from .engine import Artifact, EngineError, RoomValidationError, create_engine
    try:
        room_path = Path(a.room_file)
        room_raw = json.loads(Path(a.room_file).read_text(encoding="utf-8"))
        engine = create_engine()
        spec = engine.execute(
            ("room.parse",),
            {"room.document": Artifact("earnest.room.v1", room_raw, source=str(room_path.resolve()))}
        ).artifacts["room.model"].value
        source, source_fs = sf.read(str(a.audio), dtype="float64", always_2d=True)
        if source.shape[1] != len(spec.sources):
            raise ValueError("audio has %d channel(s), but the room defines %d source(s); provide one channel per source" %
                             (source.shape[1], len(spec.sources)))
        if source_fs != a.sample_rate:
            divisor = math.gcd(int(source_fs), int(a.sample_rate))
            source = resample_poly(source, a.sample_rate // divisor, int(source_fs) // divisor, axis=0)
        run = engine.execute(
            ("room.solve", "room.render"),
            {"room.model": Artifact("earnest.room-model.v1", spec, source=str(room_path.resolve())),
             "audio.sources": Artifact("earnest.audio-sources.v1", source, source=str(Path(a.audio).resolve()))},
            {"room.solve": {"sample_rate": a.sample_rate, "reflection_order": a.order},
             "room.render": {"sample_rate": a.sample_rate}})
        solution, rendered = run.artifacts["room.solution"].value, run.artifacts["room.rendered"].value
    except (OSError, json.JSONDecodeError, EngineError, RoomValidationError, ValueError) as exc:
        raise SystemExit("simulate: %s" % exc)
    out = Path(a.out) if a.out else new_run("simulate")
    out.mkdir(parents=True, exist_ok=True)
    ir_dir = out / "room_ir"
    ir_dir.mkdir(parents=True, exist_ok=True)
    safe = lambda value: re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    export = create_engine().execute(
        ("audio.export_receivers",),
        {"room.rendered": Artifact("earnest.room-render.v1", rendered)},
        {"audio.export_receivers": {"out_dir": str(out), "prefix": Path(a.audio).stem,
                                    "sample_rate": a.sample_rate, "subtype": "FLOAT"}})
    audio_files = export.artifacts["audio.files"].value
    outputs = {}
    for receiver_id, entry in rendered["receiver_outputs"].items():
        name = Path(audio_files[receiver_id]).name
        outputs[receiver_id] = {"file": name, **entry["analysis"]}
    compact_solution = dict(solution)
    compact_solution["source_receiver_pairs"] = []
    for pair in solution["source_receiver_pairs"]:
        row = {key: value for key, value in pair.items() if key != "band_ir"}
        base = "%s__%s" % (safe(pair["source_id"]), safe(pair["receiver_id"]))
        row["band_ir"] = {}
        for band, samples in pair["band_ir"].items():
            name = "%s_%sHz.wav" % (base, band)
            sf.write(str(ir_dir / name), np.asarray(samples, dtype=np.float32), a.sample_rate, subtype="FLOAT")
            row["band_ir"][band] = "room_ir/%s" % name
        compact_solution["source_receiver_pairs"].append(row)
    metadata = {"schema": "earnest.simulation.v1", "room_file": str(Path(a.room_file).resolve()),
                "input_audio": str(Path(a.audio).resolve()), "input_sample_rate_hz": int(source_fs),
                "render_sample_rate_hz": a.sample_rate, "input_frames_after_resampling": len(source),
                "source_channels": [s.id for s in spec.sources], "outputs": outputs,
                "render_limits": rendered["render_limits"], "model_limits": solution["model_limits"]}
    save_json(out / "simulation.json", metadata)
    save_json(out / "solution.json", compact_solution)
    print("simulate: rendered %d receiver(s) to %s (%.3f s input; output tails retained)" %
          (len(outputs), out, len(source) / a.sample_rate))
    for warning in rendered["render_limits"]:
        print("LIMIT: " + warning)
    return 0


def cmd_room_fit(a):
    from .engine import Artifact, EngineError, RoomValidationError, create_engine
    try:
        room_path, formula_path = Path(a.room_file), Path(a.formula)
        room_document = json.loads(room_path.read_text(encoding="utf-8"))
        formula_document = json.loads(formula_path.read_text(encoding="utf-8"))
        run = create_engine().execute(
            ("acoustic.infer_character", "room.fit_measurement"),
            {"room.document": Artifact("earnest.room.v1", room_document, source=str(room_path.resolve())),
             "reverb.measurement": Artifact("earnest.reverb-measurement.v1", formula_document,
                                             source=str(formula_path.resolve()))},
            {"room.fit_measurement": {"reverb_type": a.reverb_type}})
        fitted = run.artifacts["room.calibrated_document"].value
    except (OSError, json.JSONDecodeError, EngineError, RoomValidationError, ValueError) as exc:
        raise SystemExit("room-fit: %s" % exc)
    out = Path(a.out) if a.out else room_path.with_name(room_path.stem + ".calibrated.room.json")
    if out.exists():
        raise SystemExit("room-fit: refusing to overwrite existing file: %s" % out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fitted, indent=2) + "\n", encoding="utf-8")
    print("room-fit: measured decay mapped to per-band absorption controls using %s -> %s" %
          (fitted["analysis_evidence"]["fit_decay_model"], out))
    for row in fitted["analysis_evidence"]["fit"]:
        measured, predicted = row.get("measured_rt60_s"), row.get("predicted_rt60_s")
        print("  %4d Hz  measured=%s s  predicted=%s s  %s" %
              (row["hz"], "n/a" if measured is None else "%.3f" % measured,
               "n/a" if predicted is None else "%.3f" % predicted, row["status"]))
    print("  geometry and per-wall materials remain editable inputs; measured decay cannot uniquely identify them")
    return 0


def cmd_detect(a):
    from .engine.detection import detect_input
    try:
        result = detect_input(a.input)
    except (OSError, ValueError) as exc:
        raise SystemExit("detect: %s" % exc)
    print(json.dumps(result, indent=2))
    return 0


def cmd_room_solve_from_analysis(a):
    import re
    import soundfile as sf
    from .engine import Artifact, EngineError, RoomValidationError, create_engine
    from .engine.detection import detect_input

    try:
        room_path = Path(a.room_file)
        room_document = json.loads(room_path.read_text(encoding="utf-8-sig"))
        detected = detect_input(a.analysis)
        analysis_path = Path(detected.get("selected_file", detected["path"]))
        if detected["kind"] not in ("reverb_formula", "measurement"):
            raise ValueError("analysis input must be an Earnest formula.json or earnest.measurement.v1 JSON; detected %s" % detected["kind"])
        analysis_document = json.loads(analysis_path.read_text(encoding="utf-8-sig"))
        engine = create_engine()
        run = engine.execute(
            ("acoustic.infer_character", "room.solve_from_analysis"),
            {"room.document": Artifact("earnest.room.v1", room_document, source=str(room_path.resolve())),
             "reverb.measurement": Artifact("earnest.reverb-measurement.v1", analysis_document,
                                             source=str(analysis_path.resolve()))},
            {"room.solve_from_analysis": {"reverb_type": a.reverb_type,
                                           "sample_rate": a.sample_rate,
                                           "reflection_order": a.order}})
        calibrated = run.artifacts["room.calibrated_document"].value
        solution = run.artifacts["room.solution"].value
        fit_report = run.artifacts["room.fit_report"].value
        fit_report["inference"] = run.artifacts["acoustic.hypotheses"].value
    except (OSError, json.JSONDecodeError, EngineError, RoomValidationError, ValueError) as exc:
        raise SystemExit("room-solve-from-analysis: %s" % exc)

    out = Path(a.out) if a.out else new_run("room-solve-from-analysis")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise SystemExit("room-solve-from-analysis: refusing to write into a file or non-empty folder: %s" % out)
    out.mkdir(parents=True, exist_ok=True)
    calibrated_path = out / "calibrated.room.json"
    save_json(calibrated_path, calibrated)
    fit_report["source_room"] = str(room_path.resolve())
    fit_report["analysis_input"] = str(analysis_path.resolve())
    save_json(out / "fit_report.json", fit_report)

    metadata = dict(solution)
    metadata["source_room"] = str(room_path.resolve())
    metadata["analysis_input"] = str(analysis_path.resolve())
    metadata["calibrated_room"] = calibrated_path.name
    metadata["ir_files"] = []
    metadata["source_receiver_pairs"] = []
    for pair in solution["source_receiver_pairs"]:
        safe = lambda value: re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
        base = "%s__%s" % (safe(pair["source_id"]), safe(pair["receiver_id"]))
        pair_meta = {key: value for key, value in pair.items() if key != "band_ir"}
        pair_meta["ir_files"] = {}
        for band, samples in pair["band_ir"].items():
            name = "%s_%sHz.wav" % (base, band)
            sf.write(str(out / name), np.asarray(samples, dtype=np.float32), a.sample_rate, subtype="FLOAT")
            pair_meta["ir_files"][band] = name
            metadata["ir_files"].append(name)
        metadata["source_receiver_pairs"].append(pair_meta)
    save_json(out / "solution.json", metadata)
    print("room-solve-from-analysis: fitted room and solved %d source-receiver pair(s), %d band IRs -> %s" %
          (len(metadata["source_receiver_pairs"]), len(metadata["ir_files"]), out))
    for row in fit_report["fit"]:
        print("  %4d Hz  measured=%s s  predicted=%s s  %s" %
              (row["hz"], "n/a" if row.get("measured_rt60_s") is None else "%.3f" % row["measured_rt60_s"],
               "n/a" if row.get("predicted_rt60_s") is None else "%.3f" % row["predicted_rt60_s"], row["status"]))
    for warning in solution["model_limits"]:
        print("LIMIT: " + warning)
    return 0


def cmd_room_preview(a):
    from .engine import Artifact, EngineError, RoomValidationError, create_engine
    try:
        room_path = Path(a.room_file)
        raw = json.loads(room_path.read_text(encoding="utf-8"))
        engine = create_engine()
        run = engine.execute(
            ("room.parse", "audio.room_probe", "room.solve", "room.render"),
            {"room.document": Artifact("earnest.room.v1", raw, source=str(room_path.resolve()))},
            {"audio.room_probe": {"sample_rate": a.sample_rate, "duration_s": a.duration, "seed": a.seed},
             "room.solve": {"sample_rate": a.sample_rate},
             "room.render": {"sample_rate": a.sample_rate}})
        rendered = run.artifacts["room.rendered"].value
        receiver_id = a.receiver or next(iter(rendered["receiver_outputs"]))
        out_dir = Path(a.out).parent if a.out else new_run("room-preview")
        prefix = Path(a.out).stem if a.out else "room-preview"
        run = engine.execute(
            ("audio.export_receivers",), {"room.rendered": run.artifacts["room.rendered"]},
            {"audio.export_receivers": {"out_dir": str(out_dir), "prefix": prefix,
                                         "sample_rate": a.sample_rate, "subtype": "PCM_16",
                                         "receiver": receiver_id, "out_path": a.out, "max_peak": 0.95}})
        files = run.artifacts["audio.files"].value
        if receiver_id not in files:
            raise ValueError("unknown receiver %r; available: %s" % (receiver_id, ", ".join(files)))
        if a.play:
            run = engine.execute(("audio.play_default",), {"audio.files": run.artifacts["audio.files"]},
                                 {"audio.play_default": {"receiver": receiver_id}})
    except (OSError, json.JSONDecodeError, EngineError, RoomValidationError, ValueError) as exc:
        raise SystemExit("room-preview: %s" % exc)
    print("room-preview: %s receiver %s -> %s" %
          ("played" if a.play else "rendered", receiver_id, files[receiver_id]))
    return 0


def _live_room_profile(room_file: str, sample_rate: int, order: int | None,
                       dry_mix: float, wet_mix: float) -> dict:
    from .audio.profile import build_live_profile
    from .engine import Artifact, EngineError, RoomValidationError, create_engine
    try:
        room_path = Path(room_file)
        document = json.loads(room_path.read_text(encoding="utf-8-sig"))
        run = create_engine().execute(
            ("room.parse", "room.solve"),
            {"room.document": Artifact("earnest.room.v1", document, source=str(room_path.resolve()))},
            {"room.solve": {"sample_rate": sample_rate, "reflection_order": order}})
        return build_live_profile(run.artifacts["room.solution"].value, dry_mix=dry_mix, wet_mix=wet_mix)
    except (OSError, json.JSONDecodeError, EngineError, RoomValidationError, ValueError) as exc:
        raise SystemExit("route: %s" % exc)


def cmd_audio_devices(a):
    from .audio.host import AudioHostError, devices, _run
    try:
        if a.formats:
            print(_run(["--formats"]).stdout, end="")
            return 0
        rows = devices()
    except AudioHostError as exc:
        raise SystemExit("audio-devices: %s" % exc)
    if not rows:
        print("audio-devices: no active Windows render endpoints")
        return 1
    for row in rows:
        print("%s\n  %s" % (row["name"], row["id"]))
    return 0


def cmd_audio_restart(a):
    """Open the elevated, visible Windows Audio restart helper."""
    import os
    if sys.platform != "win32":
        raise SystemExit("audio-restart: Windows is required")
    helper = Path(__file__).resolve().parent.parent / "bin" / "restart-audio.bat"
    if not helper.is_file():
        raise SystemExit("audio-restart: helper not found: %s" % helper)
    try:
        os.startfile(str(helper))
    except OSError as exc:
        raise SystemExit("audio-restart: could not open helper: %s" % exc)
    print("audio-restart: opened the restart window; its status is shown there")
    return 0


def cmd_route(a):
    """Own the default Windows playback route until the foreground host stops."""
    from .audio import host
    profile = _live_room_profile(a.room_file, a.sample_rate, a.order, a.dry_mix, a.wet_mix)
    out = Path(a.profile_out) if a.profile_out else new_run("route") / "live-room-profile.json"
    if out.exists() and a.profile_out:
        raise SystemExit("route: refusing to overwrite existing profile: %s" % out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save_json(out, profile)
    switched = False
    try:
        endpoints = host.devices()
        def resolve(selector):
            exact = [row for row in endpoints if row["id"].lower() == selector.lower()]
            matches = exact or [row for row in endpoints if selector.lower() in row["name"].lower()]
            if len(matches) != 1:
                raise host.AudioHostError("endpoint %r matched %d active devices" % (selector, len(matches)))
            return matches[0]["id"]
        input_id, output_id = resolve(a.input), resolve(a.output)
        if input_id == output_id:
            raise host.AudioHostError("input and output must be different endpoints")
        if host.route_state_exists():
            raise host.AudioHostError("a saved route state already exists; run earnest route-stop first")
        previous = host.default_endpoint_id()
        host.save_route_state(previous, input_id, output_id, out)
        switched = True
        host.set_default(input_id)
        print("route: Windows default playback -> %s" % a.input)
        print("route: live room profile -> %s" % out)
        print("route: Earnest owns %s -> %s; press Ctrl+C here to stop and restore the previous default." %
              (a.input, a.output))
        code = host.route(input_id, output_id, out)
        if code:
            raise SystemExit("route: native audio host exited with code %d" % code)
        return 0
    except host.AudioHostError as exc:
        raise SystemExit("route: %s" % exc)
    finally:
        if switched:
            try:
                host.restore_route_state()
                print("route: previous Windows default playback restored")
            except (host.AudioHostError, OSError, json.JSONDecodeError) as exc:
                print("route: could not restore the previous default playback endpoint: %s" % exc, file=sys.stderr)


def cmd_route_stop(a):
    from .audio.host import AudioHostError, restore_route_state
    try:
        if restore_route_state():
            print("route-stop: previous Windows default playback restored")
        else:
            print("route-stop: no saved Earnest route state")
    except (AudioHostError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit("route-stop: %s" % exc)
    return 0


def cmd_bridge(a):
    """Compile the selected room, then run the explicit loopback bridge."""
    from .audio import host
    from .audio.convolution import compile_room
    profile = new_run("bridge") / "room.erir"
    try:
        details = compile_room(a.room_file, profile, sample_rate=a.sample_rate,
                               layout=a.layout, receiver_id=a.receiver,
                               order=a.order, dry=a.dry_mix, wet=a.wet_mix,
                               lookahead_ms=a.lookahead_ms)
        print("bridge: room profile -> %s" % details["profile"], flush=True)
        print("bridge: " + ", ".join(details["mapping"]), flush=True)
        print("bridge: %.1f ms solver lookahead + 512-frame processing block; device latency is additional" % a.lookahead_ms, flush=True)
        print("bridge: shared loopback may leave a parallel path to speakers; verify endpoint routing.", flush=True)
        print("bridge: press Ctrl+C to stop; Windows defaults are not changed.", flush=True)
        code = host.bridge(a.input, a.output, profile, capture_input=a.capture_input)
        if code:
            raise SystemExit("bridge: native audio host exited with code %d" % code)
    except (host.AudioHostError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("bridge: %s" % exc)
    return 0


def cmd_engine_init(a):
    from .engine import session
    path = Path(a.file)
    if path.exists():
        raise SystemExit("engine-init: refusing to overwrite %s" % path)
    try:
        config = session.new_session(a.room_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("engine-init: %s" % exc)
    print("engine-init: %s" % path.resolve())
    return 0


def cmd_engine_set(a):
    from .engine import session
    path = Path(a.file)
    try:
        config = session.load(path)
        if a.eq is not None:
            try:
                index = session.EQ_FREQUENCIES.index(a.eq)
            except ValueError:
                raise ValueError("EQ frequency must be one of %s Hz" % (session.EQ_FREQUENCIES,))
            config["eq_db"][index] = a.value
        else:
            key = {"wet": "wet_percent", "input": "input_gain_db", "output": "output_gain_db"}[a.control]
            config[key] = a.value
        session.validate(config)
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("engine-set: %s" % exc)
    print("engine-set: updated %s" % path.resolve())
    return 0


def cmd_engine_render(a):
    from .engine import session
    try:
        config = session.load(a.file)
        result = session.render(config, a.audio, a.out)
        if a.play:
            import tempfile
            import winsound
            import soundfile as sf
            samples, fs = sf.read(result["output"], dtype="float64")
            peak = float(np.max(np.abs(samples)))
            if peak > 0.95:
                samples *= 0.95 / peak
            with tempfile.TemporaryDirectory(prefix="earnest-play-") as directory:
                playback = Path(directory) / "preview.wav"
                sf.write(str(playback), samples, fs, subtype="PCM_16")
                winsound.PlaySound(str(playback), winsound.SND_FILENAME)
            if peak > 0.95:
                print("engine-render: playback attenuated to prevent clipping; float output unchanged")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("engine-render: %s" % exc)
    print("engine-render: receiver %s -> %s (peak %.1f dBFS; %d samples over full scale)" %
          (result["receiver"], result["output"], result["peak_dbfs"], result["samples_over_full_scale"]))
    for warning in result["model_limits"]:
        print("LIMIT: " + warning)
    return 0


def cmd_spatial_room_template(a):
    path = Path(a.file)
    if path.exists():
        raise SystemExit("spatial-room-template: refusing to overwrite %s" % path)
    document = _room_template()
    document["receivers"] = [{"id": "listener", "position": [4.0, 2.5, 1.4]}]
    # Listener faces +X; +Y is left. These starting positions are editable.
    positions = {"FL": [5.3, 3.25, 1.4], "FR": [5.3, 1.75, 1.4],
                 "FC": [5.5, 2.5, 1.4], "BL": [2.7, 3.25, 1.4],
                 "BR": [2.7, 1.75, 1.4], "SL": [4.0, 4.0, 1.4], "SR": [4.0, 1.0, 1.4]}
    document["sources"] = [{"id": name, "position": position, "level_db": [0] * 7}
                           for name, position in positions.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print("spatial-room-template: %s; listener faces +X and +Y is left" % path.resolve())
    return 0


def cmd_spatial_render(a):
    import math
    import soundfile as sf
    from scipy.signal import resample_poly
    from .engine import Artifact, create_engine
    from .engine import session
    try:
        out = Path(a.out)
        if out.exists():
            raise ValueError("refusing to overwrite %s" % out)
        raw = json.loads(Path(a.room_file).read_text(encoding="utf-8-sig"))
        config = session.load(a.session) if a.session else None
        if config and Path(config["room_file"]).resolve() != Path(a.room_file).resolve():
            raise ValueError("session room and spatial room must refer to the same file")
        audio, rate = sf.read(a.audio, dtype="float64", always_2d=True)
        fs = a.sample_rate if a.sample_rate is not None else (config["sample_rate_hz"] if config else 48000)
        if config and fs != config["sample_rate_hz"]:
            raise ValueError("sample rate must match the session sample rate")
        if fs < 24000 or fs > 192000:
            raise ValueError("sample rate must be between 24000 and 192000 Hz")
        if rate != fs:
            divisor = math.gcd(int(rate), fs)
            audio = resample_poly(audio, fs // divisor, int(rate) // divisor, axis=0)
        if config:
            from scipy.signal import sosfilt
            audio *= 10 ** (config["input_gain_db"] / 20.0)
            sos = session._eq_sos(fs, config["eq_db"])
            if len(sos):
                audio = sosfilt(sos, audio, axis=0)
        run = create_engine().execute(
            ("room.parse", "spatial.render"),
            {"room.document": Artifact("earnest.room.v1", raw, source=str(Path(a.room_file).resolve())),
             "audio.multichannel": Artifact("earnest.multichannel-audio.v1", audio, source=str(Path(a.audio).resolve()))},
            {"spatial.render": {"sample_rate": fs, "layout": a.layout, "hrtf": a.hrtf,
                                "receiver": a.receiver or (config.get("receiver") if config else None),
                                "wet_percent": config["wet_percent"] if config else 100.0}})
        result = run.artifacts["audio.binaural"].value
        if config:
            result["audio"] *= 10 ** (config["output_gain_db"] / 20.0)
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out), result["audio"], fs, subtype="FLOAT")
        peak = float(np.max(np.abs(result["audio"])))
        print("spatial-render: %s -> %s (%.2f dBFS peak)" %
              (a.layout, out.resolve(), 20 * math.log10(max(peak, 1e-15))))
        print("HRTF: %s; channel order: %s" % (result["hrtf_title"], ", ".join(result["channel_order"])))
        for match in result["direction_matches"]:
            print("  %s: measured azimuth %.1f deg, elevation %.1f deg (error %.1f deg)" %
                  (match["channel"], match["azimuth_deg"], match["elevation_deg"], match["angular_error_deg"]))
        for limit in result["limits"]:
            print("LIMIT: " + limit)
        if a.play:
            import tempfile
            import winsound
            playback = result["audio"] * min(1.0, 0.95 / max(peak, 1e-15))
            with tempfile.TemporaryDirectory(prefix="earnest-spatial-") as directory:
                path = Path(directory) / "preview.wav"
                sf.write(str(path), playback, fs, subtype="PCM_16")
                winsound.PlaySound(str(path), winsound.SND_FILENAME)
            if peak > 0.95:
                print("Playback attenuated to avoid clipping; float output unchanged.")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit("spatial-render: %s" % exc)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="earnest", description="Analyze, configure, solve, and audition modeled acoustic rooms.")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen", help="write test-signal WAV files")
    g.add_argument("--out", help="output folder (default: a new run folder)")
    g.add_argument("--suite", choices=["lite", "full"], help="write ONE probe-suite WAV with every stimulus joined (plus its manifest) instead of the separate files")
    g.set_defaults(fn=cmd_gen)
    capture = sub.add_parser("capture-kit", help="create a reproducible black-box capture project")
    capture.add_argument("--out", required=True, help="new or empty capture folder")
    capture.add_argument("--room", default="Union Stairs")
    capture.add_argument("--gain-db", type=float, default=-6.0, help="probe gain relative to full suite, -48 to 0 dB")
    capture.set_defaults(fn=cmd_capture_kit)
    check = sub.add_parser("capture-check", help="check expected capture files for basic export problems")
    check.add_argument("folder")
    check.set_defaults(fn=cmd_capture_check)
    sp = sub.add_parser("split", help="cut a wet suite export back into the named block files")
    sp.add_argument("wet")
    sp.add_argument("manifest")
    sp.add_argument("out_dir")
    sp.add_argument("--dry-out", help="also write the matching dry blocks here")
    sp.add_argument("--repeats", type=int, help="number of copies of the suite in the wet file (default: number of labels, else 1)")
    sp.add_argument("--labels", help="Mix labels per copy, e.g. 100,80,60,30,0; a last label of 0 fixes the level calibration")
    sp.add_argument("--dry", help="dry suite file (default: the file next to the manifest, else regenerated)")
    sp.set_defaults(fn=cmd_split)
    an = sub.add_parser("analyze", help="one export -> split, calibrate, room, mixcurve, stage -> summary.md")
    an.add_argument("export")
    an.add_argument("--room", required=True)
    an.add_argument("--manifest")
    an.add_argument("--labels", help="default 100,80,60,30,0")
    an.add_argument("--out")
    an.add_argument("--dry", help="dry reference EXPORT (the probe exported without the effect; single-pass use)")
    an.add_argument("--probe", help="the generated probe signal file (default: the one next to the manifest, else regenerated)")
    an.add_argument("--mix", type=int, help="Mix label of a single-pass file")
    an.add_argument("--stop-on-fail", action="store_true", help="stop at the first failed hop")
    an.set_defaults(fn=cmd_analyze)
    aa = sub.add_parser("analyze-all", help="analyze every .wav/.flac in a folder (room name = text before the first _ or -)")
    aa.add_argument("folder")
    aa.add_argument("--manifest")
    aa.add_argument("--labels")
    aa.add_argument("--stop-on-fail", action="store_true", help="abort the whole batch at the first failure")
    aa.set_defaults(fn=cmd_analyze_all)
    rs = sub.add_parser("reset", help="archive the runs folder and processed.json (nothing is deleted), check dependencies, run ping")
    rs.add_argument("--yes", action="store_true", help="do not wait for a keypress")
    rs.add_argument("--purge-archive", type=float, metavar="DAYS", help="send archive folders older than DAYS days to the Recycle Bin")
    rs.add_argument("--root", help=argparse.SUPPRESS)
    rs.add_argument("--no-ping", action="store_true", help=argparse.SUPPRESS)
    rs.set_defaults(fn=cmd_reset)
    pg = sub.add_parser("ping", help="self-test: pushes known files (clean, effect, channel lost, noise only, 16-bit) through the real chain and checks every hop")
    pg.add_argument("--quick", action="store_true", help="use the short lite probe")
    pg.set_defaults(fn=cmd_ping)
    ru = sub.add_parser("run", help="the one command: analyze every new or changed export in the inbox folder, mirror the newest results into runs/latest and open it")
    ru.add_argument("--inbox", help="default: the inbox folder next to this tool")
    ru.add_argument("--force", action="store_true", help="redo every file")
    ru.add_argument("--latest", help=argparse.SUPPRESS)
    ru.add_argument("--manifest")
    ru.add_argument("--labels")
    ru.add_argument("--no-open", action="store_true", help="do not open the results folder in File Explorer")
    ru.add_argument("--stop-on-fail", action="store_true", help="abort the whole batch at the first failure")
    ru.set_defaults(fn=cmd_run)
    mc = sub.add_parser("mixcurve", help="metrics against Mix for several room run folders (each with room.json)")
    mc.add_argument("runs", nargs="+")
    mc.add_argument("--labels")
    mc.add_argument("--title")
    mc.set_defaults(fn=cmd_mixcurve)
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
    rt = sub.add_parser("room-template", help="write a starter custom rectangular-room JSON file")
    rt.add_argument("file", help="destination room JSON; existing files are not overwritten")
    rt.set_defaults(fn=cmd_room_template)
    field_slice = sub.add_parser("room-field", help="sample a relative explicit-path sound field in a room plane")
    field_slice.add_argument("room_file")
    field_slice.add_argument("--frequency", type=int, default=1000)
    field_slice.add_argument("--grid", type=int, default=13)
    field_slice.add_argument("--height", type=float)
    field_slice.add_argument("--order", type=int, default=1)
    field_slice.add_argument("--out", help="new JSON output file; default stdout")
    field_slice.set_defaults(fn=cmd_room_field)
    field = sub.add_parser("soundfield-spectrum", help="propagate correlated source spectra through transfer matrices")
    field.add_argument("input", help="earnest.soundfield-input.v1 JSON")
    field.add_argument("--out", help="new output JSON (default: stdout)")
    field.add_argument("--room-solution", help="room-solve solution.json; input must contain source spectra")
    field.set_defaults(fn=cmd_soundfield_spectrum)
    instructions = sub.add_parser("room-from-instructions", help="build a room from a Room Studio instruction list")
    instructions.add_argument("instructions", help="earnest.room-instructions.v1 JSON file")
    instructions.add_argument("--out", required=True, help="new room JSON file")
    instructions.set_defaults(fn=cmd_room_from_instructions)
    editor = sub.add_parser("room-editor", help="open the local visual room editor using the shared physics engine")
    editor.add_argument("--port", type=int, default=8775)
    editor.add_argument("--open", action="store_true", help="open the editor in the default browser")
    editor.set_defaults(fn=cmd_room_editor)
    instrument = sub.add_parser("instrument-modes", help="compute ideal string or pipe resonator modes from a JSON model")
    instrument.add_argument("model", help="instrument model JSON file")
    instrument.set_defaults(fn=cmd_instrument_modes)
    inst_train = sub.add_parser("instrument-train", help="train experimental instrument reference model from labeled folders")
    inst_train.add_argument("examples", help="directory containing one folder per instrument label")
    inst_train.add_argument("--out", required=True, help="new model JSON file")
    inst_train.set_defaults(fn=cmd_instrument_train)
    inst_identify = sub.add_parser("instrument-identify", help="rank instrument reference matches for an isolated recording")
    inst_identify.add_argument("audio")
    inst_identify.add_argument("--model", required=True)
    inst_identify.set_defaults(fn=cmd_instrument_identify)
    frequency = sub.add_parser("frequency-trace", help="transcribe time-stamped spectral peaks from an audio file")
    frequency.add_argument("audio")
    frequency.add_argument("--out", help="new JSON output file")
    frequency.add_argument("--window", type=int, default=4096)
    frequency.add_argument("--hop", type=int, default=512)
    frequency.add_argument("--min-hz", type=float, default=40.0)
    frequency.add_argument("--max-hz", type=float)
    frequency.add_argument("--max-peaks", type=int, default=24)
    frequency.add_argument("--min-level-dbfs", type=float, default=-80.0)
    frequency.add_argument("--relative-threshold-db", type=float, default=-45.0)
    frequency.set_defaults(fn=cmd_frequency_trace)
    rf = sub.add_parser("room-fit", help="seed editable room absorption controls from a measured Earnest formula.json")
    rf.add_argument("room_file", help="base room configuration")
    rf.add_argument("formula", help="formula.json created by analyzing a dry/wet sample or plugin render")
    rf.add_argument("--out", help="destination room file (default: <room>.calibrated.room.json; existing files are not overwritten)")
    rf.add_argument("--reverb-type", help="preserve a known plugin/reverb label, e.g. plate, spring, hall, or room")
    rf.set_defaults(fn=cmd_room_fit)
    detect = sub.add_parser("detect", help="detect supported audio or analysis file format and available metadata")
    detect.add_argument("input", help="audio, room/measurement/formula JSON, or a result folder containing formula.json")
    detect.set_defaults(fn=cmd_detect)
    rfa = sub.add_parser("room-solve-from-analysis", help="fit analysis evidence to a room, then solve and export its band IRs")
    rfa.add_argument("room_file", help="editable earnest.room.v1 room JSON; geometry and positions remain fixed")
    rfa.add_argument("analysis", help="Earnest formula.json, earnest.measurement.v1 JSON, or a result folder containing formula.json")
    rfa.add_argument("--out", help="destination folder (default: a new runs folder; non-empty folders are refused)")
    rfa.add_argument("--reverb-type", help="preserve a known plugin/reverb label")
    rfa.add_argument("--order", type=int, help="maximum total specular reflection order")
    rfa.add_argument("--sample-rate", type=int, default=48000, help="IR sample rate (default 48000 Hz)")
    rfa.set_defaults(fn=cmd_room_solve_from_analysis)
    rp = sub.add_parser("room-preview", help="render a short noise burst through the configured room; optionally play it")
    rp.add_argument("room_file")
    rp.add_argument("--receiver", help="receiver id (default: first configured receiver)")
    rp.add_argument("--duration", type=float, default=4.0, help="source duration before the room tail (default 4 seconds)")
    rp.add_argument("--sample-rate", type=int, default=48000)
    rp.add_argument("--seed", type=int, default=0, help="repeatable preview noise seed")
    rp.add_argument("--out", help="destination WAV (default: a new room-preview run folder)")
    rp.add_argument("--play", action="store_true", help="play the rendered WAV on the Windows default output")
    rp.set_defaults(fn=cmd_room_preview)
    ei = sub.add_parser("engine-init", help="create an editable engine session for a room")
    ei.add_argument("file", help="new session JSON")
    ei.add_argument("room_file", help="existing room JSON, including a calibrated room")
    ei.set_defaults(fn=cmd_engine_init)
    es = sub.add_parser("engine-set", help="set a session EQ band or input, output, or wet control")
    es.add_argument("file", help="engine session JSON")
    group = es.add_mutually_exclusive_group(required=True)
    group.add_argument("--eq", type=int, metavar="HZ", help="EQ band center frequency")
    group.add_argument("--control", choices=("input", "output", "wet"))
    es.add_argument("value", type=float, help="gain in dB for EQ/input/output, or wet percentage")
    es.set_defaults(fn=cmd_engine_set)
    er = sub.add_parser("engine-render", help="process an audio file through the configured EQ and solved room")
    er.add_argument("file", help="engine session JSON")
    er.add_argument("audio", help="input audio file")
    er.add_argument("--out", required=True, help="new output WAV file")
    er.add_argument("--play", action="store_true", help="audition on the default Windows playback device")
    er.set_defaults(fn=cmd_engine_render)
    from .engine.spatial import DEFAULT_HRTF, LAYOUTS
    st = sub.add_parser("spatial-room-template", help="create an editable room with surround source positions")
    st.add_argument("file", help="new room JSON")
    st.set_defaults(fn=cmd_spatial_room_template)
    sr = sub.add_parser("spatial-render", help="render multichannel audio through a room to binaural headphones")
    sr.add_argument("room_file", help="room JSON with FL, FR, FC, BL, BR, SL and SR source IDs")
    sr.add_argument("audio", help="input audio file in the specified channel order")
    sr.add_argument("--layout", choices=tuple(LAYOUTS), required=True, help="explicit input channel layout")
    sr.add_argument("--out", required=True, help="new stereo float WAV")
    sr.add_argument("--hrtf", default=str(DEFAULT_HRTF), help="SimpleFreeFieldHRIR SOFA file")
    sr.add_argument("--receiver", help="receiver ID (default: first in room)")
    sr.add_argument("--sample-rate", type=int, help="render rate (default: session rate or 48000 Hz)")
    sr.add_argument("--session", help="engine session for EQ, input/output gain and room mix")
    sr.add_argument("--play", action="store_true", help="play through default Windows output")
    sr.set_defaults(fn=cmd_spatial_render)
    ad = sub.add_parser("audio-devices", help="list active Windows playback endpoints available to Earnest")
    ad.add_argument("--formats", action="store_true", help="show current endpoint mix formats")
    ad.set_defaults(fn=cmd_audio_devices)
    restart = sub.add_parser("audio-restart", help="open the elevated Windows Audio restart window")
    restart.set_defaults(fn=cmd_audio_restart)
    route = sub.add_parser("route", help="make Earnest the live Windows audio path through a solved room")
    route.add_argument("room_file", help="earnest.room.v1 JSON to solve for the live room adapter")
    route.add_argument("--output", required=True, help="physical Windows playback endpoint name or endpoint id")
    route.add_argument("--input", default="Earnest Virtual Speakers",
                       help="Earnest virtual playback endpoint name or id (default: Earnest Virtual Speakers)")
    route.add_argument("--sample-rate", type=int, default=48000)
    route.add_argument("--order", type=int, help="maximum specular reflection order")
    route.add_argument("--dry-mix", type=float, default=0.78, help="direct signal gain from 0 to 1 (default: 0.78)")
    route.add_argument("--wet-mix", type=float, default=0.55, help="room field gain from 0 to 1 (default: 0.55)")
    route.add_argument("--profile-out", help="write the generated live profile to this new JSON file")
    route.set_defaults(fn=cmd_route)
    route_stop = sub.add_parser("route-stop", help="restore the playback endpoint saved by earnest route")
    route_stop.set_defaults(fn=cmd_route_stop)
    bridge = sub.add_parser("bridge", help="compile a room and process a live Windows loopback stream")
    bridge.add_argument("room_file", help="earnest.room.v1 room JSON")
    bridge.add_argument("--input", required=True, help="render endpoint to capture via loopback")
    bridge.add_argument("--capture-input", action="store_true", help="input is a recording endpoint instead of a playback loopback")
    bridge.add_argument("--output", required=True, help="different render endpoint to receive processed audio")
    bridge.add_argument("--layout", choices=("stereo", "5.1-back", "5.1-side", "7.1"), default="stereo")
    bridge.add_argument("--sample-rate", type=int, default=48000)
    bridge.add_argument("--receiver", help="receiver ID; default is first in room")
    bridge.add_argument("--order", type=int, help="maximum specular reflection order")
    bridge.add_argument("--dry-mix", type=float, default=0.78)
    bridge.add_argument("--wet-mix", type=float, default=0.55)
    bridge.add_argument("--lookahead-ms", type=float, default=85.0)
    bridge.set_defaults(fn=cmd_bridge)
    live = sub.add_parser("live-view", help="open the read-only live head and playback visualizer")
    live.add_argument("--endpoint", default="Speakers (7.1 Surround Sound)", help="Windows playback endpoint name or ID")
    live.add_argument("--port", type=int, default=8774)
    live.add_argument("--editor-port", type=int, default=8775, help="local Room Studio port (0 chooses a free port)")
    live.add_argument("--open", action="store_true", help="open the local viewer in a browser")
    live.set_defaults(fn=cmd_live_view)
    visual = sub.add_parser("visualize", help="build an interactive room and measurement comparison report")
    visual.add_argument("room_file", help="editable earnest.room.v1 room JSON")
    visual.add_argument("--reference", help="measured reference formula.json")
    visual.add_argument("--comparison", help="independently analyzed candidate formula.json")
    visual.add_argument("--out", help="new standalone HTML report path")
    visual.add_argument("--sample-rate", type=int, default=24000)
    visual.add_argument("--order", type=int, help="maximum reflection order")
    visual.add_argument("--open", action="store_true", help="open report in the default browser")
    visual.set_defaults(fn=cmd_visualize)
    rsolve = sub.add_parser("room-solve", help="solve a custom room into source-to-receiver octave-band impulse responses")
    rsolve.add_argument("room_file", help="room JSON produced by room-template or following earnest.room.v1")
    rsolve.add_argument("--out", help="output folder (default: a new runs folder)")
    rsolve.add_argument("--order", type=int, help="maximum total specular reflection order (overrides engine_controls in the room file)")
    rsolve.add_argument("--sample-rate", type=int, default=48000, help="IR sample rate (default 48000 Hz)")
    rsolve.set_defaults(fn=cmd_room_solve)
    sim = sub.add_parser("simulate", help="drive source audio through a solved room, render each receiver, and analyze the output")
    sim.add_argument("room_file", help="custom room JSON")
    sim.add_argument("audio", help="audio with one input channel per configured room source")
    sim.add_argument("--out", help="output folder (default: a new runs folder)")
    sim.add_argument("--order", type=int, help="maximum total specular reflection order (overrides engine_controls in the room file)")
    sim.add_argument("--sample-rate", type=int, default=48000, help="render sample rate (default 48000 Hz)")
    sim.set_defaults(fn=cmd_simulate)
    from . import crosscheck
    c = sub.add_parser("crosscheck", help="compare room fits of the eight Univerb renders with univerb_results.csv")
    c.add_argument("--dry", default=str(crosscheck.DRY))
    c.add_argument("--wet-dir", default=str(crosscheck.WET_DIR))
    c.add_argument("--csv", default=str(crosscheck.CSV))
    c.set_defaults(fn=crosscheck.run_cmd)
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        p.print_help()
        return 0
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except KeyboardInterrupt:
        from . import trace
        trace.print_active()
        print("interrupted (Ctrl+C): the trace so far is printed above")
        return 130


if __name__ == "__main__":
    sys.exit(main())
