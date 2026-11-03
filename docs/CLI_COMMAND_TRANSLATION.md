# Earnest command language: equation controls and output

**Status: mixed implementation and UX proposal.** `detect <input>` and `room-solve-from-analysis <room> <analysis>` are implemented. The interactive room session, guided room creation/editing, master-dial translations, live output selection and refresh behavior below remain proposals. The goal is to let a person adjust the same master controls that the room engine and future StageJack adapter use, without typing internal JSON paths or equation names.

## Session shape

The room controls need an active room and a place to apply changes. Proposed entry point:

```text
earnest control <room.json>
```

This opens an interactive control session for that room. Set commands update the session's working configuration and mark it pending. `refresh` validates and recomputes the room solution and rendered preview from the current settings. It does not reset the settings. Saving the edited room file should remain a separate, explicit action so experimenting does not silently overwrite a room.

## Detect, normalize, translate, solve

The CLI should detect the **analysis/input formatting** automatically so users do not have to supply every metadata or formatting parameter. This is separate from detecting the physical room. The implemented `detect` command reads supported Earnest JSON schemas and audio headers (container, sample rate, channel count, frame count and duration); it reports channel role as unknown when headers cannot establish it. The current detector does not yet import arbitrary plugin report formats or interactively ask for missing fields. The user can inspect or override a detected choice, but routine format details should not become mandatory command flags.

Detection must preserve provenance: each normalized value is labeled as measured/read from metadata, converted, defaulted, or unknown. It must not silently invent room dimensions, material coefficients, source positions, or receiver positions from an audio format. Those are room-side parameters and need a room document, reliable external metadata, or a clearly labeled inferred hypothesis.

The central analysis-to-room operation should be one engine function, conceptually:

```text
solve_room_from_analysis(evidence, room_model, controls) -> room_hypothesis, calibrated_room, room_solution
```

The implemented core stages are:

1. **Normalize evidence.** Detect/import file or plugin format; map measurements to common frequency bands, units, channel/path labels, and confidence/provenance.
2. **Extract acoustic observations.** Use Earnest analysis outputs such as direct level, early reflection delays/levels, band RT60/EDT, DRR/C50/C80, stereo correlation/width, and tail level. Use only observations present in the evidence.
3. **Translate decay into room-equation constraints.** For known geometry, measured RT60 constrains equivalent absorption per band. The implemented fitter uses the selected Sabine/Eyring decay equation to find a per-band material-absorption scale. A Sabine starting estimate is `A_b = 0.161 V / RT60_b` (metric units); the Eyring equivalent average absorption is `alpha_b = 1 - exp(-0.161 V / (S RT60_b))`. Early-reflection times can constrain candidate path lengths through `d = c * tau`, but are currently reported as evidence rather than used to move geometry or surfaces.
4. **Fit the editable room model.** Current fitting changes only per-band absorption scales and preserves user geometry, material assignments, source positions and receiver positions. It does not yet optimize scattering, geometry, source/receiver placement, or a weighted residual across all measured metrics. Many different rooms can produce similar reverberation measurements.
5. **Run the forward room solve.** The implemented `room.solve_from_analysis` component solves the calibrated scene and returns an editable room document, fit report and source-to-receiver band responses. The CLI exports these as `calibrated.room.json`, `fit_report.json`, `solution.json` and octave-band IR WAVs.
6. **Explain the result.** The fit report records measured and predicted RT60 by band, chosen scales, source metadata and inference limitations. A future iteration should add residual scoring across early taps, level, stereo/spatial metrics, confidence and explicit boundary-hit diagnostics. Never present an equivalent acoustic fit as a uniquely recovered physical room.

The engine should distinguish `evidence` (what the input actually says), `room_hypothesis` (candidate inferred properties with uncertainty), `calibrated_room` (editable parameters chosen for the solve), and `room_solution` (forward-computed response for configured sources/receivers). The translator is a reusable engine component callable from the CLI or a future StageJack adapter; CLI syntax should only choose inputs, overrides and outputs.

Implemented command flow:

```text
earnest detect <sample-or-report>
earnest detect analysis-result-folder
earnest room-solve-from-analysis rooms/theater.json analysis-result-folder --out runs/theater
```

