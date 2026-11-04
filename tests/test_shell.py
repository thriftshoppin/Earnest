import io
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from earnest.cli import _room_template
from earnest.shell import Jack, _resolve, _tokens, run
from earnest.startup import _banner

PLAYBACK=[{'name':'Virtual Jack','id':'virtual-id'},{'name':'Headphones','id':'headphones-id'}]
CAPTURE=[{'name':'Microphone','id':'microphone-id'}]

class ShellTests(unittest.TestCase):
    def test_windows_paths_and_resolution(self):
        self.assertEqual(_tokens('set room "C:\\Users\\Test User\\my room.json"'),['set','room','C:\\Users\\Test User\\my room.json'])
        self.assertEqual(_resolve('head',PLAYBACK)['id'],'headphones-id')
        with self.assertRaisesRegex(ValueError,'more than one'):
            _resolve('head',[{'name':'Headphone A','id':'1'},{'name':'Headphone B','id':'2'}])
        with self.assertRaises(ValueError): _resolve('missing',PLAYBACK)

    def test_persistence_migration_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'stagejack').mkdir(); (root/'stagejack/earnest-settings.ini').write_text('Input=Virtual Jack\nOutput=Headphones\nRoom=old.json\n')
            j=Jack(root/'config/jack.json',root)
            self.assertEqual(j.config['input']['name'],'Virtual Jack')
            with patch('earnest.shell.host.devices',return_value=PLAYBACK):
                j.set_device('input','Virtual'); j.set_device('output','Headphones')
            self.assertEqual(Jack(j.path,root).config['input']['id'],'virtual-id')
            j.clear(); j2=Jack(j.path,root)
            self.assertIsNone(j2.config['input']); self.assertIsNone(j2.config['output'])
            self.assertIsNone(j2.config['room'])

    def test_boot_uses_saved_ids_and_stops_only_owned_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); room=root/'room.json'; room.write_text(json.dumps(_room_template()))
            j=Jack(root/'jack.json',root); j.config.update({'room':str(room),'input':PLAYBACK[0],'output':PLAYBACK[1]})
            fake=Mock(); fake.poll.return_value=None; fake.wait.return_value=0
            with patch('earnest.shell._other_earnest_hosts',return_value=[]), patch('earnest.shell.host.devices',return_value=PLAYBACK), \
                 patch('earnest.audio.convolution.compile_room') as compile_room, patch('earnest.shell.host.ensure_host',return_value=root/'native.exe'), \
                 patch('earnest.shell.subprocess.Popen',return_value=fake) as start, patch('earnest.shell.threading.Thread'):
                j.boot(); args=start.call_args.args[0]
                self.assertIn('virtual-id',args); self.assertIn('headphones-id',args)
                self.assertEqual(args[args.index('--output-limit')+1],'0.5')
                self.assertEqual(compile_room.call_args.kwargs['dry'],.5)
                with self.assertRaisesRegex(ValueError,'already running'): j.boot()
                j.clear(); fake.terminate.assert_called_once(); self.assertIsNone(j.config['input'])

    def test_boot_rejects_missing_and_overlapping_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=Jack(Path(tmp)/'jack.json',tmp)
            with patch('earnest.shell._other_earnest_hosts',return_value=['EarnestAudioHost.exe']):
                with self.assertRaisesRegex(ValueError,'another Earnest'): j.boot()
            j.config.update({'room':'unused','input':PLAYBACK[0],'output':PLAYBACK[0]})
            with patch('earnest.shell._other_earnest_hosts',return_value=[]), patch('earnest.shell.host.devices',return_value=PLAYBACK):
                with self.assertRaisesRegex(ValueError,'same endpoint'): j.boot()

    def test_prepared_room_is_reused_and_changes_invalidate_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); room=root/'room.json'; room.write_text(json.dumps(_room_template()))
            jack=Jack(root/'jack.json',root); jack.config['room']=str(room)
            def compile_fake(source, target, **kwargs):
                Path(target).write_bytes(struct.pack('<4sIIII',b'ERIR',1,48000,2,1)+bytes(8))
            with patch('earnest.audio.convolution.compile_room',side_effect=compile_fake) as compile_room:
                first=jack.prepare_room(); self.assertEqual(jack.prepare_room(),first)
                self.assertEqual(compile_room.call_count,1)
                jack.config['wet_percent']=60
                self.assertNotEqual(jack.prepare_room(),first)
                self.assertEqual(compile_room.call_count,2)
                room.write_text(room.read_text()+' ')
                jack.prepare_room(); self.assertEqual(compile_room.call_count,3)
                first.write_bytes(b'invalid')
                jack.config['wet_percent']=50; room.write_text(room.read_text().rstrip())
                jack.prepare_room(); self.assertEqual(compile_room.call_count,4)

    def test_force_is_required_above_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            jack=Jack(Path(tmp)/'jack.json',tmp)
            with self.assertRaisesRegex(ValueError,'-f'): jack.set_level('wet','150')
            jack.set_level('wet','150',True); self.assertEqual(jack.config['wet_percent'],150)
            with self.assertRaises(ValueError): jack.set_level('wet','251',True)

    def test_interactive_aliases_and_legacy_commands(self):
        fake=Mock(); fake.running.return_value=False
        commands=iter(['set in Virtual Jack','set out Headphones','set wet 55','show','audio-devices','exit'])
        with patch('earnest.cli.main') as legacy, redirect_stdout(io.StringIO()):
            self.assertEqual(run(fake,lambda prompt: next(commands)),0)
        fake.set_device.assert_any_call('input','Virtual Jack');fake.set_device.assert_any_call('output','Headphones')
        fake.set_level.assert_called_once_with('wet','55',False);fake.show.assert_called_once()
        legacy.assert_called_once_with(['audio-devices'])

    def test_banner_plain_ascii(self):
        output=io.StringIO()
        with redirect_stdout(output): _banner()
        text=output.getvalue();text.encode('ascii')
        self.assertIn('0.5.0-prerelease',text);self.assertIn('| ____|',text)

if __name__=='__main__': unittest.main()
