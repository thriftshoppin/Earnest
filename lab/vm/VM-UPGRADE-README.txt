EARNEST VM LAB - APPLICATION UPDATE

1. Copy this entire update ZIP into the VM and extract it to a writable folder
   on C: (for example C:\Users\bench\tools\Earnest-update). Do not run from a
   mounted ISO and do not copy only the scripts.
2. Stop Earnest processing and close Frankenjack, Earnest CLI, Studio, and live
   viewer windows in the VM. This update refuses to overwrite running lab apps.
3. Double-click Update-Earnest-VM.cmd. The default installed location is
   %USERPROFILE%\tools\Earnest-VM-Lab. Set EARNEST_LAB_INSTALL_DIR before
   starting it if your installation is elsewhere.
4. Read the result. Replaced files are backed up inside the existing lab folder
   under backup-update-<date>-<id>. If installation fails, keep that backup and
   the message; rollback is manual, not automatic.
5. Start the applications again. Existing rooms, imports, settings and models are
   preserved. The script does not reinstall or modify the audio driver, change
   test-signing, install Python, or change VM Secure Boot settings.

This update includes the application, CLI, room editor, live viewer files and
Frankenjack. It uses the VM's existing Python and Node runtimes. The optional
Basic Pitch and Demucs ML backends and model weights are NOT bundled. They require
internet, uv and separate Python 3.11 environments; see VM-UPGRADE.md in the
source documentation for setup. Their first model run may download weights.

Run audio at your usual safe starting level. The new room crossfade and the
StageJack playback analyzer have not been verified on this VM. The analyzer
monitors the selected Windows playback endpoint, which can include other apps.

CURRENT UPDATE
This ZIP is cumulative: it can be applied to your existing VM lab directly;
you do not need to install the earlier application update first. Advanced Mix
includes the room crossfade slider and independent direct/wet EQ controls.
The hypothesis and effect-pursuit tools are currently offline CLI analysis.
Real-time instrument separation and faders are not implemented in this build.
See documentation\EFFECT_PURSUIT.md and HYPOTHESIS_EVALUATION.md.

CAPTURE: Choose the analysis playback device. Press Start Feed, play and pause
the song, then press Stop Feed. It captures up to five minutes, then separates if
the optional Demucs backend is installed. The folder opens when it finishes.
Clips remain in the temporary Earnest-Demos folder until removed. This is not a
continuous separator and does not yet provide independent instrument faders.


FULL ONE-PASS SETUP
Run Update-Earnest-VM-Full.cmd after extracting this complete folder. It updates
the app, then downloads and installs uv if needed, the Demucs and Basic Pitch
runtimes, and the Demucs model. Internet and several GB of free disk space are
required. Progress and any errors remain visible. After success, launch
%USERPROFILE%\tools\Earnest-VM-Lab\app\Frankenjack.cmd.

VMware Workstation CUDA access is not set up by this installer. The CUDA host
worker/guest bridge and live instrument separation are not implemented.
