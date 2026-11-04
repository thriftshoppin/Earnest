import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from earnest import updater


class UpdateTests(unittest.TestCase):
    def test_check_revision_and_version(self):
        sha='a'*40
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'earnest-build.json').write_text(json.dumps({'revision':sha,'dirty':True}))
            with patch('earnest.updater._read_url',side_effect=[json.dumps({'sha':sha}).encode(),b'SHELL_VERSION = "0.5.0-prerelease"']):
                result=updater.check(root)
            self.assertTrue(result['same_revision'])
            self.assertTrue(result['installed_dirty'])
            self.assertEqual(result['remote_shell_version'],'0.5.0-prerelease')

    def test_rejects_unsafe_archive_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('root/../../bad', 'C:/outside'):
                data=io.BytesIO()
                with zipfile.ZipFile(data,'w') as z: z.writestr(zipfile.ZipInfo(name),'data')
                data.seek(0)
                with self.assertRaises(ValueError): updater._unpack(data,Path(tmp))

    def test_stage_validates_revision(self):
        with self.assertRaises(ValueError): updater.stage('../bad')


if __name__ == '__main__': unittest.main()
