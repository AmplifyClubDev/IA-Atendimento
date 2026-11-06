"""Fresh, exactly scoped reset commands; synthetic IO and messages only."""
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from contracts import inbound_key
from demo_router import DemoRouter, DemoStore, RecordingGateway, OPENING
import test_demo_router as fixtures
from test_demo_router import NOW, SCOPE, OTHER, TOKEN, event
from test_demo_review_boundaries import FakeChatwoot, REVIEW_SCOPE, STAMP


class ResetCases(unittest.TestCase):
    def setUp(self):
        self.store = DemoStore(':memory:')
        self.addCleanup(self.store.close)
        self.gateway = RecordingGateway()
        self.at = NOW
        self.router = DemoRouter(SCOPE, self.store, self.gateway, now=lambda: self.at,
                                 continuation_enabled=True)
        self.router.start('synthetic-before-reset')

    def reset(self, **changes):
        return event(text='Resetar', created_at=self.at.isoformat(), **changes)

    def counts(self):
        return tuple(self.store.db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                     for table in ('demo_runs', 'demo_outbox', 'demo_starts', 'demo_simulations'))

    def test_fresh_reset_restarts_expired_session_and_preserves_history(self):
        old = self.store.current(SCOPE.slot)
        self.at += timedelta(hours=2)
        result, code = self.router.handle(self.reset())
        new = self.store.current(SCOPE.slot)
        self.assertEqual((code, result['status']), (202, 'demo_reset_presented'))
        self.assertTrue(result['accepted'])
        self.assertFalse(result['production_effects'])
        self.assertNotEqual(old['run'], new['run'])
        self.assertNotEqual(old['parent_id'], new['parent_id'])
        self.assertEqual((new['step'], new['watermark']), ('opening', '101'))
        self.assertEqual(self.gateway.sent[-1]['payload']['content'], OPENING)
        self.assertEqual(self.counts(), (1, 2, 2, 0))
        next_event = event(message_id='102', created_at=(self.at + timedelta(seconds=1)).isoformat(),
                           demo_reply_to=new['parent_id'])
        self.assertEqual(self.router.handle(next_event)[0]['step'], 'about')

    def test_fresh_reset_restarts_unexpired_session_without_reply_parent(self):
        self.at += timedelta(seconds=10)
        old_run = self.store.current(SCOPE.slot)['run']
        self.assertEqual(self.router.handle(self.reset())[0]['status'], 'demo_reset_presented')
        self.assertNotEqual(self.store.current(SCOPE.slot)['run'], old_run)
        self.assertEqual(len(self.gateway.sent), 2)

    def test_legacy_demo_also_supports_exact_reset(self):
        self.router.continuation_enabled = False
        self.at += timedelta(hours=2)
        self.assertEqual(self.router.handle(self.reset())[0]['status'], 'demo_reset_presented')
        self.assertTrue(self.store.current(SCOPE.slot)['outbox_key'].startswith('bia-demo:v1:'))
        self.assertEqual(self.store.current(SCOPE.slot)['step'], 'opening')

    def test_reset_can_start_an_unstarted_demo(self):
        store = DemoStore(':memory:')
        self.addCleanup(store.close)
        gateway = RecordingGateway()
        router = DemoRouter(SCOPE, store, gateway, now=lambda: NOW, continuation_enabled=True)
        self.assertEqual(router.handle(self.reset())[0]['status'], 'demo_reset_presented')
        self.assertEqual(len(gateway.sent), 1)

    def test_command_is_exact_ignoring_only_case_and_outer_whitespace(self):
        self.at += timedelta(seconds=1)
        source = {**self.reset(), 'text': '  RESETAR\n'}
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_reset_presented')
        before = self.counts()
        self.at += timedelta(hours=2)
        for number, text in enumerate(('resetar agora', 'Como resetar?', 'resetar!', 'resetar tudo'), 102):
            source = {**self.reset(message_id=str(number)), 'text': text}
            self.assertEqual(self.router.handle(source)[0]['status'], 'demo_stale_event')
        self.assertEqual(self.counts(), before)

    def test_stale_missing_malformed_and_future_reset_timestamps_are_closed(self):
        self.at += timedelta(hours=2)
        before = self.store.current(SCOPE.slot)
        self.gateway.preflight = Mock(return_value={'after_message_id': '0'})
        stamps = [None, '', 'invalid', self.at.timestamp(), self.at.replace(tzinfo=None).isoformat(),
                  (self.at - timedelta(minutes=5, microseconds=1)).isoformat(),
                  (self.at + timedelta(seconds=31)).isoformat()]
        for number, stamp in enumerate(stamps, 101):
            with self.subTest(stamp=stamp):
                source = {**self.reset(message_id=str(number)), 'created_at': stamp}
                self.assertEqual(self.router.handle(source)[0]['status'], 'demo_stale_event')
        self.gateway.preflight.assert_not_called()
        self.assertEqual(self.store.current(SCOPE.slot), before)
        self.assertEqual(len(self.gateway.sent), 1)

    def test_reset_before_current_start_or_at_old_watermark_is_closed(self):
        self.at += timedelta(seconds=20)
        self.router.start('synthetic-more-recent-start')
        before = self.store.current(SCOPE.slot)
        source = {**self.reset(), 'created_at': (self.at - timedelta(seconds=1)).isoformat()}
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_stale_event')
        self.store.db.execute('UPDATE demo_runs SET watermark=?', ('102',))
        self.assertEqual(self.router.handle(self.reset(message_id='102'))[0]['status'], 'demo_stale_event')
        self.assertEqual(self.store.current(SCOPE.slot)['run'], before['run'])
        self.assertEqual(len(self.gateway.sent), 2)

    def test_scope_and_inbound_identity_are_required_before_reset(self):
        before = self.counts()
        for changes in ({'contact_id': '8'}, {'conversation_id': '8'}, {'sender_phone': OTHER},
                        {'private': True}, {'message_type': 'outgoing'}, {'sender_type': 'user'},
                        {'provider': 'other'}, {'message_id': None}):
            with self.subTest(changes=changes):
                self.assertEqual(self.router.handle(self.reset(**changes))[0]['status'], 'demo_identity_rejected')
        for changes in ({'account_id': '2'}, {'inbox_id': '2'},
                        {'contact_id': '8', 'conversation_id': '8', 'sender_phone': OTHER}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'outside_scope'):
                self.router.handle(self.reset(**changes))
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(self.gateway.sent), 1)

    def test_duplicate_and_conflicting_reset_never_create_another_send(self):
        source = self.reset()
        first = self.router.handle(source)
        self.assertEqual(self.router.handle(source), first)
        self.assertEqual(self.router.handle({**source, 'text': 'resetar'})[0]['status'],
                         'demo_conflicting_duplicate')
        self.assertEqual(self.router.handle({**source, 'text': 'Conhecer a Amplify'})[0]['status'],
                         'demo_conflicting_duplicate')
        self.assertEqual(len(self.gateway.sent), 2)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_events').fetchone()[0], 1)

    def test_concurrent_duplicate_reset_is_serialized(self):
        source = self.reset()
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.router.handle(source))) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.gateway.sent), 2)
        self.assertEqual(self.counts(), (1, 2, 2, 0))

    def test_duplicate_reset_survives_process_recreation_and_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'demo.sqlite')
            store = DemoStore(path)
            gateway = RecordingGateway()
            router = DemoRouter(SCOPE, store, gateway, now=lambda: NOW, continuation_enabled=True)
            source = self.reset()
            result = router.handle(source)
            store.close()
            again = DemoStore(path)
            try:
                router = DemoRouter(SCOPE, again, gateway, now=lambda: NOW + timedelta(days=1),
                                    continuation_enabled=True)
                self.assertEqual(router.handle(source), result)
                self.assertEqual(len(gateway.sent), 1)
            finally:
                again.close()

    def test_existing_unknown_outcome_blocks_reset_before_preflight(self):
        self.gateway.send = Mock(side_effect=TimeoutError())
        self.router.start('synthetic-pending-opening')
        old = self.store.current(SCOPE.slot)
        self.at += timedelta(hours=2)
        self.gateway.preflight = Mock(return_value={'after_message_id': '0'})
        source = self.reset()
        first = self.router.handle(source)
        self.assertEqual(first[0]['status'], 'demo_delivery_unconfirmed')
        self.assertFalse(first[0]['repeat_allowed'])
        self.assertEqual(self.router.handle(source), first)
        self.assertEqual(self.store.current(SCOPE.slot), old)
        self.gateway.preflight.assert_not_called()
        self.gateway.send.assert_called_once()

    def test_reset_uncertainty_never_retries_and_reconciliation_updates_event(self):
        send = self.gateway.send
        def uncertain(scope, payload, key):
            send(scope, payload, key)
            raise TimeoutError('synthetic provider details')
        self.gateway.send = uncertain
        source = self.reset()
        result = self.router.handle(source)
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.router.handle(source), result)
        self.assertEqual(self.router.handle(self.reset(message_id='102'))[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(len(self.gateway.sent), 2)
        self.gateway.lookup = lambda scope, key: {'status': 'accepted', 'message_id': '202', 'simulated': True}
        self.assertEqual(self.router.reconcile()['step'], 'opening')
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_reset_presented')
        self.assertEqual(self.router.handle(self.reset(message_id='102'))[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(len(self.gateway.sent), 2)

    def test_reset_event_and_unknown_outbox_commit_before_send(self):
        source = self.reset()
        send = self.gateway.send
        def observe(scope, payload, key):
            self.assertFalse(self.store.db.in_transaction)
            row = self.store.db.execute('SELECT status,receipt FROM demo_outbox WHERE key=?', (key,)).fetchone()
            self.assertEqual(row['status'], 'outcome_unknown')
            self.assertEqual(json.loads(row['receipt'])['reset_event_key'], inbound_key(source))
            row = self.store.db.execute('SELECT result FROM demo_events WHERE event_key=?',
                                        (inbound_key(source),)).fetchone()
            self.assertEqual(json.loads(row['result'])['status'], 'demo_delivery_unconfirmed')
            self.assertEqual(self.store.current(SCOPE.slot)['step'], 'delivery_pending')
            return send(scope, payload, key)
        self.gateway.send = observe
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_reset_presented')

    def test_receipt_and_reset_event_confirmation_are_atomic(self):
        self.store.db.executescript("""CREATE TRIGGER synthetic_reset_receipt_failure
            BEFORE UPDATE OF result ON demo_events
            BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END;""")
        source = self.reset()
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.store.current(SCOPE.slot)['step'], 'delivery_pending')
        row = self.store.db.execute('SELECT status FROM demo_outbox WHERE key=?',
                                   (self.store.current(SCOPE.slot)['outbox_key'],)).fetchone()
        self.assertEqual(row['status'], 'outcome_unknown')
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(len(self.gateway.sent), 2)
        self.store.db.execute('DROP TRIGGER synthetic_reset_receipt_failure')
        self.gateway.lookup = lambda scope, key: {'status': 'accepted', 'message_id': '202', 'simulated': True}
        self.router.reconcile()
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_reset_presented')
        self.assertEqual(len(self.gateway.sent), 2)


class ResetGatewayCases(unittest.TestCase):
    def setup_gateway(self, fake):
        store = DemoStore(':memory:')
        self.addCleanup(store.close)
        gateway = fake.gateway()
        gateway.continuation_enabled = True
        router = DemoRouter(REVIEW_SCOPE, store, gateway, now=lambda: STAMP, continuation_enabled=True)
        source = event(account_id=REVIEW_SCOPE.account_id, inbox_id=REVIEW_SCOPE.inbox_id,
                       contact_id=REVIEW_SCOPE.contact_id, conversation_id=REVIEW_SCOPE.conversation_id,
                       sender_phone=REVIEW_SCOPE.phone, text='Resetar', created_at=STAMP.isoformat())
        return router, source

    def test_reset_rechecks_live_identity_and_window_before_post(self):
        fake = FakeChatwoot()
        router, source = self.setup_gateway(fake)
        self.assertEqual(router.handle(source)[0]['status'], 'demo_reset_presented')
        self.assertEqual([call[0] for call in fake.calls], ['GET', 'GET', 'GET', 'GET', 'POST'])
        count = len(fake.calls)
        router.handle(source)
        self.assertEqual(len(fake.calls), count)

    def test_closed_window_or_changed_provider_scope_never_posts(self):
        for change in ('window', 'can_reply', 'conversation', 'contact', 'inbox', 'phone'):
            with self.subTest(change=change):
                fake = FakeChatwoot()
                if change == 'window': fake.messages[0]['created_at'] = (STAMP - timedelta(days=1)).timestamp()
                elif change == 'can_reply': fake.detail['can_reply'] = False
                elif change == 'conversation': fake.detail['id'] = '14'
                elif change == 'contact': fake.detail['meta']['sender']['id'] = '12'
                elif change == 'inbox': fake.detail['inbox_id'] = '5'
                else: fake.detail['meta']['sender']['phone_number'] = OTHER
                router, source = self.setup_gateway(fake)
                result = router.handle(source)
                self.assertEqual(result[0]['status'], 'demo_reset_unavailable')
                self.assertIsNone(router.store.current(REVIEW_SCOPE.slot))
                self.assertNotIn('POST', [call[0] for call in fake.calls])
                count = len(fake.calls)
                self.assertEqual(router.handle(source), result)
                self.assertEqual(len(fake.calls), count)

    def test_window_closing_after_preflight_preserves_unknown_outcome(self):
        fake = FakeChatwoot()
        router, source = self.setup_gateway(fake)
        preflight = router.gateway.preflight
        calls = []
        def closes(scope):
            calls.append(scope)
            if len(calls) == 2: fake.detail['can_reply'] = False
            return preflight(scope)
        router.gateway.preflight = closes
        self.assertEqual(router.handle(source)[0]['status'], 'demo_delivery_unconfirmed')
        self.assertNotIn('POST', [call[0] for call in fake.calls])
        self.assertEqual(router.store.current(REVIEW_SCOPE.slot)['step'], 'delivery_pending')
        count = len(fake.calls)
        self.assertEqual(router.handle(source)[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(len(fake.calls), count)


class ResetWebhookCases(unittest.TestCase):
    make_app = fixtures.FlaskRouting.make_app
    raw = fixtures.FlaskRouting.raw

    def test_expired_webhook_reset_is_authenticated_logged_and_demo_only(self):
        app, repo, transport, gateway = self.make_app()
        router = app.extensions['v5_demo_router']
        router.continuation_enabled = True
        router.start('synthetic-webhook-start')
        router.now = lambda: NOW + timedelta(hours=2)
        source = self.raw('Resetar')
        source['created_at'] = (NOW + timedelta(hours=2)).isoformat()
        client = app.test_client()
        self.assertEqual(client.post('/webhook/chatwoot', json=source).status_code, 401)
        with patch('builtins.print') as log:
            result = client.post('/webhook/chatwoot', json=source,
                                 headers={'X-Amplify-Webhook-Token': TOKEN})
        self.assertEqual(result.json['status'], 'demo_reset_presented')
        log.assert_called_once()
        self.assertEqual(json.loads(log.call_args.args[0]), {
            'message_id': '101', 'conversation_id': '7', 'status': 'demo_reset_presented'})
        self.assertEqual(log.call_args.kwargs, {'flush': True})
        self.assertEqual(len(gateway.sent), 2)
        transport.send_reply.assert_not_called()
        with repo._connection() as db:
            for table in ('sessions', 'inbound_events', 'operations', 'outbox', 'real_jobs'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0, table)

    def test_log_contains_only_safe_ids_and_status_even_on_error(self):
        app, repo, transport, gateway = self.make_app()
        router = app.extensions['v5_demo_router']
        for result in ({'status': 'demo_identity_rejected'}, {'status': 'demo_stale_event'},
                       {'status': 'demo_delivery_unconfirmed'}):
            with self.subTest(result=result):
                router.handle = Mock(return_value=(result, 202))
                with patch('builtins.print') as log:
                    response = app.test_client().post('/webhook/chatwoot', json=self.raw('private synthetic text'),
                                                     headers={'X-Amplify-Webhook-Token': TOKEN})
                self.assertEqual(response.status_code, 202)
                self.assertEqual(json.loads(log.call_args.args[0]), {
                    'message_id': '101', 'conversation_id': '7', 'status': result['status']})
        router.handle = Mock(side_effect=RuntimeError('private synthetic exception'))
        with patch('builtins.print') as log:
            response = app.test_client().post('/webhook/chatwoot', json=self.raw('private synthetic text'),
                                             headers={'X-Amplify-Webhook-Token': TOKEN})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(log.call_args.args[0]), {
            'message_id': '101', 'conversation_id': '7', 'status': 'demo_unavailable'})
        transport.send_reply.assert_not_called()
