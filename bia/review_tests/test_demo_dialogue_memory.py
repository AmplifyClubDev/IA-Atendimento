"""Synthetic dialogue memory, acknowledgments, delivery uncertainty and isolation."""
import json
import unittest
from dataclasses import replace

import demo_flow
from demo_router import DemoRouter
import test_demo_retry as fixtures


class DialogueMemory(unittest.TestCase):
    setUp = fixtures.RetryCases.setUp
    source = fixtures.RetryCases.source
    choose = fixtures.RetryCases.choose

    def install_answerer(self, clarify=False):
        self.seen = []
        def answer(question, *, conversation):
            self.seen.append((question, conversation))
            result = {'answer': 'Lives não são obrigatórias.', 'evidence': [{'id': 'lives'}],
                      'knowledge_version': 'synthetic'}
            if clarify:
                result['answer'] += ' Sua dúvida é sobre lives?'
                result['clarification_question'] = 'Sua dúvida é sobre lives?'
            return result
        answer.accepts_dialogue_context = True
        self.router.question_answerer = answer
        return answer

    def ask(self, text):
        return self.router.handle(self.source(text=text, correlated=False))[0]

    def test_acknowledgments_without_clarification_are_idempotent_noops(self):
        self.install_answerer()
        self.ask('Como funciona?')
        before = self.store.current(self.router.scope.slot)
        sends = len(self.gateway.sent)
        for text in ('sim', 'ok', 'entendi', 'Sim!', 'obrigada'):
            event = self.source(text=text, correlated=False)
            first = self.router.handle(event)
            self.assertEqual(first[0]['status'], 'demo_acknowledged')
            self.assertEqual(self.router.handle(event), first)
        self.assertEqual(self.store.current(self.router.scope.slot), before)
        self.assertEqual(len(self.gateway.sent), sends)
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 0)

    def test_explicit_clarification_reaches_answerer_without_consent(self):
        answer = self.install_answerer(clarify=True)
        for action in ('join', 'use_profile', 'continue_test'):
            self.choose(action)
        self.ask('Sobre lives?')
        self.router = DemoRouter(self.router.scope, self.store, self.gateway, now=self.router.now,
                                 continuation_enabled=True, question_answerer=answer)
        for text in ('sim', 'ok', 'entendi'):
            self.assertEqual(self.ask(text)['step'], 'faq_context')
            self.assertEqual(self.seen[-1][0], text)
            self.assertEqual(self.seen[-1][1]['pending_clarification'], 'Sua dúvida é sobre lives?')
            self.assertEqual(self.seen[-1][1]['return_step'], 'invite')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 2)
        self.assertFalse(any(self.seen[-1][1]['operational_facts'].values()))

    def test_metadata_without_actual_question_does_not_enable_short_reply(self):
        self.install_answerer()
        self.ask('Como funciona?')
        state = self.store.current(self.router.scope.slot)
        row = self.store.db.execute('SELECT receipt FROM demo_outbox WHERE key=?', (state['outbox_key'],)).fetchone()
        receipt = json.loads(row['receipt'])
        receipt['grounded']['clarification_question'] = 'Pergunta inventada?'
        self.store.db.execute('UPDATE demo_outbox SET receipt=? WHERE key=?', (json.dumps(receipt), state['outbox_key']))
        self.assertEqual(self.ask('sim')['status'], 'demo_acknowledged')
        self.assertEqual(len(self.seen), 1)

    def test_formatted_clarification_survives_emphasis_and_emoji(self):
        from demo_support import clarification_question
        seen = []
        def answer(question, *, conversation):
            seen.append(conversation)
            text = demo_flow.format_answer('Você se refere à parceria ou à comunidade?')
            return {'answer': text, 'evidence': [{'id': 'comunidade'}], 'knowledge_version': 'synthetic',
                    'clarification_question': clarification_question(text)}
        answer.accepts_dialogue_context = True
        self.router.question_answerer = answer
        self.ask('Como funciona a saída?')
        self.assertEqual(self.ask('sim')['step'], 'faq_context')
        self.assertEqual(seen[-1]['pending_clarification'], 'Você se refere à parceria ou à comunidade?')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 0)

    def test_bounded_history_redacts_identifiers_and_retains_previous_needs(self):
        self.install_answerer()
        for i in range(9):
            self.ask('Dúvida %s: como funciona?' % i)
        self.ask('Me chamo Pessoa Sintética. E para @privado, privado@example.com, https://example.com e 123.456.789-00?')
        self.ask('E lives?')
        context = self.seen[-1][1]
        self.assertEqual(len(context['recent_dialogue']), 6)
        self.assertEqual(len(context['prior_questions']), 6)
        self.assertEqual(context['recent_dialogue'][-1]['question'], context['last_question'])
        encoded = json.dumps(context)
        for private in ('Pessoa Sintética', '@privado', 'privado@example.com', 'https://example.com', '123.456.789-00'):
            self.assertNotIn(private, encoded)
        self.assertNotIn('Dúvida 0:', str(context))
        self.assertNotIn(self.router.scope.phone, encoded)
        self.assertNotIn('contact_id', encoded)

    def test_unknown_output_excluded_until_reconciled_without_model_retry(self):
        answer = self.install_answerer(clarify=True)
        original_send = self.gateway.send
        def uncertain(scope, payload, key):
            original_send(scope, payload, key)
            raise TimeoutError()
        self.gateway.send = uncertain
        source = self.source(text='Preciso fazer lives?', correlated=False)
        result = self.router.handle(source)
        self.assertEqual(result[0]['status'], 'demo_delivery_unconfirmed')
        state = self.store.current(self.router.scope.slot)
        context = self.router._dialogue_context(state, 'delivery_pending', 'opening')
        self.assertEqual(context['recent_dialogue'], [])
        self.assertEqual(context['pending_clarification'], '')
        self.assertEqual(self.ask('sim')['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(len(self.seen), 1)
        self.router = DemoRouter(self.router.scope, self.store, self.gateway, now=self.router.now,
                                 continuation_enabled=True, question_answerer=answer)
        self.gateway.send = original_send
        self.gateway.lookup = lambda scope, key: {'status': 'accepted', 'message_id': '999', 'simulated': True}
        self.router.reconcile()
        self.assertTrue(self.router.handle(source)[0]['accepted'])
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(self.ask('sim')['step'], 'faq_context')
        self.assertEqual(self.seen[-1][1]['pending_clarification'], 'Sua dúvida é sobre lives?')

    def test_new_run_and_other_slot_have_no_prior_dialogue(self):
        answer = self.install_answerer(clarify=True)
        self.ask('Como funcionam lives?')
        before = [tuple(row) for row in self.store.db.execute('SELECT * FROM demo_outbox')]
        self.router.start('synthetic-new-run')
        self.assertEqual(self.ask('sim')['status'], 'demo_acknowledged')
        self.ask('Como funciona agora?')
        self.assertEqual(self.seen[-1][1]['recent_dialogue'], [])
        self.assertEqual(self.seen[-1][1]['pending_clarification'], '')
        other = replace(self.router.scope, contact_id='999', conversation_id='998', phone='+5511999999999')
        router = DemoRouter(other, self.store, self.gateway, now=self.router.now,
                            continuation_enabled=True, question_answerer=answer)
        router.start('synthetic-other-slot')
        state = self.store.current(other.slot)
        self.assertEqual(router._dialogue_context(state, 'opening', 'opening')['recent_dialogue'], [])
        for row in before:
            self.assertEqual(tuple(self.store.db.execute('SELECT * FROM demo_outbox WHERE key=?', (row[0],)).fetchone()), row)

    def test_closed_run_restart_discards_clarification_without_erasing_history(self):
        self.install_answerer(clarify=True)
        self.ask('Como funcionam lives?')
        old_run = self.store.current(self.router.scope.slot)['run']
        for action in ('join', 'use_profile', 'continue_test', 'accept_demo', 'close'):
            self.choose(action)
        self.assertEqual(self.ask('sim')['status'], 'demo_choice_not_current')
        self.assertEqual(self.ask('Resetar')['status'], 'demo_reset_presented')
        self.assertNotEqual(self.store.current(self.router.scope.slot)['run'], old_run)
        self.ask('Como funciona?')
        self.assertEqual(self.seen[-1][1]['recent_dialogue'], [])
        self.assertEqual(self.seen[-1][1]['pending_clarification'], '')
        self.assertGreater(self.store.db.execute('SELECT count(*) FROM demo_outbox WHERE run=?', (old_run,)).fetchone()[0], 0)

    def test_old_persisted_menu_remains_correlated_and_actionable(self):
        self.choose('join'); self.choose('use_profile')
        state = self.store.current(self.router.scope.slot)
        row = self.store.db.execute('SELECT payload FROM demo_outbox WHERE key=?', (state['outbox_key'],)).fetchone()
        payload = json.loads(row['payload'])
        payload['content_attributes']['items'][0]['title'] = 'Seguir no teste'
        old = json.dumps(payload)
        self.store.db.execute('UPDATE demo_outbox SET payload=? WHERE key=?', (old, state['outbox_key']))
        self.assertEqual(self.router.handle(self.source(text='Seguir no teste'))[0]['step'], 'invite')
        self.assertEqual(self.store.db.execute('SELECT payload FROM demo_outbox WHERE key=?', (state['outbox_key'],)).fetchone()[0], old)

    def test_copy_never_claims_actual_invite_or_membership(self):
        self.assertIn('Nenhum convite real foi enviado', demo_flow.TEMPLATES['invite'][0])
        self.assertIn('Não houve aceite comercial nem vínculo real', demo_flow.TEMPLATES['confirmed'][0])
        self.assertIn('Seu perfil não foi consultado', demo_flow.TEMPLATES['conditions'][0])
        for step in ('profile', 'member', 'conditions', 'invite', 'confirmed', 'paused'):
            self.assertNotIn('teste', demo_flow.TEMPLATES[step][0].casefold())
