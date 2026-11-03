import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
from earnest.cli import main
from earnest.engine.effect_pursuit import pursue_echoes


class EffectPursuitTests(unittest.TestCase):
    def test_overlapping_sources_keep_leakage_visible(self):
        rng=np.random.default_rng(2026)
        a=rng.normal(size=4096); b=rng.normal(size=4096)
        echo=np.r_[np.zeros(37),a[:-37]]
        observed=.7*a+.2*echo+.3*b
        report,pred,res=pursue_echoes(observed,a,8000,max_delay_samples=64,max_layers=2)
        self.assertEqual({item['delay_samples'] for item in report['layers']},{0,37})
        np.testing.assert_allclose(pred[:,0]+res[:,0],observed,atol=1e-12)
        # Correlated finite signals leak into the fit: do not claim exact isolation.
        self.assertGreater(np.linalg.norm(res[:,0]-.3*b),0)
        self.assertLess(np.linalg.norm(res[:,0]-.3*b),.1*np.linalg.norm(.3*b))

    def test_known_direct_and_echo_and_split_with_changing_instrument_levels(self):
        # Two supplied dry instrument tracks, deliberately separated in time so
        # the selected delay candidates are orthogonal in this reference case.
        a=np.zeros(512); a[30]=1
        b=np.zeros(512); b[350]=1
        for gain in (.25, .8, 1.5):
            y=gain*a+.35*np.roll(a,45)+.4*b
            report,pred,res=pursue_echoes(y,a,8000,max_delay_samples=80,max_layers=3)
            self.assertEqual({layer['delay_samples'] for layer in report['layers']},{0,45})
            np.testing.assert_allclose(pred[:,0],gain*a+.35*np.roll(a,45),atol=1e-12)
            np.testing.assert_allclose(res[:,0],.4*b,atol=1e-12)
            np.testing.assert_allclose(pred[:,0]+res[:,0],y,atol=1e-12)
            self.assertAlmostEqual(report['residual_energy'],.16,places=12)
            self.assertAlmostEqual(report['final_comparison']['channels'][0]['residual_mean_square'],.16/512,places=12)

    def test_negative_gain_cutoff_and_silence(self):
        x=np.zeros(128); x[0]=1
        y=x-.5*np.roll(x,10)
        report,_,res=pursue_echoes(y,x,8000,max_delay_samples=20,layer_penalty=.21)
        self.assertEqual(len(report['layers']),1)
        self.assertAlmostEqual(np.sum(res**2),.25)
        report,_,res=pursue_echoes(y,x,8000,max_delay_samples=20)
        self.assertAlmostEqual(report['layers'][1]['gain'],-.5)
        np.testing.assert_allclose(res,0,atol=1e-12)
        report,_,_=pursue_echoes(np.zeros(128),x,8000,max_delay_samples=20)
        self.assertEqual(report['layers'],[])

    def test_validation_and_cli(self):
        x=np.zeros(128); x[0]=1
        with self.assertRaises(ValueError): pursue_echoes(x,np.zeros(128),8000,max_delay_samples=10)
        with self.assertRaises(ValueError): pursue_echoes(x,x,8000,max_delay_samples=128)
        with self.assertRaises(ValueError): pursue_echoes(x,x,8000,max_delay_samples=10,layer_penalty=-1)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); sf.write(p/'dry.wav',x,8000,subtype='FLOAT');sf.write(p/'wet.wav',x,8000,subtype='FLOAT')
            sf.write(p/'remainder.wav',np.zeros(128),8000,subtype='FLOAT')
            args=['effect-pursuit',str(p/'wet.wav'),'--dry',str(p/'dry.wav'),'--target',str(p/'wet.wav'),
                  '--remainder-reference',str(p/'remainder.wav'),'--max-delay-samples','10','--out',str(p/'out')]
            self.assertEqual(main(args),0)
            report=json.loads((p/'out/pursuit.json').read_text())
            self.assertEqual(report['layers'][0]['delay_samples'],0)
            self.assertEqual(len(report['inputs']['dry']['sha256']),64)
            self.assertLess(report['validation']['target']['channels'][0]['residual_mean_square'],1e-25)
            self.assertLess(report['validation']['remainder']['channels'][0]['residual_mean_square'],1e-25)
            self.assertTrue((p/'out/residual.wav').exists())
            with self.assertRaises(SystemExit): main(args)


if __name__=='__main__': unittest.main()
