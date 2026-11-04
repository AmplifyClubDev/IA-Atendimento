"""Synthetic safety checks: no real services or credentials, including direct entrypoints."""
from types import SimpleNamespace
from email.message import EmailMessage
import socket
import threading

import pytest
import requests
import offline_policy
from offline_policy import REASON, ExternalEffectsDisabled


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('RAILWAY_ENVIRONMENT_NAME', 'staging')
    for key in ('CADASTRO_PUBLICO_V5_ATIVO', 'CADASTRO_V5_PILOT_ENABLED', 'CADASTRO_ENTREGA_CIRCLE_ATIVA',
                'CADASTRO_RETOMADA_ATIVA', 'CADASTRO_AVISO_ACESSO_CHATWOOT_ATIVO',
                'V5_TIKTOK_NONPRODUCTION_ENABLED', 'PONTES_NONPRODUCTION_ACTIVATION_ENABLED'):
        monkeypatch.setenv(key, 'true')
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('Unexpected external effect')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(requests.Session, 'request', forbidden)
    monkeypatch.setattr(threading.Thread, 'start', forbidden)
    yield forbidden
    assert calls == []


@pytest.mark.parametrize('env,allowed', [({}, True), ({'APP_ENV': 'production'}, True),
    ({'APP_ENV': 'staging'}, False), ({'APP_ENV': ''}, False), ({'APP_ENV': 'unknown'}, False),
    ({'APP_ENV': 'production', 'RAILWAY_ENVIRONMENT_NAME': 'staging'}, False),
    ({'APP_ENV': 'staging', 'RAILWAY_ENVIRONMENT_NAME': 'production'}, False)])
def test_environment_policy(monkeypatch, env, allowed):
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('RAILWAY_ENVIRONMENT_NAME', raising=False)
    assert offline_policy.effects_allowed(env=env) is allowed


def test_explicit_production_cannot_override_process_staging(offline):
    assert not offline_policy.effects_allowed(env={'APP_ENV': 'production'}, settings={'bridge_environment': 'production'})


def test_startup_creates_no_live_dependencies_or_workers(offline, monkeypatch):
    import cadastro_server as server
    import cadastro_pilot as pilot
    monkeypatch.setattr(server, 'deps_from_env', offline)
    app = server.create_app()
    client = app.test_client()
    assert client.get('/health').json['status'] == 'disabled'
    assert client.get('/health').json['live'] is True
    for path in ('/ready', '/cadastro', '/onboarding/api/v2/publico/email/solicitar', '/pontes/test'):
        response = client.get(path)
        assert response.status_code == 503 and response.json['reason'] == REASON
    supplied = SimpleNamespace(enabled=True, entrega=offline, vigia=[offline], ativador=offline, vigia_atendimento=offline)
    assert server.create_app(supplied).test_client().get('/ready').status_code == 503
    assert pilot.create_app(base_app_factory=offline).test_client().post('/onboarding/api/v2/ensaio/respostas').status_code == 503


def test_explicit_pilot_environment_blocks_before_base_factory(monkeypatch):
    import cadastro_pilot as pilot
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('RAILWAY_ENVIRONMENT_NAME', raising=False)
    calls = []
    app = pilot.create_app(base_app_factory=lambda: calls.append('called'), environ={'APP_ENV':'staging'})
    assert not calls and app.test_client().get('/ready').status_code == 503


def test_supabase_direct_rpc_and_storage_blocked(offline):
    from v5 import RestGateway
    adapter = RestGateway('https://production.example.test', 'test-key')
    for call in (lambda: adapter.rpc('test', {}), lambda: adapter.upload('key', b'test'), lambda: adapter.download('key')):
        with pytest.raises(ExternalEffectsDisabled, match=REASON): call()


