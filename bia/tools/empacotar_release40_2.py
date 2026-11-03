"""Monta e confere o pacote selado da release 40.2 a partir de ./src (sem rede, sem variáveis).

Uso: python -I empacotar_release40_2.py
Saída: sealed40-2/ com o zip, o carregador, o manifesto e as partes base64 prontas
para V5_RELEASE_ARCHIVE_PART_1..N e V5_RELEASE_LAUNCHER_B64.
"""
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
SRC = HERE / 'src'
OUT = HERE / 'sealed40-2'
BASE_LAUNCHER = HERE.parent / 'claude-bia-release40-1-20261102' / 'sealed40-1' / 'atendimento-v5-release-20261102-40-1-launcher.py'
RELEASE = 'atendimento-v5-release-20261102-40-2'
BASE_RELEASE = 'atendimento-v5-release-20261102-40-1'
PART_LIMIT = 26000
STAMP = (2026, 11, 2, 0, 0, 0)


def sources():
    base = importlib.util.spec_from_file_location('launcher40', BASE_LAUNCHER)
    module = importlib.util.module_from_spec(base)
    base.loader.exec_module(module)
    return sorted(module.SOURCES)


def build():
    names = sources()
    files = {name: (SRC / name).read_bytes() for name in names}
    manifest = {'files': [{'bytes': len(files[name]), 'path': name, 'sha256': hashlib.sha256(files[name]).hexdigest()}
                          for name in names],
                'provenance': {'author': 'claude-bia-release40-2-20261102', 'base_release': BASE_RELEASE},
                'release': RELEASE, 'source_count': len(names)}
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, content in [*((name, files[name]) for name in names), ('MANIFEST.json', manifest_bytes)]:
            info = zipfile.ZipInfo(name, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 0
            archive.writestr(info, content)
    raw = buffer.getvalue()
    encoded = base64.b64encode(raw).decode('ascii')
    count = -(-len(encoded) // PART_LIMIT)
    size = -(-len(encoded) // count)
    parts = [encoded[index:index + size] for index in range(0, len(encoded), size)]
    launcher = BASE_LAUNCHER.read_text(encoding='utf-8')
    replacements = {
        r'^RELEASE = .*$': 'RELEASE = ' + json.dumps(RELEASE),
        r'^ARCHIVE_SHA256 = .*$': 'ARCHIVE_SHA256 = ' + repr(hashlib.sha256(raw).hexdigest()),
        r'^ARCHIVE_BASE64_LENGTH = .*$': 'ARCHIVE_BASE64_LENGTH = ' + str(len(encoded)),
        r'^ARCHIVE_PART_COUNT = .*$': 'ARCHIVE_PART_COUNT = ' + str(len(parts)),
        r'^SOURCES = frozenset\(.*$': 'SOURCES = frozenset({' + ', '.join(map(repr, names)) + '})',
    }
    for pattern, line in replacements.items():
        launcher, found = re.subn(pattern, lambda _: line, launcher, count=1, flags=re.M)
        assert found == 1, pattern
    return raw, manifest_bytes, launcher, parts


def verify(raw, launcher, parts):
    """O próprio carregador confere o pacote, instala numa pasta temporária e lê as partes."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'launcher40_2.py'
        path.write_text(launcher, encoding='utf-8')
        spec = importlib.util.spec_from_file_location('launcher40_2', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        environ = {'V5_RELEASE_ARCHIVE_PART_' + str(index): part for index, part in enumerate(parts, 1)}
        assert module.archive_from_environment(environ) == raw
        bundle = module.verify_archive(raw)
        target = module.install_archive(raw, folder)
        assert target.name == RELEASE and (target / 'reconferencia.py').read_bytes() == (SRC / 'reconferencia.py').read_bytes()
        assert all((target / name).read_bytes() == (SRC / name).read_bytes() for name in module.SOURCES)
        return len(bundle)


LIVE_RELEASE = 'atendimento-v5-release-20261102-40-1'
LIVE_FOLDER = HERE.parent / 'claude-bia-release40-1-20261102' / 'sealed40-1'


def write_rollback():
    """Variáveis da 40.1 (a que está no ar, deploy 86a3c144) recompostas do pacote selado 40.1.

    O carregador só concatena as partes, então qualquer divisão em 10 partes de até 26000 serve.
    """
    raw = (LIVE_FOLDER / (LIVE_RELEASE + '.zip')).read_bytes()
    launcher = (LIVE_FOLDER / (LIVE_RELEASE + '-launcher.py')).read_bytes()
    encoded = base64.b64encode(raw).decode('ascii')
    count = int(re.search(rb'^ARCHIVE_PART_COUNT = (\d+)', launcher, re.M).group(1))
    size = -(-len(encoded) // count)
    parts = [encoded[index:index + size] for index in range(0, len(encoded), size)]
    assert len(parts) == count and max(map(len, parts)) <= PART_LIMIT
    assert hashlib.sha256(raw).hexdigest().encode() in launcher
    target = OUT / 'volta40-1'
    target.mkdir(exist_ok=True)
    for index, part in enumerate(parts, 1):
        (target / ('V5_RELEASE_ARCHIVE_PART_' + str(index) + '.txt')).write_text(part, encoding='ascii', newline='')
    (target / 'V5_RELEASE_LAUNCHER_B64.txt').write_text(base64.b64encode(launcher).decode('ascii'),
                                                        encoding='ascii', newline='')


def main():
    raw, manifest, launcher, parts = build()
    count = verify(raw, launcher, parts)
    OUT.mkdir(exist_ok=True)
    (OUT / (RELEASE + '.zip')).write_bytes(raw)
    (OUT / (RELEASE + '-manifest.json')).write_bytes(manifest + b'\n')
    (OUT / (RELEASE + '-launcher.py')).write_text(launcher, encoding='utf-8', newline='\n')
    (SRC / 'MANIFEST.json').write_bytes(manifest)
    write_rollback()
    variables = OUT / 'variaveis'
    variables.mkdir(exist_ok=True)
    for old in variables.glob('*.txt'):
        old.unlink()
    for index, part in enumerate(parts, 1):
        (variables / ('V5_RELEASE_ARCHIVE_PART_' + str(index) + '.txt')).write_text(part, encoding='ascii', newline='')
    (variables / 'V5_RELEASE_LAUNCHER_B64.txt').write_text(
        base64.b64encode(launcher.encode('utf-8')).decode('ascii'), encoding='ascii', newline='')
    print(json.dumps({'release': RELEASE, 'files': count, 'zip_sha256': hashlib.sha256(raw).hexdigest(),
                      'zip_bytes': len(raw), 'base64_length': sum(map(len, parts)), 'parts': len(parts),
                      'launcher_sha256': hashlib.sha256(launcher.encode('utf-8')).hexdigest()}, indent=2))


if __name__ == '__main__':
    main()
