# Earnest equations and the missing room solve

## Purpose and status

**Snapshot note (November 2026):** The equations below document the analysis and first room engine, not a proof of physical or perceptual equivalence. The VM's experimental Advanced Mix adds a delayed stereo direct path and additive mid reinforcement: `M = (L + R) / 2`, `L' = g_master (g_wet W_L + g_dry D_L + g_center M)`, `R' = g_master (g_wet W_R + g_dry D_R + g_center M)`. The direct path is delayed by the configured 85 ms lookahead plus a 512-sample convolution block; the implementation applies a hard peak clamp. These controls are not vocal separation, a validated limiter, or a complete multichannel spatial model. See [lab status](LAB_STATUS.md).

This document records the equations and quantitative rules currently used by Earnest, then describes a physical-room model that connects those measurements to a reusable room solver. The first part describes the analysis implementation; threshold choices and metrics are identified as heuristics where they are not physical laws. The engine section reflects the first implemented backend, while its listed limits remain planned work.

Earnest currently analyzes a rendered effect path from dry and wet audio, estimates an impulse response (IR), and summarizes its direct sound, early peaks, decay, and stereo behavior. Its generated formula synthesizes an approximate statistical stereo tail. A room solve needs geometry, materials, source and receiver positions, propagation, and a spatial response. Those inputs are absent from the current formula schema.

## Notation

| Symbol | Meaning | Complexity it represents |
|---|---|---|
| `x_i(t)`, `y_o(t)` | input channel `i`, output channel `o` | Stereo or multichannel routing means every input can contribute differently to every output; summed channels can hide those differences. |
| `h_{o,i}(t)` | impulse response from input `i` to output `o` | Captures the whole path over time, including arrival, reflections, filtering, and decay. A single level number cannot replace it. |
| `b`, `f_c` | frequency band and its center frequency | Materials and air affect low and high frequencies differently, so the solver repeats much of its work by band and must join the bands into a usable response. |
| `V`, `S`, `S_j` | room volume, total surface area, surface `j` area | Dimensions determine both the overall decay estimate and the distances/timing of reflections; irregular geometry makes areas and visibility harder to compute. |
| `alpha_{j,b}`, `s_{j,b}` | surface absorption and scattering energy fractions in band `b` | Each surface removes some energy and redirects the rest. Values vary by material and frequency and are often uncertain or measured under different conditions. |
| `r_s`, `r_r`, `p` | source position, receiver position, and an image/reflection path | Moving either endpoint changes path lengths, directions, and which surfaces are hit; a solution for one seat does not automatically describe another. |
| `d_p`, `tau_p`, `g_{p,b}` | path length, arrival time, and pressure gain | Distance sets delay and level; each bounce adds frequency-dependent loss. Many paths can overlap, so their waveform phase can change the result. |
| `c` | speed of sound | Depends on environmental conditions; small errors shift predicted arrival times and low-frequency modal predictions. |
| `E(t)`, `EDC(t)` | instantaneous energy sequence and backward-integrated energy decay curve | The measured decay is contaminated by noise, finite recording length, and overlapping arrivals; estimating a stable slope requires careful filtering and fitting. |

Unless specified otherwise, Earnest uses SI-like seconds and Hz internally, a nominal sample rate of 48 kHz, and dB power ratios as `10 log10(power ratio)` versus amplitude ratios as `20 log10(amplitude ratio)`.

## Equations already in Earnest

### Shared signal and DSP equations (`earnest/dsp.py`)

