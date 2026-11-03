# Physics foundation and implementation notes

This is a research foundation, not a claim that every instrument or room is physically solved. Recorded instruments, voices, microphones, nonlinear effects, source positions, materials and a room's geometry cannot in general be uniquely recovered from a stereo mix. Each model below states what it computes and what it leaves out.

## Comparison to other room engines

[Pyroomacoustics' room simulation documentation](https://pyroomacoustics.readthedocs.io/en/stable/pyroomacoustics.room.html) describes an image-source model and an experimental hybrid image-source/ray-tracing simulator; its [changelog](https://pyroomacoustics.readthedocs.io/en/stable/changelog.html) describes wall scattering through ray tracing. Earnest currently models rectangular rooms with explicit image paths and a statistical diffuse late tail. It does not trace rays through arbitrary room meshes. This suggests a future matched-scene comparison of arrival times, band decay and computation cost, with measured responses as an external reference. Differences alone would not establish which tool is correct; both have assumptions and approximation limits.

## Air attenuation on explicit paths

`earnest.engine.physics.air_absorption_db_per_m` implements the ISO 9613-1 pure-tone atmospheric absorption model using temperature, relative humidity and pressure. Let `T` be kelvins, `T0 = 293.15 K`, `p0 = 101325 Pa`, `r = p/p0`, and `h` the water-vapour molar concentration in percent. The implementation computes saturation pressure using the ISO/ECMA expression, then oxygen and nitrogen relaxation frequencies `fO`, `fN`. The coefficient is

```
alpha_db_m = 8.686 f^2 [ 1.84e-11 r^-1 (T/T0)^0.5
  + (T/T0)^-2.5 (0.01275 exp(-2239.1/T)/(fO + f^2/fO)
                  + 0.1068 exp(-3352/T)/(fN + f^2/fN)) ]
pressure_gain = 10^(-alpha_db_m * distance_m / 20)
```

Sources: [ISO 9613-1:1993, sections 5–7](https://cdn.standards.iteh.ai/samples/iso/iso-9613-1-1993/505cecd76313448e9e6e456f1dd6d471/iso-9613-1-1993.pdf); [Ecma-108 Annex A](https://www.ecma-international.org/wp-content/uploads/ECMA-108_5th_edition_december_2010.pdf); [NPL reference values](https://resource.npl.co.uk/acoustics/techguides/absorption/validata.html). The latter can be used for independent numerical verification.

Enable it per room with `environment.air_absorption_enabled: true`, alongside `temperature_c`, `humidity_percent`, and `pressure_pa`. Existing documents default to disabled, preserving their previous output. Temperature is restricted to -20 to 50 °C when enabled; relative humidity 0–100%; pressure 10–200 kPa. Those input bounds do not imply uniform accuracy: the standard's stated uncertainty varies with frequency, pressure, temperature and molar concentration. Humidity is relative to saturation over liquid water.

Air attenuation multiplies each explicit image-source pressure path at the octave center. The current solver normalizes each pair to the corresponding omnidirectional direct path; therefore the direct-path air loss is normalized out and reflections retain relative loss compared with that path. The Sabine/Eyring decay estimates and the diffuse-energy approximation also include air absorption through the equivalent area `4mV` described below. Sound speed remains the existing dry-air temperature approximation. Octave-center treatment does not integrate a broadband source spectrum.

## Directional sources and receivers

Each source and receiver may specify `directivity` as `omni`, `cardioid`, or `figure8`, and a nonzero 3-D `orientation` vector in room coordinates. Defaults are omnidirectional. For the angle between the forward axis and the path direction, the signed pressure factors are `1`, `(1 + cos(theta))/2`, and `cos(theta)` respectively. Figure-eight rear response reverses polarity. The image-source solver folds the source ray back into the physical room; the receiver axis points toward the incoming path. Explicit path amplitudes and the direct/render mix use these factors. Pair normalization uses the corresponding omnidirectional direct path, so a null or negative direct path is preserved rather than divided out.

These are ideal, frequency-independent first-order polar patterns, not measured instrument or microphone responses. The statistical late-field approximation is not directional and ignores how source/receiver directivity changes diffuse energy. The current model also does not implement source obstruction, near-field radiation or complex reflection phase. See [University of Michigan recording acoustics, chapter 7](https://public.websites.umich.edu/~mejn/tsom/chapters/chapter7.pdf).

## Ideal instrument resonators

The component `instrument.modes` accepts a versioned `instrument.model` artifact and emits `earnest.instrument-modes.v1`; the CLI exposes `instrument-modes <model.json>`. The shipped [example](../examples/instruments/ideal-guitar-string.json) is illustrative, not a measured instrument.

- Ideal string fixed at both ends: `f_n = n/(2L) sqrt(T/mu)`, where length `L` is meters, tension `T` newtons, and linear density `mu` kg/m.
- Ideal tube open at both ends: `f_n = n c/(2 L_eff)`.
- Ideal tube open at one end and closed at the other: `f_n = (2n-1)c/(4 L_eff)`.
- Pinned stiff string: `f_n = n/(2L) sqrt(T/mu) sqrt(1 + B n^2)` with dimensionless inharmonicity `B >= 0`. The flexible-string base frequency is not the actual first partial when `B > 0`. This is a pinned-boundary approximation, not a general string model. See [Penn State's stiff-string discussion](https://www.acs.psu.edu/drussell/Demos/Stiffness-Inharmonicity/Stiffness-B.html).
- Fixed-edge circular membrane: `f_mn = j_mn/(2 pi a) sqrt(T_s/mu_s)`, where `j_mn` is the nth positive zero of Bessel function `J_m`, radius `a` is in meters, membrane tension `T_s` N/m, and surface density `mu_s` kg/m². Positive angular orders have two orientation-degenerate modes, reported once. See [University of Arizona's circular membrane description](https://math.arizona.edu/~lega/322/Spring07/cem.html).

All `n` start at one. Tube `L_eff` must already include the appropriate end correction; this model does not infer that correction. Except for the optional pinned stiff-string approximation, these idealized resonances do not model bending stiffness; they also omit soundboards, reeds, vocal folds, instrument-specific radiation, nonlinear excitation, transients, damping or coupling to a room. They do not identify an instrument from audio or render an instrument. See [Carnegie Mellon musical acoustics](https://www.cs.cmu.edu/~15322/book/ch12/00.html) and [University of Massachusetts string waves](https://openbooks.library.umass.edu/physicsofmusic/chapter/lab-activity-5/).

## Room Studio

Run `earnest room-editor --open`. The local browser editor imports and exports `earnest.room.v1` JSON and sends validation and solve requests to the same `RoomSpec` and `solve_room` used by the CLI. The editor never writes a room file on its own: export is a browser download. The top view visualizes geometry and source/receiver placement, not audio localization. Interactive solving caps reflection order at three and permits up to four sources, four receivers and 100 m per dimension; the exported document retains the user's selected reflection order for CLI use. This is a rectangular shoebox editor, not arbitrary mesh import.

## Frankenjack controls

Advanced Mix now exposes the existing wet return, tail-duration scale, absorption scale, scattering scale, diffuse-energy scale, and seven wet EQ bands alongside direct, additive stereo-center, master and ceiling controls. EQ is limited to ±12 dB; room scaling is 0–250% except tail minimum 10%. These are the existing Earnest control mappings, not separately measured instrument parameters. Room-shape changes still rebuild/restart the bridge; EQ and mix update via control files. Direct uses a fixed 85 ms lookahead plus a 512-frame block delay. The current wet profile is scaled by a historical 0.0001 factor, and the peak ceiling is a hard clamp, not a transparent limiter. Center boosts all shared left/right content and is not vocal isolation.

Spatial staging, full multichannel speaker layouts, measured source directivity, frequency-dependent room boundaries, diffraction and a full true suite of live controls remain open. Do not present controls as wired until they actually change the signal. More measurements, documented models and user listening are required before claiming parity with Univerb or a general instrument/room model.

## Frequency trace: measured evidence for later reasoning

### Focus and hypothesis comparison

`earnest focus-band input.wav --low 400 --high 700 --out focus.wav` applies a fourth-order Butterworth band-pass forwards and backwards with second-order sections. The forward/backward operation squares the single-pass magnitude response and removes its phase shift away from boundary effects; the nominal cutoff is therefore approximately -6 dB in the combined result. This is an offline, fixed-band operation, not yet a continuously sweeping live tuner or a source separator. Filters have transition bands and end effects, and overlapping instruments remain together. The engine component is `audio.focus_band`. Output is float WAV and may exceed full scale; no playback or gain adjustment is performed.

`earnest audio-compare reference.wav candidate.wav --out comparison.json` requires equal sample rates, channel counts and frame counts; it does not automatically align or normalize. Its residual is `e[n,c] = reference[n,c] - candidate[n,c]`, with mean-square error `sum(e²)/N`. A one-sided real FFT uses weights 1 at DC and (for even lengths) Nyquist, and 2 elsewhere, divided by `N²`; summed bin powers equal the residual mean square by Parseval's relation. The report partitions those powers into frequency ranges. Zero residual or zero reference power gives a null relative level instead of an infinite dB value. `audio.compare` also exposes residual samples as an artifact, usable by `audio.frequency_trace` or `audio.focus_band` in a later run. Neither a low residual nor a frequency band proves a unique room, source, instrument or MIDI part.

`audio-compare --segment-seconds 1` adds non-overlapping per-interval reports, including a final partial interval. `audio-rank reference.wav candidate1.wav candidate2.wav --out rank.json` sorts aligned candidates by average channel mean-square residual and records file SHA-256 hashes. These are exact sample-domain scores for the supplied files, not perceptual accuracy or independent validation.

`frequency-trace --pitch-labels --a4-hz 440` annotates each spectral peak with `m = 69 + 12 log2(f / f_A4)`, nearest equal-tempered note, and cents `100(m - nearest)`. See the [UNSW frequency and MIDI reference](https://newt.phys.unsw.edu.au/music/notes.html). It labels spectral peaks; a peak can be a harmonic or noise and does not establish a played note or MIDI event.

### Optional audio-to-MIDI backend

`earnest transcribe input.wav --out new-directory` invokes an independently installed [Basic Pitch](https://github.com/spotify/basic-pitch) backend, producing MIDI, note-event CSV and a provenance manifest. The engine exposes `audio.transcribe`; `--backend` or `EARNEST_BASIC_PITCH` selects a different executable. The local lab uses an isolated Python 3.11 environment under `runs/runtime/basic-pitch`; `requirements-basic-pitch.txt` records direct compatibility pins. A generated 440 Hz tone produced a MIDI note 69 in a local integration check. This is not an accuracy benchmark. Basic Pitch's authors state it works best with one instrument at a time; it does not identify or separate instruments into tracks. Its predictions are hypotheses, not ground truth. The environment is local and excluded from Git; other machines need their own compatible installation.

`earnest separate input.wav --out new-directory` invokes the [Demucs htdemucs model](https://github.com/facebookresearch/demucs), producing estimated vocals, drums, bass and other stems plus an input hash and manifest. The engine exposes `audio.separate`; `--backend` or `EARNEST_DEMUCS` selects its executable. The isolated local environment is `runs/runtime/demucs`, with direct dependency pins in `requirements-demucs.txt`. First use downloads model weights. The backend defaults to CPU and zero random shifts; Demucs may rescale outputs for clipping. A generated-tone smoke test produced all four files, but this does not validate music separation accuracy. Stems can contain interference, effects and reverb, and `other` can contain many instruments. Apply Basic Pitch to a stem as an experiment, not proof that it represents one isolated instrument.

`earnest frequency-trace input.wav --out trace.json` records time-stamped spectral
peaks independently for each channel. Options include `--window`, `--hop`,
`--min-hz`, `--max-hz`, `--max-peaks`, `--min-level-dbfs`, and
`--relative-threshold-db`. The default output goes into a new run folder. Existing
output files are never overwritten. This component can also be requested as
`audio.frequency_trace` with an `audio.samples` artifact.

For each channel and Hann-windowed frame, the engine locates local maxima in the
real FFT, fits a parabola to the log magnitudes of each peak and its neighbors,
and evaluates the windowed discrete Fourier transform at the interpolated
frequency. Its isolated-sinusoid peak amplitude estimate is
`2 * |sum(x[n] w[n] exp(-j 2 pi f n / fs))| / sum(w[n])`; the reported level is
`20 log10(amplitude)` in digital dBFS. Bin spacing is `fs / window_size`;
interpolation does not guarantee that close sources can be resolved. The
underlying local-maximum operation is documented by [SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html).

These data are spectral observations, not identified instruments, notes, source
separation, or a trained model. A harmonic and a fundamental can look alike;
noise, transients, nearby tones and phase can bias results. There is no physical
SPL calibration. DC and the Nyquist bin are omitted. Incomplete final windows
are zero padded and marked with `valid_samples`; their levels are not calibrated
as full-window measurements. The current implementation reads the full input and
holds the result in memory, so long recordings and small hops can be expensive.
It does not play audio.

## Experimental instrument reference classifier

`earnest instrument-train examples --out model.json` learns a reference library
from immediate subfolders, each named for a label, e.g. `acoustic_guitar`,
`synthetic_lead`, `acoustic_percussion`, `electronic_kick`, or `cymbal`. It accepts
WAV, FLAC, Ogg and MP3 as supported by the installed libsndfile. Model JSON stores
per-file feature vectors, source paths, and SHA-256 hashes. To inspect a sample,
run `earnest instrument-identify recording.mp3 --model model.json`. The same
operation is the `instrument.identify` engine component.

This is a baseline supervised nearest-reference method, not a pretrained neural
network. It ranks one closest example per label using standardized log-frequency
spectral DCT statistics; distance is not a probability. The first 15 seconds are
used and stereo is averaged to mono; phase cancellation can lose content. It has
no source separation, event timing, out-of-distribution rejection, dedicated
percussion transient model, or reliable full-song recognition. It always ranks
known classes even when none match. The automated checks use synthetic signals
and do not establish real instrument accuracy. Train and independently evaluate
on varied recordings, with separate instruments and sessions in each split.

NSynth recordings by Google Inc. are available under [CC BY 4.0](https://magenta.withgoogle.com/datasets/nsynth).
The [Strudel MP3 conversion](https://huggingface.co/datasets/vvolhejn/nsynth)
contains acoustic, electronic, and synthetic families. Dataset note samples alone
do not cover modern drum kits or a representative range of electronic percussion.
Retain source, creator, license and any edits for each sample; check licenses before
redistribution. The current room solver accepts arbitrary source positions and
ideal omni, cardioid and figure-eight patterns, which can represent simplified
stage speakers, but it has no measured loudspeaker directivity, frequency response,
crossover, cabinet, amplifier, or subwoofer-array model.

### Modeling and exporting rooms in Room Studio

Run `Open-Room-Studio.cmd` in the repository or `earnest room-editor --open`.
Set dimensions, environment, six surface materials, octave-band absorption and
scattering, source/listener positions and direction, and the solver controls.
Drag a point in the plan to move it; drag the right or top handle to resize the
rectangular room. Select a point and use arrow keys for 0.1 m nudges; Shift moves
1 m; Escape deselects. Height is edited numerically. Validation catches points
outside the room after resizing. The decay chart is an estimate, not a recorded
response. No sound is played by the editor.

Export room writes a full `earnest.room.v1` JSON document. Export instructions
writes a lossless `earnest.room-instructions.v1` JSON list of declarative `set`
operations; reconstruct it with:

```
earnest room-from-instructions earnest-room-instructions.json --out room.json
```

The command validates the reconstructed document and refuses to overwrite an
existing output. The list includes the complete top-level fields, including
unrecognized metadata; it is not an executable shell script. Room Studio is a
plain JavaScript/canvas UI backed by the existing local Python solver. It does
not yet support freeform walls, arbitrary geometry, dragging height, real-time
sound-field rendering, or direct application of rooms to Frankenjack. A manually
requested, static point-sampled sound-field slice is available as described below.

## Correlated sources

See the implemented correlated-source spectral propagation section in [the equation sheet](ROOM_SOLVER_MATH.md). The standalone calculation uses supplied complex transfer and source cross-spectral matrices; the room adapter uses coherent explicit image paths and excludes the statistical late field. Tests cover direct-distance scaling, phase, cancellation, constructive addition, and invalid cross-spectral matrices.

## Air absorption in statistical decay and fitting

With air absorption enabled, `alpha_air` is the ISO 9613-1 attenuation in dB/m.
For sound-energy attenuation, `m = alpha_air ln(10)/10` in inverse meters and
`A_air = 4 m V` in square meters. Each octave estimate uses

```
K = 24 ln(10) / c
T_Sabine = K V / (A_surface + A_air)
T_Eyring = K V / (-S ln(1 - A_surface/S) + A_air)
```

The same air term is used when fitting measured decay and in the solver's
existing diffuse-field energy estimate. See the [AFMG EASE documentation](https://www.afmg.eu/sites/default/files/2025-12/EASE_5-TE_UsersGuide.pdf)
for the Eyring expression and unit conversion. These statistical models still
assume an approximate diffuse field; they are not spatial simulations, and the
resulting decay depends on the ISO model's environmental validity. The diffuse
energy target remains an approximation, the late tail remains stochastic, and
source/receiver directionality is not modeled in that tail. With air disabled,
previous decay and fitting behavior is preserved.

## Modeled energy-time diagnostics

Each source/receiver pair now includes C50, C80, D50 and center-time estimates by solver band, with explicit early and late energies. See the [equation sheet](ROOM_SOLVER_MATH.md) for definitions, sample boundaries, undefined values, and the distinction from measured room parameters.

## Room-field slice

Room Studio's **Map sound field** button uses `room.field_slice`, the same
component available through `earnest room-field`. Select an octave center and
height, then map again after editing the room. Colors show relative sampled
power from -40 dB to the strongest sample; they do not show calibrated SPL.
The map is calculated from direct and first-order image paths, with an
omnidirectional virtual receiver. Independent, common in-phase, and opposite
polarity source assumptions are selectable; a custom complex source-correlation
matrix is supported in the CLI. It excludes the stochastic late tail. See the [equation sheet](ROOM_SOLVER_MATH.md)
for the equation and limitations.

## Source correlation in the viewer

The map now offers independent, common in-phase and two-source opposite-polarity assumptions. The CLI additionally accepts a complex correlation matrix in source order. The color scale is normalized separately for each map; it cannot compare absolute loudness between maps. Details and matrix validation are in the [equation sheet](ROOM_SOLVER_MATH.md).

## Independent decay and tail-length controls

`engine_controls.decay_scale` defaults to 1 and ranges from 0.1 to 2.5.
The solver keeps the physical Sabine and Eyring estimates unchanged, selects
the configured estimate, and computes `T_effective = decay_scale * T_physical`.
The statistical late pressure envelope uses `10^(-3t/T_effective)` and the
live profile uses the effective value. The separate `tail_duration_scale`
controls the rendered tail cutoff; it is not a decay-rate control. Both values
are exposed separately in Room Studio and Frankenjack Advanced Mix.

The stochastic tail is filtered and normalized to the existing energy target;
the cutoff is capped at eight seconds, so the rendered response is approximate
and may not contain a full 60 dB decay. Decay fitting currently targets the
physical estimate before the artistic decay multiplier; set the multiplier to
100% while fitting to interpret the fitted prediction directly. Frankenjack
currently rebuilds and restarts its bridge for these changes. Offline checks
verify generated decay slopes and control bindings; no live audio test has been
performed for this addition.

## Independent direct EQ in Frankenjack

The native mixer now applies a separate seven-band peaking-EQ cascade to the
delayed direct path before adding direct gain and shared-channel center. Wet EQ
remains a separate cascade on the reflected return. The direct EQ bands are
125, 250, 500, 1000, 2000, 4000, and 8000 Hz, from -12 to +12 dB; all default
to 0 dB. They are exposed in Advanced Mix and controlled independently through
`direct-eq.txt`. The same setting applies to every channel, and the center
reinforcement is derived from the already-filtered direct channels.

Each peaking section uses `A = 10^(G/40)`, `w = 2 pi f0/fs`,
`alpha = sin(w)/(2Q)` with `Q = sqrt(2)`, and
`b = [1+alpha A, -2 cos(w), 1-alpha A]`,
`a = [1+alpha/A, -2 cos(w), 1-alpha/A]`, normalized by `a0`.
The [W3C Audio EQ Cookbook](https://www.w3.org/TR/audio-eq-cookbook/)
documents the coefficients. Coefficients are smoothed over audio blocks, but
filter-state continuity is not a guarantee of artifact-free abrupt changes.
Offline checks verify each band's ±6 dB response at its center, verify direct
EQ does not alter the wet return, and exercise the UI control file. No live
device, headset, or listening validation was performed. Deployment requires
updating both the Frankenjack UI and its native audio host together.

## Stereo width tuning

Frankenjack's Stage Width control now adjusts the stereo sum after direct and
wet paths are mixed and before the existing hard ceiling. With
`M=(L+R)/2`, `S=(L-R)/2`, and slider value `p` from 0 to 100, the native
bridge smooths `w=p/50` and computes `L'=M+wS`, `R'=M-wS`. Thus 0 is mono,
50 preserves the original stereo, and 100 doubles the side component.
The control is independent of room parameters and uses a control file read by
the running bridge. Other channel layouts pass through this stage unchanged.
This is mid/side stereo processing, not physical source positioning or an
ears/head model; widening can increase peaks and the current ceiling is a hard
clamp. Offline tests checked mono, unity, widened, and unchanged default behavior;
no live listening test has been performed.

## Hypothesis measurements

The reconstruction residual and harmonic peak-support equations, explicit assumptions, and weighted ranking formula are documented in [hypothesis evaluation](HYPOTHESIS_EVALUATION.md). Peak-support uses squared detected peak amplitudes as a proxy and is not a complete Parseval energy calculation. It does not attribute overlapping partials to sources.

## Effect pursuit

See [effect pursuit](EFFECT_PURSUIT.md) for the implemented least-squares delay projection, acceptance criterion, assumptions and limitations. This is a greedy single-family fit; it is not a general inverse of arbitrary effect chains.
