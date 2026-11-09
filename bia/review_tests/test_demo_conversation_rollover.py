"""Synthetic conversation renewal: proof, isolated history and fail-closed IO."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, call, patch

from config import load_settings
from demo_router import (DemoConversationRouter, DemoScope, DemoWhatsAppGateway,
                         RecordingGateway, ProductionTransportFence, build_demo_router,
                         excluded_conversations, production_blocked)
from repository import Repository
from test_demo_router import NOW, SCOPE, TOKEN, settings
from test_demo_multi_scope import SECOND, THIRD_PHONE, source, multi_settings
import test_demo_multi_scope as multi_fixtures
from test_demo_pending_scope import Provider, pending_settings

NEW = replace(SCOPE, conversation_id='27')
LATER = replace(SCOPE, conversation_id='37')


def renewed_settings(directory):
    config = multi_settings(directory)
    config['demo_conversation_rollover_enabled'] = True
    return config


class ConversationRenewal(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.config = renewed_settings(directory.name)
        self.provider = Provider(NEW, self.message())
        self.mux = self.build()
        self.owner = self.mux.routers[0]

    def build(self, config=None):
        router = build_demo_router(config or self.config, conversation_gateway_factory=self.provider.factory)
        self.addCleanup(router.store.close)
        for child in router.routers: child.now = lambda: NOW
        return router

    def message(self, scope=NEW, **changes):
        return {**source(scope, text='Resetar', created_at=NOW.isoformat()), **changes}

    def bind(self, message=None):
        return self.mux.handle_verified_webhook(message or self.message())

    def bindings(self):
        return [tuple(row) for row in self.mux.store.db.execute('SELECT * FROM demo_conversation_bindings')]

    def assert_no_binding_or_send(self):
        self.assertEqual(self.bindings(), [])
        self.assertEqual(self.provider.posts, 0)
        self.assertIsNone(self.mux.store.current(NEW.slot))

    def test_reset_in_new_conversation_keeps_old_history_and_other_person(self):
        self.owner.original.start('old-conversation-start')
        self.owner.original.stop()
        self.mux.routers[1].start('other-contact-start')
        old = self.mux.store.current(SCOPE.slot)
        other = self.mux.store.current(SECOND.slot)
        history = [tuple(row) for row in self.mux.store.db.execute('SELECT * FROM demo_outbox WHERE slot=?', (SCOPE.slot,))]
        result = self.bind()
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.mux.store.current(NEW.slot)['step'], 'opening')
        self.assertEqual(self.mux.store.current(SCOPE.slot), old)
        self.assertEqual(self.mux.store.current(SECOND.slot), other)
        self.assertEqual([tuple(row) for row in self.mux.store.db.execute('SELECT * FROM demo_outbox WHERE slot=?', (SCOPE.slot,))], history)
        self.assertEqual(self.provider.posts, 1)
        self.assertEqual(len(self.bindings()), 1)

    def test_verified_new_first_message_can_open_without_reset(self):
        self.provider.messages[0]['content'] = 'Oi novamente'
        self.assertEqual(self.bind(self.message(text='Oi novamente'))[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.provider.posts, 1)

    def test_durable_proof_and_unknown_outbox_exist_before_post(self):
        def before_post():
            self.assertEqual(len(self.bindings()), 1)
            self.assertIn(NEW.conversation_key, excluded_conversations(self.config))
            self.assertEqual(self.mux.store.db.execute('SELECT status FROM demo_outbox WHERE slot=?', (NEW.slot,)).fetchone()[0], 'outcome_unknown')
        self.provider.before_post = before_post
        self.assertEqual(self.bind()[0]['status'], 'demo_reset_presented')

    def test_only_candidate_conversation_api_is_used(self):
        self.bind()
        self.assertTrue(all(url.startswith('https://chat.pending.invalid/api/v1/accounts/1/conversations/27')
                            for _, url in self.provider.calls))
        self.assertTrue(all(method == 'GET' for method, _ in self.provider.calls[:-1]))
        self.assertEqual(self.provider.calls[-1][0], 'POST')

    def test_catchup_and_controls_cannot_bind(self):
        self.assertEqual(self.mux.handle(self.message())[0]['status'], 'demo_identity_rejected')
        with self.assertRaises(ValueError): self.mux.select(asdict(NEW))
        self.assertEqual(self.provider.calls, [])
        self.assert_no_binding_or_send()

    def test_partial_identity_and_invalid_inbound_never_query_provider(self):
        changes = ({'contact_id': '99'}, {'sender_phone': THIRD_PHONE}, {'contact_id': None},
                   {'conversation_id': None}, {'conversation_id': '00'}, {'message_id': None},
                   {'message_id': True}, {'provider': 'foreign'}, {'private': True},
                   {'message_type': 'outgoing'}, {'sender_type': 'user'}, {'text': ''})
        for change in changes:
            with self.subTest(change=change):
                self.assertIn(self.bind(self.message(**change))[0]['status'],
                              ('demo_binding_unverified', 'demo_identity_rejected'))
                self.assertTrue(production_blocked(self.config, event=self.message(**change)))
        self.assertEqual(self.provider.calls, [])
        self.assert_no_binding_or_send()

    def test_foreign_account_and_inbox_are_outside_scope_without_io(self):
        for change in ({'account_id': '2'}, {'inbox_id': '4'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.bind(self.message(**change))
        self.assertEqual(self.provider.calls, [])
        self.assert_no_binding_or_send()

    def test_crossed_person_or_reserved_conversation_fails_before_lookup(self):
        for change in ({'contact_id': SECOND.contact_id}, {'sender_phone': SECOND.phone},
                       {'conversation_id': SECOND.conversation_id}):
            self.assertEqual(self.bind(self.message(**change))[0]['status'], 'demo_identity_rejected')
        self.assertEqual(self.provider.calls, [])
        self.assert_no_binding_or_send()

    def test_stale_missing_and_future_event_does_not_query(self):
        for stamp in (None, '', 'invalid', NOW.replace(tzinfo=None).isoformat(),
                      (NOW - timedelta(minutes=5, microseconds=1)).isoformat(),
                      (NOW + timedelta(seconds=31)).isoformat()):
            self.assertEqual(self.bind(self.message(created_at=stamp))[0]['status'], 'demo_binding_unverified')
        self.assertEqual(self.provider.calls, [])
        self.assert_no_binding_or_send()

    def test_unavailable_provider_fails_closed_and_does_not_touch_legacy_state(self):
        self.owner.original.start('preserve-original-state')
        old = self.mux.store.current(SCOPE.slot)
        self.provider.fail_get = True
        self.assertEqual(self.bind()[0]['status'], 'demo_binding_unverified')
        self.assertEqual(self.mux.store.current(SCOPE.slot), old)
        self.assert_no_binding_or_send()

    def test_wrong_provider_detail_identity_or_window_never_binds(self):
        base = deepcopy(self.provider.detail)
        variants = [{**base, key: value} for key, value in
                    (('id', '999'), ('account_id', '2'), ('inbox_id', '4'), ('can_reply', False))]
        variants += [{**base, 'meta': {'sender': {**base['meta']['sender'], key: value}}}
                     for key, value in (('id', '999'), ('phone_number', THIRD_PHONE))]
        for detail in variants:
            self.provider.detail = detail
            self.assertEqual(self.bind()[0]['status'], 'demo_binding_unverified')
        self.assert_no_binding_or_send()

    def test_provider_must_prove_exact_unique_inbound(self):
        original = deepcopy(self.provider.messages[0])
        variants = [[], [original, original]]
        variants += [[{**original, key: value}] for key, value in (
            ('id', '102'), ('conversation_id', '999'), ('content', 'Different'),
            ('message_type', 'outgoing'), ('private', True), ('created_at', NOW.timestamp() - 3),
            ('sender', {'id': '999', 'phone_number': NEW.phone}),
            ('sender', {'id': NEW.contact_id, 'phone_number': THIRD_PHONE}))]
        for messages in variants:
            self.provider.messages = messages
            self.assertEqual(self.bind()[0]['status'], 'demo_binding_unverified')
        self.assert_no_binding_or_send()

    def test_recording_gateway_cannot_establish_authority(self):
        self.owner.gateway_factory = lambda scope: RecordingGateway()
        self.assertEqual(self.bind()[0]['status'], 'demo_binding_unverified')
        self.assert_no_binding_or_send()

    def test_recipient_is_rechecked_after_proof_before_post(self):
        factory = self.owner.gateway_factory
        def changed_after_proof(scope):
            gateway = factory(scope)
            original = gateway.verify_inbound
            def verify(*args):
                result = original(*args)
                self.provider.detail['meta']['sender']['id'] = '999'
                return result
            gateway.verify_inbound = verify
            return gateway
        self.owner.gateway_factory = changed_after_proof
        self.assertEqual(self.bind()[0]['status'], 'demo_reset_unavailable')
        self.assertEqual(self.provider.posts, 0)
        self.assertEqual(len(self.bindings()), 1)
        self.assertIn(NEW.conversation_key, excluded_conversations(self.config))

    def test_duplicate_and_conflicting_replay_do_not_send(self):
        first = self.bind()
        calls = list(self.provider.calls)
        self.assertEqual(self.bind(), first)
        self.assertEqual(self.bind(self.message(text='altered'))[0]['status'], 'demo_conflicting_duplicate')
        self.assertEqual(self.provider.calls, calls)
        self.assertEqual(self.provider.posts, 1)

    def test_concurrent_first_webhooks_bind_and_send_once(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.bind())) for _ in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(results), 8)
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.provider.posts, 1)
        self.assertEqual(len(self.bindings()), 1)

    def test_durable_restart_loads_without_network_and_deduplicates(self):
        self.config['demo_state_path'] = str(Path(self.config['state_dir']) / 'durable.sqlite3')
        first = self.build()
        result = first.handle_verified_webhook(self.message())
        before = list(self.provider.calls)
        second = self.build()
        self.assertIn(NEW.conversation_key, excluded_conversations(self.config))
        self.assertEqual(second.handle_verified_webhook(self.message()), result)
        self.assertEqual(self.provider.calls, before)

    def test_overlapping_instances_recover_existing_binding(self):
        self.config['demo_state_path'] = str(Path(self.config['state_dir']) / 'durable.sqlite3')
        first, second = self.build(), self.build()
        result = first.handle_verified_webhook(self.message())
        self.assertEqual(second.handle_verified_webhook(self.message()), result)
        self.assertEqual(self.provider.posts, 1)
        self.assertFalse(second.routers[0].binding_failed)

    def test_old_instance_excludes_new_conversation_without_handling_any_inbound(self):
        self.config['demo_state_path'] = str(Path(self.config['state_dir']) / 'durable.sqlite3')
        first = self.build()
        other_config = deepcopy({key: value for key, value in self.config.items() if key != '_demo_scope'})
        second = self.build(other_config)
        delegate = Mock(); fence = ProductionTransportFence(delegate, second.scope)
        repo = Repository(Path(self.config['state_dir']) / 'production.sqlite3')
        repo.set_demo_scope(second.scope)
        first.handle_verified_webhook(self.message())
        self.assertNotIn(NEW.conversation_id, second.routers[0].routers)
        self.assertTrue(production_blocked(other_config, conversation_key=NEW.conversation_key))
        self.assertTrue(repo._demo_row_blocked({'conversation_key': NEW.conversation_key, 'event_json': '{}'}))
        with self.assertRaisesRegex(ValueError, 'excluded'):
            fence.http(method='POST', url='https://chat.pending.invalid/api/v1/accounts/1/conversations/27/messages')
        corrupted = self.message(contact_id='999', sender_phone=THIRD_PHONE)
        self.assertTrue(production_blocked(other_config, event=corrupted))
        self.assertEqual(fence.send_reply(corrupted)['status'], 'failed')
        self.assertEqual(delegate.mock_calls, [])

    def test_unknown_send_is_not_retried_or_bypassed_with_another_conversation(self):
        self.provider.unknown_post = True
        result = self.bind()
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.bind(), result)
        self.assertEqual(self.bind(self.message(LATER, message_id='301'))[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.provider.posts, 1)
        self.assertEqual(len(self.bindings()), 1)

    def test_original_unknown_send_blocks_new_binding(self):
        self.owner.original.gateway.send = Mock(side_effect=TimeoutError())
        self.owner.original.start('unknown-original-send')
        self.assertEqual(self.bind()[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.provider.calls, [])
        self.assert_no_binding_or_send()

    def test_persistence_failure_keeps_reservation_without_send_or_retry(self):
        self.mux.store.db.execute("CREATE TEMP TRIGGER reject_binding BEFORE INSERT ON demo_conversation_bindings BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        self.assertEqual(self.bind()[0]['status'], 'demo_binding_unavailable')
        self.assertTrue(production_blocked(self.config, conversation_key=NEW.conversation_key))
        self.assertEqual(self.bind()[0]['status'], 'demo_binding_unavailable')
        with self.assertRaises(ValueError): self.owner.select()
        self.assertEqual(self.provider.posts, 0)
        self.assertEqual(self.bindings(), [])

    def test_existing_repository_and_transport_reserve_new_identity_immediately(self):
        repo = Repository(Path(self.config['state_dir']) / 'production.sqlite3')
        repo.set_demo_scope(self.mux.scope)
        delegate = Mock(); fence = ProductionTransportFence(delegate, self.mux.scope)
        self.assertEqual(fence.send_reply(self.message())['status'], 'failed')
        self.bind()
        self.assertTrue(repo._demo_row_blocked({'conversation_key': NEW.conversation_key, 'event_json': '{}'}))
        for scope in (SCOPE, NEW):
            with self.assertRaisesRegex(ValueError, 'excluded'):
                fence.http(method='POST', url='https://chat.pending.invalid/api/v1/accounts/1/conversations/' + scope.conversation_id + '/messages')
        self.assertEqual(delegate.mock_calls, [])

    def test_new_scope_does_not_gain_authority_to_send_to_old_scope(self):
        self.bind()
        gateway = self.owner.routers[NEW.conversation_id].gateway
        with self.assertRaisesRegex(ValueError, 'scope_mismatch'):
            gateway._api(SCOPE, 'POST', '/messages', {})
        with self.assertRaisesRegex(ValueError, 'scope_mismatch'):
            gateway._api(SECOND, 'GET')
        self.assertEqual(self.provider.posts, 1)

    def test_control_selection_is_explicit_and_does_not_broadcast(self):
        self.bind()
        self.assertIs(self.owner.select(), self.owner.original)
        self.assertEqual(self.mux.select(asdict(NEW)).scope, NEW)
        before = self.mux.store.current(NEW.slot)
        self.mux.stop()
        self.assertEqual(self.mux.store.current(NEW.slot), before)
        self.assertIsNone(self.mux.store.current(SECOND.slot))

    def test_pending_old_reminders_cancel_but_rows_and_other_person_remain(self):
        for scope in (SCOPE, SECOND):
            self.mux.store.db.execute('INSERT INTO demo_followups VALUES(?,?,?,?,?,?)',
                ('reminder-' + scope.slot, scope.slot, 'source', NOW.isoformat(), 'pending', '{}'))
            self.mux.store.db.execute('INSERT INTO demo_closures VALUES(?,?,?,?,?,?,?,?)',
                ('closure-' + scope.slot, scope.slot, 'source', NOW.isoformat(), 'pending', '{}', '1', None))
        self.bind()
        for table in ('demo_followups', 'demo_closures'):
            self.assertEqual(self.mux.store.db.execute('SELECT status FROM ' + table + ' WHERE slot=?', (SCOPE.slot,)).fetchone()[0], 'cancelled')
            self.assertEqual(self.mux.store.db.execute('SELECT status FROM ' + table + ' WHERE slot=?', (SECOND.slot,)).fetchone()[0], 'pending')
            self.assertEqual(self.mux.store.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 2)

    def test_followup_dispatch_includes_new_router_without_merging_slots(self):
        import demo_followup
        self.bind()
        with patch.object(demo_followup, 'tick', return_value={'status': 'idle'}) as tick:
            self.assertEqual(len(demo_followup.tick_all(self.mux)), 3)
        self.assertEqual({item.args[0].scope.slot for item in tick.call_args_list}, {SCOPE.slot, NEW.slot, SECOND.slot})

    def test_disable_new_admission_preserves_durable_verified_exclusions(self):
        self.config['demo_state_path'] = str(Path(self.config['state_dir']) / 'durable.sqlite3')
        first = self.build()
        first.handle_verified_webhook(self.message())
        self.config['demo_conversation_rollover_enabled'] = False
        second = self.build()
        self.assertIn(NEW.conversation_key, excluded_conversations(self.config))
        before = list(self.provider.calls)
        self.assertEqual(second.handle_verified_webhook(self.message(LATER, message_id='301'))[0]['status'], 'demo_identity_rejected')
        self.assertEqual(self.provider.calls, before)

    def test_corrupt_persisted_binding_fails_startup_closed(self):
        self.config['demo_state_path'] = str(Path(self.config['state_dir']) / 'durable.sqlite3')
        first = self.build()
        first.handle_verified_webhook(self.message())
        first.store.db.execute("UPDATE demo_conversation_bindings SET first_event_digest='invalid'")
        with self.assertRaisesRegex(ValueError, 'binding_invalid'): self.build()

    def test_changed_configured_anchor_cannot_silently_drop_historical_exclusions(self):
        self.config['demo_state_path'] = str(Path(self.config['state_dir']) / 'durable.sqlite3')
        first = self.build()
        first.handle_verified_webhook(self.message())
        self.config['demo_scope'] = asdict(NEW)
        self.config['demo_scopes'][0] = asdict(NEW)
        with self.assertRaisesRegex(ValueError, 'binding_owner_changed'): self.build()

    def test_crash_after_proof_before_send_keeps_first_event_digest_authoritative(self):
        self.config['demo_state_path'] = str(Path(self.config['state_dir']) / 'durable.sqlite3')
        first = self.build()
        with patch('demo_router.DemoRouter.handle_verified_webhook', side_effect=RuntimeError('synthetic crash')):
            with self.assertRaises(RuntimeError): first.handle_verified_webhook(self.message())
        second = self.build()
        result = second.handle_verified_webhook(self.message(text='altered'))
        self.assertEqual(result[0]['status'], 'demo_conflicting_duplicate')
        self.assertEqual(self.provider.posts, 0)
        self.assertEqual(second.handle_verified_webhook(self.message())[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.provider.posts, 1)

    def test_unknown_reminder_or_closure_blocks_new_admission_and_old_known_target(self):
        self.bind()
        for table, statuses in (('demo_followups', ('outcome_unknown',)),
                                ('demo_closures', ('notice_unknown', 'resolve_unknown'))):
            for status in statuses:
                with self.subTest(table=table, status=status):
                    if table == 'demo_followups':
                        self.mux.store.db.execute('INSERT INTO demo_followups VALUES(?,?,?,?,?,?)',
                            ('unknown-reminder', NEW.slot, 'source', NOW.isoformat(), status, '{}'))
                    else:
                        self.mux.store.db.execute('INSERT INTO demo_closures VALUES(?,?,?,?,?,?,?,?)',
                            ('unknown-closure', NEW.slot, 'source', NOW.isoformat(), status, '{}', '1', None))
                    self.assertEqual(self.bind(self.message(LATER, message_id='301'))[0]['status'], 'demo_delivery_unconfirmed')
                    self.assertEqual(self.bind(self.message(SCOPE, message_id='302'))[0]['status'], 'demo_delivery_unconfirmed')
                    self.assertEqual(self.owner.original.start('blocked-cross-conversation')['status'], 'demo_delivery_unconfirmed')
                    self.mux.store.db.execute('DELETE FROM ' + table)
        self.assertEqual(self.provider.posts, 1)
        self.assertEqual(len(self.bindings()), 1)

    def test_overlapping_instances_load_new_uncertainty_before_binding_different_id(self):
        self.config['demo_state_path'] = str(Path(self.config['state_dir']) / 'durable.sqlite3')
        first, second = self.build(), self.build()
        self.provider.unknown_post = True
        first.handle_verified_webhook(self.message())
        result = second.handle_verified_webhook(self.message(LATER, message_id='301'))
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        self.assertIn(NEW.conversation_key, second.scope.conversation_keys)
        self.assertEqual(self.provider.posts, 1)

    def test_concurrent_instances_do_not_bypass_an_unknown_send(self):
        self.config['demo_state_path'] = str(Path(self.config['state_dir']) / 'durable.sqlite3')
        first, second = self.build(), self.build()
        self.provider.unknown_post = True
        other_provider = Provider(LATER, self.message(LATER, message_id='301'))
        other_provider.unknown_post = True
        second.routers[0].gateway_factory = other_provider.factory
        barrier = threading.Barrier(2)
        results = []
        def run(router, message):
            barrier.wait()
            results.append(router.handle_verified_webhook(message))
        threads = [threading.Thread(target=run, args=(first, self.message())),
                   threading.Thread(target=run, args=(second, self.message(LATER, message_id='301')))]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result[0]['status'] == 'demo_delivery_unconfirmed' for result in results))
        self.assertEqual(self.provider.posts + other_provider.posts, 1)

    def test_brazilian_mobile_alias_still_requires_same_exact_contact_and_conversation(self):
        candidate = replace(SECOND, conversation_id='47')
        provider = Provider(candidate, self.message(candidate))
        self.mux.routers[1].gateway_factory = provider.factory
        alias = candidate.phone[:5] + candidate.phone[6:]
        provider.detail['meta']['sender']['phone_number'] = alias
        provider.messages[0]['sender']['phone_number'] = alias
        result = self.bind(self.message(candidate, sender_phone=alias))
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(provider.posts, 1)

    def test_repeated_new_conversations_keep_independent_history(self):
        self.bind()
        previous = self.mux.store.current(NEW.slot)
        self.provider = Provider(LATER, self.message(LATER, message_id='301'))
        self.owner.gateway_factory = self.provider.factory
        self.assertEqual(self.bind(self.message(LATER, message_id='301'))[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.mux.store.current(NEW.slot), previous)
        self.assertEqual(self.mux.store.current(LATER.slot)['step'], 'opening')
        self.assertEqual(len(self.bindings()), 2)
        self.assertTrue({SCOPE.conversation_key, NEW.conversation_key, LATER.conversation_key} <= set(excluded_conversations(self.config)))


class RenewalConfiguration(unittest.TestCase):
    def test_env_is_opt_in_and_never_changes_production_gate_or_whitelist(self):
        values = {'CHATWOOT_ACCOUNT_ID': '1', 'CHATWOOT_INBOX_ID': '3',
                  'V5_PILOT_CONTACT_ID': SCOPE.contact_id, 'V5_PILOT_CONVERSATION_ID': SCOPE.conversation_id,
                  'V5_TEST_PHONE': SCOPE.phone, 'V5_DEMO_ROUTER_ENABLED': 'true'}
        baseline = load_settings(values)
        self.assertFalse(baseline['demo_conversation_rollover_enabled'])
        config = load_settings({**values, 'V5_DEMO_CONVERSATION_ROLLOVER_ENABLED': 'true'})
        self.assertTrue(config['demo_conversation_rollover_enabled'])
        self.assertEqual(config['gate'], baseline['gate'])
        self.assertEqual(config['demo_scope'], baseline['demo_scope'])

    def test_feature_requires_demo_router(self):
        config = settings('/tmp/synthetic-renewal', enabled=False)
        config['demo_conversation_rollover_enabled'] = True
        with self.assertRaisesRegex(ValueError, 'require_enabled'): build_demo_router(config)

    def test_flag_off_keeps_fixed_conversation_behavior(self):
        router = build_demo_router(settings('/tmp/synthetic-renewal'))
        self.addCleanup(router.store.close)
        self.assertNotIsInstance(router, DemoConversationRouter)
        self.assertEqual(router.handle_verified_webhook(source(NEW))[0]['status'], 'demo_identity_rejected')

    def test_disabled_live_delivery_cannot_prove_or_send(self):
        config = renewed_settings('/tmp/synthetic-renewal')
        config.update(chatwoot_base_url='https://chat.pending.invalid', chatwoot_api_token='synthetic',
                      demo_whatsapp_live=False)
        router = build_demo_router(config)
        self.addCleanup(router.store.close)
        router.routers[0].now = lambda: NOW
        self.assertEqual(router.handle_verified_webhook(source(NEW, text='Resetar', created_at=NOW.isoformat()))[0]['status'], 'demo_binding_unverified')
        self.assertTrue(production_blocked(config, event=source(NEW)))


class PendingConversationRenewal(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.config = pending_settings(directory.name)
        self.config['demo_conversation_rollover_enabled'] = True
        self.config['demo_state_path'] = str(Path(directory.name) / 'pending.sqlite3')
        self.new_scope = replace(SECOND, conversation_id='47')
        self.providers = {SECOND.conversation_id: Provider(SECOND),
                          self.new_scope.conversation_id: Provider(self.new_scope, self.message())}
        self.mux = self.build()

    def factory(self, scope):
        return self.providers[scope.conversation_id].factory(scope)

    def build(self):
        mux = build_demo_router(self.config, pending_gateway_factory=self.factory,
                                conversation_gateway_factory=self.factory)
        self.addCleanup(mux.store.close)
        for child in mux.routers: child.now = lambda: NOW
        return mux

    def message(self, **changes):
        return {**source(self.new_scope, text='Resetar', message_id='301', created_at=NOW.isoformat()), **changes}

    def bind_original(self):
        first = source(SECOND, text='Oi', created_at=NOW.isoformat())
        result = self.mux.handle_verified_webhook(first)
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        return first

    def test_pending_first_binding_still_proves_once_then_renews_same_contact(self):
        self.bind_original()
        old = self.mux.store.current(SECOND.slot)
        binding = tuple(self.mux.store.db.execute("SELECT * FROM demo_starts WHERE slot LIKE 'binding:%'").fetchone())
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.mux.store.current(SECOND.slot), old)
        self.assertEqual(tuple(self.mux.store.db.execute("SELECT * FROM demo_starts WHERE slot LIKE 'binding:%'").fetchone()), binding)
        self.assertTrue(production_blocked(self.config, conversation_key=self.new_scope.conversation_key))
        self.assertEqual(self.providers[SECOND.conversation_id].posts, 1)
        self.assertEqual(self.providers[self.new_scope.conversation_id].posts, 1)

    def test_existing_pending_binding_from_previous_version_reloads_and_can_renew(self):
        self.config['demo_conversation_rollover_enabled'] = False
        legacy = self.build()
        self.assertEqual(legacy.handle_verified_webhook(source(SECOND, text='Oi', created_at=NOW.isoformat()))[0]['status'], 'demo_reset_presented')
        self.config['demo_conversation_rollover_enabled'] = True
        renewed = self.build()
        self.assertEqual(renewed.handle_verified_webhook(self.message())[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.providers[SECOND.conversation_id].posts, 1)

    def test_pending_renewal_cannot_change_contact_or_cross_static_identity(self):
        self.bind_original()
        for changes in ({'contact_id': '99'}, {'contact_id': SCOPE.contact_id},
                        {'conversation_id': SCOPE.conversation_id}, {'sender_phone': SCOPE.phone}):
            result = self.mux.handle_verified_webhook(self.message(**changes))
            self.assertIn(result[0]['status'], ('demo_binding_unverified', 'demo_identity_rejected'))
        self.assertEqual(self.providers[self.new_scope.conversation_id].calls, [])

    def test_pending_renewal_survives_restart_and_disabled_admission(self):
        self.bind_original()
        first = self.mux.handle_verified_webhook(self.message())
        self.config['demo_conversation_rollover_enabled'] = False
        renewed = self.build()
        calls = list(self.providers[self.new_scope.conversation_id].calls)
        self.assertEqual(renewed.handle_verified_webhook(self.message()), first)
        self.assertEqual(self.providers[self.new_scope.conversation_id].calls, calls)
        self.assertTrue(production_blocked(self.config, conversation_key=self.new_scope.conversation_key))

    def test_pending_followup_dispatch_unwraps_both_binding_layers(self):
        import demo_followup
        self.bind_original()
        self.mux.handle_verified_webhook(self.message())
        with patch.object(demo_followup, 'tick', return_value={'status': 'idle'}) as tick:
            self.assertEqual(len(demo_followup.tick_all(self.mux)), 3)
        self.assertEqual({item.args[0].scope.slot for item in tick.call_args_list}, {SCOPE.slot, SECOND.slot, self.new_scope.slot})


class RenewalWebhook(unittest.TestCase):
    def make_app(self, *, enabled=True):
        from server import create_app
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        config = renewed_settings(directory.name)
        config['gate']['enabled'] = enabled
        repo = Repository(Path(directory.name) / 'production.sqlite3')
        transport = Mock(); transport.ready.return_value = True; transport.supports_reply_fencing = False
        app = create_app(config, repository=repo, transport=transport,
                         real_guard=Mock(return_value={'allowed': True}), real_client=Mock())
        app.testing = True
        mux = app.extensions['v5_demo_router']; self.addCleanup(mux.store.close)
        provider = Provider(NEW, source(NEW, text='Resetar', created_at=NOW.isoformat()))
        owner = mux.routers[0]; owner.gateway_factory = provider.factory; owner.now = lambda: NOW
        return app, repo, transport, mux, provider

    def raw(self):
        return multi_fixtures.MultiWebhookBoundaries.raw(self, scope=NEW)

    def test_authenticated_webhook_only_and_no_production_writes(self):
        app, repo, transport, mux, provider = self.make_app()
        client = app.test_client()
        self.assertEqual(client.post('/webhook/chatwoot', json=self.raw()).status_code, 401)
        self.assertEqual(provider.calls, [])
        response = client.post('/webhook/chatwoot?token=' + TOKEN, json=self.raw())
        self.assertEqual(response.json['status'], 'demo_reset_presented')
        self.assertEqual(provider.posts, 1)
        self.assertTrue(all(item == call.ready() for item in transport.mock_calls))
        with repo._connection() as db:
            for table in ('sessions', 'inbound_events', 'outbox', 'real_jobs', 'operations'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)

    def test_disabled_global_gate_never_binds_or_sends(self):
        app, _, _, _, provider = self.make_app(enabled=False)
        response = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=self.raw())
        self.assertIn(response.json['status'], ('ignored', 'not_ready'))
        self.assertEqual(provider.calls, [])