- Amplitude level: `L_A(x) = 20 log10(max(|x|, epsilon))`; power level: `L_P(P) = 10 log10(max(P, epsilon))`, with `epsilon = 1e-12`.
- Octave band edges around `f_c`: `f_lo = f_c / 2^(1/(2q))`, `f_hi = f_c * 2^(1/(2q))`; current room analysis uses `q=1` (octave bands, 125 Hz through 8 kHz). Listening uses octave centers 31.5 Hz through 16 kHz.
- Smooth zero-phase FFT bandpass: `B(f)= [1+(f/f_hi)^(2n)]^-1/2 [1+(f_lo/f)^(2n)]^-1/2`, zero at DC. `n=6`; FFT is padded by 0.5 seconds and cropped after inverse transform. This is a numerical analysis filter, not a room propagation law.
- Fractional peak offset for samples around a local peak: `delta = 0.5*(y[-1]-y[+1])/(y[-1]-2y[0]+y[+1])`, clipped to `[-0.5,0.5]` samples.
- Constant-power pan mapping: `theta=(p+1)pi/4`, `g_L=cos(theta)`, `g_R=sin(theta)` for `p in [-1,1]`; inverse `p=4 atan2(|a_R|,|a_L|)/pi - 1`.
- Exponential sine sweep: `L=T/log(f_2/f_1)`, `x(t)=sin(2 pi f_1 L (exp(t/L)-1))`.
- Regularized deconvolution: `H(f)=X*(f)Y(f)/(|X(f)|^2 + epsilon_X)`, where `epsilon_X=10^-4 max_f |X(f)|^2`; `h=IFFT(H)`. Negative-lag samples are retained up to 2 seconds to estimate alignment. This assumes a sufficiently linear, time-invariant path and a usable excitation spectrum.
- Moving smoothing: `smooth(e,n)[k]` is the centered moving mean over `n` points.
- Decay estimation: estimate noise `N` as mean energy in the last 10% of the sequence, floor subtract `e_2=max(e-N,0)`, smooth over 5 ms, truncate when smoothed energy falls below `max(2N, 10^-9 peak)`, then `EDC[k]=sum_{u>=k}e_2[u]`. Normalize as `EDC_dB=10log10(EDC[k]/EDC[0])`. Fit a line over -5 to -25 dB for T20, -5 to -35 dB for T30, and 0 to -10 dB for EDT. For fitted slope `m` in dB/s, extrapolated `RT60=-60/m`. These are estimates from the observed IR, not guaranteed room reverberation times; noise-floor subtraction and fit range affect them.
- IACC-like stereo similarity: `max_{|tau|<=1ms} sum_t a(t)b(t+tau) / sqrt(sum a^2 sum b^2)`. The implementation takes the maximum absolute correlation across the permitted lags.
- True peak estimate: maximum absolute sample after 4x polyphase resampling.

### IR extraction and room/effect metrics (`earnest/room.py`)

- Stereo dry input mode: treat input as dual mono when `max|L-R| <= 10^-6 max|x|`; otherwise choose the louder dry input side by squared energy.
- For each dry input and wet output, estimate an IR with the deconvolution above. Combine transfer-column energy as `e_comb[k]=sqrt(sum_{i,o} h_{o,i}[k]^2)`; strongest sample `k_0=argmax e_comb` is the reference arrival. IRs are cut with 40 ms before that sample; reported latency is `k_0 - negative_lag_samples`.
- Early-peak detection searches 0.5–80 ms after the strongest arrival. Candidate amplitude must exceed both 2.08 times the local 20 ms median and neighboring material by 6 dB, and be within 40 dB of the direct peak. It retains up to 24 peaks. Peaks are only reported as resolved when at least 3 pass. This is a peak-separation heuristic; it cannot infer reflection surfaces, path lengths, or coordinates.
- Direct transfer matrix `M[o,i]`: signed square root of mean FFT-bin power from a ±0.25 ms arrival window over 200 Hz–8 kHz; sign comes from the largest-magnitude sample. This collapses frequency-dependent directivity and phase into one scalar per input/output pair.
- Per band, direct-window duration `dw=max(3 ms, 2.7/f_c)`. Direct energy is `E_dir=sum e` in the arrival window; after energy is `E_after=sum e` after it. Tail level is `10log10(E_after/E_dir)`.
- Tail onset: mask detected peaks by ±`dw`, smooth energy over 2 ms, find the first point within 15 dB of the smoothed tail peak (searching up to 0.4 s). Reported predelay is `dw + onset`; buildup is peak time minus onset. This is Earnest’s operational onset rule, not a standardized room parameter.
- Band RT values use the backward EDC procedure above starting after the estimated onset. The synthesis target uses EDT slope until -10 dB, then RT60 slope: `target_dB(t) = -60t/EDT` for `t<EDT/6`; afterward `-10 - 60(t-EDT/6)/RT60`.
- DRR: `10log10(E[-1ms,+2.5ms]/E[+2.5ms,end])`. C50 and C80 use energy through 50/80 ms from -1 ms relative to energy after that limit. These current metrics are broadband window ratios, not a geometry-derived direct/reverberant decomposition.
- Linearity/time-variation flag: compare octave-band total IR energy and EDC between -18 and -30 dBFS sweeps and/or a repeat; any deviation over 1 dB is flagged. This is a chosen tolerance, not proof of linearity when it passes.
- Pan map: estimate input/output pan using the constant-power law, direct energy in click windows, and tail energy in 80–500 ms windows; also report tail L/R correlation and side-to-mid level.
- Overall IR validity includes a decay contrast threshold of 30 dB between first 100 ms and final 20% plus absolute latency under 1 s. These are data-quality checks.

