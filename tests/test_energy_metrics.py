import math
import unittest
import numpy as np
from earnest.cli import _room_template
from earnest.engine import RoomSpec, solve_room
from earnest.engine.energy_metrics import energy_time_metrics

class EnergyTimeTests(unittest.TestCase):
    def test_discrete_impulses_and_boundaries(self):
        x=np.zeros(200);x[10]=1;x[59]=1;x[60]=1;x[90]=1;x[100]=1
        result=energy_time_metrics(x,1000,10)
        self.assertEqual(result['early_50_energy'],2)
        self.assertEqual(result['late_50_energy'],3)
        self.assertEqual(result['early_80_energy'],3)
        self.assertEqual(result['late_80_energy'],2)
        self.assertAlmostEqual(result['c50_db'],10*math.log10(2/3))
        self.assertAlmostEqual(result['c80_db'],10*math.log10(3/2))
        self.assertAlmostEqual(result['d50'],.4)
        self.assertAlmostEqual(result['center_time_ms'],(0+49+50+80+90)/5)

    def test_undefined_and_input_validation(self):
        empty=energy_time_metrics(np.zeros(100),1000,0)
        self.assertIsNone(empty['c50_db']);self.assertIsNone(empty['d50'])
        x=np.zeros(100);x[0]=1
        self.assertIsNone(energy_time_metrics(x,1000,0)['c50_db'])
        for arr,fs,start in [([],1000,0),([1,float('nan')],1000,0),([1],0,0),([1],1000,2)]:
            with self.assertRaises(ValueError):energy_time_metrics(arr,fs,start)

    def test_room_solver_emits_seven_band_metrics(self):
        doc=_room_template();doc['engine_controls']['diffuse_energy_scale']=0
        solved=solve_room(RoomSpec.from_dict(doc),fs=24000,max_order=0)
        for pair in solved['source_receiver_pairs']:
            self.assertEqual(len(pair['energy_time_metrics_by_band']),7)
            self.assertAlmostEqual(pair['energy_time_metrics_by_band'][0]['d50'],1)
            self.assertIsNone(pair['energy_time_metrics_by_band'][0]['c50_db'])

if __name__ == '__main__':unittest.main()