def test_both_email_stacks_and_oauth_refresh_blocked(offline, monkeypatch):
    import emailer
    from legado import cadastro_delivery as legacy
    from legado.gmail_api import GmailAPI
    monkeypatch.setattr(legacy.smtplib, 'SMTP_SSL', offline)
    sender = emailer.EmailSender(host='smtp.example.test', port=465, user='test@example.test', password='test', factory=offline)
    assert not sender.configured()
    assert sender.send_code('test@example.test', '123456', '<test>') == 'disabled'
    assert sender.send_alert('test@example.test', 'test', 'test') is False
    settings = SimpleNamespace(smtp_usuario='test@example.test', smtp_senha_app='test', email_transport='gmail_api',
                               gmail_client_id='test', gmail_client_secret='test', gmail_refresh_token='test')
    with pytest.raises(ExternalEffectsDisabled): legacy.send_welcome(settings, {}, 'Start')
    gmail = GmailAPI(settings)
    message = EmailMessage();message['From'] = 'test@example.test'
    for call in (gmail.authorize_sender, lambda: gmail.send(message), lambda: gmail.read('messages')):
        with pytest.raises(ExternalEffectsDisabled): call()
    gmail._token = 'cached-test-token';gmail._expires_at = float('inf')
    with pytest.raises(ExternalEffectsDisabled): gmail.authorize_sender()


def test_circle_chatwoot_and_legacy_delivery_direct_calls(offline):
    from legado.cadastro_delivery import Circle, ChatwootAccessNotifier, deliver, notify_access_released
    circle = Circle('test-token')
    with pytest.raises(ExternalEffectsDisabled): circle.call('/community_members', 'POST', {})
    with pytest.raises(ExternalEffectsDisabled): circle.provision(email='test@example.test', name='Test', tier='Start', before_write=offline)
    notifier = ChatwootAccessNotifier()
    notifier.enabled=True
    assert notifier.send({})['notice_status'] == 'disabled'
    assert notify_access_released({})['notice_status'] == 'disabled'
    with pytest.raises(ExternalEffectsDisabled): notifier.already_sent('1', 'test')
    assert deliver(SimpleNamespace(rpc=offline), circle, None, 'test')['status'] == 'disabled'


def test_delivery_retries_callbacks_and_watchers_are_blocked(offline):
    from entrega import Entrega
    from vigia_ponte import VigiaPonte
    from vigia_atendimento import VigiaAtendimento, Chatwoot, _bia_pronta
    import pontes
    worker = Entrega(SimpleNamespace(rpc=offline), circle_token='test', settings=None, enabled=True,
                     circle_factory=offline, send=offline, notify=offline, alert=offline)
    assert worker.iniciar('test', on_done=offline) is None
    assert worker.executar('test')['status'] == 'disabled'
    assert worker._executar('test', None)['status'] == 'disabled'
    assert worker.retomar_pendentes()[0]['status'] == 'disabled'
    assert worker.iniciar_retomada()['status'] == 'disabled'
    bridge = VigiaPonte('test', offline, nome='Test', ler=offline)
    assert bridge.checar() == 'disabled'
    assert bridge.iniciar()['status'] == 'disabled'
    watcher = VigiaAtendimento(offline, chatwoot=SimpleNamespace(sem_resposta=offline), bia=offline)
    assert watcher.checar()['status'] == 'disabled'
    assert watcher.iniciar()['status'] == 'disabled'
    assert _bia_pronta() == (False, REASON)
    with pytest.raises(ExternalEffectsDisabled): Chatwoot('https://example.test', '1', 'test').sem_resposta(0)
    activator = pontes.Ativador([])
    assert activator.rodada() == [('disabled', REASON)]
    assert activator.iniciar()['status'] == 'disabled'
    assert activator._reiniciar('Test', SimpleNamespace(login=offline))['status'] == 'disabled'
    with pytest.raises(ExternalEffectsDisabled): pontes.Painel('https://example.test', 'test').ativar()
    assert pontes.ler_status('https://example.test','test') == 'disabled'