### Formula construction and synthesis (`earnest/formula.py`)

Earnest’s current model is a measured direct matrix plus discrete tap delays and a statistical tail:

`y_o(t) = sum_i [ M[o,i] x_i(t) + sum_{k:source(k)=i} a_k x_i(t-tau_k) g_o(p_k) + (h_tail,i * x_i)_o(t) ]`.

- Each tap has measured delay, relative gain, input side, and output pan. Synthesis uses `a_k = ref * 10^(gain_dB/20)` and linearly distributes fractional-sample delay over adjacent samples. `g_o(p_k)` is the constant-power pan gain.
- For each band, tail channels are generated from independent Gaussian sequences: `n_L=w_1`, `n_R=rho w_1 + sqrt(1-rho^2) w_2`. Earnest clips `rho` to `[0,0.999]`, so this model cannot synthesize negative channel correlation.
- The random noise is octave-band filtered, then multiplied by the target decay envelope and a predelay/buildup ramp. Its total energy is scaled so the energy after the direct window meets `E_target_after = E_dir * 10^(level_dB/10)`, after subtracting energy already present from direct/tap filtering. This matches aggregate band level, not a spatially sampled field.
- IR duration is `min(1.25*max(RT60)+0.6 s, 8 s)`; render convolves input with synthesized IR but truncates output to input length, so the final decay after the source ends is omitted from rendered output.
- `build()` stores DRR/C50/C80 in `formula["room"]`, but `synth_ir()` does not use those values. The current generated sound is therefore not constrained to match these three reported metrics.

### Listening, width, and probe support

These equations characterize rendered audio or make measurement files; they do not solve a physical room.

- `listen.py`: RMS, peak, 4x true peak, integrated/short-term LUFS via `pyloudnorm`; Pearson L/R correlation; mid/side `M=(L+R)/2`, `S=(L-R)/2`, level difference `10log10(E_M/E_S)`; per-band ILD `20log10(RMS_L/RMS_R)`, band coherence and correlation. Panogram computes `psi=2|Z_L Z_R*|/(|Z_L|^2+|Z_R|^2)` and `index=(1-psi)*sign(P_R-P_L)`, with energy-weighted bins. Width series is `E_S/(E_M+E_S)`. Transient score is 5 ms RMS level relative to preceding 50 ms median; reverberance proxy is mean power 150–400 ms after onset relative to the initial 30 ms.
- `stage.py`: pooled L/R correlation `sum(LR)/sqrt(sum(L^2)sum(R^2))`, side/mid ratio `10log10(E_S/E_M)` clamped ±60 dB, and width gain as wet side/mid dB minus input side/mid dB. Tail window is 0.5–5 s after bursts, clipped before next burst. This tests a plugin’s stereo response to three noise input correlations.
- `mixcurve.py`: averages 250 Hz–4 kHz metrics across bands; a metric is flagged when movement is at least 1 dB or greater than 10% of its mean (depending on metric path); tails below -40 dB relative to direct are treated as absent for selected summaries.
- `probe.py`: matched filtering/correlation locates probe copies. Noise scale estimate is `sigma=median(|correlation away from peak|)/0.6745`; threshold is `sigma*sqrt(2 ln(N_lags))*1.25`; probe amplitude estimate is peak correlation divided by sweep energy. These detect exported probe signals and are not room physics.
- `suite.py`: calibration gain over 200 Hz–8 kHz is `G=sqrt(sum|Y|^2/sum|X|^2)` for the dry Mix 0 pass. Additional click correlation and tail checks decide whether to apply it. This is export-level calibration.

