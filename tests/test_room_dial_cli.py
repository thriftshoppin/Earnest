import json
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO

from earnest.cli import _room_template, main
from earnest.engine.room import RoomSpec


class RoomDialCLITests(unittest.TestCase):
    def test_independent_controls_and_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = _room_template()
            baseline['engine_controls']['decay_scale'] = .8
            baseline['engine_controls']['diffuse_energy_scale'] = 2
            baseline['engine_controls']['tail_duration_scale'] = 1.2
            src = root / 'baseline.json'
            original = json.dumps(baseline)
            src.write_text(original, encoding='utf-8')
            for name, field, expected in [('set-decay', 'decay_scale', 1.2),
                                          ('set-tail', 'diffuse_energy_scale', 3),
                                          ('set-tail-duration', 'tail_duration_scale', 1.8)]:
                out = root / (name + '.json')
                with redirect_stdout(StringIO()):
                    self.assertEqual(main([name, str(src), '150', '-f', '--out', str(out)]), 0)
                actual = json.loads(out.read_text(encoding='utf-8'))
                RoomSpec.from_dict(actual)
                self.assertAlmostEqual(actual['engine_controls'][field], expected)
                for other in ('decay_scale', 'diffuse_energy_scale', 'tail_duration_scale'):
                    if other != field:
                        self.assertEqual(actual['engine_controls'][other], baseline['engine_controls'][other])
            self.assertEqual(src.read_text(encoding='utf-8'), original)

    def test_limits_invalid_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src, out = root / 'room.json', root / 'out.json'
            src.write_text(json.dumps(_room_template()), encoding='utf-8')
            for value, flag in [('101', []), ('251', ['-f']), ('nan', ['-f']), ('0', [])]:
                with self.assertRaises(SystemExit):
                    main(['set-decay', str(src), value, *flag, '--out', str(out)])
                self.assertFalse(out.exists())
            with redirect_stdout(StringIO()):
                main(['set-tail', str(src), '0', '--out', str(out)])
            self.assertEqual(json.loads(out.read_text())['engine_controls']['diffuse_energy_scale'], 0)
            with self.assertRaises(SystemExit):
                main(['set-tail', str(src), '50', '--out', str(out)])
            self.assertEqual(json.loads(out.read_text())['engine_controls']['diffuse_energy_scale'], 0)


if __name__ == '__main__':
    unittest.main()
