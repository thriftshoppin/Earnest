import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from earnest.engine import Artifact, create_engine, EngineError
from earnest.engine.transcription import transcribe_basic_pitch


class TranscriptionTests(unittest.TestCase):
    def test_adapter_and_component_without_running_a_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); audio=root/'audio.wav'; exe=root/'backend.exe'; out=root/'out'
            audio.write_bytes(b'reference'); exe.write_bytes(b'backend')
            def run(args, **kwargs):
                self.assertEqual(args[0],str(exe.resolve()))
                self.assertEqual(kwargs['env']['PYTHONUTF8'],'1')
                Path(args[1], 'result.mid').write_bytes(b'MThd')
                Path(args[1], 'result.csv').write_text('pitch_midi\n69\n')
                return SimpleNamespace(returncode=0)
            with patch('earnest.engine.transcription.subprocess.run',side_effect=run):
                result=create_engine().execute(('audio.transcribe',),
                    {'audio.file': Artifact('earnest.audio-file.v1',str(audio),source='test')},
                    {'audio.transcribe': {'output_dir':str(out),'backend':str(exe)}})
            manifest=result.artifacts['audio.transcription'].value
            self.assertEqual(manifest['backend'],'basic-pitch')
            self.assertEqual(len(manifest['midi_files']),1)
            self.assertEqual(json.loads((out/'earnest-transcription.json').read_text())['input_sha256'],manifest['input_sha256'])
            with self.assertRaises(FileExistsError): transcribe_basic_pitch(str(audio),str(out),str(exe))

    def test_missing_or_failed_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); audio=root/'audio.wav'; exe=root/'backend.exe'; audio.touch(); exe.touch()
            with self.assertRaises(ValueError): transcribe_basic_pitch(str(audio),str(root/'a'),str(root/'missing'))
            with patch('earnest.engine.transcription.subprocess.run',return_value=SimpleNamespace(returncode=2)):
                with self.assertRaises(RuntimeError): transcribe_basic_pitch(str(audio),str(root/'b'),str(exe))


if __name__ == '__main__': unittest.main()
