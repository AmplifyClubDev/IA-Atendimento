from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock

import conversation
import engine
from real_journey import PUBLIC_FORM_URL, _acknowledgment_only
from test_relationship_form_chat30 import AT, POLICY, GATE, eligible, inbound, invited, settle


class ContextualAcknowledgment(TestCase):
    def turn(self, state, text, planner=None, *, at=AT):
        return conversation.handle(
            state, text, planner, now=at, real_mode=True, operation_policy=POLICY,
            relationship_check_in_form=True, same_engine_enabled=True)

    def inviting(self):
        fixture = inbound('Autorizo o convite real', eligible()['state'])
        fixture['state']['cycle']['experience_version'] = 'bia-approved-v1'
        self.assertEqual(fixture['state']['cycle']['phase'], 'inviting')
        return fixture

    def assert_unchanged_business_state(self, before, result):
        self.assertEqual(result['effects'], [])
        self.assertEqual(result['state']['effects'], before['effects'])
        for key in ('phase', 'facts', 'bia_validation', 'name_question_pending',
                    'answer_clarification', 'real_operations', 'invite_consent', 'form_url'):
            self.assertEqual(result['state']['cycle'].get(key), before['cycle'].get(key))

    def test_bare_acknowledgments_are_logged_without_reply_planner_or_operation(self):
        for phase in ('inviting', 'blocked', 'validation', 'checking', 'form'):
            for text in ('Ok', 'OK!', 'Tá bom', 'Valeu 😊', 'Ok, obrigada', 'Entendi'):
                with self.subTest(phase=phase, text=text):
                    state = deepcopy(self.inviting()['state'])
                    state['cycle'].update(phase=phase, answer_clarification='Qual ponto?',
                                          bia_validation={'version': 1, 'stage': 'gmv'})
                    planner = Mock()
                    result = self.turn(state, text, planner)
                    planner.assert_not_called()
                    self.assert_unchanged_business_state(state, result)
                    self.assertEqual(result['reply'], '')
                    self.assertEqual(result['buttons'], [])
                    self.assertEqual(result['state']['revision'], state['revision'] + 1)
                    self.assertEqual(len(result['state']['history']), len(state['history']) + 1)
                    self.assertEqual(result['state']['history'][-1]['direction'], 'inbound')

    def test_questions_and_actual_actions_are_not_acknowledgments(self):
        for text in ('Sim', 'Não', 'Pode mandar', 'Pronto', 'Ok feito', 'Ok, já aceitei',
                     'Ok, e como aceito?', 'Ok?', 'Entendi sua dúvida?', '@ok', '#ok',
                     'Ok, quero saber da comissão', 'Valeu, já ativei', 'Verificar novamente'):
            self.assertFalse(_acknowledgment_only(text, engine._normal(text)), text)
        state = invited('sent')['state']
        checked = self.turn(state, 'Já aceitei', Mock())
        self.assertEqual(checked['effects'][0]['operation'], 'relationship')
        self.assertTrue(checked['state']['cycle']['facts']['aceite_declarado'])

    def test_contextual_help_while_invite_unconfirmed_is_not_a_faq_or_a_send(self):
        for text in ('Como faço ?', 'E agora?', 'Qual é o próximo passo?', 'Como eu começo?'):
            with self.subTest(text=text):
                fixture = self.inviting()
                state = fixture['state']
                planner = Mock()
                result = self.turn(state, text, planner)
                planner.assert_not_called()
                self.assert_unchanged_business_state(state, result)
                self.assertIn('ainda não foi confirmado', result['reply'])
                self.assertNotIn('aceitar', result['reply'])
                self.assertNotIn(PUBLIC_FORM_URL, result['reply'])
                self.assertNotIn('GMV', result['reply'])
                # A real provider result can still settle the original job.
                resolved = settle(result['state'], fixture['effects'][0], 'sent')
                self.assertEqual(resolved['state']['cycle']['phase'], 'form')

    def test_actual_topic_during_invite_still_reaches_knowledge(self):
        planner = Mock(return_value={'intent': 'question', 'shared_answer': {
            'engine': 'shared-answer-v1', 'status': 'supported', 'profile_id': 'amplify-v1',
            'text': 'A parceria não tem mensalidade.'}})
        result = self.turn(self.inviting()['state'], 'Conhecer benefícios', planner)
        planner.assert_called_once()
        self.assertIn('não tem mensalidade', result['reply'])

    def test_acknowledgment_keeps_inbound_idempotency(self):
        state = self.inviting()['state']
        event = dict(provider='chatwoot', account_id='1', inbox_id='3',
                     conversation_id='26097', contact_id='3', message_id='9001',
                     sender_phone=GATE['phone'], sender_type='contact', message_type='incoming',
                     private=False, text='Ok', created_at=AT.isoformat(), source_ref='chatwoot:1:9001')
        planner = Mock()
        now = AT + timedelta(seconds=1)
        first = conversation.handle_event(state, event, GATE, planner, now=now,
            real_mode=True, operation_policy=POLICY, relationship_check_in_form=True,
            same_engine_enabled=True)
        self.assert_unchanged_business_state(state, first)
        self.assertTrue(first['accepted'])
        self.assertFalse(first['duplicate'])
        self.assertEqual(first['reply'], '')
        self.assertIn('chatwoot:1:9001', first['state']['processed_inbound'])
        self.assertEqual(first['state']['history'][-1]['source_ref'], 'chatwoot:1:9001')
        duplicate = conversation.handle_event(first['state'], event, GATE, planner, now=now,
            real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(duplicate['state']['history'], first['state']['history'])
        planner.assert_not_called()
