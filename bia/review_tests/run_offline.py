"""Run only synthetic review tests, after removing credentials and denying IO."""
from pathlib import Path
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if len(sys.argv) == 3 and sys.argv[1] == '--test-deps':
    sys.path.insert(0, str(Path(sys.argv[2]).resolve()))
elif len(sys.argv) != 1:
    raise SystemExit('Usage: run_offline.py [--test-deps TEMP_DEPENDENCY_DIRECTORY]')
for name in list(os.environ):
    if name.upper() not in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH'}:
        del os.environ[name]
sys.dont_write_bytecode = True


def deny_external_calls(event, args):
    if event in {'socket.__new__', 'socket.connect', 'socket.getaddrinfo',
                 'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'}:
        raise RuntimeError('External calls are disabled in the offline review suite')


sys.addaudithook(deny_external_calls)
sys.path.insert(0, str(ROOT))
suite = unittest.defaultTestLoader.discover(str(ROOT / 'review_tests'), pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
