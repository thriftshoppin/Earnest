# Earnest: pickup notes

Continue work in `C:\Users\SysAdmin\Documents\Codex\2026-11-02\go\work\earnest`. Inspect the current Git status and history first; do not overwrite unrelated changes or push without fresh authorization. This is the source checkout, not proof that the host or VM has the latest build installed.

## Direction

Build Earnest into a reproducible, configurable audio and room engine that can eventually serve as a reference for other tools. Document assumptions and equations, compare against published methods and measurements, and distinguish simulated estimates from validation. The user is the listening evaluator; don't start audio or change the active audio route without coordinating.

The intended architecture is Earnest as the shared engine, Frankenjack as one control surface, and Studio as a broader workspace for room design and eventual connections to local tools such as Applio. External adapters and a shared live graph are goals, not implemented capabilities.

Current priority: work from the equations to independent, correctly labeled tuning controls, then pursue instrument data and validation. The room editor should remain lightweight and support custom room export.

## Current work

- `earnest/engine/`: room model, solver, rendering, physics, analysis components and offline session.
- `docs/ROOM_SOLVER_MATH.md`, `docs/PHYSICS_NOTES.md`: equations, assumptions, sources and limitations; `docs/CLI_COMMAND_TRANSLATION.md`: commands and proposals; `docs/ENGINE_ARCHITECTURE.md` and `docs/ROADMAP.md`: architecture and future direction.
- `CHANGELOG.md` records changes by local build; automated checks live in `tests/`.
- `lab/frankenjack/`: Earnest-only StageJack shell and native audio bridge. The build script places new binaries in `lab/frankenjack/build/`. Installing those into a VM or host is a separate operation.
- `lab/driver/` and `lab/vm/`: driver and VM packaging work. Check their current contents and installation state before making deployment claims.

Recent local builds separated decay from tail duration, added direct EQ independent of reflection EQ, wired stereo width and added file-based room percentage commands. The room chooser in Frankenjack lets the user select a room file. Room changes are now prepared and crossfaded within the running bridge; endpoint changes still restart it. The crossfade has offline coverage only and temporarily raises CPU load; the new room's long tail takes time to build. Width is stereo mid/side processing, not physical 3D placement. Existing live gain limits and routing require separate review; do not assume a device path is exclusive or that a selected device is safe from feedback.

The room model uses explicit image paths for rectangular geometry and a statistical late tail; it is not a full physical reconstruction of arbitrary spaces or plugin internals. Matched dry/wet recordings can constrain a model but do not uniquely identify a room or validate every source. The current instrument classifier is reference similarity, not a validated general-purpose separator or trained voice model. Pyroomacoustics is one documented simulator to compare on matched scenes and measured responses.

Latest full offline Python suite during this work: 59 tests passed. Native/UI builds and offline control checks were run separately; none establishes live listening quality. Check the working tree and rerun the appropriate tests after changes. Preserve any preexisting changes to `docs/LAB_STATUS.md` and `tests/last_results.txt`.