## The missing physical-room model (proposed)

The appropriate output is a source-to-receiver, frequency-dependent impulse response, not just an RT60 or a stereo tail. For a room with source positions `r_s`, receiver positions/orientations `r_r`, and bands `b`, the solver should produce `h_{r,s,b}(t)` (or a full-band IR assembled from bands). A sound system or plugin can then consume the same room solution through adapters.

### 1. Room geometry and material energy bookkeeping

For surface `j` with area `S_j`, absorption coefficient `alpha_{j,b}` and scattering fraction `s_{j,b}`:

`A_b = sum_j S_j alpha_{j,b}` (equivalent absorption area), `S=sum_j S_j`, and `alpha_bar_b=A_b/S`.

Require `0<=alpha<=1`, `0<=s<=1`. Of incident energy, absorption is `alpha`; reflected energy is `(1-alpha)`; its specular and diffuse portions are respectively `(1-alpha)(1-s)` and `(1-alpha)s`. At each interaction these fractions must sum to `alpha+(1-alpha)(1-s)+(1-alpha)s=1`. That conservation check prevents a solver from accidentally creating energy.

As broad decay sanity checks, use Sabine `T60_b ~= 0.161 V/A_b` seconds (SI) in the diffuse-field/low-absorption regime, and Eyring `T60_b ~= 0.161 V / [-S ln(1-alpha_bar_b)]` as an alternative for more uniform absorption. These are global statistical estimates; neither determines where reflections occur or where energy is concentrated. When enabled, ISO 9613-1 atmospheric attenuation affects explicit image paths and enters both statistical decay estimates through the `4mV` air-absorption area; details and units are below.

### 2. Propagation paths and early response

For a source-to-receiver path `p`, including direct and reflected/image paths:

`tau_p = d_p/c`.

A proposed band pressure gain is:

`g_{p,b} = D_s(p,b) D_r(p,b) / max(d_p,d_min) * product_j sqrt((1-alpha_{j,b}) * q_{j,p,b}) * exp(-m_b d_p)`

where `D_s,D_r` are source/receiver directivity, `q=1-s` for the specular share and `q=s` for a diffuse-scattering branch, and `m_b` is an optional atmospheric pressure attenuation coefficient. The square root converts the surface energy-retention fraction to pressure amplitude. `d_min` is a numerical/source-size regularizer; it must be explicit because the point-source `1/d` law is singular at zero distance. Calibration can provide the chosen reference-distance constant.

For early specular paths, sum pressure waveforms with their delays and polarity/phase: `h_early(r_r,r_s,t)=sum_p g_p delta(t-tau_p)` in the simplified band model. A real implementation needs fractional-delay filters and frequency-dependent gains. A shoebox image-source solver is a suitable first geometry backend; polygon visibility and diffraction need later work. An energy-only ray/radiosity pass can model the diffuse branches, but must not be mistaken for coherent phase prediction.

### 3. Reflection density and transition to a late field

Define measurable solver diagnostics in windows of width `Delta t`:

`rho_N(t,b)=N_b([t,t+Delta t]) / Delta t`, and `rho_E(t,b)=sum_{p in window}|g_{p,b}|^2 / Delta t`.

These count and energy densities are proposed implementation metrics, not standard room-acoustic quantities. They give a practical transition rule: retain discrete paths while arrivals are sparse and individually meaningful; transition to a diffuse late-field representation when path density is high enough that individual arrivals are no longer resolved at the selected sample rate/bandwidth. Choose threshold via comparison against measured IRs and make it an explicit solver setting.

For late decay, use measured Earnest band targets when a compatible measured IR exists; otherwise initialize the target from Sabine/Eyring and surface properties. A stochastic or feedback-delay-network late tail should match band EDC, total energy, buildup, and inter-channel correlation. The transition must preserve energy: the late-field energy begins from the energy remaining after the explicit early paths, rather than adding a second full tail on top.

