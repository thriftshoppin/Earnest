import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
from earnest.engine.band_focus import focus_band
from earnest.cli import main


class BandFocusTests(unittest.TestCase):
    def test_focus_reduces_outside_tone(self):
        fs = 16000; t = np.arange(fs) / fs
        audio = np.sin(2*np.pi*500*t) + np.sin(2*np.pi*3000*t)
        output = focus_band(audio, fs, 400, 700)[:, 0]
        center = slice(2000, -2000)
        inside = abs(np.dot(output[center], np.exp(-2j*np.pi*500*t[center])))
        outside = abs(np.dot(output[center], np.exp(-2j*np.pi*3000*t[center])))
        self.assertGreater(inside / outside, 1000)
        self.assertAlmostEqual(inside / (len(t[center])/2), 1, delta=.05)

    def test_validation_and_cli(self):
        audio = np.ones((512, 2))
        for low, high in ((0,100), (100,100), (100,4000), (float('nan'),100)):
            with self.assertRaises(ValueError): focus_band(audio,8000,low,high)
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp)/'src.wav', Path(tmp)/'out.wav'
            sf.write(src,audio,8000,subtype='FLOAT')
            self.assertEqual(main(['focus-band',str(src),'--low','100','--high','1000','--out',str(out)]),0)
            samples, rate=sf.read(out,always_2d=True)
            self.assertEqual(samples.shape,audio.shape); self.assertEqual(rate,8000)
            with self.assertRaises(SystemExit): main(['focus-band',str(src),'--low','100','--high','1000','--out',str(out)])


if __name__ == '__main__': unittest.main()
