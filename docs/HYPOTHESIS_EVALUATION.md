# Hypothesis evaluation and ranking

Earnest can evaluate candidate stems and optional note events from Demucs, Basic Pitch, another backend, or supplied files. These are offline measurements. The components are `audio.hypothesis_evaluate` and `audio.hypothesis_rank`; the commands are `hypothesis-evaluate` and `hypothesis-rank`.

## Use

First produce aligned stems and optionally a Basic Pitch CSV, then run:

```powershell
earnest hypothesis-evaluate mix.wav --stem vocals.wav --stem drums.wav --stem bass.wav --stem other.wav --notes notes.csv --out runs/candidate-1
earnest hypothesis-evaluate mix.wav --stem alternate.wav --notes alternate-notes.csv --out runs/candidate-2
earnest hypothesis-rank runs/candidate-1/evaluation.json runs/candidate-2/evaluation.json --weight-reconstruction 1 --weight-spectral 1 --out runs/ranking.json
```

Each evaluation writes `evaluation.json` and a floating-point `residual.wav` into a new directory. The report contains paths and SHA-256 hashes of the inputs and normalized note events. Notes may be a Basic Pitch note-event CSV, or a JSON object with `schema` equal to `earnest.note-events.v1` and an `events` array. Each event has `start_s`, `end_s`, and `midi_pitch`; velocity is optional. Pitch bends are not interpreted. The optional model runtimes are still separate; these commands consume their outputs and do not train them.

All audio must already have exactly the same sample rate, sample count, channel count and alignment. There is no implicit resampling, channel mapping, delay correction, or gain fitting. Model outputs can require explicit preprocessing; keep track of those transformations and retain the original. Checksums identify inputs but do not establish their correctness.

## Measurements

For reference x and aligned candidate stems s_i, the residual is r = x - sum_i(s_i). Mean squared error is the mean of r squared over samples and channels. Relative error power is sum(r squared) / sum(x squared), or null for a silent reference. A small error measures reconstruction consistency, not whether individual stems have the right identity.

When notes are supplied, complete Hann-window frames are measured using the existing frequency tracer. An event is active if its start <= window center < its end. Its ideal partials are f_h = 440 * 2^((p-69)/12) * h, for MIDI pitch p and harmonic numbers from 1 through the configured maximum, excluding frequencies at or above Nyquist. A detected peak matches when its distance to a predicted partial is at most the chosen tolerance in cents: 1200 * abs(log2(f_peak/f_h)). The unexplained peak fraction is 1 minus the sum of matched peak amplitude squares divided by the sum of all detected peak amplitude squares. This is a **peak-power proxy**, not a fraction of total signal energy. Silence and insufficient complete windows produce null. Windowing, peak thresholds, overlap, inharmonic sources, bends, percussion, room reflections and the use of ideal harmonics limit interpretation. These peaks are measured on the reference mix, not attributed to individual stems.

The ranking command requires explicit nonnegative weights; no default weights are asserted. Its score is the negative weighted sum of selected terms: relative reconstruction error, unexplained peak fraction, and note-event count per second. The complexity term is a user-selected preference, not evidence that a dense arrangement is wrong. Reports must use the same reference hash and format; spectral settings must also match when spectral weighting is used. Missing or undefined weighted measurements are rejected. The ranking is not a probability or a ground-truth accuracy score. Temporal mismatch is reserved but not implemented.

## Real backend smoke check, 2026-11-03

The locally generated A440 example was previously processed by Demucs and Basic Pitch. For this check, the 16 kHz mono reference was explicitly polyphase-resampled to 44.1 kHz and duplicated to stereo to match the four existing Demucs stems; no delay correction or gain fitting was applied. The evaluator consumed those stems and the Basic Pitch CSV. It reported one event, relative reconstruction error power about 0.00002185 and unexplained detected peak proxy fraction 0.0. Artifacts are local under `runs/hypothesis-model-check` and are not committed. This is an integration smoke check on one synthetic tone, not a validation on real music, isolated sources, or room responses.

## Next work

Per-stem trace and reference scoring, explicit timing/envelope mismatch, calibrated evaluation using held-out labeled multitracks, room-model fitting against measured references, proposed revisions and an agent-driven iteration policy remain to be built. Estimating a room or source from one mix is not guaranteed to yield a unique solution. Never treat a residual by itself as an isolated reverb or an instrument.