def test_ai_and_pilot_direct_transports_are_blocked(offline):
    import gmv_print
    import cadastro_pilot
    reader = gmv_print.GmvPrintReader('test', 'test', transport=offline)
    result = reader.read(b'test')
    assert result['situacao'] == 'indisponivel' and result['motivo'] == REASON and result['valor'] is None
    with pytest.raises(ExternalEffectsDisabled): gmv_print._http(url='https://example.test', headers={}, body={}, timeout=1)
    with pytest.raises(cadastro_pilot.PilotError) as error:
        cadastro_pilot._call(offline, 'contexto', 'GET', 'test')
    assert error.value.code == REASON
    with pytest.raises(cadastro_pilot.PilotError):
        cadastro_pilot._http(method='GET', url=cadastro_pilot.UPSTREAM, headers={}, body=None, timeout=1)


def test_bridge_adapter_does_not_claim_success_or_use_injected_transport(offline):
    from playwright_client import PlaywrightClient, _transport
    from agency import AgencyChecker
    client = PlaywrightClient({'tiktok_agency_token':'x'*40}, transport=offline)
    assert client.configuration('relationship') == {'configured': False, 'issues':[REASON]}
    assert client.execute('relationship', 'example.test')['status'] == 'disabled'
    with pytest.raises(ExternalEffectsDisabled): client._call('agency','GET','/ready')
    with pytest.raises(ExternalEffectsDisabled): _transport(method='GET',url='https://example.test',headers={})
    checker = AgencyChecker('x'*40, transport=offline)
    try:
        assert not checker.configured()
        assert checker.check('example.test')['status'] == 'disabled'
        assert checker._run('example.test')['status'] == 'disabled'
    finally: checker.pool.shutdown()


def test_public_form_direct_functions_and_separate_blueprint_are_blocked(offline):
    from flask import Flask
    import publico
    for call in (lambda: publico.read_gmv_later('test', b'test'),
                 lambda: publico.run_agency('example.test'),
                 lambda: publico.gmv_reading('test'),
                 lambda: publico.submit('test', {}, {}, None)):
        with pytest.raises(ExternalEffectsDisabled): call()
    app = Flask(__name__)
    app.register_blueprint(publico.bp)
    response = app.test_client().post('/onboarding/api/v2/publico/email/solicitar')
    assert response.status_code == 503 and response.json['reason'] == REASON


def test_supplied_staging_settings_block_delivery_and_cached_oauth(monkeypatch):
    from unittest.mock import Mock
    from entrega import Entrega
    from legado.gmail_api import GmailAPI
    from legado.cadastro_delivery import send_welcome, deliver
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.delenv('RAILWAY_ENVIRONMENT_NAME', raising=False)
    settings = SimpleNamespace(bridge_environment='nonproduction')
    bomb = Mock(side_effect=AssertionError('external adapter invoked'))
    worker = Entrega(SimpleNamespace(rpc=bomb), circle_token='test', settings=settings, enabled=True,
                     circle_factory=bomb, send=bomb, notify=bomb, alert=bomb)
    assert worker.executar('test')['status'] == 'disabled'
    assert worker._executar('test',None)['status'] == 'disabled'
    assert worker.iniciar('test') is None
    assert worker.retomar_pendentes()[0]['status'] == 'disabled'
    assert worker.iniciar_retomada()['status'] == 'disabled'
    gmail = GmailAPI(settings)
    gmail._token = 'cached-test-token'; gmail._expires_at = float('inf')
    for call in (gmail.authorize_sender, lambda: gmail.send(None), lambda: gmail.read('messages'),
                 lambda: send_welcome(settings, {}, 'Start')):
        with pytest.raises(ExternalEffectsDisabled): call()
    assert deliver(SimpleNamespace(rpc=bomb),None,settings,'test')['status'] == 'disabled'
    bomb.assert_not_called()
