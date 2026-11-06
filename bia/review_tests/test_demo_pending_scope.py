"""A preapproved phone enters rehearsal only after a read-only Chatwoot proof."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, call, patch

from config import load_settings
from demo_router import (DemoScope, DemoPhoneReservation, DemoPendingRouter, DemoWhatsAppGateway,
                         RecordingGateway, ProductionTransportFence, build_demo_router,
                         configured_scopes, configured_pending_scope, production_blocked,
                         excluded_conversations)
from repository import Repository
from test_demo_router import NOW, SCOPE, PHONE, TOKEN, settings
from test_demo_multi_scope import SECOND, THIRD_PHONE, source
import test_demo_multi_scope as multi_fixtures
import test_demo_forms as form_fixtures


def pending_settings(directory):
    config = settings(directory)
    config['demo_continuation_enabled'] = True
    config['demo_pending_scope'] = {key: getattr(SECOND, key) for key in ('account_id', 'inbox_id', 'phone')}
    return config


class Provider:
    """Synthetic HTTP responses. No network client can be created by the suite."""
    def __init__(self, scope=SECOND, message=None):
        self.scope, self.at = scope, NOW
        self.calls = []
        self.fail_get = False
        self.unknown_post = False
        self.before_post = None
        self.detail = {'id': scope.conversation_id, 'account_id': scope.account_id,
                       'inbox_id': scope.inbox_id, 'can_reply': True,
                       'meta': {'sender': {'id': scope.contact_id, 'phone_number': scope.phone}}}
        message = message or source(scope, text='Oi', created_at=NOW.isoformat())
        self.messages = [{'id': message['message_id'], 'conversation_id': scope.conversation_id,
                          'message_type': 'incoming', 'private': False, 'content': message['text'],
                          'sender': {'id': scope.contact_id, 'phone_number': scope.phone},
                          'created_at': NOW.timestamp()}]

    def factory(self, scope):
        return DemoWhatsAppGateway('https://chat.pending.invalid', 'synthetic-pending-token',
                                  scope=scope, live_enabled=True, opener=self,
                                  continuation_enabled=True, now=lambda: self.at)

    def open(self, request, timeout):
        self.calls.append((request.method, request.full_url))
        if request.method == 'POST':
            if self.before_post:
                self.before_post()
            result = {'id': '200', 'conversation_id': self.scope.conversation_id,
                      'source_id': 'synthetic-pending-receipt'}
            if self.unknown_post:
                raise TimeoutError('synthetic uncertain send')
        elif self.fail_get:
            raise TimeoutError('synthetic read failed')
        elif request.full_url.endswith('/messages'):
            result = {'payload': self.messages}
        else:
            result = self.detail
        return io.BytesIO(json.dumps(result).encode())

    @property
    def posts(self):
        return sum(method == 'POST' for method, _ in self.calls)


class PendingConfiguration(unittest.TestCase):
    def test_optional_pending_requires_complete_fixed_account_inbox_phone(self):
        config = pending_settings('/tmp/pending')
        for value in (None, [], {}, {'phone': SECOND.phone},
                      {**config['demo_pending_scope'], 'contact_id': '18'},
                      {**config['demo_pending_scope'], 'phone': '9835'},
                      {**config['demo_pending_scope'], 'account_id': '2'},
                      {**config['demo_pending_scope'], 'phone': PHONE}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                configured_pending_scope({**config, 'demo_pending_scope': value}, (SCOPE,))
        with self.assertRaises(ValueError):
            configured_pending_scope(config, (SCOPE, SECOND))

    def test_disabling_router_with_new_reservations_fails_startup_closed(self):
        config = pending_settings('/tmp/pending')
        config['demo_enabled'] = False
        with self.assertRaisesRegex(ValueError, 'require_enabled'):
            build_demo_router(config)
        config.pop('demo_pending_scope')
        config['demo_scopes'] = [asdict(SCOPE), asdict(SECOND)]
        with self.assertRaisesRegex(ValueError, 'require_enabled'):
            build_demo_router(config)

    def test_env_pending_keeps_production_gate_unchanged(self):
        values = {'CHATWOOT_ACCOUNT_ID': '1', 'CHATWOOT_INBOX_ID': '3',
                  'V5_PILOT_CONTACT_ID': SCOPE.contact_id, 'V5_PILOT_CONVERSATION_ID': SCOPE.conversation_id,
                  'V5_TEST_PHONE': PHONE, 'V5_DEMO_ROUTER_ENABLED': 'true'}
        baseline = load_settings(values)
        values['V5_DEMO_PENDING_SCOPE_JSON'] = json.dumps(pending_settings('/tmp/pending')['demo_pending_scope'])
        config = load_settings(values)
        self.assertEqual(config['gate'], baseline['gate'])
        self.assertEqual(config['demo_pending_scope']['phone'], SECOND.phone)
        for raw in ('', 'null', '{}', '[]', '{', 'x' * 2049):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                load_settings({**values, 'V5_DEMO_PENDING_SCOPE_JSON': raw})


class PendingBinding(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.config = pending_settings(directory.name)
        self.provider = Provider()
        self.mux = self.build()
        self.pending = self.mux.routers[1]

    def build(self, config=None, provider=None):
        router = build_demo_router(config or self.config,
                                   pending_gateway_factory=(provider or self.provider).factory)
        self.addCleanup(router.store.close)
        for child in router.routers: child.now = lambda: NOW
        return router

    def message(self, **changes):
        return source(SECOND, **{'text': 'Oi', 'created_at': NOW.isoformat(), **changes})

    def markers(self):
        return self.mux.store.db.execute("SELECT * FROM demo_starts WHERE slot LIKE 'binding:%'").fetchall()

    def test_pending_is_reserved_before_provider_lookup_or_any_state(self):
        for phone in (SECOND.phone, SECOND.phone[:5] + SECOND.phone[6:]):
            message = {**self.message(), 'sender_phone': phone}
            self.assertTrue(production_blocked(self.config, event=message))
        self.assertEqual(excluded_conversations(self.config), (SCOPE.conversation_key,))
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.markers(), [])
        self.assertEqual(self.mux.store.db.execute('SELECT count(*) FROM demo_runs').fetchone()[0], 0)

    def test_catchup_and_controls_cannot_bind_or_send(self):
        self.assertEqual(self.mux.handle(self.message())[0]['status'], 'demo_identity_rejected')
        with self.assertRaises(ValueError): self.mux.select(asdict(SECOND))
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.markers(), [])

    def test_first_verified_inbound_binds_persists_then_presents_once(self):
        def persisted_before_post():
            self.assertEqual(len(self.markers()), 1)
            self.assertTrue(production_blocked(self.config, conversation_key=SECOND.conversation_key))
            rows = self.mux.store.db.execute("SELECT * FROM demo_outbox WHERE slot=? AND status='outcome_unknown'", (SECOND.slot,)).fetchall()
            self.assertEqual(len(rows), 1)
        self.provider.before_post = persisted_before_post
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.pending.scope.bound_scope, SECOND)
        self.assertEqual(self.provider.posts, 1)
        self.assertTrue(all(url.startswith('https://chat.pending.invalid/api/v1/accounts/1/conversations/17')
                            for _, url in self.provider.calls))
        self.assertEqual(self.mux.handle_verified_webhook(self.message()), result)
        self.assertEqual(self.provider.posts, 1)
        self.assertIsNone(self.mux.store.current(SCOPE.slot))

    def test_conflicting_replay_never_changes_binding_or_sends(self):
        self.mux.handle_verified_webhook(self.message())
        markers = [tuple(row) for row in self.markers()]
        result = self.mux.handle_verified_webhook(self.message(text='Altered first message'))
        self.assertEqual(result[0]['status'], 'demo_conflicting_duplicate')
        self.assertEqual([tuple(row) for row in self.markers()], markers)
        self.assertEqual(self.provider.posts, 1)

    def test_second_message_continues_existing_demo_router(self):
        self.mux.handle_verified_webhook(self.message())
        current = self.mux.store.current(SECOND.slot)
        message = self.message(message_id='201', text='Conhecer a Amplify',
                               demo_reply_to=current['parent_id'], created_at=(NOW + timedelta(seconds=1)).isoformat())
        result = self.mux.handle_verified_webhook(message)
        self.assertEqual(result[0]['step'], 'about')
        self.assertEqual(self.provider.posts, 2)
        self.assertEqual(len(self.markers()), 1)

    def test_conflicting_ids_after_binding_stay_reserved_without_rebind(self):
        self.mux.handle_verified_webhook(self.message())
        calls = len(self.provider.calls)
        for changes in ({'contact_id': '19'}, {'conversation_id': '19'}, {'sender_phone': THIRD_PHONE}):
            message = {**self.message(message_id='202'), **changes}
            result = self.mux.handle_verified_webhook(message)
            self.assertEqual(result[0]['status'], 'demo_identity_rejected')
            self.assertTrue(production_blocked(self.config, event=message))
        self.assertEqual(len(self.provider.calls), calls)
        self.assertEqual(self.pending.scope.bound_scope, SECOND)

    def test_new_identity_must_not_overlap_primary(self):
        for changes in ({'contact_id': SCOPE.contact_id}, {'conversation_id': SCOPE.conversation_id}):
            result = self.mux.handle_verified_webhook({**self.message(), **changes})
            self.assertEqual(result[0]['status'], 'demo_binding_unverified')
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.markers(), [])

    def test_invalid_inbound_and_stale_first_message_never_query_provider(self):
        for changes in ({'contact_id': None}, {'message_id': None}, {'private': True},
                        {'message_type': 'outgoing'}, {'sender_type': 'user'}, {'provider': 'foreign'},
                        {'created_at': None}, {'created_at': (NOW - timedelta(minutes=6)).isoformat()},
                        {'created_at': (NOW + timedelta(minutes=1)).isoformat()}):
            result = self.mux.handle_verified_webhook({**self.message(), **changes})
            self.assertEqual(result[0]['status'], 'demo_binding_unverified')
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.markers(), [])

    def test_provider_failure_never_falls_back_or_mutates_binding(self):
        self.provider.fail_get = True
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_binding_unverified')
        self.assertIsNone(self.pending.scope.bound_scope)
        self.assertEqual(self.markers(), [])
        self.assertEqual(self.provider.posts, 0)
        self.assertTrue(production_blocked(self.config, event=self.message()))

    def test_wrong_provider_detail_identity_is_rejected_before_post(self):
        base = deepcopy(self.provider.detail)
        variants = [{**base, key: value} for key, value in
                    (('id', '999'), ('account_id', '2'), ('inbox_id', '4'), ('can_reply', False))]
        variants += [{**base, 'meta': {'sender': {**base['meta']['sender'], key: value}}}
                     for key, value in (('id', '999'), ('phone_number', THIRD_PHONE))]
        for detail in variants:
            self.provider.detail = detail
            self.assertEqual(self.mux.handle_verified_webhook(self.message())[0]['status'], 'demo_binding_unverified')
        self.assertEqual(self.markers(), [])
        self.assertEqual(self.provider.posts, 0)

    def test_provider_message_must_prove_id_sender_conversation_content_and_time(self):
        original = deepcopy(self.provider.messages[0])
        variants = [[], [original, original]]
        variants += [[{**original, key: value}] for key, value in (
            ('id', '102'), ('conversation_id', '999'), ('content', 'Different'),
            ('message_type', 'outgoing'), ('private', True), ('created_at', NOW.timestamp() - 3),
            ('sender', {'id': '999', 'phone_number': SECOND.phone}),
            ('sender', {'id': SECOND.contact_id, 'phone_number': THIRD_PHONE}))]
        for messages in variants:
            self.provider.messages = messages
            self.assertEqual(self.mux.handle_verified_webhook(self.message())[0]['status'], 'demo_binding_unverified')
        self.assertEqual(self.markers(), [])
        self.assertEqual(self.provider.posts, 0)

    def test_recording_gateway_cannot_establish_identity(self):
        self.pending.gateway_factory = lambda scope: RecordingGateway()
        self.assertEqual(self.mux.handle_verified_webhook(self.message())[0]['status'], 'demo_binding_unverified')
        self.assertEqual(self.markers(), [])

    def test_persist_failure_reserves_verified_ids_but_sends_nothing(self):
        self.mux.store.db.execute("CREATE TEMP TRIGGER reject_binding BEFORE INSERT ON demo_starts WHEN NEW.slot LIKE 'binding:%' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END")
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_binding_unavailable')
        self.assertEqual(self.provider.posts, 0)
        self.assertTrue(production_blocked(self.config, conversation_key=SECOND.conversation_key))
        self.assertEqual(self.mux.handle_verified_webhook(self.message())[0]['status'], 'demo_binding_unavailable')
        with self.assertRaises(ValueError): self.mux.select(asdict(SECOND))

    def test_concurrent_first_messages_bind_and_send_once(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.mux.handle_verified_webhook(self.message()))) for _ in range(5)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(results), 5)
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.markers()), 1)
        self.assertEqual(self.provider.posts, 1)

    def test_uncertain_send_stays_single_attempt_after_duplicate_and_restart(self):
        self.provider.unknown_post = True
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.mux.handle_verified_webhook(self.message()), result)
        self.assertEqual(self.provider.posts, 1)
        self.assertEqual(len(self.markers()), 1)
        self.assertTrue(production_blocked(self.config, conversation_key=SECOND.conversation_key))

    def test_durable_binding_reloads_without_lookup_and_keeps_dedup(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = pending_settings(directory.name)
        config['demo_state_path'] = str(Path(directory.name) / 'demo.sqlite3')
        first = self.build(config)
        result = first.handle_verified_webhook(self.message())
        before = list(self.provider.calls)
        second = self.build(config)
        self.assertEqual(second.routers[1].scope.bound_scope, SECOND)
        self.assertEqual(self.provider.calls, before)
        self.assertEqual(second.handle_verified_webhook(self.message()), result)
        self.assertEqual(self.provider.calls, before)

    def test_normalized_phone_format_can_reload_existing_binding(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = pending_settings(directory.name)
        config['demo_state_path'] = str(Path(directory.name) / 'demo.sqlite3')
        first = self.build(config)
        result = first.handle_verified_webhook(self.message())
        reformatted = {**config, 'demo_pending_scope': {**config['demo_pending_scope'], 'phone': SECOND.phone.lstrip('+')}}
        second = self.build(reformatted)
        self.assertEqual(second.handle_verified_webhook(self.message()), result)
        self.assertEqual(self.provider.posts, 1)

    def test_overlapping_started_instances_reload_unique_binding_without_resend(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = pending_settings(directory.name)
        config['demo_state_path'] = str(Path(directory.name) / 'demo.sqlite3')
        first = self.build(config)
        second = self.build(config)
        result = first.handle_verified_webhook(self.message())
        self.assertEqual(second.handle_verified_webhook(self.message()), result)
        self.assertFalse(second.routers[1].binding_failed)
        self.assertEqual(second.routers[1].scope.bound_scope, SECOND)
        self.assertEqual(self.provider.posts, 1)

    def test_corrupt_or_changed_binding_fails_startup_closed(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = pending_settings(directory.name)
        config['demo_state_path'] = str(Path(directory.name) / 'demo.sqlite3')
        first = self.build(config)
        first.handle_verified_webhook(self.message())
        original = first.store.db.execute("SELECT result FROM demo_starts WHERE slot LIKE 'binding:%'").fetchone()[0]
        for replacement in ('{}', json.dumps({**json.loads(original), 'scope_json': json.dumps(asdict(SCOPE))})):
            first.store.db.execute("UPDATE demo_starts SET result=? WHERE slot LIKE 'binding:%'", (replacement,))
            with self.assertRaises(ValueError): build_demo_router(config, pending_gateway_factory=self.provider.factory)

    def test_continuation_disabled_keeps_both_reserved_and_uses_legacy_opening(self):
        config = pending_settings(self.config['state_dir'])
        config['demo_continuation_enabled'] = False
        mux = self.build(config)
        result = mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertTrue(mux.store.current(SECOND.slot)['outbox_key'].startswith('bia-demo:v1:'))
        self.assertTrue(production_blocked(config, event=self.message()))
        self.assertTrue(production_blocked(config, event=source(SCOPE)))
        self.assertEqual(self.provider.posts, 1)

    def test_live_delivery_disabled_keeps_reservation_without_network_before_or_after_binding(self):
        config = pending_settings(self.config['state_dir'])
        config.update(chatwoot_base_url='https://chat.pending.invalid', chatwoot_api_token='synthetic',
                      demo_whatsapp_live=False)
        mux = build_demo_router(config)
        self.addCleanup(mux.store.close)
        mux.routers[1].now = lambda: NOW
        # If a socket could be created here, the offline audit hook fails the test.
        self.assertEqual(mux.handle_verified_webhook(self.message())[0]['status'], 'demo_binding_unverified')
        self.assertTrue(production_blocked(config, event=self.message()))
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config['demo_state_path'] = str(Path(directory.name) / 'demo.sqlite3')
        enabled = self.build(config)
        enabled.handle_verified_webhook(self.message())
        sends = self.provider.posts
        stopped = build_demo_router(config)
        self.addCleanup(stopped.store.close)
        stopped.routers[1].now = lambda: NOW
        self.assertTrue(production_blocked(config, conversation_key=SECOND.conversation_key))
        response = stopped.handle_verified_webhook(self.message(message_id='202', text='Resetar'))
        self.assertEqual(response[0]['status'], 'demo_reset_unavailable')
        self.assertEqual(self.provider.posts, sends)

    def test_catchup_old_jobs_and_executor_are_blocked_by_phone_before_binding(self):
        from retomada import PosPausa, Retomada
        from real_operations import RealExecutor
        repo = Repository(Path(self.config['state_dir']) / 'production.sqlite3')
        repo.set_demo_scope(self.mux.scope)
        row = {'conversation_key': SECOND.conversation_key, 'event_json': json.dumps(self.message())}
        self.assertTrue(repo._demo_row_blocked(row))
        worker = PosPausa.__new__(PosPausa); worker.settings = self.config; worker._get = Mock()
        candidate = {'id': SECOND.conversation_id, 'inbox_id': SECOND.inbox_id,
                     'meta': {'sender': {'id': SECOND.contact_id, 'phone_number': SECOND.phone}}}
        self.assertEqual(worker._candidate(candidate, NOW, 'https://example.invalid')[1], 'demo_contact_excluded_from_production')
        worker._get.assert_not_called()
        executor = RealExecutor.__new__(RealExecutor); executor.settings = self.config
        executor.repository, executor.lock_for = Mock(), Mock()
        job = {'conversation_key': SECOND.conversation_key, 'event': self.message()}
        self.assertFalse(executor._authorized(job))
        self.assertEqual(executor._apply(job)['status'], 'blocked')
        self.assertEqual(executor.repository.mock_calls, [])
        worker = Retomada.__new__(Retomada); worker.settings = self.config
        worker.repository, worker.registration = Mock(), Mock()
        from contextlib import nullcontext
        worker.lock_for = lambda *args: nullcontext()
        worker.repository.followup_source.return_value = {'event': self.message()}
        worker.repository.load_session.return_value = {}
        self.assertEqual(worker._conversation(SECOND.conversation_key, NOW)['status'], 'blocked')
        worker.registration.assert_not_called()
        self.assertIsNone(self.pending.scope.bound_scope)

    def test_existing_repository_and_transport_see_new_identity_immediately(self):
        repo = Repository(Path(self.config['state_dir']) / 'production.sqlite3')
        repo.set_demo_scope(self.mux.scope)
        delegate = Mock(); fence = ProductionTransportFence(delegate, self.mux.scope)
        self.assertEqual(fence.send_reply(self.message())['status'], 'failed')
        self.mux.handle_verified_webhook(self.message())
        # Conversation reservation must remain effective even for corrupted old event metadata.
        row = {'conversation_key': SECOND.conversation_key, 'event_json': '{}'}
        self.assertTrue(repo._demo_row_blocked(row))
        with self.assertRaisesRegex(ValueError, 'excluded'):
            fence.http(method='POST', url='https://chat.pending.invalid/api/v1/accounts/1/conversations/17/messages')
        self.assertEqual(delegate.mock_calls, [])


class PendingWebhook(unittest.TestCase):
    def make_app(self):
        from server import create_app
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = pending_settings(directory.name)
        repo = Repository(Path(directory.name) / 'production.sqlite3')
        transport = Mock(); transport.ready.return_value = True; transport.supports_reply_fencing = False
        app = create_app(config, repository=repo, transport=transport,
                         real_guard=Mock(return_value={'allowed': True}), real_client=Mock())
        app.testing = True
        mux = app.extensions['v5_demo_router']; self.addCleanup(mux.store.close)
        provider = Provider(message=source(SECOND, text='Resetar', created_at=NOW.isoformat()))
        pending = mux.routers[1]; pending.gateway_factory = provider.factory; pending.now = lambda: NOW
        return app, repo, transport, mux, provider

    def raw(self):
        return multi_fixtures.MultiWebhookBoundaries.raw(self)

    def test_only_authenticated_webhook_can_bind_and_enter_demo(self):
        app, repo, transport, mux, provider = self.make_app()
        result = app.test_client().post('/webhook/chatwoot', json=self.raw())
        self.assertEqual(result.status_code, 401)
        self.assertEqual(provider.calls, [])
        result = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=self.raw())
        self.assertEqual(result.json['status'], 'demo_reset_presented')
        self.assertEqual(provider.posts, 1)
        self.assertTrue(all(item == call.ready() for item in transport.mock_calls))
        with repo._connection() as db:
            for table in ('sessions', 'inbound_events', 'outbox', 'real_jobs', 'operations'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_conflicting_webhook_metadata_is_ignored_without_lookup(self):
        app, _, _, mux, provider = self.make_app()
        raw = self.raw(); raw['conversation']['meta']['sender'] = {**raw['sender'], 'id': '999'}
        result = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=raw)
        self.assertEqual(result.json['status'], 'ignored')
        self.assertEqual(provider.calls, [])
        self.assertIsNone(mux.routers[1].scope.bound_scope)

    def test_lookup_failure_returns_demo_status_and_never_production(self):
        app, repo, transport, mux, provider = self.make_app()
        provider.fail_get = True
        result = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=self.raw())
        self.assertEqual(result.json['status'], 'demo_binding_unverified')
        self.assertEqual(provider.posts, 0)
        self.assertTrue(all(item == call.ready() for item in transport.mock_calls))
        with repo._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM inbound_events').fetchone()[0], 0)


class PendingForms(unittest.TestCase):
    def test_legacy_form_phone_hash_is_reserved_before_ids_exist(self):
        original = form_fixtures.settings
        def configured(directory, **kwargs):
            config = original(directory, **kwargs)
            config['demo_pending_scope'] = {'account_id': '1', 'inbox_id': '3', 'phone': form_fixtures.OTHER}
            return config
        with patch.object(form_fixtures, 'settings', side_effect=configured):
            app, repo, _, rows, gateway, sender, _, _ = form_fixtures.DemoFormBoundary.make_app(self)
        pending = app.extensions['v5_demo_router'].routers[1]
        self.assertIsNone(pending.scope.bound_scope)
        before = form_fixtures.DemoFormBoundary.snapshot(self, repo)
        token = rows['other']['token']
        for route in app.url_map.iter_rules():
            if not route.endpoint.startswith(('v5_forms.', 'v5_original_form_compat.')):
                continue
            path = route.rule.replace('<token>', token).replace('<path_token>', token)
            for method in route.methods - {'HEAD', 'OPTIONS'}:
                response = app.test_client().open(path, method=method, json={},
                                                 headers={'Authorization': 'Bearer ' + token})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json['code'], 'demo_contact_excluded_from_production')
        self.assertEqual(form_fixtures.DemoFormBoundary.snapshot(self, repo), before)
        self.assertEqual(gateway.mock_calls, [])
        self.assertEqual(sender.mock_calls, [])
