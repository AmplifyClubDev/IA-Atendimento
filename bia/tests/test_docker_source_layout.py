"""Check COPY layout offline, not a Docker build or dependency-install test."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import flask

ROOT = Path(__file__).resolve().parents[1]


class DockerSourceLayoutTests(unittest.TestCase):
    def test_copied_source_starts_offline_without_importing_from_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / 'app'
            image.mkdir()
            for line in (ROOT / 'Dockerfile').read_text().splitlines():
                if not line.startswith('COPY '):
                    continue
                parts = shlex.split(line[5:])
                self.assertFalse(any(part.startswith('--') for part in parts), 'Update this COPY-layout test for new Docker flags')
                sources, destination = parts[:-1], parts[-1]
                self.assertTrue(sources)
                self.assertFalse(destination.startswith('/'), 'Update test for absolute Docker destinations')
                target = image / destination
                for source in sources:
                    src = ROOT / source
                    self.assertTrue(src.exists(), source)
                    if src.is_dir():
                        shutil.copytree(src, target, dirs_exist_ok=True,
                                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                    else:
                        dest = target / src.name if destination.endswith('/') else target
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)
            # Only installed Flask dependencies are added, never the checkout's
            # Python path: otherwise missing COPY inputs would go unnoticed.
            environment = {'PATH': os.defpath, 'APP_ENV': 'staging',
                           'V5_STATE_DIR': str(Path(folder) / 'state'),
                           'PYTHONPATH': str(Path(flask.__file__).resolve().parents[1])}
            probe = '''import json, socket, threading
from unittest.mock import patch
def denied(*args, **kwargs): raise AssertionError('external_effect_or_worker_in_copy_probe')
with patch.object(socket.socket, 'connect', denied), patch.object(socket.socket, 'connect_ex', denied), patch.object(socket, 'getaddrinfo', denied), patch.object(socket, 'create_connection', denied), patch.object(threading.Thread, 'start', denied):
 import bootstrap
 app = bootstrap.create_app()
 client = app.test_client()
 print(json.dumps({'health': client.get('/healthz').status_code, 'ready': client.get('/ready').status_code, 'preflight': app.extensions['v5_stage_preflight']}))
'''
            result = subprocess.run([sys.executable, '-c', probe], cwd=image, env=environment,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(result.stdout)
            self.assertEqual(evidence['health'], 200)
            self.assertEqual(evidence['ready'], 503)
            self.assertEqual(evidence['preflight'], {'status': 'disabled', 'reason': 'nonproduction_external_effects_disabled'})


if __name__ == '__main__':
    unittest.main()
