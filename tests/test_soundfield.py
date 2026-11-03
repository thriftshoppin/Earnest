import copy
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from earnest.engine.soundfield import propagate_spectra, room_path_spectra
from earnest.engine import RoomSpec, solve_room
from earnest.cli import _room_template
from earnest.engine import Artifact, create_engine
from earnest.cli import main


def doc():
    return {'schema':'earnest.soundfield-input.v1', 'frequencies_hz':[1000],
            'sources':['left','right'], 'receivers':['seat'],
            'transfers':[[[[1,0],[1,0]]]],
            'source_csd':[[[[1,0],[0,0]],[[0,0],[1,0]]]]}

class SoundfieldTests(unittest.TestCase):
    def test_independent_and_coherent_limits(self):
        d=doc()
        self.assertAlmostEqual(propagate_spectra(d)['receiver_power'][0][0],2)
        d['source_csd'][0][0][1]=[1,0];d['source_csd'][0][1][0]=[1,0]
        self.assertAlmostEqual(propagate_spectra(d)['receiver_power'][0][0],4)
        d['transfers'][0][0][1]=[-1,0]
        self.assertAlmostEqual(propagate_spectra(d)['receiver_power'][0][0],0)

    def test_complex_phase_and_receiver_cross_spectrum(self):
        d=doc();d['receivers']=['a','b'];d['transfers']=[[[[1,0],[0,0]],[[0,1],[0,0]]]]
        result=propagate_spectra(d)['receiver_csd'][0]
        np.testing.assert_allclose(result[0][1],[0,-1],atol=1e-12)
        np.testing.assert_allclose(result[1][0],[0,1],atol=1e-12)
        d['source_csd']=[[[[1,0],[0,1]],[[0,-1],[1,0]]]]
        d['receivers']=['a'];d['transfers']=[[[[1,0],[0,1]]]]
        self.assertAlmostEqual(propagate_spectra(d)['receiver_power'][0][0],4)

    def test_validation_of_nonphysical_spectra(self):
        bad=doc();bad['source_csd'][0][0][1]=[1,0]
        with self.assertRaisesRegex(ValueError,'Hermitian'):propagate_spectra(bad)
        bad=doc();bad['source_csd'][0][0][1]=[2,0];bad['source_csd'][0][1][0]=[2,0]
        with self.assertRaisesRegex(ValueError,'positive semidefinite'):propagate_spectra(bad)
        for mutate in (lambda d:d.update(frequencies_hz=[-1]),lambda d:d.update(transfers=[]),lambda d:d.update(sources=['x','x'])):
            bad=doc();mutate(bad)
            with self.assertRaises(ValueError):propagate_spectra(bad)

    def test_room_paths_direct_distance_and_phase(self):
        room = RoomSpec.from_dict(_room_template())
        solution = solve_room(room, fs=24000, max_order=0)
        src = {'schema':'earnest.source-spectra.v1', 'sources':['speaker_left','speaker_right'],
               'frequencies_hz':[1000], 'source_csd':[[[[1,0],[0,0]],[[0,0],[0,0]]]]}
        result = room_path_spectra(solution, src)
        distance = solution['source_receiver_pairs'][0]['direct_distance_m']
        self.assertAlmostEqual(result['receiver_power'][0][0], 1 / distance**2, places=12)
        run = create_engine().execute(('soundfield.from_room_paths',), {'room.solution':Artifact('room',solution), 'soundfield.source_spectra':Artifact('sources',src)})
        self.assertEqual(run.artifacts['soundfield.spectrum'].value['model'], 'explicit-image-paths-nearest-octave-v1')
        with tempfile.TemporaryDirectory() as tmp:
            model, inputs, output = (Path(tmp)/x for x in ('room.json','sources.json','out.json'))
            model.write_text(json.dumps(solution));inputs.write_text(json.dumps(src))
            self.assertEqual(main(['soundfield-spectrum',str(inputs),'--room-solution',str(model),'--out',str(output)]),0)
            self.assertAlmostEqual(json.loads(output.read_text())['receiver_power'][0][0],1/distance**2,places=12)
        src['sources']=['missing']
        with self.assertRaises(ValueError):room_path_spectra(solution,src)

    def test_engine_and_cli(self):
        d=doc();run=create_engine().execute(('soundfield.propagate',),{'soundfield.input':Artifact('input',d,source='test')})
        self.assertEqual(run.artifacts['soundfield.spectrum'].source,'test')
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'input.json';out=Path(tmp)/'output.json';source.write_text(json.dumps(d))
            self.assertEqual(main(['soundfield-spectrum',str(source),'--out',str(out)]),0)
            self.assertEqual(json.loads(out.read_text())['receiver_power'],[[2.0]])
            with self.assertRaises(SystemExit):main(['soundfield-spectrum',str(source),'--out',str(out)])

if __name__=='__main__':unittest.main()
