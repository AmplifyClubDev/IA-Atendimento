"""Synthetic reminders: no network, production clients or messages."""
import unittest
from datetime import timedelta
from unittest.mock import Mock
import demo_flow
from demo_followup import tick, tick_all
from demo_router import DemoRouter, DemoStore, RecordingGateway, DemoMultiplexer, configure_context_payload
from test_demo_router import NOW, SCOPE, event

class Reminders(unittest.TestCase):
    def setUp(self):
        self.store = DemoStore(':memory:')
        self.addCleanup(self.store.close)
        self.gateway = RecordingGateway()
        self.at = NOW
        self.router = DemoRouter(SCOPE, self.store, self.gateway, now=lambda: self.at,
                                 continuation_enabled=True, followup_enabled=True)
        self.router.start('synthetic-followup-start')
        self.state = self.store.current(SCOPE.slot)
        self.gateway.preflight = Mock(return_value={'after_message_id': self.state['parent_id']})

    def due(self):
        self.at += timedelta(seconds=600)

    def test_once_after_ten_minutes_preserves_step_and_run(self):
        self.assertEqual(tick(self.router)['status'], 'idle')
        self.due()
        self.assertEqual(tick(self.router)['status'], 'accepted')
        self.assertEqual(tick(self.router)['status'], 'idle')
        self.assertEqual(len(self.gateway.sent), 2)
        self.assertEqual(self.store.current(SCOPE.slot), self.state)
        self.assertNotIn('sou a Bia', self.gateway.sent[-1]['payload']['content'])

    def test_unconfirmed_send_never_retried(self):
        self.gateway.send = Mock(side_effect=TimeoutError)
        self.due()
        self.assertEqual(tick(self.router)['status'], 'unconfirmed')
        self.assertEqual(tick(self.router)['status'], 'idle')
        self.gateway.send.assert_called_once()

    def test_new_provider_message_cancels(self):
        self.gateway.preflight.return_value = {'after_message_id': str(int(self.state['parent_id'])+1)}
        self.due()
        self.assertEqual(tick(self.router)['status'], 'source_changed')
        self.assertEqual(tick(self.router)['status'], 'idle')
        self.assertEqual(len(self.gateway.sent), 1)

    def test_inbound_cancels_even_without_transition(self):
        self.router.handle(event(message_id='102', text='Voltar ao início'))
        self.due()
        self.assertEqual(tick(self.router)['status'], 'idle')
        self.assertEqual(len(self.gateway.sent), 1)

    def test_closed_paused_confirmed_and_pending_do_not_send(self):
        self.due()
        for step in ('closed', 'paused', 'confirmed', 'delivery_pending'):
            self.store.db.execute('UPDATE demo_runs SET step=?', (step,))
            self.assertEqual(tick(self.router)['status'], 'idle')
        self.assertEqual(len(self.gateway.sent), 1)

    def test_expired_window_does_not_send(self):
        self.at += timedelta(hours=1)
        self.assertEqual(tick(self.router)['status'], 'expired')
        self.assertEqual(len(self.gateway.sent), 1)

    def test_disabled_does_not_send(self):
        self.router.followup_enabled = False
        self.due()
        self.assertEqual(tick_all(self.router), [{'status': 'disabled'}])

    def test_existing_sessions_are_not_retroactively_armed(self):
        self.store.db.execute('DELETE FROM demo_followups')
        self.due()
        self.assertEqual(tick(self.router)['status'], 'idle')

    def test_removed_legacy_button_cannot_restart(self):
        self.assertIsNone(demo_flow.decision('profile', 'Voltar ao início', correlated=True,
            opening_choices={}, current_choices={'opening':'Voltar ao início'}))
        for _, menu in demo_flow.TEMPLATES.values():
            self.assertNotIn('opening', menu)

class LiveGatewayReminders(unittest.TestCase):
    def setup_live(self):
        from test_demo_review_boundaries import FakeChatwoot, REVIEW_SCOPE, STAMP
        from demo_router import DemoWhatsAppGateway
        self.at = STAMP
        fake = FakeChatwoot()
        fake.detail['status'] = 'open'
        store = DemoStore(':memory:')
        self.addCleanup(store.close)
        gateway = DemoWhatsAppGateway('https://chat.review.invalid', 'synthetic-review-token',
            scope=REVIEW_SCOPE, live_enabled=True, opener=fake, now=lambda: self.at, continuation_enabled=True)
        configure_context_payload(gateway, store, REVIEW_SCOPE)
        router = DemoRouter(REVIEW_SCOPE, store, gateway, now=lambda: self.at,
                           continuation_enabled=True, followup_enabled=True)
        router.start('synthetic-live-followup')
        fake.messages.append({'id': '201', 'message_type': 'outgoing', 'private': False})
        self.at += timedelta(seconds=600)
        return fake, router

    def test_live_exact_scope_approved_reminder_and_no_restart(self):
        fake, router = self.setup_live()
        before = router.store.current(router.scope.slot)
        self.assertEqual(tick(router)['status'], 'accepted')
        self.assertEqual(len([c for c in fake.calls if c[0]=='POST']), 2)
        self.assertEqual(fake.calls[-1][2]['content_type'], 'text')
        self.assertEqual(router.store.current(router.scope.slot), before)

    def test_human_assigned_suppresses_reminder(self):
        fake, router = self.setup_live()
        fake.detail['meta']['assignee'] = {'id':'9'}
        self.assertEqual(tick(router)['status'], 'human_or_closed')
        self.assertEqual(len([c for c in fake.calls if c[0]=='POST']), 1)

    def test_reply_arriving_at_last_check_never_posts(self):
        fake, router = self.setup_live()
        original = router.gateway.preflight
        count = [0]
        def changed(scope):
            count[0] += 1
            if count[0] == 2:
                fake.messages.append({'id':'202','message_type':'incoming','private':False,
                                      'created_at':self.at.timestamp()})
            return original(scope)
        router.gateway.preflight = changed
        self.assertEqual(tick(router)['status'], 'unconfirmed')
        self.assertEqual(tick(router)['status'], 'idle')
        self.assertEqual(len([c for c in fake.calls if c[0]=='POST']), 1)
