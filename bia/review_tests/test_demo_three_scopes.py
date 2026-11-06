"""Explicit test contacts share no session, send authority or production path."""
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from config import load_settings
from contracts import normalize_phone
from demo_router import (DemoScope, DemoScopes, MAX_DEMO_SCOPES, build_demo_router,
                         configured_scopes, configured_pending_scope, production_blocked,
                         excluded_conversations, ProductionTransportFence)
from repository import Repository
from test_demo_router import NOW, SCOPE, TOKEN
from test_demo_multi_scope import SECOND, THIRD_PHONE, multi_settings, source
import test_demo_multi_scope as multi_fixtures
import test_demo_pending_scope as pending_fixtures
import test_demo_forms as form_fixtures

THIRD = DemoScope('1', '3', '28', '27', THIRD_PHONE)
FOURTH = DemoScope('1', '3', '38', '37', '+5541981234567')
FIFTH = DemoScope('1', '3', '48', '47', '+5561981234567')
SIXTH = DemoScope('1', '3', '58', '57', '+5571981234567')
ALL = (SCOPE, SECOND, THIRD)


def three_settings(directory):
    config = multi_settings(directory)
    config['demo_scopes'].append(asdict(THIRD))
    return config


class ThreeConfiguration(unittest.TestCase):
    def test_three_four_and_five_scopes_accepted_but_six_distinct_scopes_rejected(self):
        self.assertEqual(MAX_DEMO_SCOPES, 5)
        config = three_settings('/tmp/three-demo')
        self.assertEqual(configured_scopes(config), ALL)
        config['demo_scopes'].append(asdict(FOURTH))
        self.assertEqual(configured_scopes(config), ALL + (FOURTH,))
        config['demo_scopes'].append(asdict(FIFTH))
        self.assertEqual(configured_scopes(config), ALL + (FOURTH, FIFTH))
        self.assertEqual(DemoScopes(ALL + (FOURTH, FIFTH)).scopes, ALL + (FOURTH, FIFTH))
        config['demo_scopes'].append(asdict(SIXTH))
        with self.assertRaisesRegex(ValueError, 'scopes_invalid'): configured_scopes(config)
        with self.assertRaisesRegex(ValueError, 'scopes_invalid'): DemoScopes(ALL + (FOURTH, FIFTH, SIXTH))

    def test_third_identity_complete_and_collisions_against_either_existing_scope_rejected(self):
        config = three_settings('/tmp/three-demo')
        invalid = [{k: v for k, v in asdict(THIRD).items() if k != 'contact_id'},
                   {**asdict(THIRD), 'contact_id': 28}, {**asdict(THIRD), 'account_id': '2'},
                   {**asdict(THIRD), 'inbox_id': '4'}, {**asdict(THIRD), 'phone': '9835'}]
        for existing in (SCOPE, SECOND):
            invalid += [{**asdict(THIRD), field: getattr(existing, field)}
                        for field in ('contact_id', 'conversation_id', 'phone')]
        invalid += [{**asdict(THIRD), 'phone': SECOND.phone[:5] + SECOND.phone[6:]}]
        for value in invalid:
            config['demo_scopes'] = [asdict(SCOPE), asdict(SECOND), value]
            with self.subTest(value=value), self.assertRaises(ValueError): configured_scopes(config)

    def test_env_three_scopes_preserves_primary_and_production_gate(self):
        values = {'CHATWOOT_ACCOUNT_ID': '1', 'CHATWOOT_INBOX_ID': '3',
                  'V5_PILOT_CONTACT_ID': SCOPE.contact_id, 'V5_PILOT_CONVERSATION_ID': SCOPE.conversation_id,
                  'V5_TEST_PHONE': SCOPE.phone, 'V5_DEMO_ROUTER_ENABLED': 'true'}
        baseline = load_settings(values)
        config = load_settings({**values, 'V5_DEMO_SCOPES_JSON': json.dumps([asdict(scope) for scope in ALL])})
        self.assertEqual(configured_scopes(config), ALL)
        self.assertEqual(config['gate'], baseline['gate'])
        self.assertEqual(config['demo_scope'], baseline['demo_scope'])

    def test_pending_third_counts_toward_same_total_and_checks_all_existing_identities(self):
        config = multi_settings('/tmp/three-demo')
        config['demo_pending_scope'] = {key: getattr(THIRD, key) for key in ('account_id', 'inbox_id', 'phone')}
        pending = configured_pending_scope(config, (SCOPE, SECOND))
        self.assertEqual(pending.phone, THIRD.phone)
        for existing in (SCOPE, SECOND):
            config['demo_pending_scope']['phone'] = existing.phone
            with self.subTest(existing=existing.contact_id), self.assertRaisesRegex(ValueError, 'overlap'):
                configured_pending_scope(config, (SCOPE, SECOND))
        config['demo_pending_scope']['phone'] = FOURTH.phone
        self.assertEqual(configured_pending_scope(config, ALL).phone, FOURTH.phone)
        config['demo_pending_scope']['phone'] = FIFTH.phone
        self.assertEqual(configured_pending_scope(config, ALL + (FOURTH,)).phone, FIFTH.phone)
        config['demo_pending_scope']['phone'] = SIXTH.phone
        with self.assertRaisesRegex(ValueError, 'pending_scope_invalid'):
            configured_pending_scope(config, ALL + (FOURTH, FIFTH))