### 4. Spatial noise field and spatial density

For mutually uncorrelated noise sources with power spectra `S_{x_i}(f)`, pressure spectrum at receiver `r` is:

`S_p(r,f)=sum_i |H_{r,i}(f)|^2 S_{x_i}(f)`.

With `S_x[i,j]=E[X_i conj(X_j)]` and a row transfer vector `h_r`, correlated inputs give `S_p(r,f)=h_r S_x(f) h_r^H`. This is the core distinction between a room impulse response and “how noise exists in that room”: the room gives transfer functions; source count, spectra, positions, levels, and correlations determine the resulting sound field.

Spatial sampling can report energy per cell `D_b(cell)=sum_i integral_{cell} |p_{i,b}(r)|^2 dr`, normalized by cell volume for volumetric density. A directional spread metric can be entropy `H_b=-sum_k q_{k,b} ln(q_{k,b})`, with `q_k` the fraction of reflected energy arriving from direction bin `k`. These are proposed outputs; specify grid spacing and angular bins in the result so values are reproducible. With many incoherent sources, add their powers; with coherent sources, retain cross terms through `S_x`.

### 5. Low-frequency behavior

For an ideal rectangular room with rigid boundaries, modal frequencies are:

`f_(n_x,n_y,n_z)=(c/2)*sqrt((n_x/L_x)^2+(n_y/L_y)^2+(n_z/L_z)^2)`

where each integer index is nonnegative and not all are zero. Modes indicate resonant frequencies; source/receiver coordinates determine coupling and nodes. This ideal formula omits compliant boundaries and losses. The first solver should expose modal frequencies as diagnostics or use a validated low-frequency backend; broad octave-band noise synthesis alone cannot reproduce modal build-up, phase, or position-dependent nulls.

### 6. Calibration and identifiability

Fit unknown absorption/scattering/material parameters `theta` against several source-receiver measurements, not RT60 alone. A proposed objective is:

`theta* = argmin_theta [sum_{r,s,b,t} w_{r,s,b,t} (EDC_sim(theta)-EDC_meas)^2 + lambda ||theta-theta_prior||^2]`

Bounds enforce physical coefficients; priors hold imported material estimates near plausible values. Add direct-arrival time, early reflection delay/level, band energy, and spatial metrics as observations where available. One RT value constrains total absorption approximately but cannot uniquely identify which wall absorbs energy; geometry, repeated positions, and material priors are needed. Uncertainty should be returned with fitted parameters instead of presenting one underdetermined fit as uniquely measured truth.

## Custom rooms and imports

### Hand-built room (first import path)

Start with a user-editable rectangular room: length, width, height; units; named surfaces; banded absorption and scattering; source locations/directivity; receiver/listening positions/orientations. Allow one material preset to assign coefficients to surfaces, with per-surface overrides. Validate dimensions positive, coordinates inside bounds, coefficients in `[0,1]`, and band coverage. Provide a visual plan view and cross-section for editing and review.

### Versioned `room.json` contract

```json
{
  "schema": "earnest.room.v1",
  "units": "m",
  "geometry": {"type": "shoebox", "dimensions": [8.0, 5.0, 2.8]},
  "materials": [{
    "id": "painted_plaster",
    "bands_hz": [125, 250, 500, 1000, 2000, 4000, 8000],
    "absorption": [0.08, 0.07, 0.06, 0.05, 0.04, 0.04, 0.04],
    "scattering": [0.05, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18],
    "source": "user estimate",
    "uncertainty": 0.15
  }],
  "surfaces": {
    "x_min": {"material_id": "painted_plaster"},
    "x_max": {"material_id": "painted_plaster"},
    "y_min": {"material_id": "painted_plaster"},
    "y_max": {"material_id": "painted_plaster"},
    "z_min": {"material_id": "painted_plaster"},
    "z_max": {"material_id": "painted_plaster"}
  },
  "sources": [{"id": "speaker_a", "position": [2.0, 2.5, 1.4], "level_db": [0, 0, 0, 0, 0, 0, 0]}],
  "receivers": [{"id": "seat_1", "position": [5.5, 2.5, 1.2]}],
  "environment": {"temperature_c": 20.0, "humidity_percent": 50.0},
  "measurements": []
}
```