The implementation consumes an existing formula or `earnest.measurement.v1` JSON and a user-provided editable room. It does not yet analyze raw audio by itself in this command, build a room from analysis alone, or import arbitrary plugin-specific report formats. Geometry and positions remain fixed. A reverberation measurement alone cannot uniquely determine room shape or source/listener positions.

## Percentage convention

For a percentage `P`, the multiplier is `m = P / 100`. The percentage is always relative to the room's loaded baseline, not to the last value entered. This makes `set-decay 80` followed by `set-decay 80` stable, and `set-decay 100` restore the loaded baseline.

Normal range: `0` to `100`. `-f` means **force this requested setting**, allowing an override from `0` to `250`, including values above `100`:

```text
set-decay 85
set-decay 165 -f
```

Without `-f`, values above 100 are rejected with a message explaining that `-f` enables the override. `-f` does not mean “recalculate” or “ignore invalid input”; it only authorizes the extended percentage range. The engine must still validate that the resulting room model is solvable and report any physical or model limits rather than silently changing the requested value.

## Proposed commands

| Command | User meaning | Engine translation | Expected response |
|---|---|---|---|
| `set-tail <P> [-f]` | Set the strength/amount of the late reverberant tail. | `m=P/100`; set `room.engine_controls.diffuse_energy_scale = baseline_diffuse_energy_scale * m`. Current implementation bounds this to 0–10x. It changes late-field energy, not RT60 or render duration. | Show percentage and effective late-field energy scale; mark room pending refresh. |
| `set-decay <P> [-f]` | Make the room's modeled decay shorter or longer than its loaded/calibrated baseline. | Proposed master decay multiplier `m=P/100` applied to each solved octave-band RT60: `RT60'_b = m * RT60_baseline,b`. Keep the selected Sabine/Eyring model and band-to-band shape. The current solver selects Sabine or Eyring and supports absorption calibration, but does not yet expose this single master RT60 multiplier; this command therefore requires that engine control to be added. | Show percentage and effective RT60 by band (or a concise range), plus the selected decay model; mark room pending refresh. |
| `set-output <device>` | Choose where rendered preview audio is sent. | Set the output component's device/endpoint identifier. This is routing state, not an acoustic equation. Accept an exact endpoint ID or an unambiguous displayed name; reject unavailable or ambiguous endpoints. | Show selected endpoint and channel layout. If the device cannot be opened, keep the prior route and explain why. |
| `refresh` | Apply current room settings and hear/inspect the updated result. | Validate the working room controls, rerun affected solve/render components, then update the preview output using the selected endpoint. Preserve current controls and output selection. | Report what recomputed, effective settings, output endpoint, and any solver limits. |

## Complete room and engine dial inventory

The interactive CLI needs to cover every value that changes the room solve, not only the first two percentage controls. The proposed user-facing vocabulary below avoids exposing JSON paths while still showing the exact engine meaning. “Existing” means the current room model already has the backing value; the command/session UX is still proposed. “New” means an engine parameter is needed before the command can truthfully change that quantity.

| Dial / command | Range or choices | What it changes | Backing value and state |
|---|---|---|---|
| `set-size <length> <width> <height> [unit]` | Positive dimensions; default unit metres; accept `m` and `ft` and convert on input | Shoebox geometry, wall areas, volume, and decay estimates | `geometry.dimensions`; existing. Display canonical metres and optionally the entered unit. |
| `set-material <surface> <material>` | Six surfaces: `x-min`, `x-max`, `y-min`, `y-max`, `floor`, `ceiling`; named material from room library | Which frequency-dependent absorption/scattering coefficients each surface uses | `surfaces.*.material_id`; existing. |
| `set-absorption <band|all> <P> [-f]` | Percent multiplier, normally 0–100%, forced up to 250%; band centers 125–8000 Hz | Scales the material absorption used in that octave band, changing Sabine/Eyring decay and reflected energy | `engine_controls.absorption_scale[band]`; existing, current schema range 0–20x. Enforce physical effective absorption <= 1 and explain when a surface saturates. |
| `set-scattering <band|all> <P> [-f]` | Same percentage convention and seven octave bands | Scales scattering, changing the specular/diffuse energy split | `engine_controls.scattering_scale[band]`; existing, current schema range 0–20x. Effective scattering is bounded by 1. |
| `set-decay <P> [-f]` | Normally 0–100%; forced through 250% | Scales all predicted octave-band RT60 values together, preserving the relative band shape | Proposed `decay_scale` master parameter; new. Uses current selected Sabine/Eyring baseline. |
| `set-decay-model <eyring|sabine>` | `eyring`, `sabine` | Selects which existing equation estimates late-field RT60 | `engine_controls.decay_model`; existing. |
| `set-tail <P> [-f]` | Normally 0–100%; forced through 250% | Scales late-field energy, as perceived tail strength / wet energy, without changing RT60 | Maps to `engine_controls.diffuse_energy_scale`; existing (0–10x). **Corrected proposal:** keep render duration as its own dial, since “tail” in this control UX is tail amount, not file length. |
| `set-tail-duration <P> [-f]` | Normally 0–100%; forced through 250%; cannot be less than engine's minimum | Scales how long the renderer allocates for the decay | `engine_controls.tail_duration_scale`; existing. Current solver clamps generated duration to 0.25–8 seconds; show truncation/cap clearly. |
| `set-reflections <count>` | Integer 0–12 | Maximum specular reflection order; higher values add paths and computation cost | `engine_controls.reflection_order`; existing. |
| `set-temperature <degrees> [C|F]` | Current model accepts -50 to 100 °C | Changes sound speed and predicted path arrival times | `environment.temperature_c`; existing. Humidity is present in the template but not currently used by the solver. |
| `set-source <id> <x> <y> <z> [unit]` | Position must be inside room; per-band source level is optional advanced setting | Source location and its seven band levels | `sources[]`; existing. |
| `set-receiver <id> <x> <y> <z> [unit]` | Position must be inside room | Listening/microphone location; one output response is solved per source/receiver pair | `receivers[]`; existing. |
| `set-output <device>` | Enumerated available devices; exact ID or unambiguous name | Live preview destination only | Audio output component/device identifier; proposed output-session state, not an acoustic parameter. |
| `set-sample-rate <Hz>` | Supported rate list from output backend | Preview/render sampling and IR resolution | Current render CLI has a sample-rate argument; interactive device negotiation is new. |
| `set-preview-duration <seconds>` | Positive duration subject to safe render limit | Length of the test signal sent into the room before its tail | Existing `room-preview --duration`; proposed interactive session control. |
| `set-seed <integer>` | Integer | Repeatable preview noise sequence for A/B comparisons | Existing `room-preview --seed`; proposed interactive session control. |
| `detect <input>` | Automatic, with optional explicit override | Detects supported JSON schemas and audio container metadata; reports unknown channel role and missing analysis context | Implemented for Earnest room/formula/measurement JSON and audio headers. It does not yet import arbitrary plugin report formats or infer room geometry. |
| `room-solve-from-analysis <room> <analysis>` | Editable room and recognized analysis required | Translates analysis evidence into fitted per-band absorption controls, then runs the forward room solve | Implemented engine component and CLI workflow; preserves geometry/material assignments/source/receiver positions and emits fit report, calibrated room and IRs. Does not yet fit early reflection or spatial evidence. |
| `solve [room]` / `refresh` | Current room and controls | Runs the forward propagation/render solve using the fitted or user-authored room | Existing `room.solve` engine component; interactive session command is proposed. |

Percent controls are intentionally separated by what they affect: `set-tail` is late-tail energy, `set-tail-duration` is render length, and `set-decay` is RT60. They must not alias one another. Percentages use the loaded room baseline; `-f` applies the explicitly entered value up to 250%, it does not bypass validation or device/physics failures.

### Room creation inside the CLI

`room-template` currently writes a starter JSON file, but it is not enough for a user to build a room comfortably. Proposed primary workflow:

```text
earnest room create
```

The CLI should enter a guided room builder and ask for a room name, geometry type, dimensions and units, then materials and surface assignments, source positions, receiver/listening positions, and environment. It should show a plain-language summary and ask for a final `create`/`cancel` command before writing. Save as the existing `earnest.room.v1` JSON schema, refuse accidental overwrite, and immediately offer `solve`, `preview`, or `edit` in the new room session.

Within an active room session, room editing commands should include:

```text
add material <name>
set material <name> absorption <125Hz=... ... 8kHz=...>
set material <name> scattering <125Hz=... ... 8kHz=...>
assign material <name> to <surface>
add source <id> at <x> <y> <z> [unit]
remove source <id>
add receiver <id> at <x> <y> <z> [unit]
remove receiver <id>
show room
save room [path]
```

Material coefficients are fractions from 0 to 1 per octave band. The builder can offer common starter material presets, but every preset should be editable and visibly identified as an estimate. Room dimensions plus surface materials form the current shoebox room representation. The file format should remain the portable room-import/export boundary; third-party measured response data should enter through `room-fit`, while geometry import formats (for example, mesh/CAD) require a separate geometry backend and are not supported by the current solver.

For users who prefer arguments over prompts, keep `room-template <file>` and add a non-interactive form only after the interactive fields are settled, for example:

```text
earnest room create --name theater --shape shoebox --size 12m 8m 4m --out rooms/theater.json
```

The command should state which defaults it filled (starter material, all six surface assignments, source/receiver positions); it should never imply that guessed placements or material coefficients were measured.

### Inspect and apply controls

Add `show controls` to print every dial, baseline, current effective value, allowed range, and whether the value is pending. Add `show room` to print dimensions, volume, surfaces/materials, sources and receivers. `refresh` should validate the whole room, recompute only affected components when possible, and regenerate the preview. `refresh --play` can be an explicit form if automatic playback on refresh feels too surprising; the first implementation should choose one behavior and state it consistently.

Add `reset <dial|all>` to restore the loaded/saved baseline without editing the source file. The status display should distinguish: saved baseline, current working value, and forced override. This lets a user experiment with multiple controls and reliably undo them before saving.

### Why tail amount, decay and render duration are separate

`set-decay` changes the acoustic decay estimate and therefore the envelope/RT60 used by the solver. `set-tail` changes late-field energy. `set-tail-duration` controls how much time the renderer allocates for the resulting tail. These are separate equations/controls: increasing tail energy does not lengthen RT60, and increasing render duration does not make the room more reverberant.

For a band `b`, the decay envelope is represented as:

```text
A_b(t) = A_b(0) * 10^(-3t / RT60'_b)
RT60'_b = (P_decay / 100) * RT60_baseline,b
```

The tail duration control multiplies the renderer's baseline duration estimate:

```text
E_late = E_late,baseline * (P_tail / 100)
T_render = T_render,baseline * (P_tail-duration / 100)
```

The solve must ensure `T_render` is long enough to represent the chosen decay, or clearly report truncation. It should not silently conflate the duration control with physical decay.

## Example interaction

```text
> earnest control rooms/theater.json
Room loaded: theater (Eyring decay; 7 octave bands)
Output: Default Windows device

theater> set-tail 90
Late-tail energy: 90% of room baseline (scale 0.90). Pending refresh.

theater> set-decay 165 -f
Decay: forced to 165% of loaded baseline. RT60 by band: ... Pending refresh.

theater> set-output "Speakers (7.1 Surround Sound)"
Output selected: Speakers (7.1 Surround Sound)

theater> refresh
Room solution and preview updated. Settings retained.
```

Names and exact response detail are illustrative. `detect` and `room-solve-from-analysis` are implemented as one-shot CLI workflows; device discovery and interactive control mode are not implemented.

## Script-friendly form

The same controls should eventually be usable without an interactive session, for automation:

```text
earnest room-control rooms/theater.json set-decay 165 -f
earnest room-control rooms/theater.json set-tail 90
earnest room-control rooms/theater.json set-output "Speakers (7.1 Surround Sound)"
earnest room-control rooms/theater.json refresh
```

This direct form is a future CLI shape, not a claim about the current command parser. The interactive session is the primary UX because it keeps room context, pending changes and output selection visible.

## Review points

1. Does this full dial inventory cover the controls you expect to operate directly?
2. I interpreted `set-tail` as late-tail amount/energy and separated render length into `set-tail-duration`.
3. Should `set-decay` scale all octave-band RT60 values together, preserving their relative shape, with the loaded room/fit as baseline?
4. For room building, should the guided CLI ask every field conversationally, or should we prioritize a compact command syntax as well?
5. Should `refresh` immediately play through the selected output, or rebuild the preview and wait for a separate `play` command?
6. Should analysis fitting be allowed to vary source/receiver positions when the room file marks them as inferred, or should those remain fixed until explicitly unlocked?

These choices should be settled before wiring user-facing translations into the engine controls.
