import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == 'nt', 'Windows VM updater')
class VMUpdateTests(unittest.TestCase):
    def test_update_backup_preserve_and_reject_corruption(self):
        script=Path(__file__).resolve().parents[1]/'lab/vm/Update-Earnest-VM.ps1'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); install=root/'install'; package=root/'package'
            for path, data in ((install/'app/earnest/cli.py',b'old'),(install/'python/python.exe',b'python'),(install/'app/inbox/rooms/user.json',b'room')):
                path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
            package.mkdir(); updater=package/'Update-Earnest-VM.ps1'; updater.write_bytes(script.read_bytes())
            payload=package/'payload/app/earnest/cli.py'; payload.parent.mkdir(parents=True); payload.write_bytes(b'new')
            item={'path':'app\\earnest\\cli.py','sha256':hashlib.sha256(b'new').hexdigest().upper()}
            (package/'manifest.json').write_text(json.dumps({'schema':'earnest.vm-update.v1','files':[item]}))
            command=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(updater),'-InstallDirectory',str(install)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual((install/'app/earnest/cli.py').read_bytes(),b'new')
            self.assertEqual((install/'app/inbox/rooms/user.json').read_bytes(),b'room')
            self.assertEqual(next(install.glob('backup-update-*/app/earnest/cli.py')).read_bytes(),b'old')
            payload.write_bytes(b'corrupt')
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((install/'app/earnest/cli.py').read_bytes(),b'new')


if __name__ == '__main__': unittest.main()
