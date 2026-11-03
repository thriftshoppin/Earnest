"""Built-in domain components; the engine core is independent of these choices."""
from __future__ import annotations

from typing import Any
import re

import numpy as np

from .calibration import fit_formula, solve_room_from_analysis
from .core import Artifact, ComponentContext, ControlParameter, Engine, EngineError
from .render import render_room
from .room import RoomSpec
from .solve import solve_room


class RoomParseComponent:
    name = "room.parse"
    requires = ("room.document",)
    provides = ("room.model",)
    parameters = (
        ControlParameter("reflection_order", "Reflection order", "bounces", 0, 12, 4,
                         "room.engine_controls.reflection_order", "solver cost and early-path density"),
        ControlParameter("decay_model", "Decay equation", "choice", None, None, "eyring",
                         "room.engine_controls.decay_model", "late-field decay estimate", ("eyring", "sabine")),
        ControlParameter("diffuse_energy_scale", "Diffuse energy", "x", 0, 10, 1.0,
                         "room.engine_controls.diffuse_energy_scale", "late-field energy calibration"),
        ControlParameter("decay_scale", "Decay time", "x", 0.1, 2.5, 1.0,
                         "room.engine_controls.decay_scale", "multiplier applied to modeled late-field RT60"),
        ControlParameter("tail_duration_scale", "Tail duration", "x", 0.1, 4, 1.0,
                         "room.engine_controls.tail_duration_scale", "preview/render duration"),
        ControlParameter("air_absorption_enabled", "Atmospheric absorption", "choice", None, None, "false",
                         "room.environment.air_absorption_enabled", "enable pure-tone loss on explicit paths", ("false", "true")),
        ControlParameter("temperature_c", "Air temperature", "°C", -50, 100, 20.0,
                         "room.environment.temperature_c", "sound speed; air absorption requires -20 to 50 °C"),
        ControlParameter("humidity_percent", "Relative humidity", "%", 0, 100, 50.0,
                         "room.environment.humidity_percent", "atmospheric absorption model"),
        ControlParameter("pressure_pa", "Atmospheric pressure", "Pa", 10000, 200000, 101325.0,
                         "room.environment.pressure_pa", "atmospheric absorption model"),
    ) + tuple(
        ControlParameter("absorption_scale_%d" % hz, "Absorption scale %d Hz" % hz, "x", 0, 20, 1.0,
                         "room.engine_controls.absorption_scale[%d]" % index, "per-band decay calibration")
        for index, hz in enumerate((125, 250, 500, 1000, 2000, 4000, 8000))
    ) + tuple(
        ControlParameter("scattering_scale_%d" % hz, "Scattering scale %d Hz" % hz, "x", 0, 20, 1.0,
                         "room.engine_controls.scattering_scale[%d]" % index, "specular/diffuse energy split")
        for index, hz in enumerate((125, 250, 500, 1000, 2000, 4000, 8000))
    )

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        document = context.inputs["room.document"].value
        model = RoomSpec.from_dict(document)
        return {"room.model": Artifact("earnest.room-model.v1", model,
                                        source=context.inputs["room.document"].source)}


