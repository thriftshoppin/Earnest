# Driver build inputs

The source in `sysvad/` was copied from the separate experimental Earnest audio device worktree, based on Microsoft Windows driver samples revision `f4c1ff842b6a0001152f44cb61788b216a1c7627`. The Microsoft Public License is included in this directory. The `EarnestAudioDevice.inf` alongside this document is the lab INF; the `.sys`, catalog and test certificate must be produced and signed locally as a matching package.

The existing work used Visual Studio 2022, the Windows Driver Kit 10.0.26100.0, x64 Debug configuration, and Microsoft WIL revision `a1c0cbe1d7065aef6333399d3e25608eacdffc0f`. WIL and toolchains are not vendored. The project and driver signing setup must be reviewed on a fresh machine; the copied worktree does not yet provide a validated clean build script or automated INF/catalog/signing pipeline. Do not assume the source alone produces an installable driver.

The existing test-signed `.sys`, catalog, INF and public certificate are included in `test-package/` for reproducing the local lab. The signing private key and VM disk images are excluded. This certificate is trusted in the test guest, so this is for a disposable lab, not general deployment. Production deployment needs the appropriate Microsoft signing route.
