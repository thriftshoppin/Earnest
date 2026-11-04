# Prepared rooms and the live jack

## Goal

Earnest solves a room ahead of playback and produces an editable, versioned room profile. The jack receives audio and control values and evaluates that profile in real time. Analysis and live stage simulation can request additional computation independently of ordinary profile playback. A profile is an Earnest processing description; a VST or other plugin wrapper is a later adapter.

## What exists

`prep` caches the existing ERIR convolution filter. The filter combines direct and room sound at fixed dry and wet values; it does not yet expose independent room paths, frequency-band controls, or continuous profile updates. The current native host processes one filter per channel, in 512-frame partitions, and the compiler defaults to 85 ms lookahead. Caching avoids re-solving at boot but does not remove those playback delays. Profile readiness is not a measurement of end-to-end latency.

## Profile direction

Represent a room with separately identified direct, early-reflection and late-field components and a declared channel mapping. The profile should include sample rate, solver and schema version, the room source hash, control ranges, and units; it must carry enough information to reproduce its compiled results. Per-band parameters may represent independent filter responses or parameters of a stable real-time model. The compiler must describe exactly which parameters are independently controllable and which require a background rebuild.

For a linear baseline, a conceptual channel output is

`y_c[n] = g_d (h_d,c * x_c)[n] + sum_b g_b (h_room,c,b * x_c)[n]`.

The filters must form a defined complementary band decomposition, with alignment and delay accounted for, so their sum reconstructs the intended room response. Smooth changes to gains over time; a genuinely time-varying convolution is not generally equivalent to a single fixed convolution. Room geometry or nonlinear changes cannot in general be reproduced by scaling fixed band filters alone. For controls that change filter shape, prepare a replacement away from the audio callback, warm it with input history where possible, then crossfade and report the actual application status. Prevent clipping and measure CPU and latency during overlapping transitions.

The jack supplies input frames, endpoint format and explicitly selected controls. Any audio-derived parameters require named analysis methods, measured values and update rates: room behavior must not be silently inferred from the track. A static precomputed filter cannot separate individual instruments from a mixed track; that requires a separate separation stage with its own latency and uncertainty.

## Acceptance criteria for the next implementation

1. Export an inspectable profile and verify its source hash and format when loading it.
2. Compare its neutral output sample by sample against the current fixed-filter reference, including channel and delay alignment.
3. Verify direct and each band can change independently, and that neutral bands reconstruct the reference within a documented numerical tolerance.
4. Exercise rapid control changes and room transitions offline for discontinuities, bounded output and finite samples.
5. Measure block delay, lookahead, processing time, underruns and end-to-end device latency on the actual VM route; distinguish results from offline checks.
6. Keep the audio stream open for supported control changes, and clearly mark changes requiring a rebuild or restart.

Neither the new format nor the live modulation described above is implemented yet. Existing profile caching is an intermediate step, not the completed room plugin architecture.
