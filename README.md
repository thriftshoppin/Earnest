# Earnest (earnest-ear, Phase 1)

**What it is:** an offline audio-analysis tool for studying a reverb/stereo effect (the Univerb study). You bounce a known probe signal through the effect in a DAW (Cakewalk/BandLab), drop the exports in `inbox\`, and Earnest turns them into short written summaries and numbers that Claude can read: room character per Mix level (RT60, EDT, tail level, direct-to-reverberant ratio, early taps, stereo width) and a fitted reverb formula.
**What it does for you:** one command (`earnest.bat`, or `py -3.14 -m earnest run`) from DAW exports to summaries, with telemetry that says exactly where data is lost (every stage reports OK / WARN / FAIL with the numbers it received), a self-test (`earnest ping`), and a clean-slate command (`reset.bat`). Checks are meant to be fast and verbose: every stage prints a timestamped line as it starts and finishes (turn off with env `EARNEST_LIVE=0`).
**What it never does:** play audio (no output-device code), move or delete your files, or push anything anywhere by itself.
**Status (2026-11-01):** all 76 test checks pass on the current code (see Tests). Not yet done: speed work on the room stage, coloured console output, a non-clipping probe export for the real data (the `-3 dBFS` union passes are clipped), and any test on a real Univerb export.
**What it is:** an offline audio-analysis tool for studying a reverb/stereo effect (the Univerb study). You bounce a known probe signal through the effect in a DAW (Cakewalk/BandLab), drop the exports in `inbox\`, and Earnest turns them into short written summaries and numbers that Claude can read: room character per Mix level (RT60, EDT, tail level, direct-to-reverberant ratio, early taps, stereo width) and a fitted reverb formula.
**What it does for you:** one command (`earnest.bat`, or `py -3.14 -m earnest run`) from DAW exports to summaries, with telemetry that says exactly where data is lost (every stage reports OK / WARN / FAIL with the numbers it received), a self-test (`earnest ping`), and a clean-slate command (`reset.bat`). Checks are meant to be fast and verbose: every stage prints a timestamped line as it starts and finishes (turn off with env `EARNEST_LIVE=0`).
**What it never does:** play audio (no output-device code), move or delete your files, or push anything anywhere by itself.
**Status (2026-11-01):** all 76 test checks pass on the current code (see Tests). Not yet done: speed work on the room stage, coloured console output, a non-clipping probe export for the real data (the `-3 dBFS` union passes are clipped), and any test on a real Univerb export.
Turns stereo audio into things Claude can read: a **scene sheet** (`listen`), a **room card** with a fitted **reverb formula** (`room`), and a statistical
re-render check (`resynth`). It never plays audio and contains no output-device code. Signals are written as WAV files and bounced offline in a DAW.

**Quick start: put the exports in `inbox\`, double-click `earnest.bat`.** It analyzes every new or changed file, copies the newest results (and each file's trace) to `runs\latest\` and opens that folder.
(`py -3.14 -m earnest run [--force] [--stop-on-fail]` does the same from a terminal; `inbox\processed.json` remembers what was done; your files are never moved or deleted.)
**File names:** one pass per file is the normal case. `<room><digits>.flac` is room `<room>` at Mix `<digits>` (`union100.flac` = room "union", Mix 100); a file whose name starts with `dry` is the dry reference
(the probe exported without the effect; one dry file serves every room in the inbox and becomes the Mix 0 step). A file that holds several passes (about 5 x 190 s) is one room, labelled by `--labels`.
Which kind a file is gets decided by its length, not its name. Identical files are flagged DUPLICATE and skipped. `reset.bat` archives old results and runs `earnest ping`.

## How to run (three lines)
1. Put the Cakewalk export (one file per room) in a folder.
2. `py -3.14 -m earnest analyze-all <folder>` (one room: `py -3.14 -m earnest analyze <file> --room "Atrium"`).
3. Read `all_rooms_summary.md` (and each room's `summary.md`) in the `runs\...-analyze-...` folder it prints. Nothing plays audio.

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
- `room <dry_dir> <wet_dir>` -> deconvolves the sweeps into a 2x2 IR matrix; fits direct matrix, early taps, per-octave tail, room metrics; runs the linearity check; builds the pan transfer map.
  Also accepts two WAV files (one sweep pair; a dual-mono dry sweep gives a 1-input `mono_sum` formula). Writes `formula.json`.
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
