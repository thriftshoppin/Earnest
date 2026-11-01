# Earnest (earnest-ear, Phase 1)

Turns stereo audio into things Claude can read: a **scene sheet** (`listen`), a **room card** with a fitted **reverb formula** (`room`), and a statistical
re-render check (`resynth`). It never plays audio and contains no output-device code. Signals are written as WAV files and bounced offline in a DAW.

## Install
Python 3.14 with `numpy scipy soundfile matplotlib pyloudnorm` installed globally (versions in `requirements-lock.txt`, a plain `pip freeze` of that Python).
No venv. Run from this folder: `py -3.14 -m earnest <command>`.

## Commands (each writes `runs\<YYYYMMDD-HHMMSS>-<cmd>\` with report.md (<=150 lines), one JSON, one 1600x1200 PNG)
- `gen` -> test signals, 48 kHz 32-bit float, peak -18 dBFS: `sweep_L/R.wav` (exp sweep 20 Hz-16 kHz, 8 s, 0.5 s before, 4 s silence after), `sweep_L/R_m30.wav` (same at -30 dBFS),
  `clicks_panned.wav` (pans -1, -0.5, 0, 0.5, 1, constant power, 2 s apart), `clicks_mono.wav` (same click in both channels), `noise_bursts_panned.wav`.
  Bounce each through the effect with the same names into a wet folder. For the linearity repeat, bounce `sweep_L/R.wav` twice and save the second as `sweep_L_rep.wav` / `sweep_R_rep.wav`.
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
`py -3.14 tests\run_tests.py` (synthetic IRs with known answers, PASS/FAIL with numbers; about 2 minutes). `tests\make_demo.py <dir>` builds a demo dry/wet folder pair from a known synthetic reverb.