class ThreeIsolation(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.config = three_settings(self.directory.name)
        self.mux = build_demo_router(self.config); self.addCleanup(self.mux.store.close)
        for router in self.mux.routers: router.now = lambda: NOW

    def message(self, scope=THIRD, **changes):
        return source(scope, **{'text': 'Oi', 'created_at': NOW.isoformat(), **changes})

    def test_fresh_third_first_entry_preserves_both_existing_sessions(self):
        for router in self.mux.routers[:2]: router.start('existing-session')
        before = [self.mux.store.current(scope.slot) for scope in ALL[:2]]
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual([self.mux.store.current(scope.slot) for scope in ALL[:2]], before)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [1, 1, 1])
        self.assertEqual(self.mux.handle_verified_webhook(self.message()), result)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [1, 1, 1])

    def test_shared_request_and_message_ids_remain_independent_for_all_three(self):
        for router in self.mux.routers: router.start('shared-request-id')
        runs = [self.mux.store.current(scope.slot)['run'] for scope in ALL]
        self.assertEqual(len(set(runs)), 3)
        for scope in ALL:
            state = self.mux.store.current(scope.slot)
            message = self.message(scope, text='Conhecer a Amplify', demo_reply_to=state['parent_id'])
            result = self.mux.handle_verified_webhook(message)
            self.assertEqual(result[0]['step'], 'about')
            self.assertEqual(self.mux.handle_verified_webhook(message), result)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [2, 2, 2])
        self.assertEqual(self.mux.store.db.execute('SELECT count(*) FROM demo_events').fetchone()[0], 3)

    def test_reset_and_stop_third_do_not_mutate_first_two(self):
        for router in self.mux.routers: router.start('existing-session')
        before = [self.mux.store.current(scope.slot) for scope in ALL[:2]]
        result = self.mux.handle_verified_webhook(self.message(text='Resetar'))
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.mux.select(asdict(THIRD)).stop()
        self.assertEqual([self.mux.store.current(scope.slot) for scope in ALL[:2]], before)
        self.assertTrue(production_blocked(self.config, event=self.message()))
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [1, 1, 2])

    def test_crossed_third_identity_is_reserved_without_any_send(self):
        for existing in ALL[:2]:
            for field, value in (('contact_id', existing.contact_id), ('conversation_id', existing.conversation_id),
                                 ('sender_phone', existing.phone)):
                message = {**self.message(), field: value}
                self.assertTrue(production_blocked(self.config, event=message))
                self.assertEqual(self.mux.handle_verified_webhook(message)[0]['status'], 'demo_identity_rejected')
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [0, 0, 0])

    def test_third_uncertain_send_does_not_resend_or_block_existing_contacts(self):
        self.mux.routers[2].gateway.send = Mock(side_effect=TimeoutError())
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.mux.handle_verified_webhook(self.message()), result)
        self.mux.routers[2].gateway.send.assert_called_once()
        for scope in ALL[:2]:
            self.assertEqual(self.mux.handle_verified_webhook(self.message(scope))[0]['status'], 'demo_reset_presented')
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers[:2]], [1, 1])

    def test_all_three_are_excluded_by_repository_and_transport_fences(self):
        repo = Repository(Path(self.directory.name) / 'production.sqlite3')
        repo.set_demo_scope(self.mux.scope)
        self.assertEqual(repo.excluded_conversations, tuple(scope.conversation_key for scope in ALL))
        self.assertEqual(excluded_conversations(self.config), repo.excluded_conversations)
        delegate = Mock(); fence = ProductionTransportFence(delegate, self.mux.scope)
        for scope in ALL:
            self.assertTrue(repo._demo_row_blocked({'conversation_key': scope.conversation_key, 'event_json': '{}'}))
            message = {**self.message(scope), 'conversation_id': '999'}
            self.assertTrue(repo._demo_row_blocked({'conversation_key': 'chatwoot:1:999', 'event_json': json.dumps(message)}))
            self.assertEqual(fence.send_reply(message)['status'], 'failed')
            self.assertEqual(fence.write_progress(message)['status'], 'failed')
            self.assertIsNone(fence.read_progress(message))
            with self.assertRaisesRegex(ValueError, 'excluded'):
                fence.http(method='POST', url='https://chat.example.invalid/api/v1/accounts/1/conversations/' + scope.conversation_id + '/messages')
        self.assertEqual(delegate.mock_calls, [])
        fence.send_reply(self.message(FOURTH))
        delegate.send_reply.assert_called_once()

    def test_restart_dedup_holds_third_without_mutating_existing_slots(self):
        config = three_settings(self.directory.name)
        config['demo_state_path'] = str(Path(self.directory.name) / 'demo.sqlite3')
        first = build_demo_router(config)
        try:
            for router in first.routers: router.now = lambda: NOW
            for router in first.routers[:2]: router.start('existing-session')
            before = [first.store.current(scope.slot) for scope in ALL[:2]]
            result = first.handle_verified_webhook(self.message())
        finally:
            first.store.close()
        again = build_demo_router(config)
        try:
            for router in again.routers: router.now = lambda: NOW
            self.assertEqual(again.handle_verified_webhook(self.message()), result)
            self.assertEqual([again.store.current(scope.slot) for scope in ALL[:2]], before)
            self.assertEqual([len(router.gateway.sent) for router in again.routers], [0, 0, 0])
        finally:
            again.store.close()

    def test_pending_third_binds_without_changing_two_static_sessions(self):
        config = multi_settings(self.directory.name)
        config['demo_pending_scope'] = {key: getattr(THIRD, key) for key in ('account_id', 'inbox_id', 'phone')}
        provider = pending_fixtures.Provider(THIRD, self.message())
        mux = build_demo_router(config, pending_gateway_factory=provider.factory)
        self.addCleanup(mux.store.close)
        for router in mux.routers: router.now = lambda: NOW
        for router in mux.routers[:2]: router.start('existing-session')
        before = [mux.store.current(scope.slot) for scope in ALL[:2]]
        self.assertEqual(mux.handle_verified_webhook(self.message())[0]['status'], 'demo_reset_presented')
        self.assertEqual(mux.routers[2].scope.bound_scope, THIRD)
        self.assertEqual([mux.store.current(scope.slot) for scope in ALL[:2]], before)
        self.assertEqual(provider.posts, 1)
        self.assertEqual(excluded_conversations(config), tuple(scope.conversation_key for scope in ALL))


