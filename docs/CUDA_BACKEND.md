# CUDA backend, phase 1: offline room rendering

The optional CUDA backend accelerates the existing room renderer's frequency partition and FFT convolution with CuPy on a selected NVIDIA GPU. Room parsing, geometry/image paths, decay solve, result statistics and the native real-time audio bridge remain on the CPU. The reference formulas, seven bands and float64 arithmetic are shared; this is not yet CUDA support for the entire engine, live instrument separation, or live playback.

## Setup on a CUDA-capable Windows system

Use an isolated Python environment that can see Earnest's normal dependencies. For a host installation from the repository, for example:

```powershell
python -m venv --system-site-packages runs/runtime/cuda
.\runs\runtime\cuda\Scripts\python.exe -m pip install "cupy-cuda12x[ctk]==14.2.0"
.\runs\runtime\cuda\Scripts\python.exe -m earnest cuda-devices
.\runs\runtime\cuda\Scripts\python.exe -m earnest simulate room.json source.wav --backend cuda --cuda-device 0 --out runs/cuda-example
```

A compatible NVIDIA driver and CUDA-visible GPU are required. CuPy's bundled CUDA runtime packages are optional dependencies and are not included in the VM update. See [CuPy installation](https://docs.cupy.dev/en/stable/install.html). `cuda-devices` reports the device indices visible to the current Python process, which may change after hardware or driver changes. `--backend cpu` is the default. An explicit `--backend cuda` fails if unavailable; it does not silently run on the CPU. Simulation output records the selected backend and GPU name. GPU setup and transfer overhead can outweigh computation on small jobs.

A VMware Workstation guest does not acquire CUDA access merely because the host has a GPU. The guest must itself expose a compatible CUDA device and driver, or use a separately engineered host computation service; this build has no host/guest CUDA service. Check `cuda-devices` inside whichever environment runs the simulation. Do not infer guest CUDA access from host `nvidia-smi`.

## Validation on this host, 2026-11-03

Windows listed the GTX 1650 SUPER as disabled (device problem code 22), and NVIDIA reported the RTX 4060 Ti as the only available CUDA device. GPU tests compared partition and full room-render output with the CPU implementation in float64 for a synthetic multiband room; tolerances and inputs are in `tests/test_cuda_render.py`. One warm three-second synthetic render took 0.191 s CPU versus 0.061 s GPU on this host; maximum absolute sample difference was 2.67e-15. This is one informal measurement and does not characterize startup, large rooms, GPU contention, latency, or every signal. It is agreement with the existing model, not proof the model is physically correct. The live audio path and guest GPU access were not tested.

## Remaining

Add separate acceleration and parity checks for room geometry, fitting, analysis, effects and neural inference where useful; maintain explicit device selection and CPU reference implementations. Design a host/guest service or supported GPU virtualization separately. Measure startup, data transfer, memory, underruns and end-to-end latency before using GPU processing in the real-time path. Recheck RTX performance when gaming or other GPU workloads are active.

