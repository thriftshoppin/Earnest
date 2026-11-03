import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == 'nt', 'Windows VM updater')
class VMUpdateTests(unittest.TestCase):
    def test_full_update_orchestrates_models_and_reports_failures(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); package=root/'package'; package.mkdir(); install=root/'install'; app=install/'app'
            full=package/'Update-Earnest-VM-Full.ps1'; full.write_bytes((repo/'lab/vm/Update-Earnest-VM-Full.ps1').read_bytes())
            (package/'Update-Earnest-VM.ps1').write_text('param([string]$InstallDirectory)\nexit 0\n')
            compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            source=root/'stub.cs'; source.write_text('class P { static int Main() { return 0; } }')
            stub=root/'stub.exe'; built=subprocess.run([str(compiler),'/nologo',f'/out:{stub}',str(source)],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            (root/'uv.exe').write_bytes(stub.read_bytes())
            (app/'bin').mkdir(parents=True)
            for name,folder,exe in [('setup-separation.ps1','demucs','demucs.exe'),('setup-transcription.ps1','basic-pitch','basic-pitch.exe')]:
                (app/'bin'/name).write_text(f"$p=Join-Path $PSScriptRoot '..\\runs\\runtime\\{folder}\\Scripts'\nNew-Item -ItemType Directory -Force -Path $p | Out-Null\nCopy-Item -LiteralPath $env:EARNEST_TEST_STUB -Destination (Join-Path $p 'python.exe')\nCopy-Item -LiteralPath $env:EARNEST_TEST_STUB -Destination (Join-Path $p '{exe}')\n")
            env=os.environ.copy(); env['PATH']=str(root)+os.pathsep+env['PATH']; env['EARNEST_TEST_STUB']=str(stub)
            cmd=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(full),'-InstallDirectory',str(install)]
            result=subprocess.run(cmd,capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('Full application and model-runtime update completed',result.stdout)
            (app/'bin/setup-separation.ps1').write_text('exit 9\n')
            result=subprocess.run(cmd,capture_output=True,text=True,env=env)
            self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('Demucs setup failed',result.stdout)

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