The `earnest.room.v1` rectangular schema is now accepted by the engine and can be generated with `earnest room-template room.json`. All six faces need a material assignment. The present solver uses source `level_db` by band and supports ideal source/receiver directivity and orientations on explicit paths; its statistical tail remains nondirectional. A geometry import such as OBJ/glTF remains future work and needs an acoustic sidecar assigning surface materials and units; mesh geometry by itself contains no reliable absorption/scattering data. Measured WAV IR import should capture sample rate, channel mapping, calibration, source/receiver coordinates, and measurement provenance. One measured IR constrains that pair and placement; it cannot reconstruct an entire room.

### Engine master controls and analysis-seeded rooms

Room JSON may include `engine_controls`: `reflection_order` selects the maximum image-source bounce order; `decay_model` chooses Sabine or Eyring for the statistical tail's RT60; seven `absorption_scale` and `scattering_scale` values tune the current surface coefficients per octave band; `diffuse_energy_scale` controls the diffuse-field energy estimate; and `tail_duration_scale` controls the rendered stochastic tail duration. The scales are exposed as experimental/calibration controls, not as claims that room materials have changed. Solver defaults remain equivalent when the section is absent.

`room-fit <room.json> <formula.json>` takes an Earnest measured reverb formula (made from a dry source and its wet/plugin render) and solves a per-band absorption multiplier using the room's selected Sabine or Eyring equation. It writes a separate room file, preserves the measurement evidence and plugin metadata, and records predicted versus measured RT60. A response-character hint is heuristic; it does not identify a plate, spring, or hall algorithm from decay alone. Dry/wet alignment and useful decay range still determine measurement quality. Direct measurements constrain decay and early reflection behavior at the measured source/receiver path; geometry, wall-by-wall absorption, scattering, and source directivity remain ambiguous without more positions, priors, or metadata.

For third-party analysis output, `room-fit` also accepts this vendor-neutral measurement shape. Unknown fields can be retained in `plugin_metadata`; `reverb_type` is an imported label, not a classification Earnest inferred:

```json
{
  "schema": "earnest.measurement.v1",
  "source": "Plugin preset analysis export",
  "reverb_type": "plate",
  "plugin_metadata": {"name": "Example Reverb", "preset": "Vocal Plate"},
  "bands": [
    {"hz": 125, "rt60_s": 1.8, "edt_s": 0.7, "tail_level_db": -12, "pre_delay_ms": 18, "iacc": 0.2, "modulation": null},
    {"hz": 250, "rt60_s": 1.6}, {"hz": 500, "rt60_s": 1.4},
    {"hz": 1000, "rt60_s": 1.2}, {"hz": 2000, "rt60_s": 1.0},
    {"hz": 4000, "rt60_s": 0.8}, {"hz": 8000, "rt60_s": 0.6}
  ],
  "early_taps": {"taps": []}
}
```

For sample audio, the current trustworthy path is a matched dry source and wet render: analyze them with `earnest room <dry> <wet>`, then feed its `formula.json` to `room-fit`. A wet-only sample may support broad descriptive clues, but without a dry reference Earnest cannot separate the input from the effect response reliably.

`room-preview <room.json> --play` renders a repeatable broadband burst through the configured model and plays the receiver output using the Windows default endpoint. The offline preview is a listening aid for the current octave-band approximation, not a real-time audio callback or a device-selectable playback engine.

### Current engine boundary

The CLI calls `earnest.engine.RoomSpec` for validation and `solve_room()` for computation. The engine separates room/material input (`engine/room.py`), rectangular image paths (`engine/shoebox.py`), solve orchestration/results (`engine/solve.py`), and audio driving (`engine/render.py`). `room-solve` writes per-band WAV IRs and a `solution.json` manifest. `simulate` solves a room, convolves each input source through its source-to-receiver responses, writes the resulting audio with its decay tail, and saves output level/band analysis. The current renderer sums specular path impulses and a statistical diffuse late tail, returning seven band responses independently. It normalizes each source/receiver pair to its direct path, uses temperature for a dry-air sound-speed approximation, and reports Sabine/Eyring checks, ideal modal frequencies, and per-receiver power sums for independent sources. The diffuse tail's integrated energy uses the diffuse-field estimate `R/D ~= 16 pi r^2/(A + 4mV)` when air is enabled and the Eyring decay where available; its noise samples do not claim directional ray simulation.

