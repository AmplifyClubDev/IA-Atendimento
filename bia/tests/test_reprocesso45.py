"""Release 45: a decisão é pelo Chatwoot, mesmo com a mensagem já marcada como processada.

Estado real reproduzido: a Bia processou a mensagem, salvou o atendimento (processed_inbound) e a resposta não saiu
(o envio falhou). A 44 descartava esses casos pelo filtro "newest"; às 22:01 de 02/11 a pós-pausa ficou idle.
"""
from datetime import datetime, timedelta, timezone
import unittest

import conversao
import real_journey as journey
import test_reprocesso44 as base44
from test_regressao41 import AD


class SendFails:
    def failing_send(self):
        """O envio da resposta falha (como ficou em produção) e depois volta a funcionar."""
        original = self.chatwoot.send_reply
        self.chatwoot.send_reply = lambda event, text, buttons, key, **_: {'status': 'failed', 'reason': 'chatwoot_rejected'}
        return lambda: setattr(self.chatwoot, 'send_reply', original)

    def inbound(self, lead, message_id, text, created):
        event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': '1', 'inbox_id': '3',
                 'conversation_id': lead['conversation'], 'contact_id': lead['contact'], 'message_id': str(message_id),
                 'sender_phone': lead['phone'], 'sender_type': 'contact', 'message_type': 'incoming', 'private': False,
                 'text': text, 'created_at': created.isoformat(), 'source_ref': 'chatwoot:1:' + str(message_id)}
        with self.app.app_context():
            return self.app.extensions['v5_process_inbound'](event)


class Lead56938Tests(SendFails, base44.Lead56938Tests):
    def test_processed_and_not_sent_is_answered_once_with_the_stored_reply(self):
        conv, key = 'chatwoot:1:56938', 'chatwoot:1:569380'
        restore = self.failing_send()
        self.inbound(self.LEAD, 569380, 'Oi! Encontrei a Amplify através do anúncio e quero saber mais', self.arrived)
        restore()
        state = self.repo.load_session(conv)
        self.assertIn(key, state['processed_inbound'])  # o estado real: processada e salva
        self.assertEqual([row['status'] for row in self.repo.outbox(key)], ['failed'])
        self.assertEqual(self.texts(self.LEAD), [])
        self.chatwoot_shows(self.LEAD, [self.lead_message(569380, 'Oi! Encontrei a Amplify através do anúncio', self.arrived),
                                        self.maintenance(569381, self.arrived + timedelta(seconds=2))])
        status = self.app.extensions['v5_pos_pausa']
        self.assertEqual(self.pos_pausa()['status'], 'resumed')
        texts = self.texts(self.LEAD)
        self.assertEqual(len(texts), 1)
        self.assertTrue(texts[0].startswith(conversao.OPENING + ' ' + journey._RESUME_SORRY))
        self.assertEqual(self.repo.load_session(conv)['reprocessed'][key]['mode'], 'resend_stored_reply')
        self.assertEqual(self.pos_pausa()['status'], 'idle')
        self.assertEqual(len(self.texts(self.LEAD)), 1)
        self.assertEqual((status.status()['reprocessadas'], status.status()['horario_silencioso']), (1, False))

    def test_night_is_not_quiet_for_an_answer(self):
        # 23:30 de Brasília: o lead escreveu, então é resposta, não lembrete.
        restore = self.failing_send()
        self.inbound(self.LEAD, 569380, 'Oi', self.arrived)
        restore()
        self.chatwoot_shows(self.LEAD, [self.lead_message(569380, 'Oi', self.arrived)])
        subject = self.app.extensions['v5_pos_pausa']
        subject.now = lambda: datetime(2026, 11, 3, 2, 30, tzinfo=timezone.utc)
        self.arrived = datetime(2026, 11, 2, 8, 42, tzinfo=timezone.utc)
        self.chatwoot_shows(self.LEAD, [self.lead_message(569380, 'Oi', self.arrived)])
        self.assertEqual(self.pos_pausa()['status'], 'resumed')
        self.assertEqual(len(self.texts(self.LEAD)), 1)

    def test_processed_with_nothing_stored_is_processed_again(self):
        conv, key = 'chatwoot:1:56938', 'chatwoot:1:569380'
        self.repo.save_session(conv, {'processed_inbound': [key]})  # resposta suprimida: nada guardado para enviar
        self.registered_without_answer(569380, conv)
        self.chatwoot_shows(self.LEAD, [self.lead_message(569380, 'Oi! Encontrei a Amplify através do anúncio', self.arrived)])
        self.assertEqual(self.pos_pausa()['status'], 'resumed')
        self.assertEqual(len(self.texts(self.LEAD)), 1)
        self.assertEqual(self.repo.load_session(conv)['reprocessed'][key]['mode'], 'process_again')


class Cristiane56935Tests(SendFails, base44.Cristiane56935Tests):
    def test_processed_and_not_sent_gets_the_access_answer_once(self):
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
        restore = self.failing_send()
        self.inbound(lead, 80001, 'Já aceitei', now - timedelta(hours=2))
        self.inbound(lead, 80002, 'Quando vou ter as minhas primeiras missões?', now - timedelta(minutes=10))
        restore()
        state = self.repo.load_session(conv)
        self.assertIn('chatwoot:1:80002', state['processed_inbound'])
        before = len(self.texts(lead))
        self.chatwoot_shows(lead, [self.lead_message(80001, 'Já aceitei', now - timedelta(hours=2)),
                                   self.lead_message(80002, 'Quando vou ter as minhas primeiras missões?', now - timedelta(minutes=10))])
        self.assertEqual(self.pos_pausa()['status'], 'resumed')
        answers = self.texts(lead)[before:]
        self.assertEqual(len(answers), 1)
        self.assertIn(conversao.REGISTRATION_MISSIONS + '\n\n' + conversao.REGISTRATION_CONFIRMED, answers[0])
        self.assertEqual(self.pos_pausa()['status'], 'idle')

    test_unanswered_messages_get_the_access_answer = None


for cls in (Lead56938Tests,):
    for name in [n for n in dir(base44.Lead56938Tests) if n.startswith('test_')]:
        setattr(cls, name, None)


if __name__ == '__main__':
    unittest.main()

