"""Analytical regression cases for room and signal-processing boundaries."""
import copy
import math
import unittest

import numpy as np
from scipy.signal import sosfreqz

from earnest.cli import _room_template
from earnest.dsp import bandpass_fft, deconvolve, iacc
from earnest.engine.calibration import _target_absorption_scale, fit_formula
from earnest.engine.render import _partition_audio, render_room
from earnest.engine.room import RoomSpec, RoomValidationError
from earnest.engine.session import _eq_sos
from earnest.engine.shoebox import image_paths
from earnest.engine.solve import solve_room


class EngineMathRegressions(unittest.TestCase):
    def test_partition_reconstructs_and_does_not_wrap(self):
        x = np.zeros(1024)
        x[-1] = 1.0
        bands, residual = _partition_audio(x, 48000)
        np.testing.assert_allclose(sum(bands) + residual, x, atol=1e-12)
        self.assertLess(abs(bands[3][0]), 1e-8)
        self.assertLess(abs(bandpass_fft(x, 48000, 1000)[0]), 1e-8)

    def test_iacc_absolute_peak_for_both_polarities(self):
        a = np.random.default_rng(7).normal(size=4096)
        self.assertAlmostEqual(iacc(a, a, 48000), 1.0, places=12)
        self.assertAlmostEqual(iacc(a, -a, 48000), 1.0, places=12)
        self.assertIsNone(iacc(np.zeros(128), np.zeros(128), 48000))
        with self.assertRaises(ValueError):
            iacc(a, a[:-1], 48000)

    def test_deconvolution_silent_and_direct(self):
        with self.assertRaisesRegex(ValueError, "silent"):
            deconvolve(np.zeros(512), np.zeros(512))
        dry = np.random.default_rng(3).normal(size=4096)
        h, zero = deconvolve(dry, dry, eps_rel=1e-8, neg_s=0.001)
        self.assertAlmostEqual(h[zero], 1.0, places=5)

    def test_fitting_full_absorption_and_unreachable_target(self):
        document = _room_template()
        document["materials"][0]["absorption"] = [1.0] * 7
        room = RoomSpec.from_dict(document)
        scale, predicted = _target_absorption_scale(room, 0, 0.5)
        self.assertGreaterEqual(scale, 0.0)
        self.assertAlmostEqual(predicted, 0.5, places=8)
        document["materials"][0]["absorption"] = [0.0] * 7
        formula = {"schema": "earnest.measurement.v1", "bands": [{"hz": 125, "rt60_s": 0.5}]}
        row = fit_formula(document, formula)["analysis_evidence"]["fit"][0]
        self.assertEqual(row["status"], "boundary")
        self.assertIsNone(row["predicted_rt60_s"])

    def test_sabine_eyring_and_first_order_geometry(self):
        room = RoomSpec.from_dict(_room_template())
        row = room.decay_estimates()[0]
        self.assertAlmostEqual(row["sabine_rt60_s"], 24 * math.log(10) * room.volume_m3 /
                               (room.sound_speed_m_s() * row["absorption_area_m2"]), places=12)
        paths = image_paths(room, room.sources[0], room.receivers[0], 1)
        self.assertEqual(len(paths), 7)
        self.assertAlmostEqual(paths[0].distance_m,
                               math.dist(room.sources[0].position, room.receivers[0].position), places=12)
        x, y, z = room.sources[0].position
        l, w, h = room.dimensions
        receiver = room.receivers[0].position
        images = [(-x,y,z), (2*l-x,y,z), (x,-y,z), (x,2*w-y,z), (x,y,-z), (x,y,2*h-z)]
        expected = sorted(math.dist(p, receiver) for p in images)
        np.testing.assert_allclose(sorted(p.distance_m for p in paths[1:]), expected, atol=1e-12)

    def test_coincident_points_rejected(self):
        document = copy.deepcopy(_room_template())
        document["receivers"][0]["position"] = document["sources"][0]["position"][:]
        with self.assertRaisesRegex(RoomValidationError, "separated"):
            RoomSpec.from_dict(document)

    def test_eq_gain_at_center(self):
        sos = _eq_sos(48000, [0,0,0,0,0,6,0,0,0,0])
        _, response = sosfreqz(sos, worN=[2 * np.pi * 1000 / 48000])
        self.assertAlmostEqual(20 * math.log10(abs(response[0])), 6.0, places=9)

    def test_fully_absorbing_room_has_only_direct_sound(self):
        document = _room_template()
        document["materials"][0]["absorption"] = [1.0] * 7
        room = RoomSpec.from_dict(document)
        solution = solve_room(room, fs=24000, max_order=1)
        audio = np.zeros((2048, len(room.sources)))
        audio[100, :] = 0.1
        row = render_room(room, solution, audio, fs=24000)["receiver_outputs"][room.receivers[0].id]
        np.testing.assert_allclose(row["audio"], row["direct_audio"], atol=1e-12)


if __name__ == "__main__":
    unittest.main()
