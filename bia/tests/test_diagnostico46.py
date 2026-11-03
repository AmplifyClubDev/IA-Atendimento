"""Release 46: visibilidade. Cada conversa olhada tem um motivo fixo; GET /diagnostico/conversa/<id> mostra o estado.

56938: às 22:37 de 02/11 um atendente mandou à mão a 1ª resposta (mensagem 317155, delivered) e uma nota privada,
sem se atribuir a conversa. Quando o lead responder, a Bia segue normalmente.
"""
from datetime import timedelta
import re
import unittest

import retomada
import test_reprocesso44 as base44
import test_reprocesso45 as base45
from test_regressao41 import AD

TOKEN = 'w' * 40


class ReasonListTests(unittest.TestCase):
    def test_a_reason_outside_the_list_fails(self):
        for reason in ('pulado', '', None, 'erro_envio:', 'erro_envio:Com Espaco'):
            with self.subTest(reason=reason):
                self.assertFalse(retomada.valid_reason(reason))
                with self.assertRaises(ValueError):
                    retomada.Decisoes().record('pos_pausa', '1', reason, base44.datetime.now(base44.timezone.utc))
        for reason in sorted(retomada.REASONS) + ['erro_envio:chatwoot_rejected']:
            self.assertTrue(retomada.valid_reason(reason), reason)


class Situation56938(base44.Unanswered):
    def setUp(self):
        super().setUp()
        retomada.DECISOES.__init__()  # o registro é da execução; cada teste começa vazio

    def history_with_human_reply(self):
        """05:42 lead + aviso de manutenção; 22:37 atendente (sem atribuição) + nota privada."""
        human_at = self.now - timedelta(minutes=10)  # 22:37
        return [self.lead_message(317100, 'Oi! Encontrei a Amplify através do anúncio e quero saber mais', self.arrived),
                self.maintenance(317101, self.arrived + timedelta(seconds=2)),
                {'id': 317155, 'message_type': 1, 'private': False, 'content': 'Oi! Aqui é a equipe da Amplify…',
                 'content_attributes': {}, 'sender': {'id': 7, 'type': 'user'}, 'created_at': human_at.timestamp()},
                {'id': 317156, 'message_type': 1, 'private': True, 'content': 'Respondido à mão (Bia sem resposta).',
                 'content_attributes': {}, 'sender': {'id': 7, 'type': 'user'}, 'created_at': human_at.timestamp() + 5}]

    def route_chatwoot(self, messages, *, assignee=None, can_reply=True):
        listing = self.chatwoot.listing

        def http(*, method, url, headers, timeout, json_body=None):
            assert method == 'GET'
            if '/conversations?' in url:
                return {'data': {'payload': list(listing) if 'page=1' in url else []}}
            if url.endswith('/messages'):
                return {'payload': list(messages)}
            return {'id': int(self.LEAD['conversation']), 'status': 'open', 'can_reply': can_reply,
                    'meta': {'sender': {'id': int(self.LEAD['contact']), 'phone_number': self.LEAD['phone']},
                             'assignee': assignee}}
        self.chatwoot.http = http

    def diagnose(self, token=TOKEN):
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        response = self.app.test_client().get('/diagnostico/conversa/' + self.LEAD['conversation'], headers=headers)
        return response.status_code, response.get_json()


