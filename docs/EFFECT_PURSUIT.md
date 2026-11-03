# Residual-driven effect pursuit

This first offline pursuit component tests a single family: integer-sample delayed, scaled copies of a known dry signal. The physics and effect models supply candidate predictions; the pursuit measures each candidate against the residual and saves evidence for the next step. The current implementation does not yet have a general multi-family registry or automatic agent controller.

```powershell
earnest effect-pursuit processed.wav --dry dry.wav --max-delay-samples 48000 --max-layers 8 --out runs/effect-investigation
```

Input recordings must be sample-aligned and have identical sample rate, frame count and channel count. No automatic resampling, time alignment or gain normalization is applied. Output is a new directory containing `pursuit.json`, `prediction.wav` and `residual.wav`. The report includes input hashes, options, each chosen delay and gain, energy reduction, final comparison with band energies, and an empty conditioning record. WAV outputs use floating-point samples.

## Implemented math

Let observed y and dry x have N frames. Start r = y. For each permitted delay d, form zero-padded candidate x_d[t,c] = x[t-d,c] when t >= d, otherwise 0. The shared least-squares gain is a_d = <r,x_d> / <x_d,x_d>, summing over time and channels. Its unpenalized energy reduction is delta_d = <r,x_d>^2 / <x_d,x_d>. Select the d with greatest delta, and accept only when delta / ||y||^2 exceeds both `min_improvement` and `layer_penalty`. Then r <- r - a_d x_d, record the result, and repeat up to `max_layers`. Zero-energy dry candidates are excluded. The prediction is y-r; Earnest's existing sample and frequency-band comparison measures the final residual against y. The penalty is a constant cost for adding one layer, measured relative to original observed energy; it is not a learned prior. No structure term is implemented.

Each iteration is a greedy projection. Delays can recur because earlier coefficients are not jointly optimized. A selection order is an optimization history, not proof of the original effects chain. Correlated sources and repeated signal patterns can lead to plausible but wrong candidates. A scalar gain is shared across channels and fractional delays, filters, room decay, nonlinearities and changing effects are not modeled. Thresholds do not guarantee generalization; held-out recordings are needed. No distortion cleaning is applied: filtering or attenuation cannot recover information lost to clipping, and any future conditioning must be recorded and compared against the untouched original.

## Validation and next stages

Tests construct mixes with known source tracks and an added delay, vary the first source's level, and compare the predicted track and residual to known components. An overlapping random-signal case measures leakage and verifies prediction plus residual equals the original. These are controlled mathematical tests, not real-instrument or perceptual validation. Further stages need measured dry/wet instrument recordings, independent held-out passages, more physically grounded competing effect families, candidate-specific scoring, joint refitting and explicit reporting of non-identifiability.

## Dry and known-reference checks

Every report compares the prediction with the supplied dry source as `prediction_vs_dry`. This shows the total difference, including modeled gain and echoes; it is not a separation error metric. When a known processed source is available, pass `--target known-source.wav`; for the known rest of the mixture, pass `--remainder-reference known-remainder.wav`. Their separately hashed files are compared with the prediction and residual under `validation.target` and `validation.remainder`. The comparison against the full observed mix is always retained. The dry reference itself is authoritative only if it is the correct, aligned source capture; none of these comparisons certifies its identity.
