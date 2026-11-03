import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from earnest.cli import main
from earnest.engine import Artifact, create_engine
from earnest.engine.hypothesis import evaluate, read_note_events, rank_evaluations


class HypothesisTests(unittest.TestCase):
    def setUp(self):
        self.fs=16000
        t=np.arange(8192)/self.fs
        self.a=.2*np.sin(2*np.pi*440*t)
        self.b=.1*np.sin(2*np.pi*660*t)
        self.notes={'schema':'earnest.note-events.v1','events':[{'start_s':0,'end_s':1,'midi_pitch':69}]}

    def test_reconstruction_and_unexplained_partials(self):
        report,residual=evaluate(self.a+self.b,[self.a,self.b],self.fs,self.notes)
        np.testing.assert_allclose(residual,0,atol=1e-14)
        self.assertLess(report['reconstruction']['mean_square_error'],1e-25)
        self.assertGreater(report['spectral_support']['unexplained_peak_fraction'],.15)
        self.assertLess(report['spectral_support']['unexplained_peak_fraction'],.3)
        self.assertIsNone(report['temporal_mismatch']); self.assertIsNone(report['combined_score'])

    def test_wrong_timing_silence_missing_notes(self):
        late={'schema':'earnest.note-events.v1','events':[{'start_s':2,'end_s':3,'midi_pitch':69}]}
        report,_=evaluate(self.a,[self.a],self.fs,late)
        self.assertAlmostEqual(report['spectral_support']['unexplained_peak_fraction'],1)
        report,_=evaluate(np.zeros(8192),[np.zeros(8192)],self.fs,self.notes)
        self.assertIsNone(report['spectral_support']['unexplained_peak_fraction'])
        self.assertIsNone(report['reconstruction']['relative_error_power'])
        report,_=evaluate(self.a,[self.a],self.fs,None)
        self.assertIsNone(report['spectral_support'])
        misaligned,_=evaluate(self.a,[np.roll(self.a,30)],self.fs,None)
        self.assertGreater(misaligned['reconstruction']['mean_square_error'],.001)

    def test_invalid_shapes_notes_and_partial_frames(self):
        with self.assertRaises(ValueError): evaluate(self.a,[self.a[:-1]],self.fs,None)
        with self.assertRaises(ValueError): evaluate(self.a,[self.a],self.fs,{'schema':'earnest.note-events.v1','events':[{'start_s':1,'end_s':0,'midi_pitch':69}]})
        report,_=evaluate(self.a[:2000],[self.a[:2000]],self.fs,self.notes)
        self.assertEqual(report['spectral_support']['complete_frames'],0)
        self.assertIsNone(report['spectral_support']['unexplained_peak_fraction'])

    def test_csv_component_and_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); ref=root/'ref.wav'; stem=root/'stem.wav'; notes=root/'notes.csv'; out=root/'out'
            sf.write(ref,self.a,self.fs,subtype='FLOAT');sf.write(stem,self.a,self.fs,subtype='FLOAT')
            notes.write_text('start_time_s,end_time_s,pitch_midi,velocity,pitch_bend\n0,0.5,69,80,0,1,2\n')
            parsed=read_note_events(str(notes));self.assertEqual(parsed['events'][0]['midi_pitch'],69)
            run=create_engine().execute(('audio.hypothesis_evaluate',),{
                'audio.reference':Artifact('audio',{'samples':self.a,'sample_rate_hz':self.fs}),
                'audio.stems':Artifact('stems',[self.a]),'audio.note_events':Artifact('notes',parsed)})
            self.assertEqual(run.artifacts['audio.hypothesis_evaluation'].value['note_count'],1)
            self.assertEqual(main(['hypothesis-evaluate',str(ref),'--stem',str(stem),'--notes',str(notes),'--out',str(out)]),0)
            result=json.loads((out/'evaluation.json').read_text())
            self.assertEqual(result['inputs']['reference']['path'],str(ref.resolve()))
            self.assertTrue((out/'residual.wav').exists())
            self.assertEqual(result['note_hypothesis']['events'][0]['midi_pitch'],69)
            ranking=root/'ranking.json'
            self.assertEqual(main(['hypothesis-rank',str(out/'evaluation.json'), '--weight-reconstruction','1', '--weight-spectral','2','--out',str(ranking)]),0)
            self.assertEqual(json.loads(ranking.read_text())['ranked'][0]['input_index'],0)
            with self.assertRaises(SystemExit): main(['hypothesis-rank',str(out/'evaluation.json'),'--out',str(root/'invalid.json')])
            with self.assertRaises(SystemExit): main(['hypothesis-evaluate',str(ref),'--stem',str(stem),'--out',str(out)])

    def test_ranking_explicit_weights_and_comparability(self):
        good,_=evaluate(self.a,[self.a],self.fs,self.notes)
        bad,_=evaluate(self.a,[self.a*.5],self.fs,self.notes)
        for report in (good,bad): report['inputs']={'reference':{'sha256':'a'*64}}
        ranked=rank_evaluations([bad,good],{'reconstruction':2})
        self.assertEqual(ranked['ranked'][0]['input_index'],1)
        self.assertAlmostEqual(ranked['ranked'][1]['score'],-.5)
        self.assertAlmostEqual(rank_evaluations([good],{'complexity':1})['ranked'][0]['score'],-self.fs/8192)
        with self.assertRaises(ValueError): rank_evaluations([good],{})
        with self.assertRaises(ValueError): rank_evaluations([good],{'spectral':-1})
        bad['inputs']['reference']['sha256']='b'*64
        with self.assertRaises(ValueError): rank_evaluations([good,bad],{'reconstruction':1})
        bad['inputs']['reference']['sha256']='a'*64
        bad['spectral_support']['tolerance_cents']=20
        with self.assertRaises(ValueError): rank_evaluations([good,bad],{'spectral':1})
        good['spectral_support']=None
        with self.assertRaises(ValueError): rank_evaluations([good],{'spectral':1})


if __name__=='__main__': unittest.main()
