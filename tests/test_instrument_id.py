import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
import soundfile as sf
from earnest.engine.instrument_id import features, train, identify
from earnest.engine import Artifact, create_engine
from earnest.cli import main

class InstrumentIdTests(unittest.TestCase):
    def test_validation_and_level_invariance(self):
        t=np.arange(16000)/16000
        x=np.sin(2*np.pi*440*t)
        np.testing.assert_allclose(features(x,16000),features(x*.2,16000),atol=1e-7)
        for bad in [np.zeros(1024), np.array([np.nan]*1024), np.zeros(100)]:
            with self.assertRaises(ValueError): features(bad,16000)

    def test_train_classify_component_and_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); t=np.arange(16000)/16000
            examples={'acoustic': .4*np.sin(2*np.pi*220*t),
                      'synthetic_percussion': .5*np.sin(2*np.pi*1200*t)*np.exp(-10*t)}
            for label, audio in examples.items():
                (base/label).mkdir()
                sf.write(base/label/'a.wav',audio,16000,subtype='FLOAT')
            model=train(base)
            result=identify(examples['synthetic_percussion'],16000,model)
            self.assertEqual(result['candidates'][0]['label'],'synthetic_percussion')
            self.assertLess(result['candidates'][0]['distance'], 1e-4)
            out=base/'model.json'
            self.assertEqual(main(['instrument-train',str(base),'--out',str(out)]),0)
            self.assertEqual(main(['instrument-identify',str(base/'acoustic'/'a.wav'),'--model',str(out)]),0)
            with self.assertRaises(SystemExit): main(['instrument-train',str(base),'--out',str(out)])
            run=create_engine().execute(('instrument.identify',), {'audio.samples': Artifact('samples',{'samples':examples['acoustic'],'sample_rate_hz':16000}), 'instrument.reference_model':Artifact('model',model)})
            self.assertEqual(run.artifacts['instrument.identification'].value['candidates'][0]['label'],'acoustic')
            with self.assertRaises(ValueError): identify(examples['acoustic'],16000,{'schema':'wrong'})

if __name__ == '__main__': unittest.main()
