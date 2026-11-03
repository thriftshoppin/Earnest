"""Live-view navigation with a deliberately absent monitor; no audio is opened."""
import http.client
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest


class LiveViewNavigationTests(unittest.TestCase):
    def test_room_studio_link_and_redirect(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is not installed')
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='earnest-view-test-') as tmp:
            live = Path(tmp) / 'live'; live.mkdir()
            for name in ('server.js', 'index.html', 'app.bundle.js'):
                shutil.copy2(repo / 'live' / name, live / name)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            env = os.environ.copy(); env['EARNEST_EDITOR_PORT'] = '18976'
            process = subprocess.Popen([node, str(live / 'server.js'), 'test-endpoint', str(port)],
                                       cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(60):
                    try:
                        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
                        conn.request('GET', '/'); response = conn.getresponse(); page = response.read(); conn.close()
                        break
                    except OSError:
                        if process.poll() is not None:
                            self.fail('live viewer exited before listening')
                        time.sleep(.05)
                else:
                    self.fail('live viewer did not start')
                self.assertEqual(response.status, 200)
                self.assertIn(b'href="/room-studio"', page)
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                conn.request('GET', '/room-studio'); response = conn.getresponse(); response.read()
                self.assertEqual(response.status, 302)
                self.assertEqual(response.getheader('Location'), 'http://127.0.0.1:18976/')
                conn.close()
            finally:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
