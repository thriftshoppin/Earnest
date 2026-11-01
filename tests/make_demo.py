"""Builds a demo dry/wet folder pair from a KNOWN synthetic reverb (so `room` can be run end to end without Cakewalk): python tests/make_demo.py <outdir>"""
import sys
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from earnest import gen  # noqa: E402
from earnest.io import FS, read_wav, write_wav  # noqa: E402
from run_tests import synth_system  # noqa: E402

out = Path(sys.argv[1])
dry_dir, wet_dir = out / "dry", out / "wet"
dry_dir.mkdir(parents=True, exist_ok=True)
wet_dir.mkdir(parents=True, exist_ok=True)
taps = [{"delay_ms": 7.3, "gain_db": -6.0, "pan": -0.6, "source": "L"}, {"delay_ms": 13.1, "gain_db": -9.0, "pan": 0.4, "source": "R"},
        {"delay_ms": 21.7, "gain_db": -12.0, "pan": -0.2, "source": "L"}, {"delay_ms": 34.9, "gain_db": -14.0, "pan": 0.8, "source": "R"},
        {"delay_ms": 52.3, "gain_db": -17.0, "pan": 0.0, "source": "L"}]
irs = synth_system(1.2, rho=0.3, seed=3, taps=taps)
for name, x in gen.make_all().items():
    write_wav(dry_dir / name, x)
    y = np.zeros((len(x), 2))
    for k, side in enumerate(("L", "R")):
        for c in range(2):
            y[:, c] += fftconvolve(x[:, k], irs[side][:, c])[: len(x)]
    write_wav(wet_dir / name, y)
    if name in ("sweep_L.wav", "sweep_R.wav"):
        write_wav(wet_dir / name.replace(".wav", "_rep.wav"), y)
print("demo written to", out)
