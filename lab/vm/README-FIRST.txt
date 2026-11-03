EARNEST VM LAB - INSTALLER 2

Mount the ISO in the Windows VMware guest and open its DVD drive. Run Install-Earnest-VM.cmd directly from the disc. No manual ZIP extraction is needed.

The installer checks the payload SHA-256, extracts it to a temporary folder, fills missing files in C:\Users\<you>\tools\Earnest-VM-Lab, and preserves existing files. Set EARNEST_LAB_INSTALL_DIR before running setup to choose a different target. If test signing was not enabled, reboot the guest and run the same installer again. If it is already enabled, setup proceeds to the driver. An incomplete installation is repaired in place.

The driver is experimental, test-signed and intended for an isolated virtual machine. It does not change host Secure Boot. Only VMware has been tried. The user reported a first audible room route, but reliability and end-to-end audio have not been systematically validated; the driver currently targets stereo. The VM needs a usable virtual audio output; physical hardware and Razer 7.1 are not automatically passed through.

Windows 11 x64, a VMware virtual machine, guest Secure Boot disabled, and .NET Framework 4.x are required. Python, its packages, Node, app files and DevCon are included. Internet is not required for setup. Keep playback quiet during the first audio test.
