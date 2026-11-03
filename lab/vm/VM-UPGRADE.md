# Upgrading the existing Earnest VM lab

The application update is for an existing installation; it does not create the VM or install a driver. Extract the ZIP to a writable folder in the guest, stop the lab's running applications, and run `Update-Earnest-VM.cmd`. The default install is `%USERPROFILE%\tools\Earnest-VM-Lab`; `EARNEST_LAB_INSTALL_DIR` selects a different existing installation. The updater verifies payload hashes, saves copies of existing overwritten files under `backup-update-*`, copies the new files, and verifies them again. It does not delete other files. Backups do not include newly added files, and rollback is manual. If it fails, keep the backup and error message.

The package updates the Earnest Python package and room editor, live viewer files, Frankenjack executable, and its native host. It preserves the VM's inbox, rooms, models, user settings, existing Python and Node runtimes, and driver. It does not change Secure Boot, test signing or certificates. It does not deploy model runtimes or weights. It has not been applied to the user's VM or validated against live audio.

The extracted `documentation` folder includes the changes-since-baseline report, equation notes, CLI reference, roadmap and changelog. The update ZIP and its adjacent checksum must be transferred together if you want to verify the ZIP before extraction; the payload manifest is independently checked by the updater after extraction.

## Optional model backends inside the guest

The CLI supports `earnest transcribe` (Basic Pitch) and `earnest separate` (Demucs). These require an internet connection, `uv` on PATH and the guest's own optional Python 3.11 environments. From the installed `app` directory run:

```powershell
winget install --id=astral-sh.uv -e
# Open a new PowerShell window after installation, then change to the lab app directory.
cd "$env:USERPROFILE\tools\Earnest-VM-Lab\app"
powershell -NoProfile -ExecutionPolicy Bypass -File .\bin\setup-transcription.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\bin\setup-separation.ps1
```

The scripts download dependencies; Demucs downloads its model weights on first use. These packages can be large. They install into `app\runs\runtime`, separate from the engine's Python. For a custom runtime path pass the executable with `--backend`. `separate` returns estimated vocals, drums, bass and other stems; it does not uniquely identify every instrument. `transcribe` works best on an isolated instrument. Neither has been validated on full songs in this lab.

## Building the update on the host

`powershell -ExecutionPolicy Bypass -File .\lab\vm\Build-VMUpdate.ps1 -OutputDirectory <new-directory>` creates that directory, a sibling ZIP and its SHA-256 file. The builder uses Windows .NET Framework C# compiler and the NAudio DLLs already in the repository; it builds into a separate ignored directory so an open Frankenjack window does not lock the output. Copy the ZIP to the VM and extract the complete archive. The checksum detects accidental corruption; it is not a digital signature or proof of publisher identity.

## Current update: room controls and analysis

This package is cumulative for the existing VM lab and can be installed directly; the earlier November 3 application update is not a prerequisite. Open Frankenjack and choose **Advanced Mix** for direct/dry and center gains, master gain, peak ceiling, wet gain, room tail and decay, absorption, scattering, diffuse energy, seven-band direct and wet EQ, and room selection. The new **Room Crossfade** slider sets the transition time for the next room change (20–2000 ms); the bridge keeps the endpoint open while warming and fading the replacement room. Stage width remains on the main window. Center reinforcement raises shared stereo content and is not isolated vocals.

The package includes the CLI hypothesis comparison, ranking and dry-reference effect pursuit commands, with documentation in the `documentation` folder. They are offline file analyses. Demucs and Basic Pitch are optional external runtimes, are not bundled, and are not currently real-time sources. This build does not provide live instrument separation or instrument faders; existing playback captures a mixed stream. Some legacy StageJack-looking controls are not mapped to Earnest DSP. Do not infer that every displayed StageJack control changes the audio. No live endpoint or VM listening test was performed for this update.

### Capture Demo

In Frankenjack choose the playback device under analysis, press **Start Feed**, play and pause the song, then press **Stop Feed**. The button records up to five minutes from that selected analysis monitor into a temporary WAV; it does not change the current audio route. If the guest Demucs backend is installed, separation starts after capture and the temporary folder opens with the original and estimated four stems. If it is missing, the clip is retained and the app tells you. This is a short batch workflow, not continuous real-time separation; there are no instrument faders yet. Captures reside under the guest's temporary `Earnest-Demos` folder until you or the operating system remove them. Avoid capturing material you do not want stored there. The current capture accepts mono and stereo playback devices and converts mono to stereo; choose the relevant source under analysis before recording.


## Full update in one run

Run `Update-Earnest-VM-Full.cmd` after extracting the complete package. It first runs the existing hash-checked application updater, then installs uv if necessary, installs the isolated Python 3.11 Demucs and Basic Pitch environments, downloads Demucs model weights, and checks that both backends load. This requires guest internet access and several GB of free disk space. It reports failures and can be rerun. Existing runtimes, user rooms, settings and driver are preserved. Start Frankenjack using the new `app\Frankenjack.cmd` launcher. These steps have not yet been verified inside the user's guest. This does not set up CUDA access in VMware: the host compute bridge has not been implemented, and continuous live separation and instrument faders remain unavailable.
