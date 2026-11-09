"""Draft continuation: sequential buttons, simulated effects and no production fallback."""
import json
import threading
import unittest
from unittest.mock import Mock

import demo_flow
from demo_router import DemoRouter, DemoStore, RecordingGateway, DemoWhatsAppGateway, message_payload, OPENING, CHOICES
import test_demo_router as fixtures
from test_demo_review_boundaries import FakeChatwoot, REVIEW_SCOPE, STAMP


class FlowCases(unittest.TestCase):
    def setUp(self):
        self.store = DemoStore(':memory:'); self.addCleanup(self.store.close)
        self.gateway = RecordingGateway()
        self.router = DemoRouter(fixtures.SCOPE, self.store, self.gateway, now=lambda: fixtures.NOW, continuation_enabled=True)
        self.counter = 100
        self.opening = self.router.start('synthetic-flow-start')

    def source(self, action=None, *, text=None, correlated=True):
        state = self.store.current(fixtures.SCOPE.slot)
        if action == 'use_profile':
            action, text = None, '@synthetic_profile'
        if action:
            payload = message_payload(state['outbox_key'], continuation_enabled=True)
            text = next(item['title'] for item in payload['content_attributes']['items'] if item['value'].endswith(':' + action))
        self.counter += 1
        return fixtures.event(message_id=str(self.counter), text=text,
                              demo_reply_to=state['parent_id'] if correlated else None)

    def choose(self, action):
        response = self.router.handle(self.source(action))[0]
        self.assertEqual(response['status'], 'demo_step_presented', response)
        self.assertFalse(response['production_effects'])
        return self.store.current(fixtures.SCOPE.slot)['step']

    def test_know_opens_short_topic_menu_before_explicit_join(self):
        self.assertEqual(self.choose('know'), 'about')
        payload = self.gateway.sent[-1]['payload']
        self.assertEqual(payload['content'], demo_flow.format_answer(demo_flow.TEMPLATES['about'][0]))
        self.assertEqual([item['title'] for item in payload['content_attributes']['items']],
                         ['Conhecer benefícios', 'Parceria e regras', 'Mais assuntos'])
        self.assertEqual(self.choose('faq_benefits'), 'faq_benefits')
        self.assertEqual(self.choose('join'), 'profile')

    def test_join_reaches_simulated_confirmation_without_real_profile_or_terms(self):
        self.assertEqual([self.choose(action) for action in ('join', 'use_profile', 'continue_test', 'accept_demo')],
                         ['profile', 'conditions', 'invite', 'confirmed'])
        effects = [json.loads(row[0]) for row in self.store.db.execute('SELECT result FROM demo_simulations')]
        self.assertEqual([row['operation'] for row in effects], ['tiktok', 'invite', 'invite', 'relationship'])
        self.assertTrue(all(row['status'] == 'simulated' for row in effects))
        self.assertTrue(all(row.get('sent', False) is False and row.get('provider_called', False) is False for row in effects))
        self.assertFalse(effects[-1]['production_relationship'])
        self.assertNotIn('form', [row['operation'] for row in effects])

    def test_member_branch_does_not_verify_or_claim_membership(self):
        self.assertEqual(self.choose('member'), 'member')
        self.assertIn('não vou consultar seu cadastro', self.gateway.sent[-1]['payload']['content'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 0)
        self.assertEqual(self.choose('question'), 'about')
        self.assertEqual(self.router.handle(self.source(text='Como funciona o convite?'))[0]['step'], 'faq_invite')

    def test_free_questions_use_static_answers_and_do_not_store_profile_text(self):
        self.choose('join')
        text = 'Meu perfil é @synthetic_profile. Quanto custa e tem exclusividade?'
        result = self.router.handle(self.source(text=text, correlated=False))[0]
        self.assertEqual(result['step'], 'faq_terms')
        self.assertIn('ainda precisam ser confirmadas', self.gateway.sent[-1]['payload']['content'])
        dump = '\n'.join(self.store.db.iterdump())
        self.assertNotIn('synthetic_profile', dump)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 0)

    def test_old_parent_old_version_and_unthreaded_action_do_not_advance(self):
        old = self.source('know')
        self.router.handle(old)
        count = len(self.gateway.sent)
        self.counter += 1
        stale = {**old, 'message_id': str(self.counter)}
        self.assertEqual(self.router.handle(stale)[0]['status'], 'demo_choice_not_current')
        self.assertEqual(self.router.handle(self.source(text='Conhecer a Amplify', correlated=False))[0]['status'], 'demo_choice_not_current')
        self.assertEqual(len(self.gateway.sent), count)
        other_store = DemoStore(':memory:'); self.addCleanup(other_store.close)
        legacy = DemoRouter(fixtures.SCOPE, other_store, now=lambda: fixtures.NOW)
        opening = legacy.start('synthetic-old-version')
        migrated = DemoRouter(fixtures.SCOPE, other_store, now=lambda: fixtures.NOW, continuation_enabled=True)
        result = migrated.handle(fixtures.event(demo_reply_to=opening['message_id']))[0]
        self.assertEqual(result['status'], 'demo_flow_restart_required')

    def test_duplicate_threads_create_exactly_one_continuation(self):
        source = self.source('know'); outcomes = []
        threads = [threading.Thread(target=lambda: outcomes.append(self.router.handle(source))) for _ in range(4)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(len(outcomes), 4)
        self.assertTrue(all(result == outcomes[0] for result in outcomes))
        self.assertEqual(len(self.gateway.sent), 2)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_events').fetchone()[0], 1)

    def test_unknown_continuation_reconciles_without_retry_or_overwriting_opening(self):
        source = self.source('join')
        send = self.gateway.send
        def unknown(scope, payload, key):
            send(scope, payload, key)
            raise TimeoutError('synthetic uncertainty')
        self.gateway.send = unknown
        result = self.router.handle(source)[0]
        self.assertEqual(result['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.router.handle(source)[0], result)
        self.assertEqual(self.router.start('synthetic-new-start')['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(len(self.gateway.sent), 2)
        self.gateway.lookup = lambda scope, key: {'status': 'accepted', 'message_id': '202', 'simulated': True}
        self.assertEqual(self.router.reconcile()['step'], 'profile')
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_step_presented')
        self.assertEqual(self.router.start('synthetic-flow-start'), self.opening)
        self.assertEqual(len(self.gateway.sent), 2)

    def test_reconciliation_after_admin_stop_does_not_reactivate_flow(self):
        self.gateway.send = Mock(side_effect=TimeoutError())
        self.router.handle(self.source('join'))
        self.router.stop()
        self.gateway.lookup = lambda scope, key: {'status': 'accepted', 'message_id': '202', 'simulated': True}
        self.router.reconcile()
        self.assertEqual(self.store.current(fixtures.SCOPE.slot)['step'], 'closed')
        self.assertEqual(self.router.handle(self.source(text='Quero me agenciar'))[0]['status'], 'demo_choice_not_current')

    def test_uncertainty_is_committed_before_continuation_gateway_is_called(self):
        send = self.gateway.send
        def observe(scope, payload, key):
            self.assertFalse(self.store.db.in_transaction)
            self.assertEqual(self.store.db.execute('SELECT status FROM demo_outbox WHERE key=?', (key,)).fetchone()[0], 'outcome_unknown')
            self.assertEqual(self.store.current(fixtures.SCOPE.slot)['step'], 'delivery_pending')
            return send(scope, payload, key)
        self.gateway.send = observe
        self.assertEqual(self.choose('join'), 'profile')

    def test_receipt_and_cached_event_confirmation_remain_atomic(self):
        self.store.db.executescript("""CREATE TRIGGER synthetic_flow_receipt_failure BEFORE UPDATE OF result ON demo_events
            BEGIN SELECT RAISE(ABORT, 'synthetic cache update failure'); END;""")
        source = self.source('join')
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.store.current(fixtures.SCOPE.slot)['step'], 'delivery_pending')
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM demo_outbox WHERE status='outcome_unknown'").fetchone()[0], 1)
        self.store.db.execute('DROP TRIGGER synthetic_flow_receipt_failure')
        self.gateway.lookup = lambda scope, key: {'status': 'accepted', 'message_id': '202', 'simulated': True}
        self.assertEqual(self.router.reconcile()['step'], 'profile')
        self.assertEqual(self.router.handle(source)[0]['status'], 'demo_step_presented')
        self.assertEqual(len(self.gateway.sent), 2)

    def test_pause_resume_restart_and_close_stay_in_demo(self):
        for action in ('join', 'use_profile', 'continue_test'):self.choose(action)
        self.assertEqual(self.choose('decline'), 'paused')
        self.assertEqual(self.choose('resume'), 'invite')
        self.choose('accept_demo')
        self.assertEqual(self.choose('close'), 'closed')
        self.assertTrue(self.router.claims(fixtures.event()))
        result = self.router.handle(self.source(text='Resetar', correlated=False))[0]
        self.assertEqual(result['status'], 'demo_reset_presented')
        self.assertEqual(self.router.start('synthetic-flow-start'), self.opening)

    def test_gateway_requires_explicit_continuation_and_exact_canonical_payload(self):
        key = demo_flow.new_key('b' * 32, 'about')
        payload = message_payload(key, continuation_enabled=True)
        fake = FakeChatwoot()
        with self.assertRaisesRegex(ValueError, 'continuation_disabled'):
            fake.gateway().send(REVIEW_SCOPE, payload, key)
        self.assertEqual(fake.calls, [])
        gateway = DemoWhatsAppGateway('https://chat.review.invalid', 'synthetic-token', scope=REVIEW_SCOPE,
                                      live_enabled=True, continuation_enabled=True, opener=fake, now=lambda: STAMP)
        with self.assertRaisesRegex(ValueError, 'approved'):
            gateway.send(REVIEW_SCOPE, {**payload, 'content': 'different'}, key)
        self.assertEqual(fake.calls, [])
        self.assertEqual(gateway.send(REVIEW_SCOPE, payload, key)['message_id'], '201')
        self.assertEqual([row[0] for row in fake.calls], ['GET', 'GET', 'POST'])

    def test_copy_has_no_urls_terms_numbers_or_oversized_buttons(self):
        for step, (text, choices) in demo_flow.TEMPLATES.items():
            with self.subTest(step=step):
                self.assertLessEqual(len(text), 500)
                self.assertNotRegex(text, r'https?://|\d|%|/cadastro')
                self.assertTrue((0 if step in demo_flow.TERMINAL_STEPS else 1) <= len(choices) <= 3)
                self.assertTrue(all(1 <= len(label) <= 20 for label in choices.values()))
                self.assertEqual(len(set(choices.values())), len(choices))


class FlowIntegration(unittest.TestCase):
    def test_benefits_button_and_text_leave_production_empty(self):
        app, repo, transport, gateway = fixtures.FlaskRouting.make_app(self)
        router = app.extensions['v5_demo_router']; router.continuation_enabled = True
        client = app.test_client(); headers = {'X-Amplify-Webhook-Token': fixtures.TOKEN}
        client.post('/demo/start', json={'request_id': 'synthetic-benefits-test'}, headers=headers)
        for number, (text, step) in enumerate((('Conhecer a Amplify', 'about'),
                ('Conhecer benefícios', 'faq_benefits'), ('quero beneficios', 'faq_benefits')), 201):
            state = router.store.current(fixtures.SCOPE.slot)
            event = fixtures.FlaskRouting.raw(self, text, parent=state['parent_id'], identifier=str(number))
            if text == 'quero beneficios': event['content_attributes'] = {}
            response = client.post('/webhook/chatwoot', headers=headers, json=event)
            self.assertEqual(response.json['step'], step)
            self.assertFalse(response.json['production_effects'])
        transport.send_reply.assert_not_called()
        with repo._connection() as db:
            for table in ('sessions', 'inbound_events', 'operations', 'outbox', 'real_jobs'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0, table)

    def test_complete_path_never_populates_production_or_calls_its_transport(self):
        app, repo, transport, gateway = fixtures.FlaskRouting.make_app(self)
        router = app.extensions['v5_demo_router']; router.continuation_enabled = True
        client = app.test_client(); headers = {'X-Amplify-Webhook-Token': fixtures.TOKEN}
        client.post('/demo/start', json={'request_id': 'synthetic-full-flow'}, headers=headers)
        for number, action in enumerate(('join', 'use_profile', 'continue_test', 'accept_demo'), 101):
            state = router.store.current(fixtures.SCOPE.slot)
            payload = message_payload(state['outbox_key'], continuation_enabled=True)
            title = ('@synthetic_profile' if action == 'use_profile' else
                     next(item['title'] for item in payload['content_attributes']['items'] if item['value'].endswith(':' + action)))
            response = client.post('/webhook/chatwoot', headers=headers,
                                   json=fixtures.FlaskRouting.raw(self, title, parent=state['parent_id'], identifier=str(number)))
            self.assertEqual(response.json['status'], 'demo_step_presented')
        self.assertEqual(router.store.current(fixtures.SCOPE.slot)['step'], 'confirmed')
        transport.send_reply.assert_not_called()
        with repo._connection() as db:
            for table in ('sessions', 'inbound_events', 'operations', 'outbox', 'real_jobs'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0, table)

    def test_other_contact_behavior_matches_with_continuation_on_or_off(self):
        results = []
        for continuation in (False, True):
            app, _, transport, _ = fixtures.FlaskRouting.make_app(self)
            app.extensions['v5_demo_router'].continuation_enabled = continuation
            response = app.test_client().post('/webhook/chatwoot',
                headers={'X-Amplify-Webhook-Token': fixtures.TOKEN},
                json=fixtures.FlaskRouting.raw(self, 'oi', owner=False))
            results.append((response.status_code, response.json, transport.send_reply.call_count))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][2], 1)
