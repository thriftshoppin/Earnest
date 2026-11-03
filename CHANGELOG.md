# Changelog

This log records local builds, grouped by development phase. Dates are local project dates. These builds are not necessarily installed or publicly released. The baseline is the last fetched `origin/master` at `9cabc1e`; the exact state of the user's VM has not been independently checked. See `docs/BUILD_NOTES_NOV_03.md` for a narrative and `docs/PHYSICS_NOTES.md` and `docs/ROOM_SOLVER_MATH.md` for equations, references and assumptions.

## Unreleased — Hypothesis evidence integration

- Added `audio.hypothesis_evaluate` and `hypothesis-evaluate` to compare an aligned sum of candidate stems with the original and save the residual, reconstruction measurements, input hashes and optional normalized note events. Basic Pitch CSV and versioned note-event JSON are supported.
- Added a time-windowed harmonic peak-support measurement with configurable harmonic count and cents tolerance. The reported peak-power proxy is not total signal energy or an identification result; unavailable quantities remain null.
- Added `audio.hypothesis_rank` and `hypothesis-rank`, requiring explicit weights and comparable reference hashes and formats. Scores combine chosen reconstruction, spectral and note-rate terms and are not calibrated probabilities.
- Documented equations, formats, usage, evidence limits and the remaining room, timing and iterative analysis work. Five focused tests cover known tones, incorrect timing, silence, alignment, model CSV input, ranking and CLI behavior; the complete suite passed 76 tests. Existing Demucs and Basic Pitch outputs were also evaluated together on one generated tone after explicit reference conversion.

## Unreleased — Viewer head models

- Bundled the two local LipScan head files for the live viewer and updated its server to prefer bundled models, with the previous external pack path as a fallback. VM application updates include the bundled heads.
- Added the project owner's description of their provenance and noted the conflicting older local pack metadata in `live/models/README.md`. Provenance has not been independently verified from creation records.

## Phase 8 — Source separation, transcription and VM update

### Local build bf5c8fe — 2026-11-03

- Added the optional `audio.separate` engine component and `earnest separate` CLI. The isolated Demucs `htdemucs` backend produces estimated vocals, drums, bass and other stems, plus a manifest identifying the input, hash, model and output paths. CPU is the default; CUDA and a separate backend path can be selected. The outputs can contain leakage, room sound and multiple instruments, and can be rescaled by the backend.
- Added the optional `audio.transcribe` component and `earnest transcribe` CLI using a separate Basic Pitch environment. It writes MIDI, note-event CSV and a provenance manifest; an alternate executable can be configured. Basic Pitch works best on one instrument at a time and does not identify or separate every instrument in a song.
- Added Python 3.11 setup scripts and direct dependency pins for both optional model environments. These environments and model weights are not checked into Git or bundled in the VM update. Demucs may download model weights on first use. The pins are not a complete lock of all transitive dependencies.
- Extended `audio-compare` with optional time-segmented reports, and added `audio-rank` to order aligned candidate reconstructions by mean-square error while recording source hashes. These are sample-domain measurements, not perceptual scores or proof that a source or room was identified correctly.
- Added optional equal-tempered pitch coordinates and cents offsets to spectral peaks in `frequency-trace`. This maps frequencies mathematically; it does not establish fundamentals, played notes, onsets, instrument identity or MIDI events.
- Added a VM application update builder, guest updater, per-file integrity manifest, backup of overwritten files, upgrade instructions and a separate update ZIP with accompanying checksum. It updates application code, room editor, viewer files and Frankenjack; it preserves guest inboxes and settings, existing runtimes and the installed driver. It does not update Windows, alter Secure Boot or bundle the optional models. Recovery from a failed update is manual, and the checksums are not a publisher signature.
- Added the changes-since-baseline report, model and updater documentation, and tests for pitch conversion, comparison segments/ranking, backend adapters and updater behavior. A generated A440 tone produced MIDI note 69; a generated-tone separation produced four files. These are smoke tests, not full-song accuracy evaluations. The complete Python suite passed 71 tests at the close of this build; native audio and UI checks passed offline. The update ZIP was applied to a temporary mock installation, not to the user's VM.

