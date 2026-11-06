"""Two explicitly verified demo contacts, with no production allowlist expansion."""
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
from demo_router import (DemoScope, DemoScopes, DemoRouter, DemoMultiplexer, DemoStore,
                         DemoWhatsAppGateway, RecordingGateway, ProductionTransportFence,
                         build_demo_router, configured_scopes, production_blocked,
                         excluded_conversations, verified_scopes)
from repository import Repository
from test_demo_router import NOW, SCOPE, PHONE, OTHER, TOKEN, event, settings
import test_demo_forms as form_fixtures

SECOND = DemoScope('1', '3', '18', '17', '+5521991234567')
THIRD_PHONE = '+5531981234567'


def multi_settings(directory):
    result = settings(directory)
    result['demo_scopes'] = [asdict(SCOPE), asdict(SECOND)]
    result['demo_continuation_enabled'] = True
    result['gate']['mode'] = 'lista'
    return result


def source(scope, **changes):
    return event(account_id=scope.account_id, inbox_id=scope.inbox_id,
                 contact_id=scope.contact_id, conversation_id=scope.conversation_id,
                 sender_phone=scope.phone, **changes)


class ScopeConfiguration(unittest.TestCase):
    def test_missing_optional_list_preserves_legacy_router_and_runtime_scope(self):
        config = settings('/tmp/synthetic-demo-config')
        router = build_demo_router(config)
        self.addCleanup(router.store.close)
        self.assertIsInstance(router, DemoRouter)
        self.assertIsInstance(config['_demo_scope'], DemoScope)
        self.assertEqual(verified_scopes(config), (SCOPE,))

    def test_explicit_list_is_bounded_and_requires_every_identity_field(self):
        valid = [asdict(SCOPE), asdict(SECOND)]
        invalid = [None, '', {}, [], valid * 2, [None], [asdict(SECOND)],
                   [{k: v for k, v in asdict(SCOPE).items() if k != 'phone'}],
                   [{**asdict(SCOPE), 'extra': 'x'}],
                   [asdict(SCOPE), {**asdict(SECOND), 'contact_id': 18}],
                   [asdict(SCOPE), {**asdict(SECOND), 'conversation_id': '0'}],
                   [asdict(SCOPE), {**asdict(SECOND), 'phone': '9835'}]]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                configured_scopes({**multi_settings('/tmp/demo'), 'demo_scopes': value})

    def test_primary_phone_notation_preserves_original_scope_slot_and_egress(self):
        primary = DemoScope('1', '3', '9', '7', '+5521999990000')
        config = multi_settings('/tmp/demo')
        config['demo_scope'] = asdict(primary)
        for phone in (primary.phone, primary.phone.lstrip('+'), primary.phone[:5] + primary.phone[6:]):
            config['demo_scopes'] = [{**asdict(primary), 'phone': phone}, asdict(SECOND)]
            result = configured_scopes(config)
            self.assertEqual(result[0], primary)
            self.assertEqual(result[0].slot, primary.slot)
            self.assertEqual(result[0].phone, primary.phone)
        for changes in ({'account_id': '2'}, {'inbox_id': '4'}, {'contact_id': '99'},
                        {'conversation_id': '99'}, {'phone': THIRD_PHONE}):
            config['demo_scopes'] = [{**asdict(primary), **changes}, asdict(SECOND)]
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                configured_scopes(config)

    def test_overlap_and_phone_aliases_are_rejected(self):
        primary = DemoScope('1', '3', '9', '7', '+5521999990000')
        aliases = [primary.phone, primary.phone[:5] + primary.phone[6:]]
        for changes in ({'contact_id': '9'}, {'conversation_id': '7'},
                        *({'phone': phone} for phone in aliases)):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'overlap'):
                DemoScopes((primary, DemoScope(**{**asdict(SECOND), **changes})))

    def test_same_account_inbox_and_production_gate_are_required(self):
        for changes in ({'account_id': '2'}, {'inbox_id': '2'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                DemoScopes((SCOPE, DemoScope(**{**asdict(SECOND), **changes})))
        config = multi_settings('/tmp/demo')
        config['gate'] = {**config['gate'], 'inbox_id': '2'}
        with self.assertRaisesRegex(ValueError, 'gate_mismatch'):
            configured_scopes(config)

    def test_env_json_does_not_expand_production_phone_gate(self):
        values = {'CHATWOOT_ACCOUNT_ID': '1', 'CHATWOOT_INBOX_ID': '3',
                  'V5_PILOT_CONTACT_ID': SCOPE.contact_id,
                  'V5_PILOT_CONVERSATION_ID': SCOPE.conversation_id,
                  'V5_TEST_PHONE': PHONE, 'V5_DEMO_ROUTER_ENABLED': 'true',
                  'V5_DEMO_SCOPES_JSON': json.dumps([asdict(SCOPE), asdict(SECOND)])}
        configured = load_settings(values)
        baseline = load_settings({k: v for k, v in values.items() if k != 'V5_DEMO_SCOPES_JSON'})
        self.assertEqual(configured['gate'], baseline['gate'])
        self.assertEqual(configured_scopes(configured), (SCOPE, SECOND))
        for raw in ('', 'null', '{}', '[]', '{', 'x' * 8193):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                load_settings({**values, 'V5_DEMO_SCOPES_JSON': raw})

    def test_shared_or_mismatched_gateway_is_never_used(self):
        config = multi_settings('/tmp/demo')
        shared = RecordingGateway()
        for gateway in (shared, {SCOPE.slot: shared, SECOND.slot: shared},
                        {SCOPE.slot: shared},
                        {SCOPE.slot: shared, SECOND.slot: DemoWhatsAppGateway(
                            'https://demo.example.invalid', 'synthetic-token', scope=SCOPE)}):
            with self.subTest(gateway=type(gateway).__name__), self.assertRaises(ValueError):
                build_demo_router(config, gateway=gateway)
        self.assertEqual(shared.sent, [])


class MultiplexerIsolation(unittest.TestCase):
    def setUp(self):
        self.config = multi_settings('/tmp/demo')
        self.router = build_demo_router(self.config)
        self.addCleanup(self.router.store.close)
        self.at = NOW
        for router in self.router.routers:
            router.now = lambda: self.at

    def state(self, scope):
        return self.router.store.current(scope.slot)

    def target(self, scope):
        return self.router.select(asdict(scope))

    def start_both(self):
        for scope in (SCOPE, SECOND):
            self.target(scope).start('same-synthetic-request')

    def test_independent_runs_outboxes_gateways_and_same_request_id(self):
        self.start_both()
        self.assertIsInstance(self.router, DemoMultiplexer)
        self.assertNotEqual(self.state(SCOPE)['run'], self.state(SECOND)['run'])
        self.assertNotEqual(self.state(SCOPE)['outbox_key'], self.state(SECOND)['outbox_key'])
        self.assertEqual([len(router.gateway.sent) for router in self.router.routers], [1, 1])
        self.start_both()
        self.assertEqual([len(router.gateway.sent) for router in self.router.routers], [1, 1])

    def test_legacy_controls_address_original_contact_without_broadcast(self):
        self.router.start('legacy-request-one')
        self.assertIsNotNone(self.state(SCOPE))
        self.assertIsNone(self.state(SECOND))
        for value in ({'phone': SECOND.phone}, {**asdict(SECOND), 'contact_id': '19'}, 'all', []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.router.select(value)

    def test_second_continuation_does_not_advance_first(self):
        self.start_both()
        before = self.state(SCOPE)
        message = source(SECOND, demo_reply_to=self.state(SECOND)['parent_id'])
        self.assertEqual(self.router.handle(message)[0]['step'], 'about')
        self.assertEqual(self.state(SCOPE), before)
        self.assertEqual(self.router.handle(message)[0]['step'], 'about')
        self.assertEqual([len(router.gateway.sent) for router in self.router.routers], [1, 2])

    def test_identical_event_ids_have_per_contact_dedup(self):
        self.start_both()
        for scope in (SCOPE, SECOND):
            message = source(scope, demo_reply_to=self.state(scope)['parent_id'])
            result = self.router.handle(message)
            self.assertEqual(result[0]['step'], 'about')
            self.assertEqual(self.router.handle(message), result)
        self.assertEqual(self.router.store.db.execute('SELECT count(*) FROM demo_events').fetchone()[0], 2)

    def test_crossed_identity_and_reply_context_never_advance_either(self):
        self.start_both()
        before = [self.state(scope) for scope in (SCOPE, SECOND)]
        for values in ({'sender_phone': SCOPE.phone}, {'contact_id': SCOPE.contact_id},
                       {'conversation_id': SCOPE.conversation_id}, {'sender_phone': THIRD_PHONE},
                       {'private': True}, {'provider': 'foreign'}):
            message = {**source(SECOND), **values}
            self.assertTrue(self.router.claims(message))
            self.assertTrue(production_blocked(self.config, event=message))
            self.assertEqual(self.router.handle(message)[0]['status'], 'demo_identity_rejected')
        self.assertEqual([self.state(scope) for scope in (SCOPE, SECOND)], before)
        crossed = source(SECOND, demo_reply_to=self.state(SCOPE)['parent_id'])
        self.assertEqual(self.router.handle(crossed)[0]['status'], 'demo_choice_not_current')
        self.assertEqual([len(router.gateway.sent) for router in self.router.routers], [1, 1])

    def test_reset_stop_and_simulation_do_not_mutate_other_contact(self):
        self.start_both()
        before = self.state(SCOPE)
        self.at += timedelta(seconds=5)
        reset = source(SECOND, text='Resetar', created_at=self.at.isoformat())
        first = self.router.handle(reset)
        self.assertEqual(first[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.router.handle(reset), first)
        self.assertEqual(self.state(SCOPE), before)
        self.target(SECOND).stop()
        self.assertEqual(self.state(SCOPE), before)
        self.assertTrue(production_blocked(self.config, event=source(SECOND)))
        self.assertEqual([len(router.gateway.sent) for router in self.router.routers], [1, 2])

    def test_uncertain_first_send_does_not_block_second_reset(self):
        self.target(SCOPE).gateway.send = Mock(side_effect=TimeoutError())
        self.router.start('synthetic-timeout')
        before = self.state(SCOPE)
        result = self.router.handle(source(SECOND, text='Resetar', created_at=self.at.isoformat()))
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.state(SCOPE), before)
        self.target(SCOPE).gateway.send.assert_called_once()

    def test_concurrent_two_contact_duplicates_send_once_each(self):
        results = []
        messages = [source(scope, text='Resetar', created_at=self.at.isoformat()) for scope in (SCOPE, SECOND)]
        threads = [threading.Thread(target=lambda message=message: results.append(self.router.handle(message)))
                   for message in messages for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(results), 8)
        self.assertTrue(all(result[0]['status'] == 'demo_reset_presented' for result in results))
        self.assertEqual([len(router.gateway.sent) for router in self.router.routers], [1, 1])

    def test_restart_preserves_both_dedup_and_pending_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            config = multi_settings(directory)
            config['demo_state_path'] = str(Path(directory) / 'demo.sqlite3')
            router = build_demo_router(config)
            sources = [source(scope, text='Resetar', created_at=NOW.isoformat()) for scope in (SCOPE, SECOND)]
            for child in router.routers: child.now = lambda: NOW
            results = [router.handle(message) for message in sources]
            router.store.close()
            again = build_demo_router(config)
            try:
                for child in again.routers: child.now = lambda: NOW + timedelta(days=1)
                self.assertEqual([again.handle(message) for message in sources], results)
                self.assertEqual([len(child.gateway.sent) for child in again.routers], [0, 0])
            finally:
                again.store.close()

    def test_cross_contact_receipt_and_corrupt_outbox_reference_fail_closed(self):
        self.start_both()
        first_key = self.state(SCOPE)['outbox_key']
        before = [tuple(row) for row in self.router.store.db.execute('SELECT * FROM demo_outbox ORDER BY key')]
        target = self.target(SECOND)
        with self.assertRaisesRegex(ValueError, 'scope_mismatch'):
            target._accept(first_key, {'status': 'accepted', 'message_id': '999'})
        self.assertEqual([tuple(row) for row in self.router.store.db.execute('SELECT * FROM demo_outbox ORDER BY key')], before)
        self.router.store.db.execute('UPDATE demo_runs SET outbox_key=? WHERE slot=?', (first_key, SECOND.slot))
        target.gateway.lookup = Mock()
        with self.assertRaisesRegex(ValueError, 'scope_mismatch'):
            target.reconcile()
        target.gateway.lookup.assert_not_called()

    def test_live_context_payload_lookup_is_slot_bound(self):
        gateways = {scope.slot: DemoWhatsAppGateway('https://demo.example.invalid', 'synthetic', scope=scope)
                    for scope in (SCOPE, SECOND)}
        router = build_demo_router(multi_settings('/tmp/demo'), gateway=gateways)
        self.addCleanup(router.store.close)
        key = 'synthetic-first-only'
        router.store.db.execute('INSERT INTO demo_outbox VALUES(?,?,?,?,?,?)',
                               (key, SCOPE.slot, 'synthetic-run', '{"content":"first only"}', 'accepted', '{}'))
        self.assertEqual(gateways[SCOPE.slot].context_payload(key), {'content': 'first only'})
        with self.assertRaisesRegex(ValueError, 'not_persisted'):
            gateways[SECOND.slot].context_payload(key)


class MultiProductionBoundaries(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.config = multi_settings(directory.name)
        self.router = build_demo_router(self.config)
        self.addCleanup(self.router.store.close)
        self.repo = Repository(Path(directory.name) / 'production.sqlite3')
        self.repo.set_demo_scope(self.router.scope)

    def test_reserved_conversations_and_partial_matches_for_both_are_blocked(self):
        self.assertEqual(excluded_conversations(self.config), (SCOPE.conversation_key, SECOND.conversation_key))
        self.assertEqual(self.repo.excluded_conversations, excluded_conversations(self.config))
        for scope in (SCOPE, SECOND):
            for changes in ({}, {'conversation_id': '900'}, {'contact_id': '901'}, {'sender_phone': THIRD_PHONE}):
                message = {**source(scope), **changes}
                self.assertTrue(production_blocked(self.config, event=message))
        self.assertFalse(production_blocked(self.config, event=event(
            contact_id='900', conversation_id='900', sender_phone=THIRD_PHONE)))

    def test_transport_fence_blocks_both_exact_and_partial_identities(self):
        delegate = Mock()
        fence = ProductionTransportFence(delegate, self.router.scope)
        for scope in (SCOPE, SECOND):
            for message in (source(scope), {**source(scope), 'conversation_id': '900'}):
                self.assertEqual(fence.send_reply(message)['status'], 'failed')
                self.assertEqual(fence.write_progress(message)['status'], 'failed')
                self.assertIsNone(fence.read_progress(message))
            with self.assertRaisesRegex(ValueError, 'excluded'):
                fence.http(method='POST', url='https://demo.example.invalid/api/v1/accounts/1/conversations/' + scope.conversation_id + '/messages')
        self.assertEqual(delegate.mock_calls, [])
        fence.send_reply(event(contact_id='900', conversation_id='900', sender_phone=THIRD_PHONE))
        delegate.send_reply.assert_called_once()

    def seed_job(self, key, scope, conversation, status='queued'):
        message = {**source(scope), 'conversation_id': conversation}
        conversation_key = 'chatwoot:1:' + conversation
        with self.repo._connection() as db:
            db.execute('INSERT INTO inbound_events VALUES(?,?,?,?,?,?)',
                       (key + ':source', conversation_key, 'synthetic', 'completed', NOW.isoformat(), NOW.isoformat()))
            db.execute('INSERT INTO real_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (key, conversation_key, key + ':source', 'synthetic-effect', 'synthetic-cycle',
                        '@synthetic', 'precheck', json.dumps(message), '{}', status, 0,
                        NOW.isoformat(), None, None, NOW.isoformat()))
        return conversation_key

    def test_existing_jobs_recovery_and_followup_scans_hold_both_contacts(self):
        keys = []
        for index, scope in enumerate((SCOPE, SECOND)):
            for offset, status in enumerate(('queued', 'running', 'result_ready')):
                key = 'reserved-' + str(index) + '-' + str(offset)
                keys.append(key)
                self.seed_job(key, scope, str(900 + 10 * index + offset), status)
        third = DemoScope('1', '3', '88', '87', THIRD_PHONE)
        other = self.seed_job('other-job', third, '87')
        before = [self.repo.real_job(key) for key in keys]
        self.repo.recover_real_jobs(NOW.isoformat())
        self.assertEqual([self.repo.real_job(key) for key in keys], before)
        self.assertEqual(self.repo.precheck_conversations(), [other])
        self.assertEqual(self.repo.claim_real_job(NOW.isoformat())['job_key'], 'other-job')
        self.assertIsNone(self.repo.claim_real_job(NOW.isoformat()))
        with self.repo._connection() as db:
            for scope in (SCOPE, SECOND, third):
                db.execute('INSERT INTO sessions VALUES(?,?,?)', (scope.conversation_key, '{}', NOW.isoformat()))
                db.execute('INSERT INTO followup_sources VALUES(?,?,?,?)',
                           (scope.conversation_key, 'synthetic-cycle', 'synthetic-event', json.dumps(source(scope))))
        self.assertEqual(self.repo.followup_conversations(), [third.conversation_key])

    def test_old_workers_reject_second_contact_before_io(self):
        from real_operations import RealExecutor
        from followup import Followup
        from retomada import Retomada, PosPausa
        executor = RealExecutor.__new__(RealExecutor)
        executor.settings = self.config
        executor.repository, executor.lock_for = Mock(), Mock()
        job = {'conversation_key': SECOND.conversation_key, 'event': source(SECOND)}
        self.assertFalse(executor._authorized(job))
        self.assertEqual(executor._apply(job)['status'], 'blocked')
        self.assertEqual(executor.repository.mock_calls, [])
        worker = Followup.__new__(Followup); worker.settings = self.config
        worker.conversation = SECOND.conversation_key; worker.repository = Mock()
        self.assertEqual(worker._tick()['status'], 'blocked')
        self.assertEqual(worker._tick_inactivity()['status'], 'blocked')
        self.assertEqual(worker.repository.mock_calls, [])
        worker = Retomada.__new__(Retomada); worker.settings = self.config
        worker.repository, worker.registration, worker.lock_for = Mock(), Mock(), Mock()
        self.assertEqual(worker._conversation(SECOND.conversation_key, NOW)['status'], 'blocked')
        self.assertEqual(worker.repository.mock_calls, [])
        worker = PosPausa.__new__(PosPausa); worker.settings = self.config; worker._get = Mock()
        self.assertEqual(worker._candidate({'id': SECOND.conversation_id}, NOW, 'https://example.invalid')[1],
                         'demo_contact_excluded_from_production')
        worker._get.assert_not_called()


class MultiWebhookBoundaries(unittest.TestCase):
    def make_app(self, *, gate_enabled=True):
        from server import create_app
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = multi_settings(directory.name)
        config['gate']['enabled'] = gate_enabled
        repo = Repository(Path(directory.name) / 'production.sqlite3')
        transport = Mock(); transport.ready.return_value = True; transport.supports_reply_fencing = False
        app = create_app(config, repository=repo, transport=transport,
                         real_guard=Mock(return_value={'allowed': True}), real_client=Mock())
        app.testing = True
        mux = app.extensions['v5_demo_router']; self.addCleanup(mux.store.close)
        for router in mux.routers: router.now = lambda: NOW
        return app, repo, transport, mux

    def raw(self, scope=SECOND, text='Resetar', **changes):
        sender = {'id': scope.contact_id, 'phone_number': scope.phone, 'type': 'contact'}
        value = {'event': 'message_created', 'id': '101', 'message_type': 'incoming', 'private': False,
                 'content': text, 'created_at': NOW.isoformat(), 'account': {'id': '1'},
                 'inbox': {'id': '3'}, 'sender': sender,
                 'conversation': {'id': scope.conversation_id, 'account_id': '1', 'inbox_id': '3',
                                  'meta': {'sender': sender}}}
        value.update(changes)
        return value

    def test_both_reach_demo_without_adding_second_to_production_gate(self):
        app, repo, transport, mux = self.make_app()
        for scope in (SCOPE, SECOND):
            response = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=self.raw(scope))
            self.assertEqual(response.json['status'], 'demo_reset_presented')
        self.assertEqual([len(router.gateway.sent) for router in mux.routers], [1, 1])
        self.assertTrue(all(item == call.ready() for item in transport.mock_calls))
        with repo._connection() as db:
            for table in ('sessions', 'inbound_events', 'outbox', 'operations', 'real_jobs'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_explicit_control_targets_second_and_invalid_selector_sends_nothing(self):
        app, _, _, mux = self.make_app()
        client = app.test_client()
        result = client.post('/demo/start?token=' + TOKEN,
                             json={'request_id': 'synthetic-control', 'scope': asdict(SECOND)})
        self.assertEqual(result.status_code, 200)
        self.assertEqual([len(router.gateway.sent) for router in mux.routers], [0, 1])
        for value in ({'phone': SECOND.phone}, {**asdict(SECOND), 'inbox_id': '4'}):
            result = client.post('/demo/start?token=' + TOKEN,
                                 json={'request_id': 'synthetic-control-two', 'scope': value})
            self.assertEqual(result.status_code, 409)
        self.assertEqual([len(router.gateway.sent) for router in mux.routers], [0, 1])

    def test_global_off_and_unlisted_recipient_remain_ignored(self):
        for enabled in (False, True):
            app, _, transport, mux = self.make_app(gate_enabled=enabled)
            target = SECOND if not enabled else DemoScope('1', '3', '88', '87', THIRD_PHONE)
            response = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=self.raw(target))
            self.assertEqual(response.json['status'], 'ignored' if enabled else 'not_ready')
            self.assertEqual([len(router.gateway.sent) for router in mux.routers], [0, 0])
            self.assertTrue(all(item == call.ready() for item in transport.mock_calls))

    def test_partial_second_identity_is_reserved_before_production(self):
        app, repo, transport, mux = self.make_app()
        raw = self.raw()
        raw['conversation']['id'] = '999'
        result = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=raw)
        self.assertEqual(result.json['status'], 'demo_identity_rejected')
        self.assertTrue(all(item == call.ready() for item in transport.mock_calls))
        self.assertEqual([len(router.gateway.sent) for router in mux.routers], [0, 0])
        with repo._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM inbound_events').fetchone()[0], 0)

    def test_second_storage_failure_never_falls_through_to_production(self):
        app, _, transport, mux = self.make_app()
        mux.select(asdict(SECOND)).handle_verified_webhook = Mock(side_effect=RuntimeError('synthetic storage failure'))
        response = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=self.raw())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['status'], 'demo_unavailable')
        self.assertTrue(all(item == call.ready() for item in transport.mock_calls))


