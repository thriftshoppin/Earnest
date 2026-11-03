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