class ThirdIngressAndForms(unittest.TestCase):
    def test_authenticated_third_ingress_opens_demo_without_production_effects(self):
        from server import create_app
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = three_settings(directory.name)
        repo = Repository(Path(directory.name) / 'production.sqlite3')
        transport = Mock(); transport.ready.return_value = True; transport.supports_reply_fencing = False
        app = create_app(config, repository=repo, transport=transport,
                         real_guard=Mock(return_value={'allowed': True}), real_client=Mock())
        mux = app.extensions['v5_demo_router']; self.addCleanup(mux.store.close)
        for router in mux.routers: router.now = lambda: NOW
        raw = multi_fixtures.MultiWebhookBoundaries.raw(self, scope=THIRD, text='Oi')
        client = app.test_client()
        self.assertEqual(client.post('/webhook/chatwoot', json=raw).status_code, 401)
        with redirect_stdout(io.StringIO()):
            result = client.post('/webhook/chatwoot?token=' + TOKEN, json=raw)
        self.assertEqual(result.json['status'], 'demo_reset_presented')
        self.assertEqual([len(router.gateway.sent) for router in mux.routers], [0, 0, 1])
        self.assertTrue(all(item == call.ready() for item in transport.mock_calls))
        with repo._connection() as db:
            for table in ('sessions', 'inbound_events', 'outbox', 'real_jobs', 'operations'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_third_phone_hash_blocks_all_legacy_form_routes_in_another_conversation(self):
        original = form_fixtures.settings
        second = DemoScope('1', '3', '8', '8', form_fixtures.OTHER)
        def configured(directory, **kwargs):
            config = original(directory, **kwargs)
            config['demo_scopes'] = [asdict(form_fixtures.SCOPE), asdict(second), asdict(THIRD)]
            return config
        with patch.object(form_fixtures, 'settings', side_effect=configured):
            app, repo, store, rows, gateway, sender, _, _ = form_fixtures.DemoFormBoundary.make_app(self)
        token = rows['owner_other_chat']['token']
        alias = THIRD.phone[:5] + THIRD.phone[6:]
        with store.db() as db:
            db.execute('UPDATE v5_forms SET conversation_key=?,phone_hash=? WHERE token_hash=?',
                       ('chatwoot:1:999', form_fixtures._sha(normalize_phone(alias)), form_fixtures._sha(token)))
        before = form_fixtures.DemoFormBoundary.snapshot(self, repo)
        for route in app.url_map.iter_rules():
            if not route.endpoint.startswith(('v5_forms.', 'v5_original_form_compat.')):
                continue
            path = route.rule.replace('<token>', token).replace('<path_token>', token)
            for method in route.methods - {'HEAD', 'OPTIONS'}:
                response = app.test_client().open(path, method=method, json={}, headers={'Authorization': 'Bearer ' + token})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json['code'], 'demo_contact_excluded_from_production')
        self.assertEqual(form_fixtures.DemoFormBoundary.snapshot(self, repo), before)
        self.assertEqual(gateway.mock_calls, [])
        self.assertEqual(sender.mock_calls, [])


