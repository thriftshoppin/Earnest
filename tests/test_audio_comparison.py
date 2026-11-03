import json
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from earnest.cli import main
from earnest.engine import Artifact, create_engine
from earnest.engine.comparison import compare_audio, compare_audio_segments


class AudioComparisonTests(unittest.TestCase):
    def test_rank_candidates_and_record_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); reference=root/'reference.wav'; one=root/'one.wav'; two=root/'two.wav'; report=root/'rank.json'
            x=np.sin(2*np.pi*440*np.arange(8000)/8000)*.2
            sf.write(reference,x,8000,subtype='FLOAT'); sf.write(one,x*.9,8000,subtype='FLOAT'); sf.write(two,x*.5,8000,subtype='FLOAT')
            self.assertEqual(main(['audio-rank',str(reference),str(two),str(one),'--out',str(report)]),0)
            result=json.loads(report.read_text())
            self.assertEqual([Path(row['file']).name for row in result['candidates']], ['one.wav','two.wav'])
            self.assertEqual(result['reference_sha256'],hashlib.sha256(reference.read_bytes()).hexdigest())
            self.assertEqual(result['candidates'][0]['sha256'],hashlib.sha256(one.read_bytes()).hexdigest())
            self.assertLess(result['candidates'][0]['mean_square_error'],result['candidates'][1]['mean_square_error'])
            with self.assertRaises(SystemExit): main(['audio-rank',str(reference),str(one),'--out',str(report)])

    def test_localized_error_and_last_interval(self):
        rate=8000
        ref=np.zeros(20000); time=np.arange(8000)/rate
        ref[8000:16000]=.2*np.sin(2*np.pi*1000*time)
        segments=compare_audio_segments(ref,np.zeros_like(ref),rate,1)
        self.assertEqual([(s['start_sample'],s['end_sample_exclusive']) for s in segments],[(0,8000),(8000,16000),(16000,20000)])
        self.assertAlmostEqual(segments[0]['channels'][0]['residual_mean_square'],0)
        self.assertAlmostEqual(segments[1]['channels'][0]['residual_mean_square'],.02)
        self.assertAlmostEqual(segments[2]['channels'][0]['residual_mean_square'],0)
        with self.assertRaises(ValueError): compare_audio_segments(ref,np.zeros_like(ref),rate,float('nan'))

    def test_exact_and_known_missing_component(self):
        fs = 8000
        t = np.arange(fs) / fs
        tone = .2 * np.sin(2 * np.pi * 1000 * t)
        extra = .1 * np.sin(2 * np.pi * 2000 * t)
        report, residual = compare_audio(tone + extra, tone, fs)
        np.testing.assert_allclose(residual[:, 0], extra, atol=1e-14)
        channel = report['channels'][0]
        self.assertAlmostEqual(channel['residual_mean_square'], .005, places=10)
        band = next(b for b in channel['bands'] if b['low_hz'] == 2000)
        self.assertAlmostEqual(band['mean_square'], .005, places=10)
        self.assertAlmostEqual(sum(b['mean_square'] for b in channel['bands']), channel['residual_mean_square'], places=10)
        exact, _ = compare_audio(tone, tone, fs)
        self.assertEqual(exact['channels'][0]['residual_mean_square'], 0)
        self.assertIsNone(exact['channels'][0]['residual_to_reference_db'])

    def test_nyquist_and_odd_frame_parseval(self):
        for n in (4096, 4097):
            x = np.random.default_rng(2).normal(size=(n, 2))
            result, _ = compare_audio(x, np.zeros_like(x), 8000)
            for c in result['channels']:
                self.assertAlmostEqual(sum(b['mean_square'] for b in c['bands']), c['residual_mean_square'], places=10)

    def test_validation_component_and_cli(self):
        with self.assertRaises(ValueError): compare_audio([1, 2], [1], 8000)
        with self.assertRaises(ValueError): compare_audio([float('nan')], [0], 8000)
        arr = np.arange(32, dtype=float) / 100
        audio = {'samples': arr, 'sample_rate_hz': 8000}
        run = create_engine().execute(('audio.compare',), {'audio.reference': Artifact('audio', audio), 'audio.candidate': Artifact('audio', audio)})
        self.assertEqual(run.artifacts['audio.residual'].value['samples'].shape, (32, 1))
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp); a, b, out = folder/'a.wav', folder/'b.wav', folder/'report.json'
            sf.write(a, arr, 8000, subtype='FLOAT'); sf.write(b, arr, 8000, subtype='FLOAT')
            self.assertEqual(main(['audio-compare', str(a), str(b), '--segment-seconds', '0.01', '--out', str(out)]), 0)
            saved=json.loads(out.read_text())
            self.assertEqual(saved['channels'][0]['residual_mean_square'], 0)
            self.assertEqual(len(saved['segments']),1)
            with self.assertRaises(SystemExit): main(['audio-compare', str(a), str(b), '--out', str(out)])
            sf.write(b, arr, 16000, subtype='FLOAT')
            with self.assertRaises(SystemExit): main(['audio-compare', str(a), str(b), '--out', str(folder/'bad.json')])


if __name__ == '__main__': unittest.main()
