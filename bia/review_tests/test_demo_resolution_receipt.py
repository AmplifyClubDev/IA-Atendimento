"""Actual Chatwoot status receipt and GET-only recovery of historical closures."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from demo_router import DemoWhatsAppGateway, DemoStore, DemoRouter, build_demo_router
from demo_followup import CLOSE_PAYLOAD, LEGACY_CLOSE_PAYLOAD, reconcile_resolutions, tick
from test_demo_router import SCOPE, NOW
from test_demo_pending_scope import Provider
from test_demo_multi_scope import source, multi_settings, SECOND, THIRD_PHONE
import test_demo_inactivity_close as close_fixtures


class StatusReceipt(unittest.TestCase):
    def setUp(self):
        self.gateway = DemoWhatsAppGateway('https://receipt.invalid', 'synthetic', scope=SCOPE, live_enabled=True)
        self.gateway.preflight = Mock(return_value={'after_message_id': '501'})
        self.gateway.followup_current = Mock(return_value=True)
        self.gateway.inactivity_human_guard = Mock()

    def resolve(self, receipt):
        self.gateway._api = Mock(return_value=receipt)
        return self.gateway.resolve_inactivity(SCOPE, 'bia-demo-close:synthetic')

    def test_official_nested_receipt_confirms_exact_conversation(self):
        result = self.resolve({'meta': {}, 'payload': {'success': True, 'conversation_id': int(SCOPE.conversation_id),
                               'current_status': 'resolved', 'snoozed_until': None}})
        self.assertEqual(result, {'status': 'resolved'})
        self.gateway._api.assert_called_once_with(SCOPE, 'POST', '/toggle_status', {'status': 'resolved'})

    def test_wrong_or_malformed_receipts_never_confirm(self):
        good = {'success': True, 'conversation_id': SCOPE.conversation_id, 'current_status': 'resolved'}
        values = [None, [], {}, {'payload': None}, {'payload': []}]
        values += [{'payload': {**good, key: value}} for key, value in (
            ('success', False), ('success', 1), ('success', 'true'), ('conversation_id', '999'),
            ('conversation_id', None), ('current_status', 'open'), ('current_status', None))]
        values += [{'status': 'resolved', 'payload': {**good, 'current_status': 'open'}}]
        for value in values:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'resolution_unconfirmed'):
                self.resolve(value)

    def test_flat_adapter_remains_supported_but_wrong_conversation_is_rejected(self):
        self.assertEqual(self.resolve({'status': 'resolved'}), {'status': 'resolved'})
        self.assertEqual(self.resolve({'status': 'resolved', 'conversation_id': SCOPE.conversation_id}), {'status': 'resolved'})
        with self.assertRaises(ValueError): self.resolve({'status': 'resolved', 'conversation_id': '999'})

    def test_old_code_mistook_the_real_receipt_for_failure(self):
        receipt = {'meta': {}, 'payload': {'success': True, 'conversation_id': SCOPE.conversation_id,
                                         'current_status': 'resolved', 'snoozed_until': None}}
        self.assertNotEqual(receipt.get('status'), 'resolved')
        self.assertEqual(self.resolve(receipt), {'status': 'resolved'})


class HistoricalReadback(unittest.TestCase):
    def setUp(self):
        self.store = DemoStore(':memory:'); self.addCleanup(self.store.close)
        self.provider = Provider(SCOPE)
        self.provider.detail.update(status='resolved', can_reply=False)
        self.provider.messages = [{'id': '501', 'conversation_id': SCOPE.conversation_id,
                                   'message_type': 'outgoing', 'private': False,
                                   'content': CLOSE_PAYLOAD['content'], 'content_type': 'text'}]
        self.gateway = self.provider.factory(SCOPE)
        self.router = DemoRouter(SCOPE, self.store, self.gateway, now=lambda: NOW)
        self.store.db.execute('INSERT INTO demo_outbox VALUES(?,?,?,?,?,?)',
            ('source', SCOPE.slot, 'run', '{}', 'accepted', '{}'))
        self.store.db.execute('INSERT INTO demo_closures VALUES(?,?,?,?,?,?,?,?)',
            ('bia-demo-close:historic', SCOPE.slot, 'source', (NOW - timedelta(days=2)).isoformat(),
             'resolve_unknown', json.dumps(CLOSE_PAYLOAD), '500', '501'))

    def status(self):
        return self.store.db.execute('SELECT status FROM demo_closures').fetchone()[0]

    def test_expired_reply_window_does_not_prevent_get_only_proof(self):
        before = [tuple(row) for row in self.store.db.execute('SELECT * FROM demo_outbox')]
        self.assertEqual(reconcile_resolutions(self.router), 1)
        self.assertEqual(self.status(), 'resolved')
        self.assertEqual([method for method, _ in self.provider.calls], ['GET', 'GET', 'GET'])
        self.assertEqual([tuple(row) for row in self.store.db.execute('SELECT * FROM demo_outbox')], before)
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(len(self.provider.calls), 3)

    def test_exact_approved_legacy_copy_is_verified_without_rewriting_or_resending_it(self):
        self.store.db.execute('UPDATE demo_closures SET payload=?', (json.dumps(LEGACY_CLOSE_PAYLOAD),))
        self.provider.messages[0]['content'] = LEGACY_CLOSE_PAYLOAD['content']
        self.assertEqual(reconcile_resolutions(self.router), 1)
        self.assertEqual(self.status(), 'resolved')
        self.assertEqual(json.loads(self.store.db.execute('SELECT payload FROM demo_closures').fetchone()[0]), LEGACY_CLOSE_PAYLOAD)
        self.assertEqual(self.provider.posts, 0)

    def test_legacy_receipt_cannot_be_proved_with_current_copy_or_changed_legacy_copy(self):
        self.store.db.execute('UPDATE demo_closures SET payload=?', (json.dumps(LEGACY_CLOSE_PAYLOAD),))
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.status(), 'resolve_unknown')
        self.provider.calls.clear()
        for change in ({'content': LEGACY_CLOSE_PAYLOAD['content'] + ' Changed'}, {'private': 0},
                       {'private': True}, {'content_type': 'input_select'}, {'extra': 'field'}):
            modified = {**LEGACY_CLOSE_PAYLOAD, **change}
            self.store.db.execute('UPDATE demo_closures SET payload=?', (json.dumps(modified),))
            self.provider.messages[0]['content'] = modified['content']
            self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.provider.calls, [])

    def test_still_open_conversation_is_not_reclosed_or_cleared(self):
        self.provider.detail['status'] = 'open'
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.status(), 'resolve_unknown')
        self.assertEqual([method for method, _ in self.provider.calls], ['GET'])

    def test_changed_recipient_is_never_cleared(self):
        original = deepcopy(self.provider.detail)
        variants = [{**original, key: value} for key, value in
                    (('id', '999'), ('account_id', '2'), ('inbox_id', '4'))]
        variants += [{**original, 'meta': {'sender': {**original['meta']['sender'], key: value}}}
                     for key, value in (('id', '999'), ('phone_number', THIRD_PHONE))]
        for detail in variants:
            self.provider.detail = detail
            self.assertEqual(reconcile_resolutions(self.router), 0)
            self.assertEqual(self.status(), 'resolve_unknown')
        self.assertEqual(self.provider.posts, 0)

    def test_exact_closing_message_must_exist_once_and_match(self):
        original = deepcopy(self.provider.messages[0])
        variants = [[], [original, original]]
        variants += [[{**original, key: value}] for key, value in (
            ('id', '999'), ('conversation_id', '999'), ('private', True), ('message_type', 'incoming'),
            ('content', 'different'), ('content_type', 'input_select'), ('account_id', '2'), ('inbox_id', '4'))]
        for messages in variants:
            self.provider.messages = messages
            self.assertEqual(reconcile_resolutions(self.router), 0)
            self.assertEqual(self.status(), 'resolve_unknown')
        self.assertEqual(self.provider.posts, 0)

    def test_reopened_between_reads_preserves_uncertainty(self):
        original = self.provider.open
        def reopen(request, timeout):
            result = original(request, timeout)
            if request.full_url.endswith('/messages'):
                self.provider.detail['status'] = 'open'
            return result
        self.provider.open = reopen
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.status(), 'resolve_unknown')
        self.assertEqual(self.provider.posts, 0)

    def test_read_failure_keeps_pending_without_any_write_request(self):
        self.provider.fail_get = True
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.status(), 'resolve_unknown')
        self.assertEqual(self.provider.posts, 0)

    def test_local_update_failure_does_not_clear_or_retry_provider_effect(self):
        self.store.db.execute("CREATE TEMP TRIGGER reject_reconcile BEFORE UPDATE ON demo_closures BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.status(), 'resolve_unknown')
        self.assertEqual(self.provider.posts, 0)

    def test_missing_source_or_receipt_never_even_queries_provider(self):
        self.store.db.execute("UPDATE demo_outbox SET status='outcome_unknown'")
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.store.db.execute("UPDATE demo_outbox SET status='accepted'")
        self.store.db.execute('UPDATE demo_closures SET closure_message_id=NULL')
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.provider.calls, [])

    def test_arbitrary_persisted_text_is_not_authorized_even_if_remote_text_matches(self):
        unapproved = {**CLOSE_PAYLOAD, 'content': 'A different historical message'}
        self.store.db.execute('UPDATE demo_closures SET payload=?', (json.dumps(unapproved),))
        self.provider.messages[0]['content'] = unapproved['content']
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.provider.calls, [])
        with self.assertRaisesRegex(ValueError, 'proof_invalid'):
            self.gateway.verify_resolution(SCOPE, '501', unapproved)

    def test_uncertain_notice_is_never_promoted_to_resolved(self):
        self.store.db.execute("UPDATE demo_closures SET status='notice_unknown'")
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.status(), 'notice_unknown')
        self.assertEqual(self.provider.calls, [])

    def test_unknown_outbox_and_warning_are_never_cleared(self):
        self.store.db.execute('INSERT INTO demo_outbox VALUES(?,?,?,?,?,?)',
            ('unknown-send', SCOPE.slot, 'old-run', '{}', 'outcome_unknown', '{}'))
        self.store.db.execute('INSERT INTO demo_followups VALUES(?,?,?,?,?,?)',
            ('unknown-warning', SCOPE.slot, 'source', NOW.isoformat(), 'outcome_unknown', '{}'))
        self.assertEqual(reconcile_resolutions(self.router), 1)
        self.assertEqual(self.store.db.execute("SELECT status FROM demo_outbox WHERE key='unknown-send'").fetchone()[0], 'outcome_unknown')
        self.assertEqual(self.store.db.execute("SELECT status FROM demo_followups WHERE key='unknown-warning'").fetchone()[0], 'outcome_unknown')

    def test_cross_slot_proof_and_offline_gateway_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'scope_mismatch'):
            self.gateway.verify_resolution(SECOND, '501', CLOSE_PAYLOAD)
        self.router.gateway = Mock()
        self.assertEqual(reconcile_resolutions(self.router), 0)
        self.assertEqual(self.provider.calls, [])

    def test_only_one_historical_resolution_checked_per_call(self):
        self.store.db.execute('INSERT INTO demo_closures VALUES(?,?,?,?,?,?,?,?)',
            ('bia-demo-close:second', SCOPE.slot, 'source', NOW.isoformat(), 'resolve_unknown',
             json.dumps(CLOSE_PAYLOAD), '500', '501'))
        self.assertEqual(reconcile_resolutions(self.router), 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM demo_closures WHERE status='resolve_unknown'").fetchone()[0], 1)
        self.assertEqual(len(self.provider.calls), 3)


class RolloverAfterReadback(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.config = multi_settings(directory.name)
        self.config['demo_conversation_rollover_enabled'] = True
        self.new_scope = replace(SCOPE, conversation_id='27')
        self.new_message = source(self.new_scope, text='Resetar', message_id='601', created_at=NOW.isoformat())
        self.old_provider = Provider(SCOPE)
        self.new_provider = Provider(self.new_scope, self.new_message)
        gateways = {SCOPE.slot: self.old_provider.factory(SCOPE), SECOND.slot: Provider(SECOND).factory(SECOND)}
        self.mux = build_demo_router(self.config, gateway=gateways, conversation_gateway_factory=self.new_provider.factory)
        self.addCleanup(self.mux.store.close)
        for child in self.mux.routers: child.now = lambda: NOW
        self.owner = self.mux.routers[0]
        self.owner.original.start('original-opening')
        self.old_state = self.mux.store.current(SCOPE.slot)
        self.old_provider.detail.update(status='resolved', can_reply=False)
        self.old_provider.messages.append({'id': '501', 'conversation_id': SCOPE.conversation_id,
            'message_type': 'outgoing', 'private': False, 'content': CLOSE_PAYLOAD['content'], 'content_type': 'text'})
        self.mux.store.db.execute('INSERT INTO demo_closures VALUES(?,?,?,?,?,?,?,?)',
            ('bia-demo-close:legacy', SCOPE.slot, self.old_state['outbox_key'], NOW.isoformat(),
             'resolve_unknown', json.dumps(CLOSE_PAYLOAD), '500', '501'))
        self.old_provider.calls.clear()

    def test_readback_releases_only_completed_close_then_fresh_reset_opens_once(self):
        result = self.mux.handle_verified_webhook(self.new_message)
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.new_provider.posts, 1)
        self.assertEqual(self.old_provider.posts, 0)
        self.assertEqual([method for method, _ in self.old_provider.calls], ['GET', 'GET', 'GET'])
        self.assertEqual(self.mux.store.current(SCOPE.slot), self.old_state)
        self.assertEqual(self.mux.store.db.execute('SELECT status FROM demo_closures').fetchone()[0], 'resolved')
        self.assertEqual(self.mux.handle_verified_webhook(self.new_message), result)
        self.assertEqual(self.new_provider.posts, 1)

    def test_historical_pre_copy_change_closure_unblocks_the_real_failure_pattern(self):
        self.mux.store.db.execute('UPDATE demo_closures SET payload=?', (json.dumps(LEGACY_CLOSE_PAYLOAD),))
        self.old_provider.messages[-1]['content'] = LEGACY_CLOSE_PAYLOAD['content']
        result = self.mux.handle_verified_webhook(self.new_message)
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.new_provider.posts, 1)
        self.assertEqual(self.old_provider.posts, 0)
        self.assertEqual([method for method, _ in self.old_provider.calls], ['GET', 'GET', 'GET'])
        self.assertEqual(self.mux.store.current(SCOPE.slot), self.old_state)
        self.assertEqual(self.mux.store.db.execute('SELECT status FROM demo_closures').fetchone()[0], 'resolved')
        self.assertEqual(self.mux.handle_verified_webhook(self.new_message), result)
        self.assertEqual(self.new_provider.posts, 1)

    def test_failure_to_prove_old_close_keeps_new_conversation_blocked(self):
        self.old_provider.detail['status'] = 'open'
        result = self.mux.handle_verified_webhook(self.new_message)
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.new_provider.calls, [])
        self.assertEqual(self.old_provider.posts, 0)

    def test_other_unknown_message_remains_a_blocker_after_close_proof(self):
        self.mux.store.db.execute('INSERT INTO demo_outbox VALUES(?,?,?,?,?,?)',
            ('other-unknown', SCOPE.slot, 'other-run', '{}', 'outcome_unknown', '{}'))
        result = self.mux.handle_verified_webhook(self.new_message)
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.new_provider.calls, [])
        self.assertEqual(self.old_provider.posts, 0)

    def test_wrong_or_stale_new_identity_does_not_trigger_reconciliation(self):
        for change in ({'contact_id': '999'}, {'sender_phone': THIRD_PHONE},
                       {'created_at': (NOW - timedelta(minutes=6)).isoformat()}):
            result = self.mux.handle_verified_webhook({**self.new_message, **change})
            self.assertEqual(result[0]['status'], 'demo_binding_unverified')
        self.assertEqual(self.old_provider.calls, [])
        self.assertEqual(self.new_provider.calls, [])

    def test_catchup_read_path_does_not_reconcile_or_admit(self):
        self.assertEqual(self.mux.handle(self.new_message)[0]['status'], 'demo_identity_rejected')
        self.assertEqual(self.old_provider.calls, [])
        self.assertEqual(self.new_provider.calls, [])

    def test_known_conversation_can_reconcile_only_on_fresh_authenticated_webhook(self):
        first = self.mux.handle_verified_webhook(self.new_message)
        self.assertEqual(first[0]['status'], 'demo_reset_presented')
        self.mux.store.db.execute("UPDATE demo_closures SET status='resolve_unknown'")
        self.old_provider.calls.clear()
        stale = {**self.new_message, 'message_id': '701', 'created_at': (NOW - timedelta(minutes=6)).isoformat()}
        self.assertEqual(self.mux.handle_verified_webhook(stale)[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.old_provider.calls, [])
        fresh = {**self.new_message, 'message_id': '702'}
        self.assertEqual(self.mux.handle(fresh)[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.old_provider.calls, [])
        self.assertEqual(self.mux.handle_verified_webhook(fresh)[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.old_provider.posts, 0)
        self.assertEqual(self.new_provider.posts, 2)


class RealReceiptLifecycle(unittest.TestCase):
    def test_whole_closure_lifecycle_accepts_documented_envelope(self):
        case = close_fixtures.ProviderClose('test_resolves_exact_conversation_with_explicit_status')
        case.setUp()
        self.addCleanup(case.doCleanups)
        original = case.provider.open
        def official(request, timeout):
            response = original(request, timeout)
            if request.method == 'POST' and request.full_url.endswith('/toggle_status'):
                return io.BytesIO(json.dumps({'meta': {}, 'payload': {'success': True,
                    'conversation_id': case.router.scope.conversation_id,
                    'current_status': 'resolved', 'snoozed_until': None}}).encode())
            return response
        case.provider.open = official
        self.assertEqual(tick(case.router)['status'], 'closed')
        self.assertEqual(case.store.db.execute('SELECT status FROM demo_closures').fetchone()[0], 'resolved')
        self.assertEqual(len([c for c in case.provider.calls if c[1].endswith('/toggle_status')]), 1)
