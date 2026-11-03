# Earnest: changes since the previous VM lab build

This review uses the last fetched `origin/master` commit `9cabc1e` as a concrete baseline. That was the experimental room-engine and VM-lab snapshot; the actual VM's files have not been inspected during this update, so its exact version may differ. All subsequent work described here is local until explicitly pushed. See `CHANGELOG.md` for build-by-build entries and `lab/vm/VM-UPGRADE.md` for the guest upgrade.

## Room physics and analysis

- Added an editable room model and analysis foundations, including frequency traces, optional atmospheric attenuation, idealized instrument resonator modes and documented assumptions. Air absorption and decay calculations include tests against reference values and independent numeric checks.
- Added correlated-source soundfield propagation, room-path propagation and room-field slices with independent, coherent and custom correlation assumptions. Those maps are modeled, relative results rather than measured sound pressure or a complete simulation.
- Added finite-window energy metrics including clarity and center time; added the effect of air absorption to modeled decay and absorption fitting. Fitting still assumes fixed geometry and does not uniquely identify the physical room.
- Added an experimental short-clip instrument reference matcher. It is a nearest-reference feature model with no independent accuracy benchmark; it does not separate a song into instruments.

## Creation, tuning and live controls

- Room Studio now edits rectangular rooms, materials, source and listener positions, includes a lightweight interactive field view, and can export room documents or instruction lists. Its results are model predictions.
- The room engine has a decay multiplier independent of the tail duration and the late-field energy control. CLI percentage commands create new room files without overwriting the baseline.
- Frankenjack gained a custom room selector, independent direct and reflection EQ, direct/center/master/ceiling controls, and stereo mid/side width. Source position and full binaural spatial staging are not supplied by width alone.
- Prepared room profiles can crossfade inside the running bridge; changing endpoints still restarts it. The offline transition test does not establish live glitch-free operation or available CPU headroom. The new convolver's long tail takes time to build.
- The original StageJack playback loopback analyzer was restored to the Frankenjack source and its displayed curve was matched to Earnest's seven reflection EQ filters. It monitors a selected Windows playback mix, which may include other applications; it is not an exclusive per-bridge measurement. The updated live display has not been verified in the VM.

## Investigation and transcription

- `focus-band` creates an offline band-pass output; `frequency-trace` identifies spectral peaks and can annotate pitch coordinates. A peak is not necessarily a note or an instrument.
- `audio-compare` reports residual energy for aligned reference and candidate files, optionally by time interval. `audio-rank` orders candidates by sample-domain error and records hashes. These measurements do not prove that a source or room hypothesis is unique or perceptually best.
- Optional `separate` uses Demucs to estimate vocals, drums, bass and other stems. Optional `transcribe` invokes Basic Pitch to estimate note events and MIDI. These are separate pretrained models, not a model trained by Earnest. Their separate Python environments and weights are not included in the VM update. A generated tone produced MIDI note 69 and a separate generated-tone run produced four stem files; neither is a real-song accuracy evaluation. See `PHYSICS_NOTES.md`.

## VM deployment and testing

The new VM update packages the application files for an existing installation, verifies file hashes and backs up files it replaces. It preserves inboxes, room files, settings, runtimes and the installed driver; it does not update Windows, modify Secure Boot or reinstall the driver. Model backends require separate installation inside the guest. Read `lab/vm/VM-UPGRADE.md` for steps and recovery details.

Unit and offline integration tests are in `tests/`. On this build, 71 Python tests passed. The native audio build and UI checks use generated signals and do not open an output device. The MIDI and separation smoke tests use a generated tone, not human listening or a validation dataset. The guest updater was exercised against a temporary mock installation, including backup, file verification and preservation of a room; the actual guest has not been upgraded.

The source contains user-specific and lab-specific history. Verify paths, device routing, selected room, model availability and package state on each machine. Do not claim VM installation, live EQ behavior or comparison with Univerb without a corresponding guest test.
