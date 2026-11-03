"""Concorrência real com SQLite e SMTP controlado; nenhuma mensagem externa."""
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace
from uuid import uuid4

from flask import Flask
import pytest
import publico
from store import Store
import tokens


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / 'email.sqlite3')
    fid, secret = str(uuid4()), 's' * 40
    store.open_session(fid, 'local')
    mail = SimpleNamespace(configured=lambda: True)
    app = Flask(__name__)
    app.extensions['cadastro_v5'] = SimpleNamespace(store=store, secret=secret, email=mail)
    app.register_blueprint(publico.bp)
    header = {'Authorization': 'Bearer ' + tokens.sign(secret, 'sessao', {'f': fid})}
    def call(route, **body):
        with app.test_client() as client:
            response = client.post('/onboarding/api/v2/publico/email/' + route, json=body, headers=header)
            return response.status_code, response.get_json()
    return store, fid, mail, call


def test_simultaneous_requests_send_once_and_poll_sees_reservation(setup):
    store, fid, mail, call = setup
    entered, release, sent = threading.Event(), threading.Event(), []
    def send(*args):
        sent.append(args)
        entered.set()
        assert release.wait(5)
        return 'enviado'
    mail.send_code = send
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(call, 'solicitar', email='lead@example.com')
        assert entered.wait(5)
        try:
            assert call('estado', email='lead@example.com')[1]['status'] == 'enviando'
            assert call('solicitar', email='lead@example.com')[1]['status'] == 'enviando'
            assert call('solicitar', email='other@example.com')[1]['retry_after'] > 0
        finally:
            release.set()
        value = first.result()[1]
    assert len(sent) == 1
    assert value['status'] == 'enviado'
    assert value['expires_at'] - value['requested_at'] == 600
    assert sent[0][2].split('@')[0].endswith(value['request_reference'])
    assert call('confirmar', email='lead@example.com', code=sent[0][1])[1]['verified'] is True


def test_atomic_claim_between_independent_store_instances(setup):
    store, fid, _, _ = setup
    other = Store(store.path)
    barrier = threading.Barrier(2)
    def claim(item):
        barrier.wait()
        return item.claim_email_code(fid, 'email', str(id(item)), now=1000, ttl=600, wait=60)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, [store, other])) == ['claimed', 'waiting']


def test_stale_send_result_cannot_replace_new_code_or_confirmed_state(setup):
    store, fid, _, _ = setup
    assert store.claim_email_code(fid, 'email', 'old', now=1000, ttl=600, wait=60) == 'claimed'
    # Crash no envio: não repetir enquanto ainda pode estar em andamento.
    assert store.claim_email_code(fid, 'email', 'new', now=1061, ttl=600, wait=60) == 'waiting'
    assert store.claim_email_code(fid, 'email', 'new', now=1601, ttl=600, wait=60) == 'claimed'
    store.finish_email_code(fid, 'old', 'enviado')
    assert store.session(fid)['otp_status'] == 'enviando'
    store.finish_email_code(fid, 'new', 'enviado')
    assert store.confirm_email_code(fid, 'email', 'old', 'sha', 'now', now=1602, maximum=10) == 'codigo_incorreto'
    assert store.confirm_email_code(fid, 'email', 'new', 'sha', 'now', now=1602, maximum=10) == 'confirmado'
    store.finish_email_code(fid, 'new', 'devolvido')
    assert store.session(fid)['otp_status'] == 'confirmado'


def test_retry_preserves_attempt_limit_and_email_change_obeys_wait(setup):
    store, fid, _, _ = setup
    store.claim_email_code(fid, 'email', 'one', now=1000, ttl=600, wait=60)
    store.finish_email_code(fid, 'one', 'enviado')
    store.update(fid, otp_attempts=10)
    assert store.claim_email_code(fid, 'other', 'two', now=1001, ttl=600, wait=60) == 'waiting'
    assert store.claim_email_code(fid, 'email', 'two', now=1061, ttl=600, wait=60) == 'claimed'
    assert store.session(fid)['otp_attempts'] == 10


def test_smtp_unknown_is_recorded_without_retry(setup):
    _, _, mail, call = setup
    calls = []
    def fail(*args):
        calls.append(args)
        raise TimeoutError()
    mail.send_code = fail
    assert call('solicitar', email='lead@example.com')[1]['status'] == 'incerto'
    assert call('solicitar', email='lead@example.com')[1]['status'] == 'incerto'
    assert len(calls) == 1