class Lead56938Tests(Situation56938, base44.Lead56938Tests):
    def test_after_the_manual_reply_the_scan_says_why_and_the_next_message_is_answered(self):
        messages = self.history_with_human_reply()
        self.chatwoot_shows(self.LEAD, messages)
        self.route_chatwoot(messages)
        outcome = self.pos_pausa()
        self.assertEqual(outcome['status'], 'idle')
        self.assertEqual(outcome['puladas_por_motivo'], {'ja_respondida_no_chatwoot': 1})
        self.assertEqual(self.texts(self.LEAD), [])
        # O lead responde: a Bia segue normalmente (atendente não atribuído não bloqueia).
        self.say(self.LEAD, 'Oi, obrigada! Quero sim')
        texts = self.texts(self.LEAD)
        self.assertEqual(len(texts), 1)
        self.assertNotIn('Desculpa a demora', texts[0])
        status, body = self.diagnose()
        self.assertEqual(status, 200)
        self.assertEqual(body['decisoes']['pos_pausa']['motivo'], 'ja_respondida_no_chatwoot')
        self.assertTrue(body['atendimento']['existe'])

    def test_assigned_to_the_agent_the_bia_stays_out_and_says_so(self):
        messages = self.history_with_human_reply()
        messages.append(self.lead_message(317200, 'Oi, obrigada! Quero sim', self.now - timedelta(minutes=5)))
        self.chatwoot_shows(self.LEAD, messages)
        self.route_chatwoot(messages, assignee={'id': 7, 'type': 'user'})
        self.app.extensions['v5_pos_pausa'].guard = lambda event: {'allowed': False, 'reason': 'human_assignee_blocked'}
        outcome = self.pos_pausa()
        self.assertEqual(outcome['puladas_por_motivo'], {'controle_humano': 1})
        self.assertEqual(self.diagnose()[1]['decisoes']['pos_pausa'],
                         {'motivo': 'controle_humano', 'detalhe': 'human_assignee_blocked',
                          'em': self.diagnose()[1]['decisoes']['pos_pausa']['em']})

    def test_endpoint_shows_the_state_and_writes_nothing(self):
        messages = [self.lead_message(569380, 'Oi! Encontrei a Amplify através do anúncio', self.arrived),
                    self.maintenance(569381, self.arrived + timedelta(seconds=2))]
        self.chatwoot_shows(self.LEAD, messages)
        self.route_chatwoot(messages)
        self.assertEqual(self.diagnose(token=None)[0], 401)
        self.assertEqual(self.diagnose(token='x' * 40)[0], 401)
        with self.repo._connection() as db:
            before = [db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                      for table in ('sessions', 'inbound_events', 'operations', 'outbox')]
        status, body = self.diagnose()
        with self.repo._connection() as db:
            after = [db.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                     for table in ('sessions', 'inbound_events', 'operations', 'outbox')]
        self.assertEqual((status, before), (200, after))
        self.assertEqual(body['chatwoot']['piloto'], {'no_piloto': True, 'variacao': 'igual', 'final_do_telefone': '4946'})
        self.assertEqual(body['chatwoot']['ultima_do_lead']['id'], 569380)
        self.assertEqual([item['tipo'] for item in body['chatwoot']['depois_dela']], ['automatica'])
        self.assertFalse(body['atendimento']['existe'])
        self.assertEqual(body['decisoes'], {})  # nenhuma varredura olhou: a pós-pausa não chegou a ela
        self.assertNotIn(self.LEAD['phone'], str(body))

    test_registered_message_without_answer_is_answered_once = None
    test_bia_reply_after_it_is_never_duplicated = None
    test_human_reply_after_it_is_never_reprocessed = None
    test_a_reply_already_accepted_is_never_reprocessed = None
    test_too_recent_waits_3_minutes = None


class Counters56935Tests(base45.Cristiane56935Tests):
    def test_respondidas_counts_the_reprocessed_answer(self):
        base45.Cristiane56935Tests.test_processed_and_not_sent_gets_the_access_answer_once(self)
        status = self.app.extensions['v5_pos_pausa'].status()
        self.assertEqual((status['respondidas'], status['reprocessadas']), (1, 1))
        self.assertIn('puladas_por_motivo', status)

    test_processed_and_not_sent_gets_the_access_answer_once = None


class EveryScanHasAReasonTests(Situation56938, base44.Lead56938Tests):
    """Cada conversa olhada nas três varreduras recebe um motivo da lista (Decisoes.record recusa outro)."""

    def test_every_looked_conversation_has_a_listed_reason(self):
        self.say(self.LEAD, AD)
        self.say(self.LEAD, self.LEAD['handle'])
        self.drain()
        messages = [self.lead_message(569380, 'Oi', self.arrived)]
        self.chatwoot_shows(self.LEAD, messages)
        self.route_chatwoot(messages)
        self.pos_pausa()
        self.run_scan()
        retomada_scan = self.app.extensions['v5_retomada']
        retomada_scan.next_scan_at = None
        retomada_scan.tick()
        decisions = retomada.DECISOES.for_conversation(self.LEAD['conversation'])
        self.assertEqual(set(decisions), {'pos_pausa', 'reconferencia', 'retomada'})
        for scan, entry in decisions.items():
            self.assertTrue(retomada.valid_reason(entry['motivo']), (scan, entry))
            self.assertTrue(re.fullmatch(r'\d{4}-\d\d-\d\dT.*', entry['em']))

    test_registered_message_without_answer_is_answered_once = None
    test_bia_reply_after_it_is_never_duplicated = None
    test_human_reply_after_it_is_never_reprocessed = None
    test_a_reply_already_accepted_is_never_reprocessed = None
    test_too_recent_waits_3_minutes = None


if __name__ == '__main__':
    unittest.main()
