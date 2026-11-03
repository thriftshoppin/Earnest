# Earnest (earnest-ear, Phase 1)

**What it is:** an audio-analysis and room-modeling tool. It measures reverb from dry/wet samples, creates editable room models, solves their acoustic response, and can audition a modeled receiver from the CLI.
**What it does for you:** the existing analysis commands turn DAW or plugin renders into room measurements and a fitted reverb formula. The room commands let you edit geometry, materials and solver controls, fit measured decay into those controls, render a room preview, and write simulation WAVs.
**Playback:** `room-preview --play` auditions a rendered room on the Windows default output. The experimental virtual device was installed in a VMware guest and the user reported hearing a room through it. Repeatability, device recovery, buffering and surround remain unverified; see [VM lab status](docs/LAB_STATUS.md).

Earnest's engine is being organized as a component host: analysis, room inference, propagation solving, rendering, and output are components exchanging versioned artifacts. The CLI assembles those components into workflows; it is not the location of the equations. See [the engine architecture](docs/ENGINE_ARCHITECTURE.md) for the extension contract and current boundaries.

The research direction is documented in the [roadmap](docs/ROADMAP.md); the equations and their limitations are in [room solver math](docs/ROOM_SOLVER_MATH.md). The current root license is all-rights-reserved, despite the project's open-source ambition; a license change remains to be selected.