Scattering reduces the specular share in the current path model, while a global energy estimate fills a statistical late tail. This does not predict directional redistribution of scattered energy. The engine also does not yet fit measured IRs, render low-frequency modal pressure responses, combine bands into phase-aligned full-band IRs, include correlated-source cross terms in its default receiver summary, or compute arbitrary spatial grids. A separate explicit-path soundfield component now evaluates supplied correlated source spectra; it does not include the statistical tail.

### Proposed solver sequence

1. (Implemented for shoebox rooms) Establish units, geometry, temperature-based sound speed, source/receiver positions, and material bands; reject incomplete or invalid input.
2. (Implemented) Compute room volume/surface area and Sabine/Eyring estimates as sanity checks.
3. (Implemented) Solve direct and specular paths with a shoebox image-source method and frequency-dependent surface losses.
4. (Partial) Fill remaining reverberant energy with a statistical diffuse tail; directional scattering and a calibrated path-density transition remain future work.
5. (Partial) Propagate supplied cross-spectra through transfer matrices or modeled explicit paths. Spatial grids, statistical late-field coherence, and calibrated absolute levels remain open.
6. If measurements exist, align/deconvolve using Earnest’s current IR workflow, fit parameters across positions/bands, and report uncertainty and residuals.
7. (Partial) Export a versioned room solution with source-to-receiver band IRs and drive source audio through those responses. A phase-aligned full-band solution and adapter format for other tools remain future work.

## What this means for Earnest’s current math

Earnest already has a useful measurement layer: deconvolution, direct/tail separation, band decay, stereo correlation, early peak detection, and a formula synthesizer. The missing link is not a single “room equation.” It is the mapping from geometry and surface properties to paths and frequency-dependent transfer functions, followed by source-weighted spatial evaluation. Existing `room` metrics are useful calibration targets, but DRR/C50/C80 are presently not enforced by synthesis. Early peak delays/gains are measured without geometric causes, and the stochastic tail has no position-dependent density or modal structure.

## Research references

