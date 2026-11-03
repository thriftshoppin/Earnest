# Earnest Audio Device

This is the separate Windows virtual playback device for Earnest. Windows applications write to **Earnest Virtual Speakers**. The driver exposes that mixed stream through WASAPI loopback; Earnest's terminal audio host captures it, applies the selected room profile, and renders it to a physical output.

```text
Windows applications
        |
        v
Earnest Virtual Speakers (default Windows playback)
        |
SYSVAD render stream -> kernel SPSC ring -> WASAPI loopback capture
        |
Earnest CLI audio host -> Earnest DSP -> selected physical output
```

The virtual device has no physical output pin. The current host opens the physical endpoint in shared mode, so applications explicitly assigned to that endpoint can bypass Earnest. The route command attempts to set and restore the default playback endpoint; this lifecycle has not yet been validated on the new device.

## Driver source

The starting WDM/WaveRT project is Microsoft's SYSVAD sample, included under its license in `LICENSE-MICROSOFT.txt`. Earnest narrows it to a single virtual speaker endpoint and replaces the sample loopback tone with an audio ring that carries the actual Windows render stream. The ring is lock-free and single-producer/single-consumer; the render endpoint produces data and its WASAPI loopback pin consumes it. Other sample capture paths and hardware-style outputs are not part of this device.

The project currently targets x64 Windows 11 with the 10.0.26100 WDK and Visual Studio 2022 C++ tools. `wil` is a Microsoft WIL submodule.

## Current implementation boundary

The driver and CLI host were compiled, and the INF previously passed Universal validation. The user reported installing the device and hearing a room through the route in a VMware guest. This first listening result does not validate the kernel ring, format handling, device recovery or end-to-end reliability. The host's initial FDN uses the median solved decay, not all per-band or spatial room data. The driver is not automatically installed or set as the Windows default by this source project.

The included lab package uses a local WDK test certificate. Production deployment requires appropriate Microsoft driver signing; the test package is for an isolated guest that permits test signing. Do not treat a successful build as proof that Windows loaded or routed audio through it.