## Phase 7 — Frequency focus and comparison

### Local build 25633df — 2026-11-03

- Added the `audio.focus_band` engine component and `focus-band` CLI. An offline forward/backward Butterworth band-pass writes a float WAV for a selected frequency range. Tests exercise cutoff validation, preservation of a selected tone, rejection of a distant tone, channel layout and overwrite protection.
- Added `audio.compare` and `audio-compare`: subtract an already aligned candidate from a reference and report channel error and frequency-band energies using real-FFT Parseval normalization. The component exposes residual samples for subsequent analysis. Tests cover known missing tones, exact matches, channel/bounds checks and even/odd FFT lengths.
- Documented filter phase and edge limitations, spectral band weighting and alignment requirements. Frequency focusing does not uniquely isolate instruments, and a low residual does not prove a unique explanation.

## Phase 6 — Live room controls and visualization

### Local build 4aaa619 — 2026-11-03

- Reused the original StageJack selected-playback WASAPI loopback monitor and spectrum renderer in Frankenjack, restored the analysis device picker and connected its output to the visualizer. This monitors the chosen Windows endpoint mix, which can include other applications; it is not an exclusive measurement of the Earnest bridge.
- Replaced the hard-coded flat displayed EQ response with the response of Earnest's seven reflection peaking filters, and aligned the displayed nodes with those controls. Offline checks cover sample decoding, missing-input behavior and the displayed filter response. The updated display has not been validated live in the VM.
- Added `docs/SUITE_UPDATES_PLAN.md` describing a future versioned suite updater, compatibility checks, staged installation and rollback. That broader updater remains a plan; the later VM application updater is a narrower implementation.

### Local build 93a7ce8 — 2026-11-03

- Added preparation of replacement room profiles while the bridge stays open, then a 120 ms warm-up and 150 ms linear crossfade between the current and replacement convolver outputs. Invalid profile preparation retains the current room.
- Added offline checks for transition continuity and invalid updates. Endpoint changes still restart the bridge; the new tail builds from limited recent history, overlap briefly increases processing load, and no live glitch-free result is claimed. The UI reports preparation rather than confirmed application.

### Local build c87e84f — 2026-11-03

- Added a saved room-file chooser to Frankenjack Advanced Mix, replacing the fixed Union Stairs source path. The chooser displays the selected file and rejects a missing file; the room is compiled by the existing adapter.
- Added offline room-selector and control-window checks. At this build, changing a room restarted the bridge; the later crossfade build changes that behavior. This does not validate every room format or live device route.

### Local build 489e0d8 — 2026-11-03

- Added file-based `set-decay`, `set-tail` and `set-tail-duration` commands. Each scales its corresponding control from an explicit baseline room and writes a new file; normal and forced percentage bounds, room-schema limits and existing-file protection are checked.
- Added CLI tests for independent controls, the extended range and invalid output. Documented the distinction between late-field energy, decay time and rendered duration, and recorded a research comparison with Pyroomacoustics. The interactive command session, live refresh and device-selection commands remain proposals.

### Local build 4f57715 — 2026-11-03

- Connected the Stage Width dial to a smoothed stereo mid/side operation after the direct and wet mix: zero removes side, the midpoint preserves the signal and the maximum doubles side. The stage enable control now reaches that path.
- Added offline tests for mono, unity and widened channel outputs and documented the equations. This is stereo processing rather than physical source placement, multichannel rendering or binaural spatialization; widening can increase peaks before the ceiling.

### Local build e877184 — 2026-11-03

- Added a separate seven-band direct-sound peaking EQ, its Advanced Mix controls and its own control file. It processes delayed direct sound before the center contribution; reflection EQ remains independent and both default to unity.
- Added offline checks at every EQ center for positive and negative gain, direct/wet isolation and UI bindings. Documented the coefficient equations and native-host deployment path. No live listening result is implied.

### Local build 9bb7239 — 2026-11-03

