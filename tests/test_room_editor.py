"""Exercise the local editor API without starting audio or opening a browser."""
import json
import tempfile
from pathlib import Path

from earnest.room_instructions import make_instructions, apply_instructions
from earnest.cli import main
import threading
import unittest
import urllib.error
import urllib.request

from earnest.room_editor import create_server


class RoomEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = 'http://127.0.0.1:%d' % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def get(self, path):
        with urllib.request.urlopen(self.origin + path, timeout=10) as response:
            return response.read()

    def post(self, path, data, origin=None):
        request = urllib.request.Request(self.origin + path, data=json.dumps(data).encode(),
                  headers={'Content-Type': 'application/json', 'Origin': origin or self.origin})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    def test_template_validation_and_shoebox_solve(self):
        self.assertIn(b'ROOM STUDIO', self.get('/'))
        room = json.loads(self.get('/api/template'))
        valid = self.post('/api/validate', room)
        self.assertEqual(valid['volume_m3'], 8 * 5 * 2.8)
        room['engine_controls']['reflection_order'] = 0
        room['engine_controls']['diffuse_energy_scale'] = 0
        solved = self.post('/api/solve', room)
        self.assertEqual(len(solved['pairs']), 2)
        self.assertEqual(solved['interactive_reflection_order'], 0)
        self.assertTrue(all(p['path_count'] == 1 for p in solved['pairs']))

    def test_instructions_roundtrip_and_cli(self):
        room = json.loads(self.get('/api/template'))
        room['metadata'] = {'name': 'Custom room', 'extra': [1, 2, 3]}
        plan = self.post('/api/instructions', room)
        self.assertEqual(apply_instructions(plan), room)
        self.assertEqual(make_instructions(room), plan)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'instructions.json'
            out = Path(tmp) / 'room.json'
            src.write_text(json.dumps(plan), encoding='utf-8')
            self.assertEqual(main(['room-from-instructions', str(src), '--out', str(out)]), 0)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8')), room)
            with self.assertRaises(SystemExit):
                main(['room-from-instructions', str(src), '--out', str(out)])
        plan['instructions'].append(plan['instructions'][0])
        with self.assertRaises(ValueError):
            apply_instructions(plan)

    def test_field_api_uses_room_geometry(self):
        room = json.loads(self.get('/api/template'))
        field = self.post('/api/field', {'room': room, 'frequency_hz': 1000, 'grid_size': 3,
                                       'height_m': 1.2, 'reflection_order': 0})
        self.assertEqual(field['schema'], 'earnest.room-field-slice.v1')
        self.assertEqual(field['grid_size'], 3)
        self.assertEqual(len(field['relative_level_db']), 3)
        coherent = self.post('/api/field', {'room': room, 'frequency_hz': 1000, 'grid_size': 3,
                                           'reflection_order': 0, 'correlation_mode': 'opposed'})
        self.assertEqual(coherent['correlation_mode'], 'opposed')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('/api/field', {'room': room, 'grid_size': 50})
        self.assertEqual(error.exception.code, 400)
        error.exception.close()

    def test_invalid_room_and_cross_origin_are_rejected(self):
        room = json.loads(self.get('/api/template'))
        room['geometry']['dimensions'][0] = -1
        with self.assertRaises(urllib.error.HTTPError) as invalid:
            self.post('/api/validate', room)
        self.assertEqual(invalid.exception.code, 400)
        invalid.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.post('/api/validate', room, 'http://attacker.invalid')
        self.assertEqual(denied.exception.code, 403)
        denied.exception.close()


if __name__ == '__main__':
    unittest.main()
