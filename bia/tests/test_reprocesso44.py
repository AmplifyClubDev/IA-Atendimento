"""Release 44: a mensagem do lead já registrada, sem resposta da Bia depois dela no Chatwoot, é reprocessada uma vez.

- 56938: lead às 05:42 e o aviso de manutenção da regra 3; o registro ficou da tentativa que falhou (42, 19:47);
- 56935 (Cristiane): "Já aceitei" e "missões" com resultado incerto na 40.2; responde no modo acesso;
- mensagem com resposta da Bia ou de um atendente depois dela: nada é reprocessado nem duplicado.
"""
from datetime import datetime, timedelta, timezone
import unittest

import conversao
import test_convite42 as base
import test_conversas0211 as cristiane
from test_regressao41 import AD


class Unanswered:
    """O Chatwoot da pós-pausa, montado com as mensagens reais da conversa."""

    def chatwoot_shows(self, lead, messages):
        conv = int(lead['conversation'])
        latest = messages[-1]
        self.chatwoot.listing = [{'id': conv, 'inbox_id': 3, 'last_activity_at': latest['created_at'],
                                  'meta': {'sender': {'id': int(lead['contact']), 'phone_number': lead['phone']}},
                                  'last_non_activity_message': dict(latest)}]
        self.chatwoot.messages = messages

    def lead_message(self, message_id, text, at):
        return {'id': message_id, 'message_type': 0, 'private': False, 'content': text, 'created_at': at.timestamp()}

    def maintenance(self, message_id, at):
        return {'id': message_id, 'message_type': 1, 'private': False, 'content': 'Estamos em manutenção',
                'content_attributes': {'automation_rule_id': 3}, 'created_at': at.timestamp()}

    def registered_without_answer(self, message_id, conv):
        """Como a tentativa que falhou deixou: o evento registrado, sem resposta e sem estado salvo."""
        key = 'chatwoot:1:' + str(message_id)
        self.assertTrue(self.repo.reserve_event(key, conv, 'tentativa-que-falhou')['reserved'])
        self.repo.finish_event(key, 'outcome_unknown')
        return key

    def pos_pausa(self):
        subject = self.app.extensions['v5_pos_pausa']
        subject.next_scan_at = None
        return subject.tick()


