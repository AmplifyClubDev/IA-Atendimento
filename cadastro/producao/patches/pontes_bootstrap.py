"""Cadastro-only boot patch; existing image and entrypoint are preserved."""
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
OLD_HASHES = ['9fcac3b77e943ef392cf358efb10c19a22527ea44640f250c70628f3f4634d4c', '71ce27a84de35f352c302dd5b974e877e05125df74ff5b3afcaf2f7ba9c08a1b']
NEW_HASH = 'f16c63fe82f7df920a02df45ea82f6ad5f5d64a638309951d74de7bbbf305a69'
SOURCE = '<retirado: base64 de cadastro/producao/efetivo/pontes.py, sha256 f16c63fe82f7df920a02df45ea82f6ad5f5d64a638309951d74de7bbbf305a69>'
COMMAND = ['gunicorn', '--bind', '0.0.0.0:3000', '--workers', '1', '--threads', '16', '--timeout', '90', '--graceful-timeout', '100', 'cadastro_pilot:create_app()']

def apply_patch(target):
    temporary = None
    try:
        current = target.read_bytes()
        before = hashlib.sha256(current).hexdigest()
        if before == NEW_HASH:
            print('[pontes-recovery] already_applied sha256=' + NEW_HASH, flush=True)
            return True
        if before not in OLD_HASHES:
            print('[pontes-recovery] NOT_APPLIED source_mismatch sha256=' + before, flush=True)
            return False
        payload = base64.b64decode(SOURCE, validate=True)
        if hashlib.sha256(payload).hexdigest() != NEW_HASH:
            raise ValueError('payload_hash_mismatch')
        compile(payload, str(target), 'exec')
        with tempfile.NamedTemporaryFile(prefix='.pontes-recovery-', dir=target.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, target.stat().st_mode & 511)
        os.replace(temporary, target)
        temporary = None
        print('[pontes-recovery] applied old_sha256=' + before + ' new_sha256=' + NEW_HASH, flush=True)
        return True
    except Exception as error:
        print('[pontes-recovery] NOT_APPLIED error=' + type(error).__name__, flush=True)
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

def smoke():
    code = "\nimport os, time, json\nfrom urllib.parse import quote\nfrom urllib.request import build_opener, ProxyHandler\nfrom urllib.error import HTTPError\nopener = build_opener(ProxyHandler({}))\nsecret = os.environ.get('PONTES_LINK_SEGREDO', '')\nif len(secret) < 32:\n    print('[pontes-recovery] smoke_skipped missing_link', flush=True)\nelse:\n    for attempt in range(12):\n        try:\n            with opener.open('http://127.0.0.1:3000/health', timeout=2) as response:\n                if response.status == 200:\n                    break\n        except Exception:\n            time.sleep(5)\n    else:\n        print('[pontes-recovery] smoke_failed health_unavailable', flush=True)\n        raise SystemExit(0)\n    try:\n        with opener.open('http://127.0.0.1:3000/pontes/' + quote(secret, safe=''), timeout=60) as response:\n            revision = response.headers.get('X-Amplify-Pontes-Revision', '')\n            body = response.read(65536).decode('utf-8', errors='replace')\n            print('[pontes-recovery] smoke status=' + str(response.status) + ' revision=' + ('verified' if revision == 'recovery-20261114-activation-v2' else 'unexpected') + ' ready=' + str(body.count('>NO AR<')) + ' login=' + str(body.count('>PRECISA DE LOGIN<')) + ' limited=' + str(body.count('HTTP 429')), flush=True)\n    except HTTPError as error:\n        print('[pontes-recovery] smoke_failed http=' + str(error.code), flush=True)\n    except Exception as error:\n        print('[pontes-recovery] smoke_failed error=' + type(error).__name__, flush=True)\n"
    subprocess.Popen([sys.executable, '-c', code], env={'PONTES_LINK_SEGREDO': os.environ.get('PONTES_LINK_SEGREDO', '')})

def main():
    applied = apply_patch(Path('/app/pontes.py'))
    if applied:
        try:
            smoke()
        except Exception as error:
            print('[pontes-recovery] smoke_failed start=' + type(error).__name__, flush=True)
    os.execvp(COMMAND[0], COMMAND)
if __name__ == '__main__':
    main()