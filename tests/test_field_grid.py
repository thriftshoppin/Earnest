import copy
import math
import cmath
import numpy as np
import unittest
import tempfile
import json
from pathlib import Path
from earnest.cli import main
from earnest.cli import _room_template
from earnest.engine import Artifact, EngineError, RoomSpec, create_engine
from earnest.engine.field_grid import sample_room_field

class FieldGridTests(unittest.TestCase):
    def simple(self):
        d=_room_template();d['geometry']['dimensions']=[6,6,3]
        d['sources']=[{'id':'speaker','position':[1,3,1]}]
        d['receivers']=[{'id':'listener','position':[3,3,1]}]
        return d
    def test_direct_field_follows_inverse_square(self):
        room=RoomSpec.from_dict(self.simple())
        field=sample_room_field(room,frequency_hz=1000,grid_size=3,height_m=1,reflection_order=0)
        rows=field['relative_level_db']
        self.assertIsNone(rows[1][0])
        # At (3,3,1) the source distance is 2m; at (5,3,1) it is 4m.
        self.assertAlmostEqual(rows[1][2]-rows[1][1],-10*math.log10(4),places=10)
        self.assertEqual(field['cell_spacing_m'],[2,2])
    def test_first_reflections_match_analytical_images(self):
        room=RoomSpec.from_dict(self.simple()); f=1000; c=room.sound_speed_m_s()
        actual=sample_room_field(room,grid_size=3,height_m=1,reflection_order=1)
        # Independent image construction for a 6x6x3 room and source (1,3,1).
        image_positions=[(1,3,1),(-1,3,1),(11,3,1),(1,-3,1),(1,9,1),(1,3,-1),(1,3,5)]
        reflection_gain=math.sqrt((1-.05)*(1-.10))
        powers=[]
        for j in range(3):
            row=[]
            for i in range(3):
                point=(2*i+1,2*j+1,1)
                if point==(1,3,1):row.append(None);continue
                value=0j
                for k,image in enumerate(image_positions):
                    distance=math.dist(image,point)
                    value+=(1 if k==0 else reflection_gain)*cmath.exp(-2j*math.pi*f*distance/c)/distance
                row.append(abs(value)**2)
            powers.append(row)
        peak=max(v for row in powers for v in row if v is not None)
        for j,row in enumerate(powers):
            for i,v in enumerate(row):
                if v is not None:self.assertAlmostEqual(actual['relative_level_db'][j][i],10*math.log10(v/peak),places=9)

    def test_two_uncorrelated_identical_sources_double_power_without_changing_relative_map(self):
        d=self.simple();r1=sample_room_field(RoomSpec.from_dict(d),grid_size=4,reflection_order=0)
        second=copy.deepcopy(d['sources'][0]);second['id']='second';d['sources'].append(second)
        r2=sample_room_field(RoomSpec.from_dict(d),grid_size=4,reflection_order=0)
        for a,b in zip(sum(r1['relative_level_db'],[]),sum(r2['relative_level_db'],[])):
            if a is None:self.assertIsNone(b)
            else:self.assertAlmostEqual(a,b,places=10)
    def test_coherent_sources_interfere_at_equal_distance(self):
        doc=self.simple();doc['sources'].append({'id':'other','position':[5,3,1]})
        room=RoomSpec.from_dict(doc)
        independent=sample_room_field(room,grid_size=3,height_m=1,reflection_order=0)
        same=sample_room_field(room,grid_size=3,height_m=1,reflection_order=0,correlation_mode='in_phase')
        opposed=sample_room_field(room,grid_size=3,height_m=1,reflection_order=0,correlation_mode='opposed')
        self.assertEqual(same['correlation_mode'],'in_phase')
        self.assertLessEqual(opposed['relative_level_db'][1][1], -250)
        self.assertLess(same['relative_level_db'][0][0], independent['relative_level_db'][0][0])

    def test_complex_correlation_and_invalid_matrices(self):
        doc=self.simple();doc['sources'].append({'id':'other','position':[5,3,1]})
        room=RoomSpec.from_dict(doc)
        matrix=[[[1,0],[0,1]],[[0,-1],[1,0]]]
        custom=sample_room_field(room,grid_size=3,height_m=1,reflection_order=0,source_correlation=matrix)
        self.assertEqual(custom['source_correlation'],matrix)
        self.assertEqual(custom['correlation_mode'],'custom')
        source_points=[(1,3,1),(5,3,1)]
        corr=np.array([[1,1j],[-1j,1]],dtype=complex)
        raw=[]
        for j in range(3):
            row=[]
            for i in range(3):
                point=(1+2*i,1+2*j,1)
                if point in source_points:row.append(None);continue
                distance=[math.dist(point,source) for source in source_points]
                h=np.array([cmath.exp(-2j*math.pi*1000*r/room.sound_speed_m_s())/r for r in distance])
                row.append(max(float(np.real(h @ corr @ h.conj())),0))
            raw.append(row)
        peak=max(v for row in raw for v in row if v is not None)
        for j,row in enumerate(raw):
            for i,v in enumerate(row):
                if v and v>1e-12:self.assertAlmostEqual(custom['relative_level_db'][j][i],10*math.log10(v/peak),places=9)
        for bad in ([[[1,0],[2,0]],[[2,0],[1,0]]], [[[1,0],[0,1]],[[0,1],[1,0]]], [[[0,0],[0,0]],[[0,0],[1,0]]]):
            with self.subTest(matrix=bad),self.assertRaises(ValueError):
                sample_room_field(room,grid_size=3,source_correlation=bad)
        with self.assertRaises(ValueError):
            sample_room_field(RoomSpec.from_dict(self.simple()),correlation_mode='opposed')
        with self.assertRaises(ValueError):
            sample_room_field(room,correlation_mode='in_phase',source_correlation=matrix)

    def test_cli_writes_field_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            room, target = Path(temp)/'room.json', Path(temp)/'field.json'
            room.write_text(json.dumps(self.simple()))
            self.assertEqual(main(['room-field',str(room),'--grid','3','--order','0','--out',str(target)]),0)
            self.assertEqual(json.loads(target.read_text())['grid_size'],3)
            with self.assertRaises(SystemExit):main(['room-field',str(room),'--grid','3','--out',str(target)])

    def test_directionality_and_validation(self):
        d=self.simple();d['sources'][0].update(directivity='cardioid',orientation=[-1,0,0])
        field=sample_room_field(RoomSpec.from_dict(d),grid_size=3,height_m=1,reflection_order=0)
        self.assertLessEqual(field['relative_level_db'][1][1], -250)
        room=RoomSpec.from_dict(self.simple())
        for kwargs in ({'frequency_hz':300},{'grid_size':22},{'height_m':0},{'reflection_order':2}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):sample_room_field(room,**kwargs)
        result=create_engine().execute(('room.field_slice',),{'room.model':Artifact('room',room)}, {'room.field_slice':{'grid_size':3,'reflection_order':0}})
        self.assertEqual(result.artifacts['room.field_slice'].value['schema'],'earnest.room-field-slice.v1')

if __name__=='__main__':unittest.main()
