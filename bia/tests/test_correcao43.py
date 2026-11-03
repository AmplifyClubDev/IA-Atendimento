"""Release 43: os 4 casos de 02/11 com a 42 no ar (deploy 6268c308) e a regra "nenhum lead sem resposta em silêncio".

- 56932 @viralstoresbr: "Já aceitei" às 14:42, a Bia respondeu "Vou conferir" e nada mais; às 19:55 a lista dava linked;
- 56933 @gabinaresse: às 18:16 a 42 disse "Seu convite foi enviado agora" e às 19:55 a lista dava not_found;
  às 18:27 saiu o lembrete "Seu convite continua no TikTok";
- 56938 (+558396914946, sem o 9): escreveu às 05:42, entrou na lista às 19:47 e a pós-pausa não respondeu;
- 32922: "Não tenho interesse" às 13:52, sem resposta.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

import contracts
import conversao
import real_journey as journey
import retomada
from repository import Repository
import test_convite42 as base
from test_convite42 import LINKED, LIST, PENDING, TEXT_1, TEXT_2, invite_unknown, operations, outbound
from test_regressao41 import AD, eligible, invited, say, settle
from test_relationship_form_chat30 import AT

URL = journey.PUBLIC_FORM_URL


class Viralstoresbr56932Tests(base.DaytimeTests):
    """O aviso do vínculo não chegou: a Bia lê a lista de novo e manda o texto 2."""

    def accepted(self):
        state = invited('@viralstoresbr')['state']
        turn = say('Já aceitei', state, AT + timedelta(minutes=5))
        return settle(turn['state'], turn['effects'][0], 'linked', AT + timedelta(minutes=5), evidence=dict(LINKED))

    def test_linked_reply_marks_the_notice_to_be_confirmed(self):
        linked = self.accepted()
        self.assertIn(URL, linked['reply'])
        self.assertEqual(linked['state']['cycle']['linked_notice']['delivered'], None)

    def test_undelivered_notice_is_read_again_and_sent_as_text_2(self):
        state = self.accepted()['state']
        state['cycle']['linked_notice']['delivered'] = False  # o servidor marca quando o envio não foi aceito
        at = AT + timedelta(hours=3)
        read = journey.agency_read_effect(state, at)
        self.assertEqual(read['payload']['source'], 'invite_tracking')
        again = settle(state, read, 'linked', at, evidence=dict(LINKED))
        self.assertEqual(again['reply'], TEXT_2)
        self.assertEqual(again['state']['cycle']['linked_notice']['attempts'], 2)
        again['state']['cycle']['linked_notice']['delivered'] = False
        self.assertIsNone(journey.agency_read_due(again['state'], at + timedelta(hours=3)))  # no máximo 2 vezes

    def test_state_left_by_the_41_without_the_mark_gets_text_2(self):
        state = self.accepted()['state']
        state['cycle'].pop('linked_notice')  # como ficou a 56932: vínculo gravado, aviso nunca entregue
        at = AT + timedelta(hours=3)
        again = settle(state, journey.agency_read_effect(state, at), 'linked', at, evidence=dict(LINKED))
        self.assertEqual(again['reply'], TEXT_2)

    def test_delivered_notice_is_not_repeated(self):
        state = self.accepted()['state']
        state['cycle']['linked_notice']['delivered'] = True
        self.assertIsNone(journey.agency_read_due(state, AT + timedelta(hours=3)))

    def test_a_read_stuck_without_result_does_not_block_the_follow_up(self):
        state = invited('@viralstoresbr')['state']
        turn = say('Já aceitei', state, AT + timedelta(minutes=5))
        stuck = turn['state']  # o resultado da leitura nunca foi aplicado: a leitura ficou "pending"
        self.assertIsNone(journey.agency_read_due(stuck, AT + timedelta(minutes=20)))
        at = AT + timedelta(minutes=40)
        read = journey.agency_read_effect(stuck, at)
        self.assertIsNotNone(read)
        self.assertEqual(stuck['effects'][turn['effects'][0]['id']]['status'], 'superseded_stale')
        self.assertEqual(settle(stuck, read, 'linked', at, evidence=dict(LINKED))['reply'], TEXT_2)

    def test_button_goes_to_the_number_whatsapp_reported(self):
        from transport import ChatwootTransport
        gate = {'enabled': True, 'phones': ('+5511999990001', '+5583996914946'), 'phone': '+5511999990001'}
        sent = []
        transport = ChatwootTransport('https://chatwoot.example', 't', gate,
                                      http=lambda **request: sent.append(request) or {'messages': [{'id': 'wamid.1'}]},
                                      cloud={'token': 'x', 'phone_number_id': '123456'})
        button = transport._form_button('Agora é só fazer seu cadastro por aqui:\n' + URL)
        self.assertTrue(transport._send_url_button({'sender_phone': '+558396914946'}, button))
        self.assertEqual(sent[0]['json_body']['to'], '558396914946')  # o número da conversa, não a grafia da lista


class Viralstoresbr56932ServerTests(base.GabinaresseServerTests):
    """Pelo servidor: o resultado do "Já aceitei" sai mesmo com outra mensagem mais nova na fila."""

    LEAD = {'conversation': '56932', 'contact': '8932', 'phone': '+5511987654332', 'handle': '@viralstoresbr'}

    def invite_sent(self):
        lead = self.LEAD
        self.say(lead, AD)
        self.say(lead, lead['handle'])
        self.drain()
        self.invites[0] = self.invites[1]
        self.say(lead, 'Pode mandar')
        self.drain()

    def test_acceptance_result_is_sent_even_with_a_newer_message_in_flight(self):
        lead, conv = self.LEAD, 'chatwoot:1:56932'
        self.invite_sent()
        self.relations[:] = ['linked']
        self.say(lead, 'Já aceitei')
        self.assertIn('Vou conferir agora', self.texts(lead)[-1])
        # 41/42: uma mensagem admitida e ainda não processada tornava o resultado "velho" e ele sumia.
        self.app.extensions['v5_reply_fence'].observe({'provider': 'chatwoot', 'account_id': '1', 'conversation_id': '56932',
                                                       'message_id': str(self.message_id + 50)})
        self.drain()
        self.assertIn('vínculo com a Amplify está ativo', self.texts(lead)[-1])
        self.assertTrue(self.repo.load_session(conv)['cycle']['linked_notice']['delivered'])
        self.earlier(180)
        self.assertNotEqual(self.run_scan()['status'], 'queued')

    def test_undelivered_link_is_sent_again_by_the_scan(self):
        lead, conv = self.LEAD, 'chatwoot:1:56932'
        self.invite_sent()
        self.relations[:] = ['linked', 'linked']
        original = self.chatwoot.send_reply
        self.chatwoot.send_reply = lambda event, text, buttons, key, **_: (
            {'status': 'failed', 'reason': 'chatwoot_rejected'} if URL in text else original(event, text, buttons, key))
        self.say(lead, 'Já aceitei')
        self.drain()
        self.assertFalse(self.repo.load_session(conv)['cycle']['linked_notice']['delivered'])
        self.chatwoot.send_reply = original
        self.earlier(20)
        self.assertEqual(self.run_scan()['status'], 'queued')
        self.drain()
        self.assertEqual(self.texts(lead)[-1], TEXT_2)

    test_resent_once_then_followed_until_linked = None
    test_registered_lead_is_never_read = None


class Gabinaresse56933Tests(base.DaytimeTests):
    """O envio só é anunciado quando a lista mostra o convite; sem ele, aviso honesto e novo envio."""

    def unverified(self):
        state = invite_unknown('@gabinaresse')['state']
        at = AT + timedelta(minutes=20)
        gone = settle(state, journey.agency_read_effect(state, at), 'not_found', at, evidence=dict(LIST))
        fresh = settle(gone['state'], gone['effects'][0], 'eligible', at)
        # 18:16: a ponte de Convites aceitou o pedido, mas não confirmou o convite na lista.
        return settle(fresh['state'], fresh['effects'][0], 'pending_verification', at, confirmed=False,
                      evidence={'post_attempted': True, 'create_accepted': True})

    def test_unconfirmed_send_is_never_announced_as_sent(self):
        sent = self.unverified()
        self.assertEqual(sent['reply'], conversao.INVITE_CONFIRMING)  # tabela 5b
        self.assertNotIn(TEXT_1, outbound(sent['state']))
        read = sent['effects'][0]
        self.assertEqual((read['operation'], read['payload']['not_before']),
                         ('relationship', (AT + timedelta(minutes=25)).isoformat()))  # a lista em 5 min

    def test_the_list_showing_the_invite_announces_it(self):
        sent = self.unverified()
        at = AT + timedelta(minutes=25)
        shown = settle(sent['state'], sent['effects'][0], 'pending', at, evidence=dict(PENDING))
        self.assertEqual(shown['reply'], TEXT_1)

    def test_the_list_showing_linked_sends_the_registration(self):
        sent = self.unverified()
        at = AT + timedelta(minutes=25)
        linked = settle(sent['state'], sent['effects'][0], 'linked', at, evidence=dict(LINKED))
        self.assertEqual(linked['reply'], TEXT_2)

    def resend_after_missing(self):
        sent = self.unverified()
        at = AT + timedelta(minutes=25)
        missing = settle(sent['state'], sent['effects'][0], 'not_found', at, evidence=dict(LIST))
        self.assertEqual(missing['reply'], conversao.INVITE_NOT_LANDED)
        chain = missing
        if operations(chain) == ['precheck']:
            chain = settle(chain['state'], chain['effects'][0], 'eligible', at)
        self.assertEqual(operations(chain), ['invite'])
        return chain, at

    def test_invite_missing_from_the_list_gets_an_honest_notice_and_one_more_send(self):
        chain, at = self.resend_after_missing()
        sent = settle(chain['state'], chain['effects'][0], 'sent', at, evidence=dict(PENDING))
        self.assertEqual(sent['reply'], TEXT_1)
        self.assertEqual(sent['state']['invite_resends']['@gabinaresse']['count'], 2)

    def test_after_two_sends_that_never_landed_it_keeps_checking_without_a_third(self):
        chain, at = self.resend_after_missing()
        again = settle(chain['state'], chain['effects'][0], 'pending_verification', at, confirmed=False,
                       evidence={'post_attempted': True, 'create_accepted': True})
        self.assertEqual(again['reply'], conversao.INVITE_CONFIRMING)
        at += timedelta(minutes=5)
        last = settle(again['state'], again['effects'][0], 'not_found', at, evidence=dict(LIST))
        self.assertEqual((last['reply'], operations(last)), ('', []))  # o aviso honesto já foi dado
        invites = [e for e in last['state']['effects'].values() if e.get('operation') == 'invite']
        self.assertEqual(len(invites), 3)  # o original e os 2 reenvios, cada um com a prova da lista
        self.assertIsNotNone(journey.agency_read_due(last['state'], at + timedelta(hours=2)))  # segue conferindo

    def test_state_left_by_the_42_after_the_list_said_not_found(self):
        # 42: texto 1 às 18:16 com o envio não confirmado; a leitura seguinte deu not_found e o acompanhamento parou.
        state = invite_unknown('@gabinaresse')['state']
        at = AT + timedelta(minutes=20)
        gone = settle(state, journey.agency_read_effect(state, at), 'not_found', at, evidence=dict(LIST))
        fresh = settle(gone['state'], gone['effects'][0], 'eligible', at)
        sent = settle(fresh['state'], fresh['effects'][0], 'pending_verification', at, confirmed=False,
                      evidence={'post_attempted': True, 'create_accepted': True})
        legacy = sent['state']
        legacy['cycle'].pop('invite_verify', None)
        legacy['cycle']['invite_tracking'].update(stopped='not_found', last_read_at=(at + timedelta(minutes=15)).isoformat())
        legacy['invite_resends']['@gabinaresse'].pop('count')  # a 42 não guardava a contagem
        later = at + timedelta(hours=3)
        missing = settle(legacy, journey.agency_read_effect(legacy, later), 'not_found', later, evidence=dict(LIST))
        self.assertEqual(missing['reply'], conversao.INVITE_NOT_LANDED)
        self.assertTrue(set(operations(missing)) <= {'precheck', 'invite'} and operations(missing))

    def test_reminder_counts_from_the_new_send(self):
        state = invited('@gabinaresse')['state']
        morning = AT - timedelta(hours=7, minutes=33)  # 10:43, a última mensagem dela
        state['cycle']['last_inbound_at'] = morning.isoformat()
        invite = next(e for e in state['effects'].values() if e.get('operation') == 'invite')
        invite['created_at'] = AT.isoformat()  # 18:16, o reenvio
        stub = type('Stub', (), {'repository': type('Repo', (), {'get_operation': staticmethod(lambda key: None)})()})()
        due = lambda at: retomada.Retomada._due(stub, state, {'event_key': 'chatwoot:1:1'}, at)
        self.assertIsNone(due(AT + timedelta(minutes=11)))  # 18:27: nada de "Seu convite continua no TikTok"
        self.assertEqual(due(AT + timedelta(minutes=15)), 1)


class Gabinaresse56933ServerTests(base.GabinaresseServerTests):
    """Pelo servidor: convite aceito pela ponte sem aparecer na lista, aviso honesto, novo envio e texto 1."""

    def test_unconfirmed_resend_then_honest_notice_then_real_send(self):
        lead = self.LEAD
        self.relations[:] = ['not_found', 'not_found']
        self.invites[1:] = [{'status': 'pending_verification', 'confirmed': False, 'reason': 'invitation_reconciliation_required',
                             'evidence': {'post_attempted': True, 'create_accepted': True}},
                            {'status': 'sent', 'confirmed': True, 'reason': 'invitation_verified',
                             'evidence': {'post_attempted': True, 'create_accepted': True, **PENDING}}]
        self.say(lead, AD)
        self.say(lead, lead['handle'])
        self.drain()
        self.say(lead, 'Pode mandar')
        self.drain()
        self.earlier(15)
        self.assertEqual(self.run_scan()['status'], 'queued')
        self.drain()
        self.assertEqual(self.texts(lead)[-1], conversao.INVITE_CONFIRMING)  # nunca "enviado" sem a lista
        self.assertNotIn(TEXT_1, self.texts(lead))
        # 5 min depois: a leitura da lista agendada pelo "Tô confirmando" (a fila roda agora no teste).
        self.earlier(6)
        with self.repo._connection() as db:
            db.execute("UPDATE real_jobs SET next_run_at=? WHERE status='queued'", (datetime.now(timezone.utc).isoformat(),))
        self.drain()
        texts = self.texts(lead)
        self.assertEqual(texts[-2:], [conversao.INVITE_NOT_LANDED, TEXT_1])
        self.assertEqual([call[0] for call in self.client.calls].count('invite'), 3)

    test_resent_once_then_followed_until_linked = None
    test_registered_lead_is_never_read = None


class Lead56938PhoneTests(unittest.TestCase):
    """+558396914946, sem o 9: a lista e o Chatwoot podem grafar o mesmo número de jeitos diferentes."""

    def test_both_spellings_match_in_both_directions(self):
        for listed, received in (('+5583996914946', '+558396914946'), ('+558396914946', '+5583996914946'),
                                 ('+558396914946', '+558396914946')):
            with self.subTest(listed=listed, received=received):
                self.assertEqual(contracts.pilot_phone({'phones': (listed,)}, received), listed)

    def test_the_list_still_refuses_the_same_number_twice(self):
        self.assertEqual(contracts.parse_pilot_phones('+558396914946,+5583996914946', '+558396914946')[1],
                         'pilot_phones_invalid')

    def test_landlines_and_other_numbers_never_get_a_ninth_digit(self):
        self.assertIsNone(contracts.pilot_phone({'phones': ('+558332223333',)}, '+5583932223333'))  # fixo (3…)
        self.assertIsNone(contracts.pilot_phone({'phones': ('+558396914946',)}, '+5583996914947'))


class Lead56938PosPausaTests(unittest.TestCase):
    """05:42: fora do horário, o Chatwoot respondeu com o aviso automático da caixa (tipo template)."""

    NOW = datetime(2026, 11, 2, 22, 47, tzinfo=timezone.utc)      # 19:47 de Brasília
    ARRIVED = datetime(2026, 11, 2, 8, 42, tzinfo=timezone.utc)   # 05:42 de Brasília

    def subject(self, listed_phone, chatwoot_phone):
        from test_release39 import FakeChatwoot, GATE, PHONE
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='correcao43-')
        self.addCleanup(tmp.cleanup)
        repo = Repository(Path(tmp.name) / 'state.sqlite3')
        parsed, issue = contracts.parse_pilot_phones(PHONE + ',' + listed_phone, PHONE)
        self.assertIsNone(issue)
        away = {'id': 569381, 'message_type': 3, 'private': False, 'sender': None,
                'content': 'Nosso horário de atendimento é das 8h às 18h. Respondemos assim que possível.',
                'content_attributes': {}, 'created_at': self.ARRIVED.timestamp() + 1}
        history = [{'id': 569380, 'message_type': 0, 'private': False, 'content': 'Oi, quero saber mais',
                    'created_at': self.ARRIVED.timestamp()}, away]
        conversation = {'id': 56938, 'inbox_id': 3, 'meta': {'sender': {'id': 9938, 'phone_number': chatwoot_phone}},
                        'last_activity_at': int(self.ARRIVED.timestamp()) + 1, 'last_non_activity_message': deepcopy(away)}
        chatwoot = FakeChatwoot()
        chatwoot.http = lambda **request: ({'data': {'payload': [deepcopy(conversation)] if 'page=1' in request['url'] else []}}
                                           if '/conversations?' in request['url'] else {'payload': deepcopy(history)})
        self.calls = []
        process = lambda event, resumed: self.calls.append((event['conversation_id'], resumed['texts'])) or {'status': 'completed'}
        return retomada.PosPausa(repo, {'pos_pausa_enabled': True, 'tiktok_mode': 'real', 'real_worker_enabled': True,
                                        'conversation_enabled': True, 'gate': {**GATE, 'phones': parsed}},
                                 chatwoot, lambda _: {'allowed': True}, process, now=lambda: self.NOW)

    def test_out_of_office_notice_does_not_hide_the_lead(self):
        self.assertEqual(self.subject('+558396914946', '+558396914946').tick()['status'], 'resumed')
        self.assertEqual(self.calls, [(56938, ['Oi, quero saber mais'])])

    def test_listed_with_the_ninth_digit(self):
        self.assertEqual(self.subject('+5583996914946', '+558396914946').tick()['status'], 'resumed')

    def test_listed_without_it_and_chatwoot_with_it(self):
        self.assertEqual(self.subject('+558396914946', '+5583996914946').tick()['status'], 'resumed')


class NotInterested32922Tests(unittest.TestCase):
    """32922: "Não tenho interesse" às 13:52 ficou sem resposta."""

    def test_one_respectful_answer_and_the_attendance_closes(self):
        for label, state in (('início', None), ('apresentação', say(AD)['state']),
                             ('autorização', eligible('@lead32922')['state']), ('convite', invited('@lead32922')['state'])):
            with self.subTest(label):
                turn = say('Não tenho interesse', state)
                self.assertEqual((turn['reply'], turn['buttons']), (conversao.NOT_INTERESTED, []))
                self.assertEqual((turn['state']['cycle']['status'], turn['state']['cycle']['reason']),
                                 ('closed', 'lead_not_interested'))

    def test_variants(self):
        for text in ('não tenho interesse', 'Não tenho mais interesse, obrigada', 'Sem interesse', 'Não quero',
                     'não me interessa', 'Obrigada, não tenho interesse'):
            with self.subTest(text):
                self.assertTrue(journey.not_interested(text))
        for text in ('Não tenho interesse em fazer live?', 'Não tenho interesse em live, mas quero vender mais com vídeos',
                     'não', 'quero sim'):
            with self.subTest(text):
                self.assertFalse(journey.not_interested(text))

    def test_writing_again_starts_over(self):
        closed = say('Não tenho interesse', say(AD)['state'])['state']
        again = say('Oi, mudei de ideia', closed, AT + timedelta(hours=1))
        self.assertEqual(again['state']['cycle']['status'], 'open')
        self.assertNotEqual(again['reply'], conversao.NOT_INTERESTED)


class NeverSilentServerTests(base.GabinaresseServerTests):
    """Regra geral: se a mensagem do lead falha no processamento, ele recebe um aviso honesto (uma vez por hora)."""

    LEAD = {'conversation': '56935', 'contact': '8935', 'phone': '+5511987654335', 'handle': '@mydearshop8'}

    def test_failed_inbound_gets_an_honest_answer(self):
        lead = self.LEAD
        self.say(lead, AD)
        import conversation
        with mock.patch.object(conversation, 'handle_event', side_effect=RuntimeError('contato_terminal_or_clock_regression')):
            self.message_id += 1
            event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': '1', 'inbox_id': '3',
                     'conversation_id': lead['conversation'], 'contact_id': lead['contact'],
                     'message_id': str(self.message_id), 'sender_phone': lead['phone'], 'sender_type': 'contact',
                     'message_type': 'incoming', 'private': False, 'text': 'Já aceitei',
                     'created_at': datetime.now(timezone.utc).isoformat(), 'source_ref': 'chatwoot:1:' + str(self.message_id)}
            with self.app.app_context():
                body, code = self.app.extensions['v5_process_inbound'](event)
            self.assertEqual(code, 202)
            self.say(lead, 'Oi?')  # a 2ª falha na mesma hora não repete o aviso
        self.assertEqual(self.texts(lead).count(conversao.INBOUND_FALLBACK), 1)

    def say(self, lead, text):
        self.message_id += 1
        event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': '1', 'inbox_id': '3',
                 'conversation_id': lead['conversation'], 'contact_id': lead['contact'], 'message_id': str(self.message_id),
                 'sender_phone': lead['phone'], 'sender_type': 'contact', 'message_type': 'incoming', 'private': False,
                 'text': text, 'created_at': datetime.now(timezone.utc).isoformat(),
                 'source_ref': 'chatwoot:1:' + str(self.message_id)}
        with self.app.app_context():
            self.app.extensions['v5_process_inbound'](event)

    test_resent_once_then_followed_until_linked = None
    test_registered_lead_is_never_read = None


if __name__ == '__main__':
    unittest.main()
