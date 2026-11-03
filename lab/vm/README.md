# Build a configurable VM lab package

This is an experimental source-based lab, not a signed production installer. Start with a disposable x64 Windows VM with guest Secure Boot disabled and a working virtual audio output. The installer supports recognizable VM vendors but only VMware has been tried. Setup enables test signing and installs the provided test certificate inside the guest; it does not modify the host boot configuration.

On the Windows build machine, supply a Python installation with `requirements-lock.txt` and `tkinterdnd2` installed, Node.js, and the x64 `devcon.exe` from the Windows Driver Kit. The builder compiles the Frankenjack shell and live monitor, gathers those inputs, and creates `Earnest-Payload.zip`, its checksum and the installer scripts. The checked-in driver package is the same test-signed lab artifact used in the initial VMware session; an alternate matching `.inf`, `.sys`, `.cat` and public `.cer` can be supplied with `-DriverPackage`.

```powershell
powershell -ExecutionPolicy Bypass -File .\lab\vm\Build-LabPayload.ps1 `
  -PythonHome 'C:\path\to\python' `
  -NodeExe 'C:\path\to\node.exe' `
  -DevconExe 'C:\path\to\x64\devcon.exe' `
  -OutputDirectory 'C:\path\to\new-lab-package'
```

`-LipscanModels` optionally supplies a directory containing the `v_male` and `v_female` model assets; do not redistribute models without confirming their rights. Transfer the resulting files to the guest together, then run `Install-Earnest-VM.cmd`. Setup uses `%USERPROFILE%\tools\Earnest-VM-Lab` by default; set the `EARNEST_LAB_INSTALL_DIR` environment variable in the guest to select another path. If it enables test signing, restart the guest and rerun setup.

Build sources and dependencies are supplied; building this package from a clean checkout has not yet been verified. The packaged test certificate is public and contains the original build identity; its private key is not included. See [lab status](../../docs/LAB_STATUS.md) for the first listening report and known limitations.
