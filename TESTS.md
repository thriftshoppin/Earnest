# What the tests check (and what they do not)

Plain words. Last full run 2026-11-01: 76 checks, 0 failed (22 + 19 + 16 + 13 + 6). Every test runs in a console with live timestamped output and is a script in `tests\`; each prints PASS or FAIL with the raw numbers and writes a `last_*_results.txt` next to it.

## Read this first: where the "truth" comes from
- Almost every test builds its own audio: a synthetic reverb with known numbers (RT60, taps, a 3 ms direct delay, tail correlation) or a crossfade `y = (1-m) dry + m reverb(dry)`.
- For the crossfade tests (mixcurve, single-pass inbox, ping) the expected tail level and DRR are computed by running **the same estimators** on the exact impulse response, not from an independent formula.
  So those tests prove the plumbing (finding the passes, calibration, cutting, deconvolution, bookkeeping), **not** that the estimators measure the real world correctly.
- The tests that check an estimator against something independent are the RT60 / IACC / tap / pan tests in `run_tests.py` (limits set by the spec), the exact-exponential EDT test, the stage test (analytic values for a known side boost) and the noise-floor test (re-measured directly from the file).
- **No test has used a real BandLab/Cakewalk export or real Univerb audio.** The only real files seen so far are the six in `inbox\`, and those were only run through the trace and the analysis, with no known answer to compare against.
- Files are written with libsndfile. Its 16-bit conversion truncates instead of rounding, so synthetic 16-bit files are not a model of Cakewalk's dither.

## run_tests.py (22 checks, 120 s): the maths
- **RT60 0.3 / 1.2 / 2.5 s** (3 checks): a known exponential noise tail is pushed through the real sweep chain (sweep -> convolve -> deconvolve -> analyse); every octave band 125 Hz-8 kHz must be within 5 % (worst seen 4.67 %). Does not cover non-exponential tails, modulation, or levels below -60 dB.
- **IACC** (3): measured tail L/R correlation within 0.05 of the *realised* correlation of the synthetic tail (random noise never has exactly the nominal value). Same estimator on the truth.
- **Taps**: five known taps are found within 0.2 ms and 0.05 pan, none invented; a dense tail with no taps must say "unresolved" and never pad. Does not cover overlapping taps closer than about 1.5 ms.
- **Direct matrix**: a known 1.0 / 0.1 matrix is recovered (read over 200 Hz-8 kHz, so a coloured direct path would read as a mean).
- **Linearity**: a linear system passes, a soft-clipped one is flagged (> 1 dB between a -18 and a -30 dBFS sweep). Does not cover slow time variation.
- **Pan transfer map**: an identity system returns the input pans.
- **Resynth smoke**: a formula re-rendered with 5 noise seeds stays within 15 % RT60 of its own numbers. Self-consistency only; it is not a comparison with real audio.
- **Suite identity / 7 ms delay / reverb through the suite** (8): the 12-block probe survives a suite -> split round trip to 1e-6, a 7 ms delay + gain is found to within 1 sample, and a known reverb through the lite suite -> split -> room gives RT60 within 5 %. A lite set must print "linearity: not run (lite set)".

## run_suite_tests.py (19 checks, 383 s): five-pass exports
- **split --repeats 5** on lite exports (44.1 kHz/16-bit normalised, irregular gaps; 24-bit/48 kHz; 32-bit float; 16-bit not normalised): all five passes located within 1 sample, level gain G recovered within 0.3 dB (worst 0.01 dB).
- **mixcurve** recovers the crossfade (tail level and DRR) within 1 dB (crossfade truth: same estimators, see above). The Mix 0 step must be a near identity with no tail.
- **Silent pass**: reported EMPTY and placed, the other four still correct; asking for more copies than exist aborts with a count; a Mix 0 pass that is not clean dry is warned about and not used for calibration.
- **Stage**: a known +6 dB side boost and tail correlation 0.2 give the expected correlation (within 0.05) and side/mid (within 1 dB) in the 250 Hz-4 kHz mean. Mid/side inputs' direct side/mid is clamped and leak-limited and is not compared.
- **analyze / analyze-all** on a full-probe 5-pass export (982 s): runs end to end, summary <= 120 lines, calibration within 0.3 dB, mixcurve within 1 dB, RT60 within 5 %, the room with an empty pass listed as failed. Run time and peak memory are reported, not limited.

## run_onecmd_tests.py (16 checks, 455 s): the one-command build
- **EDT convention**: exact exponential decay gives EDT = RT60 (within 0.5 %); a noise tail through the real chain gives a 7-band **mean** within 5 % (single bands are not: up to 18 % off, listed in the output).
- **Dry step n/a, noise floor, clip start**: the Mix 0 pass shows n/a for RT60/EDT/IACC and drops out of the mixcurve flags; the reported noise floor equals the file's own silent lead-in measured independently (within 3 dB; seen 0.1 dB); digital silence reads -140 dBFS; the summary says "clip start s".
- **CLI commands run for real** as subprocesses: `split`, `analyze` (with `--manifest` and `--probe`), `mixcurve <folders>`, `analyze-all`, and `run`.
- **run**: inbox with two files (one with a silent pass): expected files in `latest\`, EMPTY flagged, a re-run skips both, `--force` redoes both, a third file is the only one processed, the user's files are untouched. These tests use `--no-open`: **File Explorer opening is not tested.**

## run_trace_tests.py (13 checks, 382 s): the traced pipeline and single-pass rooms
- **Single-pass inbox**: two synthetic rooms x five Mix levels (100, 80, 60, 40, 20) + a dry file, once with the probe at its own level and once +15 dB (the "v2_loud" level), crossfade effect; tail level and DRR within 1 dB of the known crossfade, G within 0.3 dB of the true gain (0 and +15 dB), every file listed with role, peak, floor and matched-filter scores, the dry file is the Mix 0 step. Uses the lite probe (stage blocks are not exercised here).
- **Matched filter floor**: the probe at -100 ... -180 dBFS peak in 24-bit files with and without dither; the output lists how far down it is found. A file holding only +-1 LSB noise must give the "no probe found" line.
- **Duplicates**: two identical files, the second is flagged DUPLICATE and skipped.
- **Stop function**: a failing hop stops that file only (next room still processed, the failing file keeps its peaks and match scores in the summary); `--stop-on-fail` stops the batch.
- **Watchdog**: a hop that outlives its limit is a FAIL "stuck at hop X" and the process exits 3 with the trace printed (tested with a 1 s limit, not the real 10 minutes). **Ctrl+C trace printing is not tested.**
- **Trace log**: `trace_log.csv` gets a header and one row per hop; `trace.txt` and `trace.json` are saved.
- **ping**: all 14 self-test checks pass in under 2 minutes (clean file, two effect files, 16-bit 44.1 kHz file, channel lost, noise only).

## run_reset_test.py (6 checks, 104 s): reset.bat
- In a temporary folder: runs\ folders (including `latest`) archived, nothing deleted; `processed.json` archived and replaced by an empty one; inbox files byte-identical (SHA-256); `data\` intact; dependency versions printed; ping ran; console ends with READY.
- `--purge-archive 30` sends a dummy old archive folder to the **Recycle Bin** (checked by listing the bin; the dummy folder stays in the user's Recycle Bin afterwards).

## Not covered anywhere
- Real exports (clip placement, export dither, normalize behaviour, real Univerb latency/clipping, tails longer than 6 s, real Mix-knob behaviour).
- The full probe's stage blocks through the single-pass path (they run only in the 5-pass tests).
- `earnest.bat` / `reset.bat` double-clicked by a person, and what File Explorer does.
- Any estimator against an independent reference implementation; accuracy claims rest on the synthetic limits above.
