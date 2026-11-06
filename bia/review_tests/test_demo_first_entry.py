"""A fresh authenticated first message opens an exact static demo once."""
from dataclasses import asdict
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, call, patch

from demo_router import build_demo_router, DemoWhatsAppGateway, production_blocked
from test_demo_router import NOW, SCOPE, TOKEN
from test_demo_multi_scope import SECOND, THIRD_PHONE, multi_settings, source
import test_demo_multi_scope as multi_fixtures


class StaticFirstEntry(unittest.TestCase):
    def setUp(self):
        self.config = multi_settings('/tmp/synthetic-first-entry')
        self.mux = build_demo_router(self.config)
        self.addCleanup(self.mux.store.close)
        for router in self.mux.routers: router.now = lambda: NOW
        self.first, self.second = self.mux.routers

    def message(self, **changes):
        return source(SECOND, **{'text': 'Oi, quero conhecer a Amplify', 'created_at': NOW.isoformat(), **changes})

    def test_first_normal_message_opens_second_and_preserves_existing_first_session(self):
        self.first.start('existing-primary-session')
        before = self.mux.store.current(SCOPE.slot)
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_reset_presented')
        self.assertTrue(result[0]['accepted'])
        self.assertEqual(self.mux.store.current(SECOND.slot)['step'], 'opening')
        self.assertEqual(self.mux.store.current(SCOPE.slot), before)
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [1, 1])

    def test_catchup_and_read_controls_do_not_start_an_unstarted_static_contact(self):
        result = self.mux.handle(self.message())
        self.assertEqual(result[0]['status'], 'demo_not_started')
        self.assertIsNone(self.mux.store.current(SECOND.slot))
        self.assertEqual(self.second.reconcile()['status'], 'demo_not_started')
        with self.assertRaises(ValueError): self.second.simulate('invite')
        self.assertEqual(self.second.gateway.sent, [])

    def test_duplicate_and_changed_first_message_do_not_send_again(self):
        first = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(self.mux.handle_verified_webhook(self.message()), first)
        conflict = self.mux.handle_verified_webhook(self.message(text='Different content'))
        self.assertEqual(conflict[0]['status'], 'demo_conflicting_duplicate')
        self.assertEqual(len(self.second.gateway.sent), 1)
        self.assertEqual(self.mux.store.db.execute('SELECT count(*) FROM demo_events WHERE slot=?', (SECOND.slot,)).fetchone()[0], 1)

    def test_simultaneous_first_deliveries_present_one_opening(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.mux.handle_verified_webhook(self.message()))) for _ in range(5)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(results), 5)
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.second.gateway.sent), 1)

    def test_stale_missing_and_future_first_message_do_not_preflight_or_start(self):
        self.second.gateway.preflight = Mock()
        stamps = [None, '', 'invalid', NOW.replace(tzinfo=None).isoformat(),
                  (NOW - timedelta(minutes=5, microseconds=1)).isoformat(),
                  (NOW + timedelta(seconds=31)).isoformat()]
        for index, stamp in enumerate(stamps, 101):
            result = self.mux.handle_verified_webhook(self.message(message_id=str(index), created_at=stamp))
            self.assertEqual(result[0]['status'], 'demo_stale_event')
        self.assertIsNone(self.mux.store.current(SECOND.slot))
        self.second.gateway.preflight.assert_not_called()
        self.assertEqual(self.second.gateway.sent, [])

    def test_wrong_and_crossed_identity_cannot_start_or_fall_through(self):
        for changes in ({'contact_id': SCOPE.contact_id}, {'conversation_id': SCOPE.conversation_id},
                        {'sender_phone': SCOPE.phone}, {'sender_phone': THIRD_PHONE},
                        {'message_id': None}, {'private': True}, {'message_type': 'outgoing'},
                        {'provider': 'foreign'}, {'sender_type': 'user'}):
            message = {**self.message(), **changes}
            self.assertTrue(production_blocked(self.config, event=message))
            self.assertEqual(self.mux.handle_verified_webhook(message)[0]['status'], 'demo_identity_rejected')
        self.assertIsNone(self.mux.store.current(SECOND.slot))
        self.assertEqual(self.second.gateway.sent, [])

    def test_ambiguous_scope_acceptance_never_selects_a_recipient(self):
        # Defense in depth if an in-process adapter is faulty. Valid configuration
        # already forbids duplicate phones/contact/conversation identities.
        with patch.object(type(self.second.scope), 'accepts', return_value=True):
            self.assertEqual(self.mux.handle_verified_webhook(self.message())[0]['status'], 'demo_identity_rejected')
        self.assertEqual([len(router.gateway.sent) for router in self.mux.routers], [0, 0])

    def test_unknown_first_send_blocks_replays_and_future_turn_without_resend(self):
        send = self.second.gateway.send
        def unknown(*args):
            send(*args)
            raise TimeoutError('synthetic ambiguous provider outcome')
        self.second.gateway.send = unknown
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.mux.handle_verified_webhook(self.message()), result)
        followup = self.mux.handle_verified_webhook(self.message(message_id='102', text='Oi novamente'))
        self.assertEqual(followup[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(len(self.second.gateway.sent), 1)
        self.assertTrue(production_blocked(self.config, event=self.message()))

    def test_ambiguous_preflight_cannot_send_and_is_not_retried_on_duplicate(self):
        self.second.gateway.preflight = Mock(side_effect=ValueError('demo_recipient_or_window_unverified'))
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_reset_unavailable')
        self.assertEqual(self.mux.handle_verified_webhook(self.message()), result)
        self.second.gateway.preflight.assert_called_once()
        self.assertEqual(self.second.gateway.sent, [])
        self.assertIsNone(self.mux.store.current(SECOND.slot))

    def test_live_gateway_checks_exact_recipient_before_first_post(self):
        calls = []
        class Opener:
            def open(inner, request, timeout):
                calls.append(request.method)
                return io.BytesIO(json.dumps({'id': SECOND.conversation_id, 'account_id': '1',
                    'inbox_id': '3', 'can_reply': True,
                    'meta': {'sender': {'id': '999', 'phone_number': THIRD_PHONE}}}).encode())
        self.second.gateway = DemoWhatsAppGateway('https://chat.first.invalid', 'synthetic', scope=SECOND,
            live_enabled=True, continuation_enabled=True, opener=Opener(), now=lambda: NOW)
        result = self.mux.handle_verified_webhook(self.message())
        self.assertEqual(result[0]['status'], 'demo_reset_unavailable')
        self.assertEqual(calls, ['GET'])
        self.assertIsNone(self.mux.store.current(SECOND.slot))

    def test_closed_or_expired_existing_session_is_not_automatically_restarted(self):
        self.second.start('existing-second-session')
        self.second.stop()
        before = self.mux.store.current(SECOND.slot)
        self.mux.handle_verified_webhook(self.message())
        self.assertEqual(self.mux.store.current(SECOND.slot), before)
        self.assertEqual(len(self.second.gateway.sent), 1)
        self.second.now = lambda: NOW + timedelta(hours=2)
        result = self.mux.handle_verified_webhook(self.message(message_id='102', created_at=(NOW + timedelta(hours=2)).isoformat()))
        self.assertEqual(result[0]['status'], 'demo_stale_event')
        self.assertEqual(self.mux.store.current(SECOND.slot), before)
        self.assertEqual(len(self.second.gateway.sent), 1)

    def test_restart_preserves_first_entry_duplicate_and_uncertainty(self):
        with tempfile.TemporaryDirectory() as directory:
            config = multi_settings(directory)
            config['demo_state_path'] = str(Path(directory) / 'demo.sqlite3')
            original = build_demo_router(config)
            try:
                for router in original.routers: router.now = lambda: NOW
                original.routers[1].gateway.send = Mock(side_effect=TimeoutError())
                result = original.handle_verified_webhook(self.message())
            finally:
                original.store.close()
            again = build_demo_router(config)
            try:
                for router in again.routers: router.now = lambda: NOW + timedelta(days=1)
                self.assertEqual(again.handle_verified_webhook(self.message()), result)
                self.assertEqual(again.routers[1].gateway.sent, [])
            finally:
                again.store.close()

    def test_normal_first_message_opens_only_after_authenticated_webhook(self):
        app, repo, transport, mux = multi_fixtures.MultiWebhookBoundaries.make_app(self)
        raw = multi_fixtures.MultiWebhookBoundaries.raw(self, text='Oi')
        client = app.test_client()
        self.assertEqual(client.post('/webhook/chatwoot', json=raw).status_code, 401)
        self.assertEqual([len(router.gateway.sent) for router in mux.routers], [0, 0])
        response = client.post('/webhook/chatwoot?token=' + TOKEN, json=raw)
        self.assertEqual(response.json['status'], 'demo_reset_presented')
        self.assertEqual([len(router.gateway.sent) for router in mux.routers], [0, 1])
        self.assertTrue(all(item == call.ready() for item in transport.mock_calls))
        with repo._connection() as db:
            for table in ('sessions', 'inbound_events', 'outbox', 'real_jobs', 'operations'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