class RoomSolveComponent:
    name = "room.solve"
    requires = ("room.model",)
    provides = ("room.solution",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        room = context.inputs["room.model"].value
        solution = solve_room(room, fs=int(context.options.get("sample_rate", 48000)),
                              max_order=context.options.get("reflection_order"))
        return {"room.solution": Artifact("earnest.room-solution.v1", solution,
                                           source=room.schema, notes=tuple(solution["model_limits"]))}


class RoomFieldSliceComponent:
    name = "room.field_slice"
    requires = ("room.model",)
    provides = ("room.field_slice",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .field_grid import sample_room_field
        try:
            result = sample_room_field(context.inputs["room.model"].value, **dict(context.options))
        except (TypeError, ValueError) as exc:
            raise EngineError("room.field_slice: %s" % exc) from exc
        return {"room.field_slice": Artifact(result["schema"], result,
                source=context.inputs["room.model"].source, notes=tuple(result["limits"]))}


class RoomPathSoundFieldComponent:
    name = "soundfield.from_room_paths"
    requires = ("room.solution", "soundfield.source_spectra")
    provides = ("soundfield.spectrum",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .soundfield import room_path_spectra
        try:
            result = room_path_spectra(context.inputs["room.solution"].value, context.inputs["soundfield.source_spectra"].value)
        except (ValueError, TypeError, KeyError) as exc:
            raise EngineError("soundfield.from_room_paths: %s" % exc) from exc
        return {"soundfield.spectrum": Artifact(result["schema"], result,
                 source=context.inputs["room.solution"].source, notes=tuple(result["limits"]))}


class SoundFieldSpectrumComponent:
    name = "soundfield.propagate"
    requires = ("soundfield.input",)
    provides = ("soundfield.spectrum",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .soundfield import propagate_spectra
        try:
            result = propagate_spectra(context.inputs["soundfield.input"].value)
        except (ValueError, TypeError) as exc:
            raise EngineError("soundfield.propagate: %s" % exc) from exc
        return {"soundfield.spectrum": Artifact(result["schema"], result,
                 source=context.inputs["soundfield.input"].source, notes=tuple(result["limits"]))}


class HypothesisEvaluationComponent:
    name = "audio.hypothesis_evaluate"
    requires = ("audio.reference", "audio.stems", "audio.note_events")
    provides = ("audio.hypothesis_evaluation", "audio.residual")

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .hypothesis import evaluate
        try:
            reference = context.inputs['audio.reference'].value
            report, residual = evaluate(reference['samples'], context.inputs['audio.stems'].value,
                                        reference['sample_rate_hz'], context.inputs['audio.note_events'].value,
                                        **dict(context.options))
        except (TypeError, KeyError, ValueError) as exc:
            raise EngineError('audio.hypothesis_evaluate: %s' % exc) from exc
        return {'audio.hypothesis_evaluation': Artifact(report['schema'], report, notes=tuple(report['limits'])),
                'audio.residual': Artifact('earnest.audio-samples.v1', {'samples': residual, 'sample_rate_hz': reference['sample_rate_hz']})}


class HypothesisRankingComponent:
    name = 'audio.hypothesis_rank'
    requires = ('audio.hypothesis_evaluations',)
    provides = ('audio.hypothesis_ranking',)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .hypothesis import rank_evaluations
        try:
            result = rank_evaluations(context.inputs['audio.hypothesis_evaluations'].value, context.options.get('weights', {}))
        except (TypeError, ValueError) as exc:
            raise EngineError('audio.hypothesis_rank: %s' % exc) from exc
        return {'audio.hypothesis_ranking': Artifact(result['schema'], result, notes=tuple(result['limits']))}


class SeparationComponent:
    name = "audio.separate"
    requires = ("audio.file",)
    provides = ("audio.separation",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .separation import separate_demucs
        try:
            result = separate_demucs(context.inputs["audio.file"].value, context.options["output_dir"], context.options.get("backend"), context.options.get("device", "cpu"))
        except (OSError, TypeError, KeyError, ValueError, RuntimeError) as exc:
            raise EngineError("audio.separate: %s" % exc) from exc
        return {"audio.separation": Artifact(result["schema"], result,
                source=context.inputs["audio.file"].source, notes=tuple(result["limits"]))}


class TranscriptionComponent:
    name = "audio.transcribe"
    requires = ("audio.file",)
    provides = ("audio.transcription",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .transcription import transcribe_basic_pitch
        try:
            result = transcribe_basic_pitch(context.inputs["audio.file"].value, context.options["output_dir"], context.options.get("backend"))
        except (OSError, TypeError, KeyError, ValueError, RuntimeError) as exc:
            raise EngineError("audio.transcribe: %s" % exc) from exc
        return {"audio.transcription": Artifact(result["schema"], result,
                source=context.inputs["audio.file"].source, notes=tuple(result["limits"]))}


class BandFocusComponent:
    name = "audio.focus_band"
    requires = ("audio.samples",)
    provides = ("audio.focused",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .band_focus import focus_band
        audio = context.inputs["audio.samples"].value
        try:
            result = focus_band(audio["samples"], audio["sample_rate_hz"], context.options["low_hz"], context.options["high_hz"])
        except (TypeError, KeyError, ValueError) as exc:
            raise EngineError("audio.focus_band: %s" % exc) from exc
        return {"audio.focused": Artifact("earnest.audio-samples.v1", {"samples": result, "sample_rate_hz": audio["sample_rate_hz"]},
                source=context.inputs["audio.samples"].source, notes=("Frequency focus is not instrument separation; forward/backward filtering has edge effects.",))}


class AudioComparisonComponent:
    name = "audio.compare"
    requires = ("audio.reference", "audio.candidate")
    provides = ("audio.comparison", "audio.residual")

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .comparison import compare_audio, compare_audio_segments
        ref, candidate = context.inputs["audio.reference"].value, context.inputs["audio.candidate"].value
        try:
            if ref["sample_rate_hz"] != candidate["sample_rate_hz"]:
                raise ValueError("sample rates differ; resample and align explicitly")
            rate = ref["sample_rate_hz"]
            result, residual = compare_audio(ref["samples"], candidate["samples"], rate)
            if context.options.get("segment_seconds") is not None:
                result["segments"] = compare_audio_segments(ref["samples"], candidate["samples"], rate, context.options["segment_seconds"])
        except (TypeError, KeyError, ValueError) as exc:
            raise EngineError("audio.compare: %s" % exc) from exc
        return {"audio.comparison": Artifact(result["schema"], result, notes=tuple(result["limits"])),
                "audio.residual": Artifact("earnest.audio-samples.v1", {"samples": residual, "sample_rate_hz": rate})}


class FrequencyTraceComponent:
    name = "audio.frequency_trace"
    requires = ("audio.samples",)
    provides = ("audio.frequency_trace",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .frequency_trace import trace_frequencies
        audio = context.inputs["audio.samples"].value
        if not isinstance(audio, dict) or "samples" not in audio or "sample_rate_hz" not in audio:
            raise EngineError("audio.samples needs samples and sample_rate_hz")
        try:
            result = trace_frequencies(audio["samples"], audio["sample_rate_hz"], **dict(context.options))
        except (TypeError, ValueError) as exc:
            raise EngineError("audio.frequency_trace: %s" % exc) from exc
        return {"audio.frequency_trace": Artifact(result["schema"], result,
                 source=context.inputs["audio.samples"].source, notes=tuple(result["limits"]))}


class InstrumentIdentificationComponent:
    name = "instrument.identify"
    requires = ("audio.samples", "instrument.reference_model")
    provides = ("instrument.identification",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .instrument_id import identify
        audio = context.inputs["audio.samples"].value
        try:
            result = identify(audio["samples"], audio["sample_rate_hz"], context.inputs["instrument.reference_model"].value)
        except (TypeError, KeyError, ValueError) as exc:
            raise EngineError("instrument.identify: %s" % exc) from exc
        return {"instrument.identification": Artifact(result["schema"], result,
                source=context.inputs["audio.samples"].source, notes=tuple(result["notes"]))}


class InstrumentModesComponent:
    """Ideal resonator modes; instrument body and excitation are not inferred."""
    name = "instrument.modes"
    requires = ("instrument.model",)
    provides = ("instrument.modes",)
    parameters = (
        ControlParameter("kind", "Ideal resonator type", "choice", None, None, "ideal-string",
                         "instrument.model.kind", "select an idealized model",
                         ("ideal-string", "stiff-string", "ideal-open-pipe", "ideal-closed-pipe", "ideal-circular-membrane")),
        ControlParameter("count", "Mode count", "modes", 1, 256, 12,
                         "instrument.model.count", "number of modes; circular membrane supports up to 24"),
    )

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .physics import ideal_pipe_modes, ideal_string_modes, stiff_string_modes, circular_membrane_modes
        model = context.inputs["instrument.model"].value
        if not isinstance(model, dict):
            raise EngineError("instrument.model must be an object")
        kind = model.get("kind")
        try:
            count = model.get("count", 12)
            if kind == "ideal-string":
                frequencies = ideal_string_modes(model["length_m"], model["tension_n"], model["linear_density_kg_m"], count)
            elif kind == "stiff-string":
                frequencies = stiff_string_modes(model["length_m"], model["tension_n"], model["linear_density_kg_m"], model["inharmonicity"], count)
            elif kind in ("ideal-open-pipe", "ideal-closed-pipe"):
                boundary = "open-open" if kind == "ideal-open-pipe" else "open-closed"
                frequencies = ideal_pipe_modes(model["effective_length_m"], model.get("sound_speed_m_s", 343.0), boundary, count)
            elif kind == "ideal-circular-membrane":
                modes = circular_membrane_modes(model["radius_m"], model["tension_n_m"], model["surface_density_kg_m2"], count)
                frequencies = [mode["frequency_hz"] for mode in modes]
            else:
                raise ValueError("unknown resonator kind")
        except (KeyError, TypeError, ValueError) as exc:
            raise EngineError("instrument.modes: %s" % exc) from exc
        return {"instrument.modes": Artifact("earnest.instrument-modes.v1",
                {"kind": kind, "frequencies_hz": frequencies,
                 "mode_metadata": modes if kind == "ideal-circular-membrane" else None,
                 "limits": ["Ideal linear resonator only; no excitation, body, radiation, dynamics or identification."]},
                source=context.inputs["instrument.model"].source)}


class RoomRenderComponent:
    name = "room.render"
    requires = ("room.model", "room.solution", "audio.sources")
    provides = ("room.rendered",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        room = context.inputs["room.model"].value
        source = context.inputs["audio.sources"].value
        sample_rate = int(context.options.get("sample_rate", 48000))
        rendered = render_room(room, context.inputs["room.solution"].value, source, fs=sample_rate)
        return {"room.rendered": Artifact("earnest.room-render.v1", rendered,
                                           source=room.schema,
                                           notes=tuple(rendered["render_limits"]))}


class SpatialRenderComponent:
    """Convert labeled multichannel sources into a room-shaped headphone signal."""
    name = "spatial.render"
    requires = ("room.model", "audio.multichannel")
    provides = ("audio.binaural",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .spatial import DEFAULT_HRTF, HrirDataset, render_binaural
        options = context.options
        result = render_binaural(context.inputs["room.model"].value,
                                 context.inputs["audio.multichannel"].value,
                                 int(options.get("sample_rate", 48000)),
                                 str(options.get("layout", "stereo")),
                                 HrirDataset(options.get("hrtf", DEFAULT_HRTF)),
                                 options.get("receiver"), float(options.get("wet_percent", 100.0)))
        return {"audio.binaural": Artifact("earnest.binaural-render.v1", result,
                                            source=context.inputs["audio.multichannel"].source,
                                            notes=tuple(result["limits"]))}


class RoomFitComponent:
    name = "room.fit_measurement"
    requires = ("room.document", "acoustic.hypotheses")
    provides = ("room.calibrated_document",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        source_room = context.inputs["room.document"]
        hypothesis = context.inputs["acoustic.hypotheses"]
        measurement = hypothesis.value["measurement"]
        fitted = fit_formula(source_room.value, measurement,
                             context.options.get("reverb_type"))
        fitted["analysis_evidence"]["inference"] = hypothesis.value
        return {"room.calibrated_document": Artifact(
            "earnest.room.v1", fitted, source=hypothesis.source,
            notes=("Decay fit is evidence for absorption controls, not a unique room reconstruction.",))}


class RoomSolveFromAnalysisComponent:
    """Fit measurement evidence to an editable room, then run its forward solve."""
    name = "room.solve_from_analysis"
    requires = ("room.document", "acoustic.hypotheses")
    provides = ("room.calibrated_document", "room.solution", "room.fit_report")

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        source_room = context.inputs["room.document"]
        hypothesis = context.inputs["acoustic.hypotheses"]
        result = solve_room_from_analysis(
            source_room.value, hypothesis.value["measurement"],
            context.options.get("reverb_type"),
            int(context.options.get("sample_rate", 48000)),
            context.options.get("reflection_order"))
        return {
            "room.calibrated_document": Artifact(
                "earnest.room.v1", result["calibrated_room"], source=source_room.source,
                notes=("Geometry and source/receiver positions remain fixed; fit is not a unique reconstruction.",)),
            "room.solution": Artifact("earnest.room-solution.v1", result["room_solution"],
                                       source=hypothesis.source,
                                       notes=tuple(result["room_solution"]["model_limits"])),
            "room.fit_report": Artifact("earnest.room-fit-report.v1", result["fit"],
                                         source=hypothesis.source)
        }


class ReverbAnalysisComponent:
    """Turn supplied dry/wet sweep pairs into Earnest observations and a reusable formula."""
    name = "reverb.analyze"
    requires = ("reverb.sweeps",)
    provides = ("reverb.observations", "reverb.measurement", "reverb.plot_data")

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        from .. import formula, room as room_analysis
        payload = context.inputs["reverb.sweeps"].value
        if isinstance(payload, dict) and "sets" in payload:
            observations, plot_data = room_analysis.run_room_sets(
                payload["sets"], payload.get("clicks", {}), payload.get("notes", ()))
        else:
            observations, plot_data = room_analysis.analyze_sweeps(payload)
        measurement = formula.build(observations, context.options.get("source", ""))
        return {
            "reverb.observations": Artifact("earnest.reverb-observations.v1", observations),
            "reverb.measurement": Artifact("earnest.reverb-formula.v1", measurement,
                                             source=measurement.get("source")),
            "reverb.plot_data": Artifact("earnest.reverb-plot-data.v1", plot_data),
        }


class AcousticInferenceComponent:
    """Turn measured features into explicit, bounded character hypotheses."""
    name = "acoustic.infer_character"
    requires = ("reverb.measurement",)
    provides = ("acoustic.hypotheses",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        measurement_artifact = context.inputs["reverb.measurement"]
        measurement = measurement_artifact.value
        if not isinstance(measurement, dict):
            raise EngineError("reverb.measurement artifact must contain a JSON object")
        if measurement.get("schema") == "earnest.measurement.v1":
            rows = measurement.get("bands", [])
            if not isinstance(rows, list) or any(not isinstance(row, dict) or "hz" not in row for row in rows):
                raise EngineError("earnest.measurement.v1 needs band objects with hz values")
            tail = {"bands_hz": [row.get("hz") for row in rows],
                    **{key: [row.get(key, row.get("tail_level_db") if key == "level_db" else None)
                             for row in rows]
                       for key in ("rt60_s", "edt_s", "level_db", "pre_delay_ms", "buildup_ms", "iacc", "modulation")}}
        else:
            tail = measurement.get("tail", {})
        if not isinstance(tail, dict):
            raise EngineError("reverb.measurement has no valid tail observation object")
        band_values = tail.get("bands_hz", [])
        if not isinstance(band_values, list):
            band_values = []
        rts = [float(value) for value in tail.get("rt60_s", [])
               if isinstance(value, (int, float)) and np.isfinite(value) and value > 0]
        median_rt = sorted(rts)[len(rts) // 2] if rts else None
        mods = tail.get("modulation") or []
        modulated_bands = [band_values[i] for i, value in enumerate(mods)
                           if value is not None and i < len(band_values)]
        tap_document = measurement.get("early_taps")
        taps = tap_document.get("taps", []) if isinstance(tap_document, dict) else []
        iacc = [float(value) for value in tail.get("iacc", [])
                if isinstance(value, (int, float)) and np.isfinite(value)]
        features = {"median_rt60_s": median_rt, "measured_band_count": len(rts),
                    "modulation_detected_bands_hz": modulated_bands,
                    "early_tap_count": len(taps),
                    "mean_tail_iacc": float(np.mean(iacc)) if iacc else None}
        candidates = []
        if len(modulated_bands) >= 2:
            candidates.append({"character": "modulated tail", "confidence": "moderate",
                               "evidence": ["decay-envelope modulation detected in multiple bands"]})
        if median_rt is not None and median_rt <= 0.35 and len(taps) >= 3:
            candidates.append({"character": "short reflection-rich response", "confidence": "low",
                               "evidence": ["short median decay", "multiple early reflections"]})
        if median_rt is not None and median_rt >= 1.2 and len(taps) >= 3:
            candidates.append({"character": "long diffuse or hall-like response", "confidence": "low",
                               "evidence": ["long median decay", "multiple early reflections"]})
        if not candidates:
            candidates.append({"character": "unresolved reverb character", "confidence": "low",
                               "evidence": ["current measurements do not distinguish a response family"]})
        plugin_metadata = measurement.get("plugin_metadata") or {}
        if not isinstance(plugin_metadata, dict):
            plugin_metadata = {}
        external_label = measurement.get("reverb_type") or plugin_metadata.get("reverb_type")
        result = {"schema": "earnest.acoustic-hypotheses.v1", "candidates": candidates,
                  "features": features, "external_reverb_label": external_label,
                  "external_label_is_inference": False,
                  "limitations": ["Character clues do not identify plugin algorithms such as plate or spring.",
                                  "Measured decay and early reflections do not uniquely recover room geometry or materials."] ,
                  "measurement": measurement}
        return {"acoustic.hypotheses": Artifact("earnest.acoustic-hypotheses.v1", result,
                                                 source=measurement_artifact.source,
                                                 notes=tuple(result["limitations"]))}


class RoomNoiseSourceComponent:
    name = "audio.room_probe"
    requires = ("room.model",)
    provides = ("audio.sources",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        room = context.inputs["room.model"].value
        fs = int(context.options.get("sample_rate", 48000))
        frames = int(float(context.options.get("duration_s", 4.0)) * fs)
        if frames < 1:
            raise EngineError("room probe duration must be positive")
        rng = np.random.default_rng(int(context.options.get("seed", 0)))
        source = np.zeros((frames, len(room.sources)), dtype=np.float64)
        burst = min(int(0.25 * fs), frames)
        noise = rng.standard_normal(burst)
        ramp = min(int(0.01 * fs), max(1, burst // 2))
        envelope = np.ones(burst)
        envelope[:ramp] = np.linspace(0.0, 1.0, ramp)
        envelope[-ramp:] = np.linspace(1.0, 0.0, ramp)
        source[:burst, 0] = noise * envelope * 0.1
        return {"audio.sources": Artifact("earnest.audio-sources.v1", source,
                                           source="repeatable noise burst")}


class ReceiverWavExportComponent:
    name = "audio.export_receivers"
    requires = ("room.rendered",)
    provides = ("audio.files",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        import soundfile as sf
        from pathlib import Path
        rendered = context.inputs["room.rendered"].value
        out_dir = Path(context.options["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = str(context.options.get("prefix", "room"))
        fs = int(context.options.get("sample_rate", rendered["sample_rate_hz"]))
        subtype = str(context.options.get("subtype", "PCM_16"))
        only_receiver = context.options.get("receiver")
        exact_path = context.options.get("out_path")
        max_peak = context.options.get("max_peak")
        safe = lambda value: re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))
        files = {}
        for receiver_id, entry in rendered["receiver_outputs"].items():
            if only_receiver and receiver_id != only_receiver:
                continue
            path = Path(exact_path) if exact_path else out_dir / ("%s__%s.wav" % (safe(prefix), safe(receiver_id)))
            audio = np.asarray(entry["audio"], dtype=np.float64)
            peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
            if max_peak is not None and peak > float(max_peak):
                audio = audio * (float(max_peak) / peak)
            path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(path), audio.astype(np.float32), fs, subtype=subtype)
            files[receiver_id] = str(path.resolve())
        return {"audio.files": Artifact("earnest.audio-files.v1", files, source=str(out_dir.resolve()))}


class DefaultAudioPlaybackComponent:
    name = "audio.play_default"
    requires = ("audio.files",)
    provides = ("audio.playback",)

    def process(self, context: ComponentContext) -> dict[str, Artifact]:
        try:
            import winsound
        except ImportError as exc:
            raise EngineError("default-device playback is available only on Windows") from exc
        files = context.inputs["audio.files"].value
        receiver = context.options.get("receiver") or next(iter(files))
        if receiver not in files:
            raise EngineError("unknown receiver %r; available: %s" % (receiver, ", ".join(files)))
        winsound.PlaySound(files[receiver], winsound.SND_FILENAME)
        return {"audio.playback": Artifact("earnest.audio-playback.v1",
                                           {"receiver": receiver, "path": files[receiver], "status": "played"})}


def create_engine() -> Engine:
    """Build the standard Earnest host; applications can register more components."""
    engine = Engine()
    for component in (RoomParseComponent(), RoomSolveComponent(), InstrumentModesComponent(), FrequencyTraceComponent(), HypothesisEvaluationComponent(), HypothesisRankingComponent(), TranscriptionComponent(), SeparationComponent(), BandFocusComponent(), AudioComparisonComponent(), InstrumentIdentificationComponent(), SoundFieldSpectrumComponent(), RoomPathSoundFieldComponent(), RoomFieldSliceComponent(), RoomRenderComponent(), SpatialRenderComponent(),
                      RoomFitComponent(), RoomSolveFromAnalysisComponent(),
                      ReverbAnalysisComponent(), AcousticInferenceComponent(), RoomNoiseSourceComponent(),
                      ReceiverWavExportComponent(), DefaultAudioPlaybackComponent()):
        engine.register(component)
    return engine