class FourStaticScopes(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.scopes = ALL + (FOURTH,)
        self.config = three_settings(self.directory.name)
        self.config['demo_scopes'].append(asdict(FOURTH))
        self.mux = build_demo_router(self.config); self.addCleanup(self.mux.store.close)
        for router in self.mux.routers: router.now = lambda: NOW

    def message(self, scope, **changes):
        return source(scope, **{'text': 'Oi', 'created_at': NOW.isoformat(), **changes})

    def test_fourth_first_entry_and_reset_preserve_all_existing_sessions(self):
        for router in self.mux.routers[:3]: router.start('existing-session')
        before = [self.mux.store.current(scope.slot) for scope in ALL]
        message = self.message(FOURTH)
        result = self.mux.handle_verified_webhook(message)
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.mux.handle_verified_webhook(message), result)
        self.assertEqual([self.mux.store.current(scope.slot) for scope in ALL], before)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [1, 1, 1, 1])
        self.assertEqual(self.mux.handle_verified_webhook(self.message(FOURTH, text='Resetar', message_id='102'))[0]['status'], 'demo_reset_presented')
        self.mux.select(asdict(FOURTH)).stop()
        self.assertEqual([self.mux.store.current(scope.slot) for scope in ALL], before)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [1, 1, 1, 2])

    def test_all_four_use_independent_same_request_and_event_ids(self):
        for router in self.mux.routers: router.start('shared-start-id')
        self.assertEqual(len({self.mux.store.current(scope.slot)['run'] for scope in self.scopes}), 4)
        for scope in self.scopes:
            state = self.mux.store.current(scope.slot)
            message = self.message(scope, text='Conhecer a Amplify', demo_reply_to=state['parent_id'])
            result = self.mux.handle_verified_webhook(message)
            self.assertEqual(result[0]['step'], 'about')
            self.assertEqual(self.mux.handle_verified_webhook(message), result)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [2, 2, 2, 2])
        self.assertEqual(self.mux.store.db.execute('SELECT count(*) FROM demo_events').fetchone()[0], 4)

    def test_fourth_collision_with_any_existing_scope_is_rejected(self):
        for scope in ALL:
            for field in ('contact_id', 'conversation_id', 'phone'):
                values = [asdict(item) for item in self.scopes]
                values[3][field] = getattr(scope, field)
                with self.subTest(scope=scope.contact_id, field=field), self.assertRaisesRegex(ValueError, 'overlap'):
                    configured_scopes({**self.config, 'demo_scopes': values})

    def test_all_four_reserved_in_scans_jobs_and_transport_without_starving_other(self):
        repo = Repository(Path(self.directory.name) / 'production.sqlite3')
        repo.set_demo_scope(self.mux.scope)
        self.assertEqual(excluded_conversations(self.config), tuple(scope.conversation_key for scope in self.scopes))
        delegate = Mock(); fence = ProductionTransportFence(delegate, self.mux.scope)
        for scope in self.scopes + (FIFTH,):
            key = 'synthetic-' + scope.contact_id
            message = self.message(scope)
            with repo._connection() as db:
                db.execute('INSERT INTO inbound_events VALUES(?,?,?,?,?,?)',
                    (key + ':source', scope.conversation_key, 'synthetic', 'completed', NOW.isoformat(), NOW.isoformat()))
                db.execute('INSERT INTO real_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (key, scope.conversation_key, key + ':source', 'effect-' + key, 'cycle-' + key, '@synthetic',
                     'precheck', json.dumps(message), '{}', 'queued', 0, NOW.isoformat(), None, None, NOW.isoformat()))
            if scope != FIFTH:
                self.assertTrue(production_blocked(self.config, event=message))
                self.assertEqual(fence.send_reply(message)['status'], 'failed')
                with self.assertRaisesRegex(ValueError, 'excluded'):
                    fence.http(method='POST', url='https://chat.example.invalid/api/v1/accounts/1/conversations/' + scope.conversation_id + '/messages')
        self.assertEqual(delegate.mock_calls, [])
        self.assertEqual(repo.precheck_conversations(), [FIFTH.conversation_key])
        self.assertEqual(repo.claim_real_job(NOW.isoformat())['job_key'], 'synthetic-' + FIFTH.contact_id)
        self.assertIsNone(repo.claim_real_job(NOW.isoformat()))
        for scope in self.scopes:
            self.assertEqual(repo.real_job('synthetic-' + scope.contact_id)['status'], 'queued')
            self.assertEqual(repo.real_job('synthetic-' + scope.contact_id)['attempts'], 0)

    def test_four_static_env_load_does_not_change_gate_or_primary(self):
        values = {'CHATWOOT_ACCOUNT_ID': '1', 'CHATWOOT_INBOX_ID': '3',
                  'V5_PILOT_CONTACT_ID': SCOPE.contact_id, 'V5_PILOT_CONVERSATION_ID': SCOPE.conversation_id,
                  'V5_TEST_PHONE': SCOPE.phone, 'V5_DEMO_ROUTER_ENABLED': 'true'}
        baseline = load_settings(values)
        config = load_settings({**values, 'V5_DEMO_SCOPES_JSON': json.dumps([asdict(scope) for scope in self.scopes])})
        self.assertEqual(configured_scopes(config), self.scopes)
        self.assertEqual(config['gate'], baseline['gate'])
        self.assertEqual(config['demo_scope'], baseline['demo_scope'])


