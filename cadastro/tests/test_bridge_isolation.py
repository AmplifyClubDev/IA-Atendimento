"""Offline regression tests. All credentials are inert test values."""
import importlib.util
from pathlib import Path

import pytest
from flask import Flask
import agency
import pontes
from bridge_config import bridge_settings, bridge_origin

ROOT = Path(__file__).resolve().parents[2]
PROD = 'https://tiktok-agenciamento-production.up.railway.app'
STAGE = 'https://agency-staging.example.test'


def staging(**extra):
    return {'APP_ENV': 'staging', 'V5_TIKTOK_NONPRODUCTION_ENABLED': 'true',
            'V5_TIKTOK_AGENCY_URL': STAGE + '/bridge',
            'V5_TIKTOK_AGENCY_ALLOWED_HOST': 'agency-staging.example.test', **extra}


@pytest.mark.parametrize('path', ['bia/playwright_client.py', 'cadastro/app/playwright_client.py'])
def test_clients_fail_closed_and_keep_production_allowlist(path):
    spec = importlib.util.spec_from_file_location('isolated_client', ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for env, url, accepted in [
        ({}, PROD + '/bridge', True),
        ({}, STAGE + '/bridge', False),
        ({'APP_ENV': 'staging'}, PROD + '/bridge', False),
        (staging(), PROD + '/bridge', False),
        (staging(), STAGE + '/bridge', True),
        (staging(V5_TIKTOK_NONPRODUCTION_ENABLED='false'), STAGE + '/bridge', False),
        (staging(V5_TIKTOK_AGENCY_ALLOWED_HOST='*'), STAGE + '/bridge', False),
        (staging(V5_TIKTOK_AGENCY_ALLOWED_HOST=PROD.removeprefix('https://')), PROD + '/bridge', False),
    ]:
        calls = []
        client = mod.PlaywrightClient({**bridge_settings(env), 'tiktok_agency_url': url,
                                       'tiktok_agency_token': 'x' * 40},
                                      transport=lambda **kwargs: calls.append(kwargs))
        assert client.configuration('relationship')['configured'] is accepted
        if not accepted:
            client.execute('relationship', 'example.test')
            assert calls == []


@pytest.mark.parametrize('url', [
    'http://agency-staging.example.test/bridge', STAGE + ':444/bridge',
    'https://user:pass@agency-staging.example.test/bridge', STAGE + '/bridge?token=secret',
    STAGE + '/bridge#secret', STAGE + '/wrong', STAGE + '/bridge//',
    'https://agency-staging.example.test.evil.test/bridge', '\n' + STAGE + '/bridge',
])
def test_invalid_origins_never_receive_credentials(url):
    assert bridge_origin(staging(V5_TIKTOK_AGENCY_URL=url), 'agency', PROD) == ''
    assert pontes.pontes(staging(V5_TIKTOK_AGENCY_URL=url)) == []


def test_railway_environment_is_honored_and_missing_urls_do_not_fall_back():
    assert pontes.pontes({'RAILWAY_ENVIRONMENT_NAME': 'staging'}) == []
    assert pontes.pontes({'APP_ENV': ''}) == []
    assert len(pontes.pontes({})) == 3


def test_nonproduction_activation_requires_second_opt_in(monkeypatch):
    env = staging(V5_TIKTOK_AGENCY_TOKEN='x' * 40, PONTE_AGENCIAMENTO_CONSOLE_TOKEN='console-test',
                  PONTES_LINK_SEGREDO='x' * 40)
    entries = pontes.pontes(env)
    assert entries[0]['base'] == STAGE and entries[0]['console'] == ''
    assert pontes.Ativador(entries).pontes == []
    def forbidden(*args, **kwargs):
        raise AssertionError('console must never be accessed')
    monkeypatch.setattr(pontes, 'Painel', forbidden)
    monkeypatch.setattr(pontes, 'ler_status', lambda *a: 'login_required')
    app = Flask(__name__)
    pontes.registrar(app, env=env)
    client = app.test_client()
    assert client.get('/pontes/' + 'x' * 40).status_code == 200
    assert client.get('/pontes/' + 'x' * 40 + '/agenciamento').status_code == 404
    env['PONTES_NONPRODUCTION_ACTIVATION_ENABLED'] = 'true'
    assert pontes.pontes(env)[0]['console'] == 'console-test'


def test_agency_uses_same_explicit_endpoint():
    checker = agency.AgencyChecker('x' * 40, env=staging())
    try:
        assert checker.configured()
        assert checker.client.settings['tiktok_agency_url'] == STAGE + '/bridge'
    finally:
        checker.pool.shutdown()


def test_bridge_control_rejects_redirects():
    assert pontes._NoRedirect().redirect_request(None, None, 302, '', {}, PROD) is None


def test_deployment_copies_stay_identical():
    assert (ROOT / 'bia/bridge_config.py').read_bytes() == (ROOT / 'cadastro/app/bridge_config.py').read_bytes()


@pytest.mark.parametrize('env', [
    {'APP_ENV': 'production', 'RAILWAY_ENVIRONMENT_NAME': 'staging'},
    {'APP_ENV': 'staging', 'RAILWAY_ENVIRONMENT_NAME': 'production'},
    {'APP_ENV': 'production', 'RAILWAY_ENVIRONMENT_NAME': ''},
    {'APP_ENV': '', 'RAILWAY_ENVIRONMENT_NAME': 'production'},
])
def test_conflicting_environment_markers_never_enable_production(env):
    assert bridge_settings(env)['bridge_environment'] == 'nonproduction'
    assert pontes.pontes(env) == []
    checker = agency.AgencyChecker('x' * 40, env=env)
    try:
        assert not checker.configured()
    finally:
        checker.pool.shutdown()


@pytest.mark.parametrize('value', ['', '  '])
def test_cadastro_empty_optional_production_url_preserves_historical_default(value):
    env = {'V5_TIKTOK_AGENCY_URL': value}
    assert bridge_origin(env, 'agency', PROD) == PROD
    assert len(pontes.pontes(env)) == 3
    assert bridge_origin({**env, 'APP_ENV': 'staging'}, 'agency', PROD) == ''


@pytest.mark.parametrize('env', [{}, {'APP_ENV': 'staging'},
                                {'APP_ENV': 'production', 'RAILWAY_ENVIRONMENT_NAME': 'staging'}])
def test_empty_panel_is_unconfigured_not_healthy(env, monkeypatch):
    env = {**env, 'PONTES_LINK_SEGREDO': 'x' * 40}
    def forbidden(*args, **kwargs):
        raise AssertionError('No network for an unconfigured panel')
    monkeypatch.setattr(pontes, 'ler_status', forbidden)
    app = Flask(__name__)
    pontes.registrar(app, env=env)
    response = app.test_client().get('/pontes/' + 'x' * 40)
    assert response.status_code == 503
    assert 'desabilitadas ou não configuradas' in response.get_data(as_text=True)
    assert 'estão no ar' not in response.get_data(as_text=True)


@pytest.mark.parametrize('directory', ['bia', 'cadastro/app'])
def test_helper_is_packaged_and_importable_in_independent_context(directory):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c',
        'import bridge_config, playwright_client; assert bridge_config.bridge_settings({})["bridge_environment"] == "production"'],
        cwd=ROOT / directory, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_docker_contexts_include_helper():
    assert 'COPY bridge_config.py ./' in (ROOT / 'bia/Dockerfile').read_text()
    assert 'COPY . /app' in (ROOT / 'cadastro/app/Dockerfile').read_text()
