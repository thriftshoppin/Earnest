import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from earnest.cli import _room_template
from earnest.dsp import decay
from earnest.engine import RoomSpec
from earnest.engine.solve import _late_field, solve_room
from earnest.audio.profile import build_live_profile
from earnest.audio import stagejack

class DecayControlTests(unittest.TestCase):
    def test_decay_scales_rt_without_changing_physical_estimates(self):
        doc=_room_template();baseline=RoomSpec.from_dict(doc)
        prior=baseline.decay_estimates()
        doc['engine_controls']['decay_scale']=1.5
        longer=RoomSpec.from_dict(doc)
        for a,b in zip(prior,longer.decay_estimates()):
            self.assertAlmostEqual(a['sabine_rt60_s'],b['sabine_rt60_s'])
            self.assertAlmostEqual(a['eyring_rt60_s'],b['eyring_rt60_s'])
            self.assertAlmostEqual(b['effective_rt60_s'],a['effective_rt60_s']*1.5)
        for bad in (0,2.51,float('nan')):
            doc['engine_controls']['decay_scale']=bad
            with self.assertRaises(ValueError):RoomSpec.from_dict(doc)

    def test_synthesized_tail_tracks_target_slope(self):
        doc=_room_template();room=RoomSpec.from_dict(doc)
        rts=[]
        for target in (.45,.9):
            signal,meta=_late_field(room,3,3,0,target,24000,314)
            estimate=decay(signal**2,24000)
            self.assertIsNotNone(estimate['t20'])
            self.assertAlmostEqual(estimate['t20'],target,delta=target*.18)
            rts.append(estimate['t20'])
        self.assertGreater(rts[1],rts[0]*1.65)

    def test_room_solution_and_live_profile_use_effective_decay(self):
        doc=_room_template();doc['engine_controls']['decay_scale']=1.5
        room=RoomSpec.from_dict(doc);solution=solve_room(room,fs=24000,max_order=0)
        for row,meta in zip(solution['decay_estimates'],solution['source_receiver_pairs'][0]['diffuse_tail_by_band']):
            self.assertAlmostEqual(meta['rt60_s'],row['effective_rt60_s'])
        profile=build_live_profile(solution)
        self.assertAlmostEqual(profile['rt60_s'][0],round(solution['decay_estimates'][0]['effective_rt60_s'],6))

    def test_frankenjack_compilation_maps_decay_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'room.json';output=root/'room.erir'
            source.write_text(json.dumps(_room_template()))
            with patch.object(sys,'argv',['stagejack',str(source),str(output),'--decay','150','--tail','80']), \
                 patch.object(stagejack,'compile_room',return_value={'profile':str(output)}):
                stagejack.main()
            controls=json.loads(output.with_suffix('.room.json').read_text())['engine_controls']
            self.assertEqual(controls['decay_scale'],1.5)
            self.assertEqual(controls['tail_duration_scale'],.8)

if __name__=='__main__': unittest.main()