class FiveStaticScopes(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.scopes = ALL + (FOURTH, FIFTH)
        self.config = three_settings(self.directory.name)
        self.config['demo_scopes'].extend([asdict(FOURTH), asdict(FIFTH)])
        self.mux = build_demo_router(self.config); self.addCleanup(self.mux.store.close)
        for router in self.mux.routers: router.now = lambda: NOW

    def message(self, scope, **changes):
        return source(scope, **{'text': 'Oi', 'created_at': NOW.isoformat(), **changes})

    def test_fifth_first_entry_and_reset_preserve_all_existing_sessions(self):
        for router in self.mux.routers[:4]: router.start('existing-session')
        before = [self.mux.store.current(scope.slot) for scope in self.scopes[:-1]]
        message = self.message(FIFTH)
        result = self.mux.handle_verified_webhook(message)
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.mux.handle_verified_webhook(message), result)
        self.assertEqual([self.mux.store.current(scope.slot) for scope in self.scopes[:-1]], before)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [1, 1, 1, 1, 1])
        self.assertEqual(self.mux.handle_verified_webhook(self.message(FIFTH, text='Resetar', message_id='102'))[0]['status'], 'demo_reset_presented')
        self.mux.select(asdict(FIFTH)).stop()
        self.assertEqual([self.mux.store.current(scope.slot) for scope in self.scopes[:-1]], before)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [1, 1, 1, 1, 2])

    def test_all_five_use_independent_same_request_and_event_ids(self):
        for router in self.mux.routers: router.start('shared-start-id')
        self.assertEqual(len({self.mux.store.current(scope.slot)['run'] for scope in self.scopes}), 5)
        for scope in self.scopes:
            state = self.mux.store.current(scope.slot)
            message = self.message(scope, text='Conhecer a Amplify', demo_reply_to=state['parent_id'])
            result = self.mux.handle_verified_webhook(message)
            self.assertEqual(result[0]['step'], 'about')
            self.assertEqual(self.mux.handle_verified_webhook(message), result)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [2, 2, 2, 2, 2])
        self.assertEqual(self.mux.store.db.execute('SELECT count(*) FROM demo_events').fetchone()[0], 5)

    def test_fifth_collision_with_any_existing_scope_is_rejected(self):
        for scope in self.scopes[:-1]:
            for field in ('contact_id', 'conversation_id', 'phone'):
                values = [asdict(item) for item in self.scopes]
                values[4][field] = getattr(scope, field)
                with self.subTest(scope=scope.contact_id, field=field), self.assertRaisesRegex(ValueError, 'overlap'):
                    configured_scopes({**self.config, 'demo_scopes': values})

    def test_all_five_reserved_in_scans_jobs_and_transport_without_starving_other(self):
        repo = Repository(Path(self.directory.name) / 'production.sqlite3')
        repo.set_demo_scope(self.mux.scope)
        self.assertEqual(excluded_conversations(self.config), tuple(scope.conversation_key for scope in self.scopes))
        delegate = Mock(); fence = ProductionTransportFence(delegate, self.mux.scope)
        for scope in self.scopes + (SIXTH,):
            key = 'synthetic-' + scope.contact_id
            message = self.message(scope)
            with repo._connection() as db:
                db.execute('INSERT INTO inbound_events VALUES(?,?,?,?,?,?)',
                    (key + ':source', scope.conversation_key, 'synthetic', 'completed', NOW.isoformat(), NOW.isoformat()))
                db.execute('INSERT INTO real_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (key, scope.conversation_key, key + ':source', 'effect-' + key, 'cycle-' + key, '@synthetic',
                     'precheck', json.dumps(message), '{}', 'queued', 0, NOW.isoformat(), None, None, NOW.isoformat()))
            if scope != SIXTH:
                self.assertTrue(production_blocked(self.config, event=message))
                self.assertEqual(fence.send_reply(message)['status'], 'failed')
                with self.assertRaisesRegex(ValueError, 'excluded'):
                    fence.http(method='POST', url='https://chat.example.invalid/api/v1/accounts/1/conversations/' + scope.conversation_id + '/messages')
        self.assertEqual(delegate.mock_calls, [])
        self.assertEqual(repo.precheck_conversations(), [SIXTH.conversation_key])
        self.assertEqual(repo.claim_real_job(NOW.isoformat())['job_key'], 'synthetic-' + SIXTH.contact_id)
        self.assertIsNone(repo.claim_real_job(NOW.isoformat()))
        for scope in self.scopes:
            self.assertEqual(repo.real_job('synthetic-' + scope.contact_id)['status'], 'queued')
            self.assertEqual(repo.real_job('synthetic-' + scope.contact_id)['attempts'], 0)

    def test_five_static_env_load_does_not_change_gate_or_primary(self):
        values = {'CHATWOOT_ACCOUNT_ID': '1', 'CHATWOOT_INBOX_ID': '3',
                  'V5_PILOT_CONTACT_ID': SCOPE.contact_id, 'V5_PILOT_CONVERSATION_ID': SCOPE.conversation_id,
                  'V5_TEST_PHONE': SCOPE.phone, 'V5_DEMO_ROUTER_ENABLED': 'true'}
        baseline = load_settings(values)
        config = load_settings({**values, 'V5_DEMO_SCOPES_JSON': json.dumps([asdict(scope) for scope in self.scopes])})
        self.assertEqual(configured_scopes(config), self.scopes)
        self.assertEqual(config['gate'], baseline['gate'])
        self.assertEqual(config['demo_scope'], baseline['demo_scope'])

    def test_fifth_restart_dedup_preserves_four_existing_histories(self):
        config = {**self.config, 'demo_state_path': str(Path(self.directory.name) / 'restart.sqlite3')}
        first = build_demo_router(config)
        try:
            for router in first.routers: router.now = lambda: NOW
            for router in first.routers[:4]: router.start('existing-session')
            before = [first.store.current(scope.slot) for scope in self.scopes[:-1]]
            result = first.handle_verified_webhook(self.message(FIFTH))
            self.assertEqual(result[0]['status'], 'demo_reset_presented')
        finally:
            first.store.close()
        again = build_demo_router(config)
        try:
            for router in again.routers: router.now = lambda: NOW
            self.assertEqual(again.handle_verified_webhook(self.message(FIFTH)), result)
            self.assertEqual([again.store.current(scope.slot) for scope in self.scopes[:-1]], before)
            self.assertEqual([len(router.gateway.sent) for router in again.routers], [0] * 5)
        finally:
            again.store.close()

    def test_pending_fifth_binds_without_changing_four_existing_sessions(self):
        config = {**self.config, 'demo_scopes': [asdict(scope) for scope in self.scopes[:-1]]}
        config['demo_pending_scope'] = {key: getattr(FIFTH, key) for key in ('account_id', 'inbox_id', 'phone')}
        provider = pending_fixtures.Provider(FIFTH, self.message(FIFTH))
        mux = build_demo_router(config, pending_gateway_factory=provider.factory)
        self.addCleanup(mux.store.close)
        for router in mux.routers: router.now = lambda: NOW
        for router in mux.routers[:4]: router.start('existing-session')
        before = [mux.store.current(scope.slot) for scope in self.scopes[:-1]]
        result = mux.handle_verified_webhook(self.message(FIFTH))
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(mux.handle_verified_webhook(self.message(FIFTH)), result)
        self.assertEqual(mux.routers[4].scope.bound_scope, FIFTH)
        self.assertEqual([mux.store.current(scope.slot) for scope in self.scopes[:-1]], before)
        self.assertEqual(provider.posts, 1)
        self.assertEqual(excluded_conversations(config), tuple(scope.conversation_key for scope in self.scopes))

    def test_fifth_uncertain_delivery_never_resends_or_blocks_existing_four(self):
        self.mux.routers[4].gateway.send = Mock(side_effect=TimeoutError())
        result = self.mux.handle_verified_webhook(self.message(FIFTH))
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.mux.handle_verified_webhook(self.message(FIFTH)), result)
        self.mux.routers[4].gateway.send.assert_called_once()
        for scope in self.scopes[:-1]:
            self.assertEqual(self.mux.handle_verified_webhook(self.message(scope))[0]['status'], 'demo_reset_presented')
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers[:4]], [1] * 4)