- J. B. Allen and D. A. Berkley, “Image method for efficiently simulating small-room acoustics,” *Journal of the Acoustical Society of America* (1979): [paper PDF](https://jontalle.web.engr.illinois.edu/Public/AllenBerkley79.pdf). Basis for image-source room impulse responses in rectangular rooms.
- P. Koutsouris et al., “A combined acoustical radiosity and image-source model for room impulse response prediction,” *JASA* (2013): [PubMed record](https://pubmed.ncbi.nlm.nih.gov/23742350/). Supports combining specular image paths and diffuse energy transport for absorption/scattering and more general geometries.
- F. Wittebol et al., “A hybrid wave and geometrical acoustics model for room impulse response simulation,” *Applied Acoustics* (2024): [paper page](https://www.sciencedirect.com/science/article/pii/S0003682X24002196). Supports a future low-frequency wave / higher-frequency geometric hybrid rather than expecting octave-noise synthesis to model all regimes.
- A. Lehmann and A. Johansson, “Prediction of energy decay in room impulse responses simulated with an image-source model,” *JASA* (2008): [PubMed record](https://pubmed.ncbi.nlm.nih.gov/18646975/). Relevant to decay prediction with nonuniform absorption.
- H. Hanyu, “A theoretical framework for quantitatively characterizing the sound field diffusion in architectural spaces,” *JASA* (2010): [PubMed record](https://pubmed.ncbi.nlm.nih.gov/20815450/). Relevant to scattering, absorption, and diffusion characterization.
- L. Visentin et al., “An experimental comparison of the performance of sound field diffusion models,” *JASA* (2012): [PubMed record](https://pubmed.ncbi.nlm.nih.gov/23145602/). Useful caution that diffusion approximations depend on room conditions.
- “Sabine and Eyring revisited: Effect of room acoustics on measured absorption coefficients,” *JASA* (2022): [PubMed record](https://pubmed.ncbi.nlm.nih.gov/36050177/). Supports treating uncertain material coefficients and air absorption as calibration concerns rather than exact known inputs.



## Implemented correlated-source spectral propagation (November 2026)

For each frequency, define the source CSD matrix `Sx_ij = E[X_i conj(X_j)]` and
the transfer matrix `H[r,i]`. The receiver CSD is `Sy = H Sx H^H` and receiver
power spectral values are `Re Sy[r,r]`. Inputs must be Hermitian and positive
semidefinite; values use `[real, imaginary]` pairs. Note that SciPy `csd(x,y)`
uses `conj(X) Y`, the transposed convention for off-diagonal entries. See
[SciPy CSD documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.csd.html)
and the [University of Southampton acoustic cross-spectral matrix formulation](https://resource.isvr.soton.ac.uk/staff/pubs/PubPDFs/Pub1007.pdf).

`soundfield.propagate` consumes explicit transfer matrices, while
`soundfield.from_room_paths` forms `H[r,i](f) = sum_p g_p,b exp(-j 2 pi f tau_p)`
from the room solution's explicit image paths, using the nearest octave center
for `g_p,b`. Source levels are supplied in the source CSD, so the source
`level_db` metadata must not also be assumed to have been applied. Unlike the
room render's per-pair direct normalization, these path gains use `1/d` without
a calibrated source factor; neither predicts absolute SPL without calibration.
The statistical late tail is not included, and there is no frequency integration
or arbitrary spatial grid. The default room-solve receiver summary still assumes
independent sources.

Example: `earnest room-solve room.json --out solve` followed by
`earnest soundfield-spectrum examples/soundfield/independent-stereo.json --room-solution solve/solution.json --out field.json`
when the room has `speaker_left` and `speaker_right` source IDs.


## Air absorption in statistical room decay (November 2026)

For ISO 9613-1 attenuation `alpha_air` in dB/m, the intensity decay coefficient
`m = alpha_air ln(10)/10` in m^-1, and effective diffuse absorption area is
`A_air = 4mV`. With `K = 24 ln(10)/c`, the updated estimates are
`T_S = K V/(A + 4mV)` and `T_E = K V/(-S ln(1-A/S) + 4mV)`.
The fitting routine uses the same denominator, including boundary cases where
a target is unattainable. The diffuse-tail energy estimate uses `A + 4mV` as
an approximation. Air loss is optional and defaults to disabled for existing
rooms. An air-only room can have finite estimated decay even when all surface
absorption is zero; no finite decay is reported when both loss mechanisms vanish.
See [AFMG EASE, room acoustics calculation](https://www.afmg.eu/sites/default/files/2025-12/EASE_5-TE_UsersGuide.pdf)
for the formula and coefficient convention. The estimates assume a diffuse field;
they do not predict individual late paths or calibrated SPL.


## Modeled energy-time diagnostics (November 2026)

For each modeled band IR, the known direct arrival identifies the first sample
`n0=floor(t_direct * fs)` of the fractional direct impulse. Define
`e[n]=h[n]^2`, `E_early(T)=sum e[n]` for samples `n0 <= n < n0+ceil(T fs)`,
and `E_late(T)=sum e[n]` for the remaining finite response. The solver reports
`C50=10 log10(E_early(.05)/E_late(.05))`, `C80` with `.08`,
`D50=E_early(.05)/(E_early(.05)+E_late(.05))`, and
`Ts=sum((n-n0)e[n])/(fs sum(e[n]))`. A zero total or zero early/late term
makes the corresponding ratio undefined; it is serialized as `null` and the
energy terms are retained.

These are finite-window predictions from the current separately modeled band
IRs. Their onset is known from the simulated path and rounded to a sample;
they have no measured noise-floor correction, and they are not claims of
ISO-compliant measurements. The solver may truncate long tails at eight seconds.
See [Acoustical Society of America on C80](https://acoustics.org/pressroom/httpdocs/154th/paek.html)
and [phonometry's room-acoustics implementation and equations](https://docs.jmrp.io/phonometry/reference/theory/rooms-buildings/).