**Quick start: put the exports in `inbox\`, double-click `earnest.bat`.** It analyzes every new or changed file, copies the newest results (and each file's trace) to `runs\latest\` and opens that folder.
(`py -3.14 -m earnest run [--force] [--stop-on-fail]` does the same from a terminal; `inbox\processed.json` remembers what was done; your files are never moved or deleted.)
**File names:** one pass per file is the normal case. `<room><digits>.flac` is room `<room>` at Mix `<digits>` (`union100.flac` = room "union", Mix 100); a file whose name starts with `dry` is the dry reference
(the probe exported without the effect; one dry file serves every room in the inbox and becomes the Mix 0 step). A file that holds several passes (about 5 x 190 s) is one room, labelled by `--labels`.
Which kind a file is gets decided by its length, not its name. Identical files are flagged DUPLICATE and skipped. `reset.bat` archives old results and runs `earnest ping`.

## How to run (three lines)
1. Put the Cakewalk export (one file per room) in a folder.
2. `py -3.14 -m earnest analyze-all <folder>` (one room: `py -3.14 -m earnest analyze <file> --room "Atrium"`).
3. Read `all_rooms_summary.md` (and each room's `summary.md`) in the `runs\...-analyze-...` folder it prints.

On Windows, `bin\earnest.cmd` is the PATH launcher. After adding the repository's `bin` folder to the system PATH, use `earnest --help` or `earnest <command>` from any directory. With no arguments, `earnest` lists the available commands.

## Experimental live audio

`earnest audio-restart` opens an administrator Windows Audio restart window, force-terminates the Windows Audio host, and starts Windows Audio again. If the host is shared, other services in that process are also terminated. The window reports command output and remains open. From the repository without the PATH launcher, use `python -m earnest audio-restart`.

`earnest audio-devices` lists active Windows playback devices. `earnest route <room.json> --output "device name"` is intended to send the default Windows mix through Earnest Virtual Speakers to a selected output. `earnest route-stop` restores a saved default after an interrupted route. The separate driver project must first be installed and verified; the locally built driver is test signed and is not a production Windows driver. The current host uses shared playback, so applications explicitly targeting a physical endpoint can bypass Earnest. It cannot yet guarantee exclusive ownership of the speakers.

The live DSP currently maps the median solved RT60 to a feedback delay network with dry and wet controls. The solver's per-band absorption, reflection paths, and spatial detail are not yet reproduced in that live DSP. The profile records those values for a future processor. Full route behavior, device recovery, multiple playback roles, and the driver bridge require end-to-end validation before everyday use.

`earnest bridge <room.json> --input "endpoint" --output "endpoint"` is a separate experimental convolution bridge. It solves the chosen room and compiles per-channel responses from the Python renderer into a native streaming profile. It accepts stereo, 5.1 and 7.1 layouts when the input endpoint actually exposes that layout (`--layout`); inspect formats with `earnest audio-devices --formats`. Sources named FL, FR, FC, BL, BR, SL, and SR match their channel; absent names fall back to the first source. LFE is direct only. Each channel is filtered independently: reflection directions and cross-channel spatial mixing are not modeled. The bridge does not change the Windows default or prevent the captured endpoint from also playing through another route. The input must be an isolated virtual sink to avoid a dry parallel path. The zero-phase offline bank is approximated using finite lookahead (85 ms by default) plus a 512-frame block and device buffering; this is not optimized for gaming. Samples exceeding full scale are clipped. Endpoint changes, clock drift, underruns and continuous operation still need validation. It is not a VST or a finished surround renderer.

## Spatial headphone rendering

Earnest can render a stereo, 5.1 or 7.1 file through a configured room into stereo headphone audio. For 7.1, create an editable room and render audio in Windows order FL, FR, FC, LFE, BL, BR, SL, SR:

```text
earnest spatial-room-template surround-room.json
earnest spatial-render surround-room.json game-7.1.wav --layout 7.1 --out headphones.wav --play
```

Supported layouts are `stereo`, `5.1-back`, `5.1-side` and `7.1`; choose explicitly, since channel count alone does not identify the speaker layout. The listener faces +X and +Y is left. Each directional channel is mapped by its room source ID, while LFE is sent equally to both ears without bass management. Existing `room-fit` output can be used to calibrate the room's absorption before rendering.

Optionally create a session with `earnest engine-init surround-engine.json surround-room.json` and pass `--session surround-engine.json` to `spatial-render` to apply its EQ, input and output gains, and wet control. Both commands must point to the same room file.

The default uses MIT KEMAR measured HRIRs by Bill Gardner and Keith Martin (see `earnest/audio/data/MIT_KEMAR_ATTRIBUTION.md`). An alternative `SimpleFreeFieldHRIR` SOFA file can be supplied with `--hrtf`. The nearest measured direction is chosen, without interpolation. This is an offline reference implementation: each source's complete mono room response is filtered with that source's direct HRIR, so individual reflected directions, head tracking, full-band phase alignment, and live system audio routing remain future work. The HRTF is a generic measured head, not a personalized measurement.

## Configure and audition the engine with an audio file

This workflow uses the existing room solver and does not require the virtual driver or a change to Secure Boot. Create a room and a session, adjust the session, then render an input file:

```text
earnest room-template my-room.json
earnest engine-init my-engine.json my-room.json
earnest engine-set my-engine.json --eq 1000 3
earnest engine-set my-engine.json --control wet 75
earnest engine-set my-engine.json --control output -6
earnest engine-render my-engine.json input.wav --out rendered.wav --play
```

EQ bands are 31, 62, 125, 250, 500, 1000, 2000, 4000, 8000 and 16000 Hz; values are dB. `input` and `output` are also dB; `wet` is a percentage from 0 to 100. At 0% only the modeled direct paths are heard; at 100% the full solved room is heard. Both use the same source gains and propagation delays. Each render reloads the session and room, solves the room and writes a new float WAV. Playback uses the Windows default output and is attenuated if necessary to avoid clipping. The exported float WAV preserves the calculated level and reports samples above full scale.

To use measured black-box evidence, analyze matching dry and wet probes with `earnest room`, then run `earnest room-fit my-room.json <formula.json>` and initialize an engine session with the resulting calibrated room file. The fit uses measured octave-band decay to adjust absorption; it does not identify a unique physical room or reproduce every plugin behavior. The current room renderer outputs one mono pressure signal per receiver, including for stereo sources. This is an offline audition path; it does not intercept system audio.

## Telemetry (trace) and ping
Every command that reads audio (`analyze`, `run`, `analyze-all`, `split`) prints a trace at the end: one line per hop, `OK`, `WARN` or `FAIL`, with what the hop received against what it expected:
FILE (container, rate, channels, bit depth, length), READ (per channel: frames, peak, RMS, DC, clipped samples, noise floor, L/R correlation), CONVERT (resampling: frames and per-channel peaks in and out),
MATCH (each channel against each sweep of the probe: peak-to-noise in dB and where it was found; the detection threshold is the largest value Gaussian noise would reach over all lags, plus 25 %; the sweep's
processing gain is used, so a probe below the file's bit step can still be found and the trace says how far below), SPLIT (copies found), LEVEL (calibration gain G, usable range), ROOM (direct matrix, IR energy, tail, taps), WRITE.
The first FAIL stops that file (with the likely cause) and the batch goes on to the next file; `--stop-on-fail` stops the whole batch. A hop over 10 minutes is a FAIL ("stuck at hop X"); Ctrl+C prints the trace so far.
`trace.txt` and `trace.json` are saved per file (in `runs\...\trace\`, mirrored to `runs\latest\`), and every hop is appended to `data\trace_log.csv`. A failed hop never blanks the summary: what was read stays in it.
`py -3.14 -m earnest ping` writes known files (clean probe as 24-bit FLAC with dither, the same through a crossfade effect twice, a 16-bit 44.1 kHz copy, a right-channel-muted copy, noise only), runs the real chain and
checks every hop against the known truth; about 100 s, output in `runs\ping\`. `reset.bat [--yes] [--purge-archive DAYS]` moves `runs\*` and `processed.json` into `archive\<time>\` (nothing deleted; old archives go to
the Recycle Bin only with --purge-archive), checks the Python packages and runs ping; it ends with READY or the failing hops.

## Exporting a room (what to do in Cakewalk)
- Import the probe once (`gen --suite full` writes it; the user's version is `probe\earnest_probe_v1.flac`, 190.5 s, with its `.json`). Put one Univerb track per Mix level, with the Mix knob **fixed** (no automation) at 100, 80, 60, 30 and 0 **in that order**, the room set to the one you are measuring.
- Put the same probe clip on each track at a different time, one after another, with **at least 4 s of silence** between the clips. No solo or mute changes between them; only that track's effect may be in the path.
- The **last clip must be Mix 0**: it is the dry reference. Earnest measures its level against the generated probe and removes any global gain (normalize, master fader).
- Export one file per room. Normalize may stay on. 24-bit / 48 kHz is preferred; 16-bit / 44.1 kHz works (it is resampled to 48 kHz, and a 16-bit floor near -90 dBFS limits how far long tails can be fitted; bands with under 45 dB of decay range are flagged).
- `analyze` finds the five clips itself (by their sweep), so exact placement does not matter. It stops with a non-zero exit code if a clip is silent or the Mix 0 clip is not clean dry, and says which.

## Install
Python 3.14 with `numpy scipy soundfile matplotlib pyloudnorm` installed globally (versions in `requirements-lock.txt`, a plain `pip freeze` of that Python).
No venv. Run from this folder: `py -3.14 -m earnest <command>`.

## Commands (each writes `runs\<YYYYMMDD-HHMMSS>-<cmd>\` with report.md (<=150 lines), one JSON, one 1600x1200 PNG)
- `gen` -> test signals, 48 kHz 32-bit float, peak -18 dBFS: `sweep_L/R.wav` (exp sweep 20 Hz-16 kHz, 8 s, 0.5 s before, 4 s silence after), `sweep_L/R_m30.wav` (same at -30 dBFS),
  `clicks_panned.wav` (pans -1, -0.5, 0, 0.5, 1, constant power, 2 s apart), `clicks_mono.wav` (same click in both channels), `noise_bursts_panned.wav`.
  Bounce each through the effect with the same names into a wet folder. For the linearity repeat, bounce `sweep_L/R.wav` twice and save the second as `sweep_L_rep.wav` / `sweep_R_rep.wav`.
- `analyze`, `analyze-all`, `split --repeats/--labels`, `mixcurve` and `stage` are described under "Multi-pass workflow" below.
- `gen --suite lite|full` -> ONE WAV `probe_suite_<mode>.wav` (+ `.json` manifest, report, PNG) with every stimulus joined, so one DAW export per effect setting gives everything `room` needs.
  Same signals and names as above; each block has a 6 s silent tail; 2 s silence at the start, 1 s at the end. **lite** (81.5 s): sweep_L, sweep_R, clicks_panned, clicks_mono, noise_bursts_panned.
  **full** (139.5 s): sweep_L, sweep_R, sweep_L_m30, sweep_R_m30, sweep_L_rep, sweep_R_rep (identical copy of the -18 dBFS sweep), clicks_panned, clicks_mono, noise_bursts_panned.
- `split <wet_suite.wav> <manifest.json> <out_dir> [--dry-out <dir>]` -> finds the wet export's offset against the dry suite (cross-correlating the sweep_L block; aborts if over 0.5 s),
  cuts every block at start + offset into `<name>.wav` (48 kHz, 32-bit float, same names as `gen`), optionally writes the matching dry blocks, and reports the offset, per-block peak/RMS and any block under -90 dBFS as EMPTY.
  The offset includes the effect's own latency, so it is removed from the cut files.
- `listen <file>` -> loudness (LUFS, true peak), correlation, mid/side, per-octave pan and coherence, panogram, width over time, transients with pan, blind reverberance, <=20-segment summary.
- `zoom <file> --from 0.4 --to 1.4` -> `listen` at higher resolution on a slice.
- `room <dry_dir> <wet_dir>` -> deconvolves the sweeps into a 2x2 IR matrix; fits direct matrix, early taps, per-octave tail, room metrics; runs the linearity check; builds the pan transfer map; then runs a separate acoustic-inference component. Also accepts two WAV files (one sweep pair; a dual-mono dry sweep gives a 1-input `mono_sum` formula). Writes `formula.json` and `inference.json`.
- `room-template <room.json>` -> writes a starter editable rectangular room with six surfaces, one material, a stereo source pair and a receiver. Existing files are not overwritten.
- `room-fit <room.json> <formula.json|measurement.json> [--reverb-type LABEL]` -> runs the acoustic inference component, then fits each usable measured RT60 band to a per-band absorption scale. It records evidence and candidate interpretations and writes a new room file. Earnest formula files come from dry/wet audio analysis; third-party tools can export the `earnest.measurement.v1` JSON contract documented in `docs/ROOM_SOLVER_MATH.md`. A known plugin label can be supplied or preserved from `plugin_metadata`; measurements do not uniquely reveal room geometry or wall materials.
- `detect <input>` -> identifies supported Earnest room, formula, measurement JSON, or audio container metadata. A result folder can be supplied when it contains `formula.json`, `measurement.json`, or `room.json`. Audio detection reports sample rate, channels, duration and container; it does not guess dry/wet pairing or room geometry.
- `room-solve-from-analysis <room.json> <formula.json|measurement.json|result-folder> [--order N] [--sample-rate Hz] [--out folder]` -> detects and loads the analysis format, runs acoustic inference, fits measured RT60 into per-band absorption scales on a copy of the supplied room, then solves that calibrated room and exports solution metadata plus per-band IR WAVs. Writes `calibrated.room.json` and `fit_report.json`; preserves the supplied geometry, materials, sources and receivers. This is an equivalent acoustic fit, not unique physical room reconstruction.
- `room-preview <room.json> [--play] [--receiver ID]` -> drives a repeatable noise burst through the configured room, writes a WAV, and optionally plays it through the Windows default output.
- `room-solve <room.json> [--order 4] [--sample-rate 48000] [--out folder]` -> runs the physical-room engine and writes `solution.json` plus one octave-band IR WAV per source/receiver/band. The current engine solves specular paths in a shoebox; it reports model limits with every result.
- `simulate <room.json> <input.wav> [--order 4] [--out folder]` -> solves the room, drives one input channel per configured source through each receiver response, writes rendered WAVs with the full decay, and saves level/band analysis plus reusable room IRs. This is offline rendering; it does not open an audio device.
- `resynth <formula.json> <dry.wav> [--compare wet.wav] [--seeds 5]` -> renders the formula against the dry sweep and reports error mean +- sd over seeds.
- `crosscheck` -> fits the eight Univerb renders and tabulates them against `univerb_results.csv` (refuses wet files that are not renders of the dry sweep).

## Suite workflow
`gen --suite lite` (or `full`) -> import the dry suite WAV into the DAW, export it through the effect for each setting (export all of it, same start point) -> `split <wet export> <manifest> <wet_dir> --dry-out <dry_dir>` -> `room <dry_dir> <wet_dir>`.
Use `full` when you want the linearity check (needs the -30 dBFS and repeat sweeps).

## What the numbers mean
- **pan**: -1 left, +1 right; from a level ratio under a constant-power law (gL=cos((p+1)pi/4), gR=sin((p+1)pi/4)).
- **RT60**: seconds for a 60 dB fall, from Schroeder backward integration (T30 preferred, else T20); **EDT** from 0 to -10 dB. Measured from the end of the direct-sound window, with detected early taps masked.
- **IACC**: peak L/R correlation of the tail within +-1 ms.
- **level dB re direct**: energy after the direct-sound window divided by energy in it; **DRR/C50/C80** use broadband energy.
- **pre-delay / build-up**: time until the band's smoothed tail energy is within 15 dB of its peak / time from there to the peak.
- **early taps**: isolated peaks >= 6 dB above the local floor in the first 80 ms; "unresolved" (with the count found) when fewer than 3 qualify. Never padded.
- **linearity**: IR from -18 and -30 dBFS sweeps (and a repeat) compared per band; > 1 dB in level or EDC flags `nonlinear_or_time_variant: true`.

## Limits
- The tail is **statistical**: noise shaped by the formula. Comparisons use means over seeds, never waveforms. A "match" is only ever stated against numbers.
- Assumes a **linear, time-invariant** system (checked, not guaranteed). Time-varying effects (modulation) are detected only coarsely.
- The sweep is band-limited to 20 Hz-16 kHz; the direct gain is read over 200 Hz-8 kHz. Band measurements below ~125 Hz or above 8 kHz are not made.
- A 125 Hz band cannot separate the direct sound from taps closer than about 20 ms (the filter's own ringing).
- Wet files at other rates are resampled to 48 kHz and the report says so.
- A dual-mono dry sweep identifies only the sum of the two input paths.
- The physical room engine is an initial rectangular-room backend: it calculates direct/specular image paths, a statistical diffuse late tail, Sabine/Eyring decay estimates, and ideal low-frequency mode frequencies. It does not yet model directional diffuse rays, mode response, air absorption, mesh geometry, or absolute SPL. Its seven octave-band IR files are separate band responses, not a phase-aligned full-band RIR. `simulate` combines those bands for offline rendering and passes unmodeled frequencies through the delayed direct path.
- Room JSON `engine_controls` exposes the current solver's reflection order, Sabine/Eyring decay equation, per-band absorption/scattering multipliers, diffuse-tail energy scale, and tail-duration scale. These are model controls for experimentation; absorption/scattering multipliers are calibration knobs, not replacement material measurements.
- `room-fit` uses measured decay to seed absorption controls. Its response-character label is a cautious heuristic; plate, spring, hall, and other effect-family labels require plugin metadata or a user-supplied `--reverb-type`. A wet sample without its matching dry source cannot reliably isolate the effect response.

## Tests
Each test script runs in a console with live output (step and hop lines with timestamps, then PASS/FAIL with the numbers) and writes `tests\last_*_console.txt` and `last_*_results.txt`. Current results (2026-11-01): `run_tests.py` 22 checks / 120 s, `run_suite_tests.py` 19 / 383 s, `run_onecmd_tests.py` 16 / 455 s, `run_trace_tests.py` 13 / 382 s, `run_reset_test.py` 6 / 104 s: 76 checks, 0 failed. `tests\make_demo.py <dir>` builds a demo dry/wet folder pair from a known synthetic reverb. What each test proves, and what it cannot, is in `TESTS.md`.

## Multi-pass workflow (commands)
- `gen --suite full` reproduces `earnest_probe_v1` (12 blocks, 190.5 s; the three noise-width blocks are copied from the bundled `probe\` reference). `lite` has the first 5 blocks needed by `room` (81.5 s).
- `split <wet> <manifest.json> <out_dir> --repeats 5 --labels 100,80,60,30,0 [--dry-out <dir>]`: finds each copy of the suite independently (cross-correlating the dry sweep_L block with the wet file in chunks, never loading a big file whole), writes `step1_mix100\ ... step5_mix0\`, divides the Mix 0 level gain out of every file, reports each offset, peak/RMS per block, and names any silent pass EMPTY. Everything is read from the manifest (names, times); the dry signal comes from the file next to the manifest if there is one.
- `analyze <export> --room "<name>" [--manifest ...] [--labels ...] [--out ...]`: split + calibration + `room` on every pass (against the generated dry blocks) + `mixcurve` + `stage`; writes `summary.md` (<= 120 lines), `summary.json`, `mixcurve.png` and one folder per pass with the usual room report, formula.json and room.png. Exit code 2 if a pass is empty or the Mix 0 pass is not clean dry.
- `run [--inbox dir] [--force]`: the one command (also `earnest.bat`). Analyzes every .wav/.flac in `inbox\` that is new or changed, records it in `inbox\processed.json`, mirrors the newest results of every room into `runs\latest\` (`all_rooms_summary.md`, `<room>_summary.md`, `<room>_mixcurve.png`, `<room>_room.png` = the Mix 100 pass) and opens it in File Explorer. Prints one line per room (OK / EMPTY / not clean dry and why). Non-zero exit if anything was flagged.
- `analyze-all <folder>`: `analyze` on every .wav/.flac there (room = text before the first `_` or `-` in the file name); writes `all_rooms_summary.md` (<= 100 lines) with one row per room and Mix level.
- `mixcurve <room run folder> ... [--labels 100,80,...]`: the room metrics against Mix, one curve, flags for metrics that move more than 10% (dB values: 1 dB). A pass with no tail (Mix 0) gets no RT60/EDT/IACC.
- `stage` (inside `analyze`): from noise_mid (input correlation +1), noise_wide (0), noise_side (-1): L/R correlation and side/mid dB of the direct part and of the tail (0.5 s after each burst ends, up to 5 s or the next burst; per octave 125 Hz-8 kHz), and the width gain (output minus input side/mid dB, defined for noise_wide only).

## Conventions
- **RT60 and EDT** are both measured from the **tail onset**: the first moment the smoothed tail energy (direct sound and detected taps masked) comes within 15 dB of its peak. The direct sound, the early taps and any pre-delay gap are not in the decay curve. For a pure exponential tail with no pre-delay this gives EDT = RT60. It is **not** the ISO 3382 EDT, which starts at the direct arrival and therefore includes the direct sound (with a strong direct sound that EDT is much shorter and mostly measures the direct-to-reverberant ratio). EDT of a noise-like tail in a single octave band is statistically noisy (about +-15 % per band); the mean over bands is steadier.
- **Dry or near-dry steps** (tail under -40 dB re direct, e.g. the Mix 0 pass) show n/a for RT60, EDT and IACC and are left out of the Mix-curve "moves by" flags.
- **Usable range** (summary column) = loudest sweep peak of a pass minus the RMS of that copy's silent head and end, both in the file's own dBFS scale before calibration. A 16-bit file's floor is about -96 dBFS with dither (digital silence reads as -140). Passes under 45 dB are flagged.
- **Clip start s** = where a copy of the suite begins in the export file (clip position; it also includes the effect's own latency).
