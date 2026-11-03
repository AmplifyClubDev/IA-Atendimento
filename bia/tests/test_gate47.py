"""Release 47: V5_GATE_MODE. 'lista' é a 46; 'todos' atende toda a caixa 3, com as exclusões lidas no Chatwoot."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

import config
import contracts
import retomada
import server
from real_operations import chatwoot_control_guard, gate_exclusion
import test_reprocesso44 as base44
from test_regressao41 import AD

TEST_PHONE = '+5547991154859'
GATE = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3', 'phone': TEST_PHONE}


class ConfigTests(unittest.TestCase):
    def settings(self, mode=None):
        env = {'V5_ENABLED': 'true', 'V5_TEST_PHONE': TEST_PHONE, 'CHATWOOT_ACCOUNT_ID': '1', 'CHATWOOT_INBOX_ID': '3'}
        if mode is not None:
            env['V5_GATE_MODE'] = mode
        return config.load_settings(env)

    def test_default_is_the_list(self):
        self.assertEqual(self.settings()['gate']['mode'], 'lista')
        self.assertEqual(self.settings('todos')['gate']['mode'], 'todos')
        self.assertIn('gate_mode_invalid', self.settings('tudo')['readiness_issues'])
        self.assertEqual(self.settings('tudo')['gate']['mode'], 'lista')


class GateTests(unittest.TestCase):
    def test_list_mode_is_the_46(self):
        gate = {**GATE, 'phones': ('+5547991154859', '+558396914946')}
        self.assertEqual(contracts.pilot_phone(gate, '+558396914946'), '+558396914946')
        self.assertIsNone(contracts.pilot_phone(gate, '+5511912345678'))
        self.assertIsNone(gate_exclusion(gate, {'sender_phone': '+558396914946'}, {'labels': ['Renovacao de contrato']}))

    def test_all_mode_takes_any_valid_phone_and_never_a_group_or_empty(self):
        gate = {**GATE, 'mode': 'todos', 'phones': ('+5547991154859',)}
        self.assertEqual(contracts.pilot_phone(gate, '+55 11 91234-5678'), '+5511912345678')
        for value in (None, '', '120363025555555555@g.us', 'Phone number is not available'):
            self.assertIsNone(contracts.pilot_phone(gate, value), value)

    def test_renewal_label_is_excluded_except_the_test_number(self):
        gate = {**GATE, 'mode': 'todos'}
        for label in ('Renovacao de contrato', 'Renovação de contrato', 'renovacao_de_contrato'):
            self.assertEqual(gate_exclusion(gate, {'sender_phone': '+5511912345678'}, {'labels': [label]}),
                             'fora_do_gate:renovacao_de_contrato', label)
        self.assertIsNone(gate_exclusion(gate, {'sender_phone': TEST_PHONE}, {'labels': ['Renovacao de contrato']}))
        self.assertIsNone(gate_exclusion(gate, {'sender_phone': '+5511912345678'}, {'labels': ['anuncio']}))

    def test_guard_reads_the_label_and_the_assignee(self):
        gate = {**GATE, 'mode': 'todos'}
        event = {'provider': 'chatwoot', 'event': 'message_created', 'conversation_id': '57001', 'account_id': '1',
                 'inbox_id': '3', 'contact_id': '9001', 'message_id': '1', 'sender_phone': '+5511912345678',
                 'sender_type': 'contact', 'message_type': 'incoming', 'private': False, 'text': 'oi'}

        def transport(labels=(), assignee=None):
            detail = {'id': 57001, 'account_id': 1, 'inbox_id': 3, 'status': 'open', 'can_reply': True,
                      'labels': list(labels), 'custom_attributes': {},
                      'meta': {'sender': {'id': 9001, 'phone_number': '+5511912345678'}, 'assignee': assignee}}
            return type('T', (), {'token': 't', 'http': staticmethod(lambda **_: detail),
                                  '_conversation_url': staticmethod(lambda e: 'https://chatwoot.invalid/c/57001')})()
        self.assertEqual(chatwoot_control_guard(transport(), gate, event)['allowed'], True)
        renewal = chatwoot_control_guard(transport(labels=['Renovacao de contrato']), gate, event)
        self.assertEqual(retomada.guard_reason(renewal, gate), 'fora_do_gate:renovacao_de_contrato')
        assigned = chatwoot_control_guard(transport(assignee={'id': 7, 'type': 'user'}), gate, event)
        self.assertEqual(retomada.guard_reason(assigned, gate), 'fora_do_gate:responsavel_humano')
        self.assertEqual(retomada.guard_reason(assigned, GATE), 'controle_humano')  # modo lista: como na 46


class AllModeServerTests(base44.Unanswered, base44.base.GabinaresseServerTests):
    """Modo 'todos' pelo servidor inteiro: lead novo, fora da lista, sem a manutenção."""

    LEAD = {'conversation': '57001', 'contact': '9001', 'phone': '+5511912345678', 'handle': '@leadnovo'}
    decisions = {}

    def setUp(self):
        test = self
        original = server.create_app

        def create_app(settings, *args, **kwargs):
            settings['gate']['mode'] = 'todos'
            kwargs['real_guard'] = lambda event: test.decisions.get(str(event.get('conversation_id')), {'allowed': True})
            return original(settings, *args, **kwargs)
        server.create_app = create_app
        self.addCleanup(setattr, server, 'create_app', original)
        retomada.DECISOES.__init__()
        self.decisions = {}
        super().setUp()
        self.now = datetime.now(timezone.utc)

    def webhook(self, lead, text):
        self.message_id += 1
        payload = {'event': 'message_created', 'id': self.message_id, 'content': text, 'message_type': 'incoming',
                   'private': False, 'created_at': self.now.isoformat(), 'account': {'id': 1},
                   'inbox': {'id': 3}, 'conversation': {'id': int(lead['conversation']), 'contact_inbox': {'contact_id': int(lead['contact'])}},
                   'sender': {'id': int(lead['contact']), 'phone_number': lead['phone'], 'type': 'contact'}}
        return self.app.test_client().post('/webhook/chatwoot?token=' + 'w' * 40, json=payload)

    def test_a_new_lead_outside_the_list_is_answered(self):
        self.say(self.LEAD, AD)
        texts = self.texts(self.LEAD)
        self.assertEqual(len(texts), 1)
        self.assertTrue(texts[0].startswith('Oi! Aqui é a Bia'))

    def test_renewal_and_assigned_conversations_stay_silent_with_the_reason(self):
        for reason, guard in (('fora_do_gate:renovacao_de_contrato', {'allowed': False, 'reason': 'fora_do_gate:renovacao_de_contrato'}),
                              ('fora_do_gate:responsavel_humano', {'allowed': False, 'reason': 'human_assignee_blocked'})):
            with self.subTest(reason):
                retomada.DECISOES.__init__()
                self.decisions[self.LEAD['conversation']] = guard
                response = self.webhook(self.LEAD, 'Oi, quero renovar meu contrato')
                self.assertEqual(response.get_json().get('reason'), reason)
                self.assertEqual(self.texts(self.LEAD), [])
                self.assertEqual(retomada.DECISOES.for_conversation(self.LEAD['conversation'])['entrada']['motivo'], reason)
                self.assertIsNone(self.repo.event('chatwoot:1:' + str(self.message_id)))  # nada registrado

    def test_the_test_number_is_always_in(self):
        self.decisions['26097'] = {'allowed': False, 'reason': 'fora_do_gate:renovacao_de_contrato'}
        lead = {'conversation': '26097', 'contact': '3', 'phone': TEST_PHONE, 'handle': '@teste'}
        self.assertNotEqual(self.webhook(lead, 'oi').get_json().get('reason'), 'fora_do_gate:renovacao_de_contrato')

    def test_pos_pausa_answers_a_lead_who_only_got_maintenance(self):
        arrived = self.now - timedelta(hours=3)
        self.chatwoot_shows(self.LEAD, [self.lead_message(57100, 'Oi! Encontrei a Amplify através do anúncio', arrived),
                                        self.maintenance(57101, arrived + timedelta(seconds=2))])
        outcome = self.pos_pausa()
        self.assertEqual((outcome['status'], outcome['motivo']), ('resumed', 'respondida'))
        self.assertEqual(len(self.texts(self.LEAD)), 1)

    def test_pos_pausa_records_why_it_skipped(self):
        arrived = self.now - timedelta(hours=3)
        self.chatwoot_shows({**self.LEAD, 'phone': ''}, [self.lead_message(57100, 'Oi', arrived)])
        outcome = self.pos_pausa()
        self.assertEqual(outcome['puladas_por_motivo'], {'fora_do_gate:sem_telefone': 1})
        self.decisions[self.LEAD['conversation']] = {'allowed': False, 'reason': 'fora_do_gate:renovacao_de_contrato'}
        self.chatwoot_shows(self.LEAD, [self.lead_message(57102, 'Oi', arrived + timedelta(minutes=1))])
        self.assertEqual(self.pos_pausa()['puladas_por_motivo'], {'fora_do_gate:renovacao_de_contrato': 1})
        for entry in retomada.DECISOES.for_conversation(self.LEAD['conversation']).values():
            self.assertTrue(retomada.valid_reason(entry['motivo']))

    test_resent_once_then_followed_until_linked = None
    test_registered_lead_is_never_read = None


class ListScriptTests(unittest.TestCase):
    """O script de leitura antes de ligar 'todos': só GET, contagem e fila de 1 por minuto."""

    def test_lists_who_would_receive_and_why_the_others_not(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        import listar_entrada_todos as script
        now = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)

        def message(mid, kind, at, **extra):
            return {'id': mid, 'message_type': kind, 'private': False, 'content': 'Oi' if kind == 0 else 'Estamos em manutenção',
                    'created_at': at.timestamp(), **extra}
        lead_at = now - timedelta(hours=5)
        conversations = {
            100: ([message(1000, 0, lead_at), message(1001, 1, lead_at, content_attributes={'automation_rule_id': 3})], [], None),
            101: ([message(1010, 0, lead_at)], ['Renovacao de contrato'], None),
            102: ([message(1020, 0, lead_at)], [], {'id': 7}),
            103: ([message(1030, 0, lead_at), message(1031, 1, lead_at, sender={'id': 7})], [], None),
        }
        listing = [{'id': cid, 'inbox_id': 3, 'labels': labels, 'last_activity_at': int(msgs[-1]['created_at']),
                    'last_non_activity_message': msgs[-1],
                    'meta': {'sender': {'id': cid, 'phone_number': '+55119123456' + str(cid)[-2:]}, 'assignee': assignee}}
                   for cid, (msgs, labels, assignee) in conversations.items()]
        methods = []

        def http(self, *, method, url, headers, timeout, json_body=None):
            methods.append(method)
            assert method == 'GET'
            if '/conversations?' in url:
                return {'data': {'payload': listing if 'page=1' in url else []}}
            return {'payload': conversations[int(url.rsplit('/', 2)[-2])][0]}
        out = io.StringIO()
        with mock.patch.object(script.ReadOnlyChatwoot, 'http', http), \
                mock.patch.dict('os.environ', {'CHATWOOT_BASE_URL': 'https://chatwoot.invalid', 'CHATWOOT_API_TOKEN': 't'}), \
                mock.patch.object(sys, 'argv', ['x', now.isoformat()]), mock.patch('sys.stdout', out):
            script.main()
        report = json.loads(out.getvalue())
        self.assertEqual(report['receberiam'], 1)
        self.assertEqual([row['conversa'] for row in report['lista']], [100])
        self.assertEqual(report['fora_por_motivo'], {'fora_do_gate:renovacao_de_contrato': 1, 'fora_do_gate:responsavel_humano': 1,
                                                     'ja_respondida_no_chatwoot': 1})
        self.assertEqual(set(methods), {'GET'})


if __name__ == '__main__':
    unittest.main()