class MultiFormBoundaries(unittest.TestCase):
    def test_legacy_forms_for_both_contacts_are_blocked_before_mutation(self):
        original = form_fixtures.settings
        second = DemoScope('1', '3', '8', '8', form_fixtures.OTHER)
        def configured(directory, **kwargs):
            config = original(directory, **kwargs)
            config['demo_scopes'] = [asdict(form_fixtures.SCOPE), asdict(second)]
            return config
        with patch.object(form_fixtures, 'settings', side_effect=configured):
            app, repo, _, rows, gateway, sender, _, _ = form_fixtures.DemoFormBoundary.make_app(self)
        before = form_fixtures.DemoFormBoundary.snapshot(self, repo)
        checked = 0
        for label in ('owner', 'other', 'owner_other_chat', 'owner_alias'):
            token = rows[label]['token']
            for route in app.url_map.iter_rules():
                if not route.endpoint.startswith(('v5_forms.', 'v5_original_form_compat.')):
                    continue
                path = route.rule.replace('<token>', token).replace('<path_token>', token)
                for method in route.methods - {'HEAD', 'OPTIONS'}:
                    with self.subTest(label=label, path=path, method=method):
                        response = app.test_client().open(path, method=method, json={},
                                                         headers={'Authorization': 'Bearer ' + token})
                        self.assertEqual(response.status_code, 409)
                        self.assertEqual(response.json['code'], 'demo_contact_excluded_from_production')
                        checked += 1
        self.assertGreater(checked, 40)
        self.assertEqual(form_fixtures.DemoFormBoundary.snapshot(self, repo), before)
        self.assertEqual(gateway.mock_calls, [])
        self.assertEqual(sender.mock_calls, [])