class Lead56938Tests(Unanswered, base.GabinaresseServerTests):
    LEAD = {'conversation': '56938', 'contact': '9938', 'phone': '+558396914946', 'handle': '@lead56938'}

    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)
        self.arrived = self.now - timedelta(hours=15, minutes=5)  # 05:42 → 20:47

    def test_registered_message_without_answer_is_answered_once(self):
        conv = 'chatwoot:1:56938'
        key = self.registered_without_answer(569380, conv)
        self.chatwoot_shows(self.LEAD, [self.lead_message(569380, 'Oi! Encontrei a Amplify através do anúncio e quero saber mais',
                                                          self.arrived),
                                        self.maintenance(569381, self.arrived + timedelta(seconds=2))])
        self.assertEqual(self.pos_pausa(), {'status': 'resumed', 'result': 'completed'})
        texts = self.texts(self.LEAD)
        self.assertEqual(len(texts), 1)
        self.assertIn('Desculpa a demora', texts[0])
        state = self.repo.load_session(conv)
        self.assertEqual(state['reprocessed'][key]['previous']['status'], 'outcome_unknown')  # o registro
        self.assertEqual(self.repo.event(key)['status'], 'completed')
        # O Chatwoot de teste não mostra a resposta; mesmo assim, nunca uma 2ª vez.
        self.assertEqual(self.pos_pausa()['status'], 'idle')
        self.assertEqual(len(self.texts(self.LEAD)), 1)

    def test_bia_reply_after_it_is_never_duplicated(self):
        self.registered_without_answer(569380, 'chatwoot:1:56938')
        reply = {'id': 569382, 'message_type': 1, 'private': False, 'content': 'Oi! Aqui é a Bia',
                 'content_attributes': {'amplify_actor': 'v5_rehearsal'}, 'sender': {'id': 1},
                 'created_at': (self.arrived + timedelta(minutes=1)).timestamp()}
        self.chatwoot_shows(self.LEAD, [self.lead_message(569380, 'Oi', self.arrived), reply])
        self.assertEqual(self.pos_pausa()['status'], 'idle')
        self.assertEqual(self.texts(self.LEAD), [])

    def test_human_reply_after_it_is_never_reprocessed(self):
        self.registered_without_answer(569380, 'chatwoot:1:56938')
        human = {'id': 569382, 'message_type': 1, 'private': False, 'content': 'Oi, aqui é a Ana da Amplify',
                 'content_attributes': {}, 'sender': {'id': 7, 'type': 'user'},
                 'created_at': (self.arrived + timedelta(minutes=1)).timestamp()}
        self.chatwoot_shows(self.LEAD, [self.lead_message(569380, 'Oi', self.arrived), human])
        self.assertEqual(self.pos_pausa()['status'], 'idle')
        self.assertEqual(self.texts(self.LEAD), [])

    def test_a_reply_already_accepted_is_never_reprocessed(self):
        conv = 'chatwoot:1:56938'
        key = self.registered_without_answer(569380, conv)
        self.repo.prepare_reply(key, conv, {}, key + ':reply', {'text': 'Oi', 'buttons': []})
        self.repo.finish_outbox(key + ':reply', 'accepted', {'status': 'accepted', 'message_id': '1'})
        self.chatwoot_shows(self.LEAD, [self.lead_message(569380, 'Oi', self.arrived),
                                        self.maintenance(569381, self.arrived + timedelta(seconds=2))])
        self.pos_pausa()
        self.assertEqual(self.texts(self.LEAD), [])  # o botão do WhatsApp só deixa nota privada no Chatwoot

    def test_too_recent_waits_3_minutes(self):
        self.registered_without_answer(569380, 'chatwoot:1:56938')
        self.chatwoot_shows(self.LEAD, [self.lead_message(569380, 'Oi', self.now - timedelta(minutes=2, seconds=30))])
        self.assertEqual(self.pos_pausa()['status'], 'idle')

    test_resent_once_then_followed_until_linked = None
    test_registered_lead_is_never_read = None


class Cristiane56935Tests(Unanswered, cristiane.CristianeServerTests):
    """Acesso liberado às 08:21; "Já aceitei" às 10:27 e "missões" às 12:33 ficaram sem resposta na 40.2."""

    def test_unanswered_messages_get_the_access_answer(self):
        lead, conv = self.LEAD, 'chatwoot:1:56935'
        self.say(lead, AD)
        self.say(lead, lead['handle'])
        self.drain()
        self.say(lead, 'Pode mandar')
        self.drain()
        state = self.repo.load_session(conv)
        self.gateway.closed.add(state['cycle']['id'])
        self.gateway.situacao = 'confirmado'
        now = datetime.now(timezone.utc)
        self.registered_without_answer(80001, conv)
        self.registered_without_answer(80002, conv)
        self.chatwoot_shows(lead, [self.lead_message(80001, 'Já aceitei', now - timedelta(hours=2, minutes=6)),
                                   self.lead_message(80002, 'Quando vou ter as minhas primeiras missões?', now - timedelta(minutes=10))])
        before = len(self.texts(lead))
        self.assertEqual(self.pos_pausa(), {'status': 'resumed', 'result': 'completed'})
        answers = self.texts(lead)[before:]
        self.assertEqual(len(answers), 1)
        self.assertIn(conversao.MISSIONS, answers[0])
        self.assertTrue(self.repo.load_session(conv)['cycle'].get('acesso_liberado'))
        self.assertEqual(self.pos_pausa()['status'], 'idle')

    test_after_the_form_the_next_messages_are_answered = None
    test_emy_and_thaina_are_rechecked_once_each_when_the_bridge_returns = None
    test_bridge_flapping_during_the_retry_stays_silent_and_waits_ten_minutes = None
    test_switch_and_status = None


if __name__ == '__main__':
    unittest.main()