- Added `decay_scale` to the room model, solver, live profile adapter, Room Studio and Frankenjack. It multiplies the selected modeled RT60 while preserving raw Sabine/Eyring estimates; tail render duration remains a separate control with an eight-second cap.
- Added tests of raw and effective decay, synthesized tail slope, profile propagation and controls; updated the equation sheet and command reference. The multiplier is a tuning control, not a recovered physical room property.

## Phase 5 — Room-field and decay refinements

### Local build 8fba240 — 2026-11-03

- Added independent, common in-phase and opposite-polarity source assumptions in Room Studio's field map, plus custom complex source-correlation matrices in the engine and CLI. Added an opposed-source example.
- Added validation and cancellation tests; exact zero and unavailable near-source samples have distinct representations. The view remains a modeled, relative single-frequency slice.

### Local build 6ce0354 — 2026-11-03

- Added an interactive room-field slice, engine component and CLI export. It sums coherent image paths for each source and initially assumes independent powers across sources; source and receiver placement come from the editable room.
- Added field-grid and editor checks, including cancellation behavior and invalid inputs. This point-sampled preview is not calibrated SPL and does not model the diffuse late field.

### Local build c773cd3 — 2026-11-03

- Added finite-window C50, C80, D50 and center-time energy diagnostics for modeled source/listener octave-band responses. Added tests for time boundaries, zero energy and known signal cases.
- Updated equation and physics documentation. Results are limited to the simulated finite response, not an independently measured venue.

### Local build 8a9f011 — 2026-11-03

- Added optional atmospheric absorption to Sabine/Eyring decay, absorption fitting and the diffuse-field approximation using the documented `4mV` correction; explicit paths already had optional atmospheric attenuation.
- Added reference-value, air-only and fit-consistency checks and updated the equation and physics notes. Model validity remains bounded by the stated atmospheric and room assumptions.

### Local build 1102fb3 — 2026-11-03

- Added cross-spectral propagation for multiple correlated sources and receivers, input validation for Hermitian positive-semidefinite correlation matrices, a CLI and an adapter for explicit room paths. Added an independent-stereo example and numerical checks.
- Corrected documented IACC, source directivity, atmospheric attenuation, specular-scattering and cross-spectral conventions. The propagation adapter excludes the diffuse statistical tail and is not calibrated absolute SPL.

## Phase 4 — Room authoring and instrument reference work

### Local build b7e0b66 — 2026-11-03

- Expanded Room Studio controls for dimensions, surface materials, environmental parameters, sources, listeners, decay and room settings. Added click/drag and keyboard editing, room JSON export, and reconstructable instruction export with corresponding CLI support.
- Added editor and round-trip checks. The supported geometry is rectangular; the viewer and exported room are not a general arbitrary-mesh acoustic solver.

### Local build 092e434 — 2026-11-03

- Added an experimental supervised reference matcher: labeled short recordings produce log-spectrum feature vectors and an identification command ranks examples by distance. Model files retain input paths and hashes.
- Added unit and CLI checks and documented format and model limitations. It is not a pretrained neural network, source separator, calibrated probability model or validated full-song classifier.

### Local build bfc8387 — 2026-11-03

- Added room-physics foundations: optional atmospheric loss and idealized source/receiver directivity on explicit paths; ideal string, pipe, stiff-string and circular-membrane mode equations; and time-stamped spectral peak tracing.
- Added a lightweight room-editor foundation, live-view navigation work, and expanded Frankenjack Advanced Mix controls. Added equation, reference-value, frequency-trace, UI and offline mix checks.
- Documented the formulas and limitations. Spectral peaks are measurements rather than note events, ideal modes do not fully model real instruments, and the room model does not establish a uniquely recovered space.

## Baseline 9cabc1e — 2026-11-02

- Consolidated the experimental room engine, configurable audio lab, VM packaging, CLI, viewer and initial math documentation. The VM device and routing were experimental; the user's earlier listening report was not a controlled equivalence test. Earlier repository history predates this changelog.
