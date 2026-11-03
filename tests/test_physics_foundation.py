"""Equation checks against published values and independent analytical cases.

Sources are referenced in docs/PHYSICS_NOTES.md. No sound is played.
"""
import copy
import math
import unittest
import numpy as np

from earnest.cli import _room_template
from earnest.engine import Artifact, EngineError, RoomSpec, create_engine
from earnest.engine.physics import (air_absorption_db_per_m, ideal_string_modes,
                                    ideal_pipe_modes, stiff_string_modes, circular_membrane_modes,
                                    directivity_pressure)
from earnest.engine.shoebox import image_paths
from earnest.engine.solve import solve_room, _late_field
from earnest.engine.calibration import _target_absorption_scale
from earnest.engine.render import render_room


class AirAbsorptionTests(unittest.TestCase):
    def test_against_npl_published_iso_reference_values(self):
        # NPL validation table, pressure 101.325 kPa. Values are rounded dB/m.
        cases = [(125.89, 0, 40, 0.000427), (316.23, 20, 80, 0.001504),
                 (1000.0, 45, 20, 0.010102), (5011.87, 5, 90, 0.050175)]
        for f, temperature, humidity, expected in cases:
            with self.subTest(frequency=f):
                actual = air_absorption_db_per_m(f, temperature, humidity)
                self.assertAlmostEqual(actual, expected, delta=expected * 0.008)

    def test_zero_frequency_and_nonphysical_inputs(self):
        self.assertEqual(air_absorption_db_per_m(0, 20, 50), 0.0)
        for values in [(-1, 20, 50, 101325), (1000, 51, 50, 101325),
                       (1000, 20, 101, 101325), (1000, 20, 50, 0),
                       (float('nan'), 20, 50, 101325), (1000, 50, 100, 10000)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                air_absorption_db_per_m(*values)

    def test_path_pressure_attenuation_and_legacy_default(self):
        document = _room_template()
        disabled = RoomSpec.from_dict(document)
        legacy = copy.deepcopy(document)
        legacy['environment'].pop('air_absorption_enabled', None)
        legacy['environment'].pop('pressure_pa', None)
        old = RoomSpec.from_dict(legacy)
        enabled_doc = copy.deepcopy(document)
        enabled_doc['environment']['air_absorption_enabled'] = True
        enabled = RoomSpec.from_dict(enabled_doc)
        def paths(room):
            return {p.image_index: p for p in image_paths(room, room.sources[0], room.receivers[0], 1)}
        base, prior, changed = paths(disabled), paths(old), paths(enabled)
        self.assertEqual(base, prior)
        for key, p in base.items():
            for i, f in enumerate((125, 250, 500, 1000, 2000, 4000, 8000)):
                attenuation = air_absorption_db_per_m(f, 20, 50)
                self.assertAlmostEqual(changed[key].gain_by_band[i],
                    p.gain_by_band[i] * 10 ** (-attenuation * p.distance_m / 20), places=12)

    def test_diffuse_decay_air_term_and_legacy_compatibility(self):
        doc = _room_template()
        baseline = RoomSpec.from_dict(doc)
        doc['environment']['air_absorption_enabled'] = True
        room = RoomSpec.from_dict(doc)
        areas = room.wall_areas()
        surface = sum(areas.values())
        c = room.sound_speed_m_s()
        for band, row in enumerate(room.decay_estimates()):
            alpha_db = air_absorption_db_per_m(row['hz'], 20, 50, 101325)
            air_area = 4 * room.volume_m3 * alpha_db * math.log(10) / 10
            a = row['absorption_area_m2']
            expected_sabine = (24 * math.log(10) / c) * room.volume_m3 / (a + air_area)
            expected_eyring = (24 * math.log(10) / c) * room.volume_m3 / (-surface * math.log1p(-a/surface) + air_area)
            self.assertAlmostEqual(row['air_absorption_area_m2'], air_area, places=12)
            self.assertAlmostEqual(row['sabine_rt60_s'], expected_sabine, places=12)
            self.assertAlmostEqual(row['eyring_rt60_s'], expected_eyring, places=12)
            self.assertLess(row['sabine_rt60_s'], baseline.decay_estimates()[band]['sabine_rt60_s'])
        self.assertEqual(baseline.air_absorption_area_m2(6), 0)

    def test_fit_uses_same_air_corrected_equation(self):
        for model in ('sabine', 'eyring'):
            doc = _room_template()
            doc['environment']['air_absorption_enabled'] = True
            doc['engine_controls']['decay_model'] = model
            doc['engine_controls']['absorption_scale'] = [0.6] * 7
            target_room = RoomSpec.from_dict(doc)
            for band, row in enumerate(target_room.decay_estimates()):
                target = row[model + '_rt60_s']
                scale, predicted = _target_absorption_scale(target_room, band, target)
                self.assertAlmostEqual(scale, .6, places=9)
                self.assertAlmostEqual(predicted, target, places=9)

    def test_air_only_absorption_has_finite_decay_and_tail(self):
        doc = _room_template()
        doc['materials'][0]['absorption'] = [0] * 7
        doc['environment']['air_absorption_enabled'] = True
        room = RoomSpec.from_dict(doc)
        rt = room.decay_estimates()[6]['sabine_rt60_s']
        self.assertGreater(rt, 0)
        tail, meta = _late_field(room, 6, 1, 0, rt, 24000, 42)
        self.assertGreater(len(tail), 0)
        self.assertAlmostEqual(float(np.sum(tail**2)), meta['late_energy'], places=10)
        doc['environment']['air_absorption_enabled'] = False
        self.assertIsNone(RoomSpec.from_dict(doc).decay_estimates()[6]['sabine_rt60_s'])

    def test_points_on_each_room_boundary_are_rejected(self):
        document = _room_template()
        for index in range(3):
            for coordinate in (0, document['geometry']['dimensions'][index]):
                candidate = copy.deepcopy(document)
                candidate['sources'][0]['position'][index] = coordinate
                with self.subTest(axis=index, coordinate=coordinate), self.assertRaises(ValueError):
                    RoomSpec.from_dict(candidate)


class ResonatorTests(unittest.TestCase):
    def test_ideal_string_modes_from_known_wave_speed(self):
        # T/mu = 10000 -> c = 100 m/s, L = 0.5 m -> f1 = 100 Hz.
        self.assertEqual(ideal_string_modes(0.5, 100, 0.01, 3), [100.0, 200.0, 300.0])

    def test_open_and_closed_tube_boundary_conditions(self):
        self.assertEqual(ideal_pipe_modes(1, 340, 'open-open', 3), [170.0, 340.0, 510.0])
        self.assertEqual(ideal_pipe_modes(1, 340, 'open-closed', 3), [85.0, 255.0, 425.0])
        with self.assertRaises(ValueError):
            ideal_pipe_modes(1, 340, 'unknown')

    def test_stiff_string_reduces_to_ideal_and_stretches_partials(self):
        ideal = ideal_string_modes(0.5, 100, 0.01, 3)
        self.assertEqual(stiff_string_modes(0.5, 100, 0.01, 0, 3), ideal)
        result = stiff_string_modes(0.5, 100, 0.01, 0.001, 3)
        for n, value in enumerate(result, 1):
            self.assertAlmostEqual(value, n * 100.0 * math.sqrt(1 + .001 * n * n))
        with self.assertRaises(ValueError):
            stiff_string_modes(0.5, 100, 0.01, -1, 3)

    def test_membrane_bessel_zero_ratios(self):
        # The first J0 and J1 zeros, and their ratio, are tabulated modal constants.
        modes = circular_membrane_modes(1, 100, 1, 2)
        self.assertEqual((modes[0]['angular_order'], modes[0]['radial_index']), (0, 1))
        self.assertEqual((modes[1]['angular_order'], modes[1]['radial_index']), (1, 1))
        self.assertAlmostEqual(modes[0]['frequency_hz'], 2.4048255577 * 10 / (2 * math.pi), places=9)
        self.assertAlmostEqual(modes[1]['frequency_hz'] / modes[0]['frequency_hz'], 1.59334, places=4)

    def test_engine_component_and_validation(self):
        model = {'kind': 'ideal-string', 'length_m': .5, 'tension_n': 100,
                 'linear_density_kg_m': .01, 'count': 2}
        output = create_engine().execute(('instrument.modes',),
            {'instrument.model': Artifact('earnest.instrument-model.v1', model)})
        self.assertEqual(output.artifacts['instrument.modes'].value['frequencies_hz'], [100, 200])
        for bad in [0, -1, float('nan')]:
            model['length_m'] = bad
            with self.assertRaises(EngineError):
                create_engine().execute(('instrument.modes',),
                    {'instrument.model': Artifact('earnest.instrument-model.v1', model)})


class DirectionalityTests(unittest.TestCase):
    def test_cardioid_and_figure_eight_polar_response(self):
        axis = (1, 0, 0)
        for pattern, expected in [('omni', (1, 1, 1)), ('cardioid', (1, .5, 0)), ('figure8', (1, 0, -1))]:
            for ray, value in zip(((1, 0, 0), (0, 1, 0), (-1, 0, 0)), expected):
                with self.subTest(pattern=pattern, ray=ray):
                    self.assertAlmostEqual(directivity_pressure(pattern, axis, ray), value)
        with self.assertRaises(ValueError):
            directivity_pressure('cardioid', (0, 0, 0), axis)

    def test_reflected_source_ray_is_mirrored_in_physical_frame(self):
        doc = _room_template()
        doc['sources'] = [dict(id='s', position=[2, 2, 1], directivity='figure8', orientation=[1, 0, 0])]
        doc['receivers'] = [dict(id='r', position=[4, 2, 1])]
        room = RoomSpec.from_dict(doc)
        paths = image_paths(room, room.sources[0], room.receivers[0], 1)
        direct = next(p for p in paths if p.image_index == (0, 0, 0))
        low_wall = next(p for p in paths if p.image_index == (1, 0, 0))
        self.assertAlmostEqual(direct.directivity_gain, 1.0)
        self.assertAlmostEqual(low_wall.directivity_gain, -1.0)

    def test_receiver_cardioid_uses_direction_toward_incoming_source(self):
        doc = _room_template()
        doc['sources'] = [dict(id='s', position=[2, 2, 1])]
        doc['receivers'] = [dict(id='r', position=[4, 2, 1], directivity='cardioid', orientation=[-1, 0, 0])]
        room = RoomSpec.from_dict(doc)
        direct = image_paths(room, room.sources[0], room.receivers[0], 0)[0]
        self.assertAlmostEqual(direct.directivity_gain, 1.0)
        doc['receivers'][0]['orientation'] = [1, 0, 0]
        room = RoomSpec.from_dict(doc)
        self.assertAlmostEqual(image_paths(room, room.sources[0], room.receivers[0], 0)[0].directivity_gain, 0.0)

    def test_directional_null_and_polarity_reach_renderer(self):
        doc = _room_template()
        doc['sources'] = [dict(id='s', position=[2, 2, 1], directivity='cardioid', orientation=[-1, 0, 0])]
        doc['receivers'] = [dict(id='r', position=[4, 2, 1])]
        doc['engine_controls']['diffuse_energy_scale'] = 0
        room = RoomSpec.from_dict(doc)
        solution = solve_room(room, fs=24000, max_order=0)
        self.assertEqual(solution['source_receiver_pairs'][0]['directivity_gain'], 0.0)
        source = np.zeros((1024, 1)); source[10, 0] = .1
        output = render_room(room, solution, source, fs=24000)['receiver_outputs']['r']
        self.assertLess(np.max(np.abs(output['audio'])), 1e-12)
        doc['sources'][0]['directivity'] = 'figure8'
        room = RoomSpec.from_dict(doc)
        solution = solve_room(room, fs=24000, max_order=0)
        self.assertEqual(solution['source_receiver_pairs'][0]['directivity_gain'], -1.0)
        output = render_room(room, solution, source, fs=24000)['receiver_outputs']['r']
        self.assertLess(float(np.min(output['direct_audio'])), -.01)


if __name__ == '__main__':
    unittest.main()
