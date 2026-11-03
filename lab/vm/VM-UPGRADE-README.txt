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
