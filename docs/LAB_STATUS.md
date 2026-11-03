# VM audio lab: source and status

The lab combines the Earnest CLI and desktop with a test-signed SYSVAD-derived virtual playback device, a native WASAPI audio host, a StageJack-derived Earnest-only control shell and a live visualizer. The main workstation and its Secure Boot state are not modified by the guest installer.

The user reported audible sound through the virtual device and an Earnest room in the Windows VMware guest. This is a user-reported first listening result, not a repeatable device or audio validation. Glitches, intermittent dropouts, excessive quietness, the hard output clamp, lack of true vocal separation and independently adjustable processing remain open issues. The Advanced Mix update is compiled but has not been verified end to end in the guest. Its center control raises shared stereo material, not isolated vocals. Its output ceiling is a hard clamp, not a transparent limiter.

`lab/vm/` contains the configurable guest installer and payload builder. The large local v3 ISO and ZIP contain bundled runtimes and are not checked in. Run the installer in a supported guest, reboot if test signing was just enabled, and rerun it. In a fresh guest, the installer creates the TrustedPublisher store when importing the lab certificate. Only VMware has been tried. Set `EARNEST_LAB_INSTALL_DIR` to change the install path for setup and the update helper.

`lab/driver/` contains the SYSVAD-derived source, Microsoft Public License and the actual test-signed package from the lab. Its public test certificate identifies its original builder; the private signing key is not included. The package is an experimental lab artifact, not a production-signed driver. Building a fresh signed package requires the Windows Driver Kit and Microsoft WIL. Original upstream snapshots: Windows driver samples `f4c1ff842b6a0001152f44cb61788b216a1c7627`, WIL `a1c0cbe1d7065aef6333399d3e25608eacdffc0f`. WIL and the WDK are not bundled.

`lab/frankenjack/` contains the StageJack-derived shell and advanced mixer source under its own MIT license. This is a separate audio path from the CLI's `route` host; do not run both against the same endpoints at once. The current interface controls a wet convolution return, with an experimental delayed direct path and center mix. Center is not a vocal separator.

`live/` is the experimental local visualizer. It requires Node, a compiled monitor, and separately supplied LipScan head assets. The supplied user-local assets are not included because their redistribution rights have not been established. The rings describe energy; they do not measure the direction of sound.

The root LICENSE remains all-rights-reserved at this snapshot. Despite the open-source project goal, selecting and applying an open-source license to Earnest itself is an explicit outstanding decision. Third-party components retain their own license terms.
