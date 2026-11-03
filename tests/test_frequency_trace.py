import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from earnest.engine import Artifact, create_engine
from earnest.engine.frequency_trace import trace_frequencies
from earnest.engine.pitch import frequency_to_pitch
from earnest.cli import main


class FrequencyTraceTests(unittest.TestCase):
    def test_pitch_coordinates_are_not_note_detection(self):
        self.assertEqual(frequency_to_pitch(440)['nearest_equal_tempered_note'], 'A4')
        self.assertEqual(frequency_to_pitch(880)['nearest_note_number'], 81)
        self.assertAlmostEqual(frequency_to_pitch(440 * 2**(.25/12))['cents_from_nearest'], 25)
        self.assertAlmostEqual(frequency_to_pitch(432,432)['midi_pitch'], 69)
        for value in (0, -1, float('nan')):
            with self.assertRaises(ValueError): frequency_to_pitch(value)
        signal = .25*np.sin(2*np.pi*440*np.arange(4096)/48000)
        peak = trace_frequencies(signal,48000,pitch_labels=True)['frames'][0]['channels'][0]['peaks'][0]
        self.assertEqual(peak['pitch_coordinate']['nearest_equal_tempered_note'], 'A4')
        self.assertAlmostEqual(peak['pitch_coordinate']['midi_pitch'], 69, delta=.02)

    def setUp(self):
        self.fs = 48000
        self.time = np.arange(4096) / self.fs

    def test_interpolated_sine_frequency_and_level(self):
        signal = .25 * np.sin(2 * np.pi * 440 * self.time + .37)
        frame = trace_frequencies(signal, self.fs)['frames'][0]
        peak = frame['channels'][0]['peaks'][0]
        self.assertAlmostEqual(peak['hz'], 440, delta=.3)
        self.assertAlmostEqual(peak['level_dbfs'], 20 * math.log10(.25), delta=.2)
        self.assertEqual(frame['valid_samples'], 4096)
        self.assertAlmostEqual(frame['center_s'], 4096 / self.fs / 2)

    def test_channels_are_independent(self):
        signal = np.column_stack((.4 * np.sin(2*np.pi*440*self.time), .3 * np.sin(2*np.pi*880*self.time)))
        result = trace_frequencies(signal, self.fs)
        channels = result['frames'][0]['channels']
        self.assertAlmostEqual(channels[0]['peaks'][0]['hz'], 440, delta=.3)
        self.assertAlmostEqual(channels[1]['peaks'][0]['hz'], 880, delta=.3)
        self.assertEqual(result['channels'], 2)

    def test_multiple_tones_and_peak_limit(self):
        signal = sum(a*np.sin(2*np.pi*f*self.time) for a, f in ((.4, 440), (.2, 660), (.1, 880)))
        peaks = trace_frequencies(signal, self.fs, max_peaks=2)['frames'][0]['channels'][0]['peaks']
        self.assertEqual(len(peaks), 2)
        self.assertAlmostEqual(peaks[0]['hz'], 440, delta=.3)
        self.assertAlmostEqual(peaks[1]['hz'], 660, delta=.3)

    def test_silence_and_partial_frames(self):
        result = trace_frequencies(np.zeros(500), self.fs, window_size=256, hop_size=128)
        self.assertTrue(all(not frame['channels'][0]['peaks'] for frame in result['frames']))
        self.assertEqual(result['frames'][-1]['valid_samples'], 116)
        self.assertAlmostEqual(result['frames'][-1]['start_s'], 384/self.fs)

    def test_frequency_bounds_and_level_threshold(self):
        signal = .2*np.sin(2*np.pi*440*self.time) + .02*np.sin(2*np.pi*880*self.time)
        peaks = trace_frequencies(signal, self.fs, min_hz=700, max_hz=1000)['frames'][0]['channels'][0]['peaks']
        self.assertTrue(peaks)
        self.assertTrue(all(700 <= p['hz'] <= 1000 for p in peaks))
        self.assertAlmostEqual(peaks[0]['hz'], 880, delta=.3)
        peaks = trace_frequencies(signal, self.fs, min_level_dbfs=-20)['frames'][0]['channels'][0]['peaks']
        self.assertTrue(all(p['hz'] < 700 for p in peaks))

    def test_invalid_inputs(self):
        for audio, fs, opts in [(np.array([]), 48000, {}), ([float('nan')], 48000, {}),
                                ([0], 0, {}), ([0], 48000, {'window_size': 3}),
                                ([0], 48000, {'hop_size': 5000}), ([0], 48000, {'max_peaks': 0}),
                                ([0], 48000, {'max_hz': 30000}), ([0], 48000, {'relative_threshold_db': 1})]:
            with self.subTest(fs=fs, opts=opts), self.assertRaises(ValueError):
                trace_frequencies(audio, fs, **opts)

    def test_component_and_cli_export(self):
        signal = .25 * np.sin(2*np.pi*440*self.time)
        run = create_engine().execute(('audio.frequency_trace',),
            {'audio.samples': Artifact('earnest.audio-samples.v1', {'samples': signal, 'sample_rate_hz': self.fs}, source='reference')}, {})
        self.assertEqual(run.artifacts['audio.frequency_trace'].source, 'reference')
        with tempfile.TemporaryDirectory() as temp:
            src, out = Path(temp)/'input.wav', Path(temp)/'output.json'
            sf.write(src, signal, self.fs, subtype='FLOAT')
            self.assertEqual(main(['frequency-trace', str(src), '--out', str(out)]), 0)
            result = json.loads(out.read_text(encoding='utf-8'))
            self.assertAlmostEqual(result['frames'][0]['channels'][0]['peaks'][0]['hz'], 440, delta=.3)
            with self.assertRaises(SystemExit):
                main(['frequency-trace', str(src), '--out', str(out)])


if __name__ == '__main__':
    unittest.main()
