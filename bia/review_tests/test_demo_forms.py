"""Full bootstrap and legacy form boundary, with synthetic rows and fake providers."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

import bootstrap
from contracts import normalize_phone
from demo_router import DemoScope
from forms import FormError, FormStore, _sha, register_forms
from repository import Repository
from server import create_app as create_server
from test_demo_router import settings


STAMP = datetime(2026, 2, 1, tzinfo=timezone.utc)
PHONE = '+55' + '21' + '99' + '0' * 7
OTHER = '+55' + '22' + '98' + '0' * 7
SCOPE = DemoScope('1', '3', '9', '7', PHONE)
SECRET = 'synthetic-form-secret-' + 'x' * 32
FORM_URL = 'https://amplify-cadastro.up.railway.app/cadastro/ensaio'


class DemoFormBoundary(unittest.TestCase):
    def make_app(self, *, enabled=True):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = settings(directory.name, enabled=enabled)
        config.update(form_secret=SECRET, public_url='https://demo.example.invalid',
                      form_public_url=FORM_URL,
                      demo_scope={name: getattr(SCOPE, name) for name in SCOPE.__dataclass_fields__},
                      pilot_scope={'phone': PHONE, 'contact_id': '9', 'conversation_id': '7'})
        config['gate'].update(phone=PHONE, phones=[PHONE, OTHER])
        repo = Repository(Path(directory.name) / 'atendimento.sqlite3')
        store = FormStore(repo.path)
        rows = {}
        for index, (label, conversation, phone) in enumerate((
                ('owner', '7', PHONE), ('other', '8', OTHER),
                ('owner_other_chat', '18', PHONE), ('owner_alias', '19', PHONE[:5] + PHONE[6:])), 1):
            form_id, creator, session, cycle = (str(UUID(int=index * 10 + offset)) for offset in range(1, 5))
            token = base64.urlsafe_b64encode(hmac.new(SECRET.encode(), ('form:' + form_id).encode(), hashlib.sha256).digest()).decode().rstrip('=')
            key = 'chatwoot:1:' + conversation
            state = {'session_id': session, 'creator_id': creator,
                     'cycle': {'id': cycle, 'mode': 'simulated', 'status': 'open', 'phase': 'form',
                               'expires_at': (STAMP + timedelta(hours=2)).isoformat(),
                               'form_url': config['public_url'] + '/cadastro/' + token, 'facts': {}}}
            repo.save_session(key, state)
            with store.db() as db:
                db.execute('INSERT INTO v5_forms(token_hash,form_id,creator_id,event_id,conversation_key,session_id,cycle_id,account_id,inbox_id,phone_hash,created_at,expires_at,receipt_email_operation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (_sha(token), form_id, creator, 'synthetic-event-' + label, key, session, cycle,
                            '1', '3', _sha(normalize_phone(phone)), STAMP.isoformat(),
                            (STAMP + timedelta(hours=2)).isoformat(), str(UUID(int=index * 10 + 5))))
            rows[label] = {'token': token, 'state': state, 'key': key, 'row': store.row(token)}
        gateway, sender, transport = Mock(), Mock(), Mock()
        sender.send_otp.return_value = {'status': 'accepted'}
        transport.ready.return_value = True
        transport.supports_reply_fencing = False
        def server_factory(**kwargs):
            app = create_server(**kwargs, repository=repo, transport=transport,
                                real_guard=Mock(return_value={'allowed': True}), real_client=Mock())
            app.extensions['v5_form_clock'] = lambda: STAMP
            return app
        with patch.object(bootstrap, 'create_server', side_effect=server_factory), \
             patch.object(bootstrap, 'Gateway', return_value=gateway) as gateway_factory, \
             patch.object(bootstrap, 'SmtpSender', return_value=sender) as sender_factory, \
             redirect_stdout(io.StringIO()):
            app = bootstrap.create_app(config)
        app.testing = True
        router = app.extensions.get('v5_demo_router')
        if router:self.addCleanup(router.store.close)
        return app, repo, store, rows, gateway, sender, gateway_factory, sender_factory

    def snapshot(self, repo):
        with repo._connection() as db:
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {name: sorted(tuple(row) for row in db.execute('SELECT * FROM ' + name)) for name in tables}

    def test_bootstrap_passes_verified_runtime_scope_to_forms_and_providers(self):
        app, _, _, _, _, _, gateway_factory, sender_factory = self.make_app()
        runtime = app.extensions['v5_settings']
        self.assertIsInstance(runtime['_demo_scope'], DemoScope)
        self.assertIs(gateway_factory.call_args.args[0], runtime)
        self.assertIs(sender_factory.call_args.args[0], runtime)

    def test_startup_keeps_owner_forms_and_sessions_unchanged(self):
        app, repo, _, rows, gateway, sender, _, _ = self.make_app()
        for label in ('owner', 'owner_other_chat', 'owner_alias'):
            self.assertEqual(repo.load_session(rows[label]['key']), rows[label]['state'], label)
        self.assertEqual(repo.load_session(rows['other']['key'])['cycle']['form_url'],
                         FORM_URL + '#s=' + rows['other']['token'])
        self.assertEqual(gateway.mock_calls, [])
        self.assertEqual(sender.mock_calls, [])

    def test_all_native_and_compat_routes_reject_owner_before_effects(self):
        app, repo, _, rows, gateway, sender, _, _ = self.make_app()
        before = self.snapshot(repo)
        token = rows['owner']['token']
        checked = 0
        for route in app.url_map.iter_rules():
            if not route.endpoint.startswith(('v5_forms.', 'v5_original_form_compat.')):continue
            path = route.rule.replace('<token>', token).replace('<path_token>', token)
            for method in route.methods - {'HEAD', 'OPTIONS'}:
                with self.subTest(path=route.rule, method=method):
                    response = app.test_client().open(path, method=method, json={},
                                                     headers={'Authorization': 'Bearer ' + token})
                    self.assertEqual(response.status_code, 409, response.get_json())
                    self.assertEqual(response.json['code'], 'demo_contact_excluded_from_production')
                    checked += 1
        # Six native route methods and twelve compatibility route methods.
        self.assertEqual(checked, 18)
        self.assertEqual(self.snapshot(repo), before)
        self.assertEqual(gateway.mock_calls, [])
        self.assertEqual(sender.mock_calls, [])

    def test_phone_identity_and_mobile_alias_block_old_forms_in_other_conversations(self):
        app, repo, _, rows, gateway, sender, _, _ = self.make_app()
        before = self.snapshot(repo)
        for label in ('owner_other_chat', 'owner_alias'):
            response = app.test_client().post('/cadastro/api/email/enviar', json={},
                headers={'Authorization': 'Bearer ' + rows[label]['token']})
            self.assertEqual((response.status_code, response.json['code']),
                             (409, 'demo_contact_excluded_from_production'))
        self.assertEqual(self.snapshot(repo), before)
        self.assertEqual(gateway.mock_calls, [])
        self.assertEqual(sender.mock_calls, [])

    def test_direct_link_and_identity_helpers_reject_owner(self):
        app, repo, _, rows, _, _, _, _ = self.make_app()
        before = self.snapshot(repo)
        event = {'account_id': '1', 'inbox_id': '3', 'conversation_id': '7',
                 'contact_id': '9', 'sender_phone': PHONE}
        with app.app_context():
            for name, args in (('v5_form_link_factory', ({}, {}, event)),
                               ('v5_form_creator_hint', ({}, event))):
                with self.assertRaises(FormError) as caught:app.extensions[name](*args)
                self.assertEqual(caught.exception.code, 'demo_contact_excluded_from_production')
        self.assertEqual(self.snapshot(repo), before)

    def test_other_contact_otp_and_startup_match_with_demo_disabled(self):
        outcomes = []
        for enabled in (False, True):
            app, repo, _, rows, gateway, sender, _, _ = self.make_app(enabled=enabled)
            response = app.test_client().post('/cadastro/api/email/enviar',
                json={'email': 'synthetic' + '@' + 'example.invalid'},
                headers={'Authorization': 'Bearer ' + rows['other']['token']})
            self.assertEqual(response.status_code, 202, response.json)
            outcomes.append((response.json, repo.load_session(rows['other']['key']), sender.send_otp.call_count))
            self.assertEqual(gateway.mock_calls, [])
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0][2], 1)

    def test_disabled_demo_preserves_owner_normal_form_behavior(self):
        app, _, _, rows, _, sender, _, _ = self.make_app(enabled=False)
        response = app.test_client().post('/cadastro/api/email/enviar',
            json={'email': 'synthetic' + '@' + 'example.invalid'},
            headers={'Authorization': 'Bearer ' + rows['owner']['token']})
        self.assertEqual(response.status_code, 202, response.json)
        sender.send_otp.assert_called_once()

    def test_enabled_demo_without_verified_runtime_scope_fails_before_store_access(self):
        from flask import Flask
        app, repository = Flask(__name__), Mock()
        with self.assertRaisesRegex(ValueError, 'demo_forms_require_verified_scope'):
            register_forms(app, {'demo_enabled': True}, repository)
        self.assertEqual(repository.mock_calls, [])
