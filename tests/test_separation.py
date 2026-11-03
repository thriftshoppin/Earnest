import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from earnest.engine import Artifact, create_engine
from earnest.engine.separation import separate_demucs


class SeparationTests(unittest.TestCase):
    def test_component_outputs_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); src=root/'audio.wav'; exe=root/'demucs.exe'; out=root/'result'
            src.write_bytes(b'audio'); exe.touch()
            def run(args, **kwargs):
                self.assertIn('--shifts', args)
                self.assertEqual(kwargs['env']['PYTHONUTF8'], '1')
                dest=Path(args[args.index('-o')+1])/'htdemucs'; dest.mkdir()
                for name in ('vocals','drums','bass','other'): (dest/(name+'.wav')).write_bytes(b'stem')
                return SimpleNamespace(returncode=0)
            with patch('earnest.engine.separation.subprocess.run',side_effect=run):
                runresult=create_engine().execute(('audio.separate',), {'audio.file':Artifact('audio',str(src))},
                    {'audio.separate':{'output_dir':str(out),'backend':str(exe),'device':'cpu'}})
            self.assertEqual(set(runresult.artifacts['audio.separation'].value['stems']),{'vocals','drums','bass','other'})
            with self.assertRaises(FileExistsError): separate_demucs(str(src),str(out),str(exe))
            with self.assertRaises(ValueError): separate_demucs(str(src),str(root/'bad'),str(exe),'bad')


if __name__ == '__main__': unittest.main()
