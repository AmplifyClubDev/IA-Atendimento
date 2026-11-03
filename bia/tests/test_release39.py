"""Release 39: conduta da Bia após a auditoria dos 10 atendimentos (31/10/2026).

1) retomada automática de quem para de responder (15 min, 2 h, 23h30);
2) "aceitei"/"feito"/"pronto" conferem o vínculo na hora e de novo em 5/15/60 min;
3) toda menção ao formulário vem com o botão; pedido do link sempre reenvia;
4) depois de uma pausa, a resposta retoma o pedido de cada lead;
e as respostas sem avisos internos, usando o último fato confirmado.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest

import contracts
import conversao
import conversation
import real_journey as journey
import receipt_grounding
import retomada
from config import load_settings
from real_operations import build_jobs
from repository import Repository
from transport import ChatwootTransport
from test_relationship_form_chat30 import AT, POLICY, inbound, invited, qualified

URL = journey.PUBLIC_FORM_URL
PHONE = '+5547991154859'
GATE = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3', 'phone': PHONE}


def say(text, state, *, at=AT, **options):
    return conversation.handle(state, text, now=at, real_mode=True, operation_policy=POLICY,
                               relationship_check_in_form=True, **options)


def settle_at(state, effect, status, at):
    result = dict(operation=effect['operation'], creator=effect['creator'].lstrip('@'), status=status,
                  confirmed=True, observed_at=at.isoformat(), evidence={'source': 'offline', 'complete': True})
    return conversation.resolve_tiktok_result(state, effect['id'], result, now=at, operation_policy=POLICY)


def chat_checks(state):
    return [effect for effect in state['effects'].values()
            if (effect.get('payload') or {}).get('source') == 'chat_acceptance']


def no_invite_effect(result):
    return not any(effect.get('operation') == 'invite' for effect in result.get('effects', []))


class AcceptanceCheckTests(unittest.TestCase):
    """Ponto 2: o aceite declarado é conferido pela ponte, nunca vira prova sozinho."""

    def accepted(self, text='aceitei'):
        sent = invited('sent')
        self.assertEqual(sent['state']['cycle']['phase'], 'form')
        return say(text, sent['state'])

    def test_aceitei_checks_relationship_now_without_invite(self):
        turn = self.accepted()
        self.assertEqual(len(turn['effects']), 1)
        check = turn['effects'][0]
        self.assertEqual(check['operation'], 'relationship')
        self.assertEqual(check['payload']['source'], 'chat_acceptance')
        self.assertEqual(check['payload']['check'], 0)
        self.assertNotIn('not_before', check['payload'])
        self.assertEqual(turn['state']['cycle']['phase'], 'checking_acceptance')
        self.assertIn('Vou conferir agora no TikTok', turn['reply'])
        self.assertTrue(no_invite_effect(turn))
        self.assertTrue(turn['state']['cycle']['facts']['aceite_declarado'])

    def test_feito_and_pronto_count_only_after_an_invite(self):
        for text in ('Feito', 'pronto!', 'Já aceitei', 'Aceitei o convite', 'prontinho'):
            with self.subTest(text=text):
                turn = self.accepted(text)
                self.assertEqual(turn['effects'][0]['payload']['source'], 'chat_acceptance')
        early = inbound('Feito', qualified()['state'])
        self.assertFalse(chat_checks(early['state']))
        for text in ('Não aceitei ainda', 'Aceitei?', 'ainda não fiz'):
            with self.subTest(text=text):
                self.assertFalse(journey.acceptance_declared(text, invited('sent')['state']['cycle']))

    def test_linked_result_sends_the_single_form_button(self):
        turn = self.accepted()
        done = settle_at(turn['state'], turn['effects'][0], 'linked', AT)
        self.assertEqual(done['state']['cycle']['phase'], 'form')
        self.assertTrue(done['reply'].startswith('Confirmei no TikTok: seu vínculo com a Amplify está ativo'))
        self.assertIn(URL, done['reply'])
        self.assertEqual(done['buttons'], [])  # sem botões de resposta: a URL vira o botão "Fazer cadastro"
        self.assertEqual(done['state']['cycle']['form_button_stage'], 'linked')
        self.assertFalse(done['effects'])

    def test_pending_rechecks_alone_at_5_15_and_60_minutes(self):
        turn = self.accepted()
        first = settle_at(turn['state'], turn['effects'][0], 'pending', AT)
        self.assertIn('5, 15 e 60 minutos', first['reply'])
        self.assertIn('*Parcerias* ou *Notificações*', first['reply'])
        self.assertNotIn('não substitui', first['reply'])
        state, effect = first['state'], first['effects'][0]
        self.assertEqual(state['cycle']['phase'], 'await_acceptance')
        for step, minutes in ((1, 5), (2, 15), (3, 60)):
            self.assertEqual(effect['payload']['check'], step)
            self.assertEqual(effect['payload']['not_before'], (AT + timedelta(minutes=minutes)).isoformat())
            result = settle_at(state, effect, 'not_found', AT + timedelta(minutes=minutes))
            state = result['state']
            if step < 3:
                self.assertEqual(result['reply'], '')  # reconferência sem novidade não gera mensagem
                effect = result['effects'][0]
        self.assertIn('Ainda não consegui ver o seu aceite', result['reply'])
        self.assertEqual(result['buttons'], ['Já aceitei'])
        self.assertFalse(result['effects'])
        self.assertNotIn('acceptance_check', state['cycle'])

    def test_recheck_finding_the_link_warns_with_the_button(self):
        turn = self.accepted()
        first = settle_at(turn['state'], turn['effects'][0], 'pending', AT)
        later = AT + timedelta(minutes=5)
        found = settle_at(first['state'], first['effects'][0], 'linked', later)
        self.assertIn('Confirmei no TikTok', found['reply'])
        self.assertIn(URL, found['reply'])
        self.assertEqual(found['buttons'], [])

    def test_failed_bridge_read_is_honest_and_still_rechecks(self):
        turn = self.accepted()
        result = settle_at(turn['state'], turn['effects'][0], 'verification_pending', AT)
        self.assertIn('Não consegui consultar o TikTok agora', result['reply'])
        self.assertEqual(result['effects'][0]['payload']['check'], 1)
        self.assertTrue(no_invite_effect(result))

    def test_new_aceitei_brings_the_scheduled_recheck_forward(self):
        turn = self.accepted()
        first = settle_at(turn['state'], turn['effects'][0], 'pending', AT)
        scheduled = first['effects'][0]
        again = say('Aceitei agora', first['state'], at=AT + timedelta(minutes=2))
        self.assertEqual(again['state']['effects'][scheduled['id']]['status'], 'superseded')
        self.assertEqual(again['effects'][0]['payload']['check'], 0)

    def test_already_linked_in_this_cycle_answers_at_once(self):
        """lemosalycee: disse "Feito" com o vínculo já confirmado e ouviu "sem confirmação"."""
        turn = self.accepted()
        linked = settle_at(turn['state'], turn['effects'][0], 'linked', AT)
        later = say('Feito', linked['state'], at=AT + timedelta(hours=2))
        self.assertFalse(later['effects'])
        self.assertIn('Confirmei no TikTok', later['reply'])

    def test_each_check_gets_its_own_worker_row(self):
        turn = self.accepted()
        first = settle_at(turn['state'], turn['effects'][0], 'pending', AT)
        event = dict(provider='chatwoot', account_id='1', conversation_id='26097', message_id='777')
        keys = {job['job_key'] for result in (turn, first)
                for job in build_jobs(event, result['state'], result['effects'])}
        self.assertEqual(len(keys), 2)


class FormButtonTests(unittest.TestCase):
    """Ponto 3: botão do /cadastro em toda menção, uma vez por etapa, reenviado a pedido."""

    def test_asking_where_the_form_is_always_resends_the_button(self):
        sent = invited('sent')
        self.assertIn(URL, sent['reply'])
        for text in ('Onde fica o formulário?', 'Não apareceu o formulário', 'manda o link de novo', 'Cadê o link?'):
            with self.subTest(text=text):
                turn = say(text, sent['state'])
                self.assertIn(URL, turn['reply'])
                self.assertEqual(turn['buttons'], [])
                self.assertTrue(no_invite_effect(turn))

    def test_button_goes_once_per_stage(self):
        cycle = deepcopy(invited('sent')['state']['cycle'])
        self.assertEqual(cycle['form_button_stage'], 'invite')
        text, buttons = journey._form_button_once(cycle, 'Faça seu cadastro por aqui:\n' + URL, [])
        self.assertNotIn(URL, text)
        self.assertIn('*Fazer cadastro* que te mandei acima', text)
        forced, _ = journey._form_button_once(cycle, 'Faça seu cadastro por aqui:\n' + URL, [], force=True)
        self.assertIn(URL, forced)

    def test_new_stage_gets_the_button_again(self):
        turn = say('aceitei', invited('sent')['state'])
        done = settle_at(turn['state'], turn['effects'][0], 'linked', AT)
        self.assertIn(URL, done['reply'])

    def test_any_form_mention_carries_the_button_when_not_yet_sent(self):
        cycle = deepcopy(invited('sent')['state']['cycle'])
        cycle.pop('form_button_stage')
        text, buttons = journey._form_button_once(cycle, 'O próximo passo é o formulário.', ['Menu'])
        self.assertIn(URL, text)
        self.assertEqual(buttons, [])

    def test_before_an_invite_there_is_no_form_to_send(self):
        turn = inbound('Onde fica o formulário?', qualified()['state'])
        self.assertNotIn(URL, turn['reply'])
        self.assertIn('depois que você aceita o convite', turn['reply'])

    def test_whatsapp_button_label_and_body(self):
        transport = ChatwootTransport('https://chatwoot.invalid', 'token', GATE,
                                      cloud={'token': 'x', 'phone_number_id': '123456'})
        cycle = deepcopy(invited('sent')['state']['cycle'])
        button = transport._form_button(journey._linked_reply({'cycle': cycle}))
        self.assertEqual(button['label'], 'Fazer cadastro')
        self.assertEqual(button['url'], URL)
        self.assertNotIn(URL, button['body'])


class ReplyTextTests(unittest.TestCase):
    """Sem aviso de controle interno; o último fato confirmado nunca é desmentido."""
    INTERNAL = ('por si só', 'não confirma', 'não substitui', 'sem confirmação suficiente', 'Ainda não tenho confirmação de envio')

    def test_operational_answers_have_no_internal_control_warnings(self):
        sent = invited('sent')['state']
        for state in (qualified()['state'], sent):
            for question in ('Recebi o acesso?', 'E o convite?', 'Já posso fazer o cadastro?'):
                answer = receipt_grounding.ground_reply(question, 'Seu acesso foi liberado.', {'intent': 'question'},
                                                        state, policy=POLICY, now=AT)
                for phrase in self.INTERNAL:
                    self.assertNotIn(phrase, answer)
        for phase in ('await_acceptance', 'checking_acceptance'):
            cycle = {'phase': phase, 'relationship_check_in_form': True}
            self.assertNotIn('não confirma', journey._phase_prompt(cycle))

    def test_invite_sent_is_never_contradicted_later_in_the_cycle(self):
        state = invited('sent')['state']
        answer = receipt_grounding.ground_reply('E o convite?', 'O convite chegou?', {'intent': 'question'},
                                                state, policy=POLICY, now=AT + timedelta(hours=3))
        self.assertIn('confirmou o envio', answer)
        self.assertNotIn('não tenho confirmação', answer)

    def test_unrelated_question_keeps_its_answer(self):
        """priscila: perguntou "Recebe pra isso?" e ouviu sobre o vínculo."""
        reply = ('Você ganha comissão sobre as vendas que fizer como creator. '
                 'O vínculo com a agência ainda não foi confirmado.')
        answer = receipt_grounding.ground_reply('Recebe pra isso?', reply, {'intent': 'question'},
                                                qualified()['state'], policy=POLICY, now=AT)
        self.assertEqual(answer, 'Você ganha comissão sobre as vendas que fizer como creator.')

    def test_name_instead_of_handle_explains_where_to_find_it(self):
        self.assertIn('abra seu perfil', journey._HANDLE_UNKNOWN)


class ResumeAfterPauseTests(unittest.TestCase):
    """Ponto 4: a volta da pausa retoma o pedido, não manda saudação genérica."""

    def test_generic_interest_is_resumed_with_the_concrete_next_step(self):
        texts = ['Olá! Tenho interesse e queria mais informações.']
        turn = say(texts[0], {}, resumed={'texts': texts})
        # Release 40: a primeira mensagem vende e termina pedindo o @.
        self.assertTrue(turn['reply'].startswith(conversao.OPENING + ' Desculpa a demora'))
        self.assertIn(conversao.ASK_HANDLE, turn['reply'])
        self.assertEqual(turn['state']['history'][-1]['text'], turn['reply'])
        self.assertTrue(turn['state']['cycle']['arroba_pedido'])
        answer = say('@lead_teste', turn['state'])
        facts = answer['state']['cycle']['facts']
        self.assertEqual(facts['tiktok_declarado'], '@lead_teste')
        self.assertTrue(facts['interesse_agenciamento'])
        self.assertEqual(answer['reply'], conversao.RECEIVED.format(handle='@lead_teste'))

    def test_specific_question_is_answered_after_the_apology(self):
        turn = say('Quais os benefícios?', {}, resumed={'texts': ['Oi', 'Quais os benefícios?']})
        self.assertIn('Desculpa a demora', turn['reply'])
        self.assertNotIn(conversao.ASK_HANDLE, turn['reply'])

    def test_bare_name_is_not_taken_as_handle(self):
        turn = say('Oi', {}, resumed={'texts': ['Oi']})
        answer = say('Priscila', turn['state'])
        self.assertNotIn('tiktok_declarado', answer['state']['cycle']['facts'])

    def test_handle_event_carries_the_resume_marker(self):
        event = dict(provider='chatwoot', event='message_created', account_id='1', inbox_id='3', conversation_id='26097',
                     contact_id='3', message_id='5000', sender_phone=PHONE, sender_type='contact',
                     message_type='incoming', private=False, text='Oi, tenho interesse', created_at=AT.isoformat(),
                     source_ref='chatwoot:1:5000')
        result = conversation.handle_event({}, event, GATE, now=AT, real_mode=True, operation_policy=POLICY,
                                           relationship_check_in_form=True, resumed={'texts': ['Oi, tenho interesse']})
        self.assertTrue(result.get('resumed'))
        self.assertIn('chatwoot:1:5000', result['state']['processed_inbound'])


class FakeChatwoot:
    def __init__(self):
        self.token = 'offline'
        self.base_url = 'https://chatwoot.invalid'
        self.messages, self.listing, self.sent = [], [], []
        self.receipt = {'status': 'accepted', 'message_id': '9900'}

    def _conversation_url(self, event):
        return self.base_url + '/api/v1/accounts/1/conversations/' + str(event['conversation_id'])

    def http(self, *, method, url, headers, timeout, json_body=None):
        assert method == 'GET'
        if '/conversations?' in url:
            return {'data': {'payload': deepcopy(self.listing)}}
        return {'payload': deepcopy(self.messages)}

    def send_reply(self, event, text, buttons, key, *, before_write=None):
        if before_write() is not True:
            return {'status': 'failed', 'reason': 'send_cancelled_before_post'}
        self.sent.append({'text': text, 'buttons': buttons, 'key': key})
        return dict(self.receipt)


class RetomadaTests(unittest.TestCase):
    """Ponto 1: 15 min, 2 h e 23h30 depois do silêncio, cada etapa uma vez."""
    CONV = 'chatwoot:1:40001'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='release39-')
        self.addCleanup(tmp.cleanup)
        self.repo = Repository(Path(tmp.name) / 'state.sqlite3')
        self.inbound_at = datetime.now(timezone.utc) - timedelta(minutes=16)
        self.event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': '1', 'inbox_id': '3',
                      'conversation_id': '40001', 'message_id': '700', 'contact_id': '55', 'sender_phone': PHONE,
                      'sender_type': 'contact', 'message_type': 'incoming', 'private': False,
                      'text': 'Quero conhecer', 'created_at': self.inbound_at.isoformat(), 'source_ref': 'chatwoot:1:700'}
        self.state = {'session_id': 's', 'revision': 2, 'creator_id': 'c', 'processed_inbound': ['chatwoot:1:700'],
                      'history': [], 'effects': {},
                      'cycle': {'id': 'cycle-1', 'mode': 'real', 'status': 'open', 'phase': 'intro', 'facts': {},
                                'relationship_check_in_form': True,
                                'opened_at': (self.inbound_at - timedelta(minutes=1)).isoformat(),
                                'last_inbound_at': self.inbound_at.isoformat(),
                                'expires_at': (self.inbound_at + timedelta(hours=24)).isoformat()}}
        self.repo.reserve_event('chatwoot:1:700', self.CONV, 'offline')
        self.repo.prepare_reply('chatwoot:1:700', self.CONV, self.state, 'reply-700',
                                {'text': 'O que você gostaria de conhecer?', 'buttons': []})
        self.repo.finish_outbox('reply-700', 'accepted', {'status': 'accepted', 'message_id': '701'})
        with self.repo._connection() as db:
            db.execute("UPDATE outbox SET updated_at=? WHERE outbox_key='reply-700'",
                       ((self.inbound_at + timedelta(seconds=5)).isoformat(),))
        self.repo.finish_event('chatwoot:1:700', 'completed')
        self.assertTrue(self.repo.remember_followup_source(self.CONV, self.event, self.state))
        self.chatwoot = FakeChatwoot()
        self.chatwoot.messages = [{'id': 700, 'message_type': 0, 'private': False, 'content': 'Quero conhecer'},
                                  {'id': 701, 'message_type': 1, 'private': False, 'content': 'O que...'}]
        self.allowed = {'allowed': True}
        self.settings = {'retomada_enabled': True, 'tiktok_mode': 'real', 'real_worker_enabled': True,
                         'conversation_enabled': True, 'gate': GATE}
        self.clock = datetime.now(timezone.utc)
        self.lock = threading.RLock()
        self.subject = retomada.Retomada(self.repo, self.settings, self.chatwoot, lambda _: self.lock,
                                         lambda _: self.allowed, now=lambda: self.clock, policy=lambda: POLICY)

    def tick_at(self, after):
        self.clock = self.inbound_at + after
        self.subject.next_scan_at = None
        return self.subject.tick()

    def test_three_steps_once_each_with_a_concrete_action(self):
        self.tick_at(timedelta(minutes=10))
        self.assertEqual(self.chatwoot.sent, [])
        self.tick_at(timedelta(minutes=16))
        self.assertEqual(len(self.chatwoot.sent), 1)
        self.assertIn('Me manda seu @ do TikTok', self.chatwoot.sent[0]['text'])
        self.tick_at(timedelta(minutes=40))
        self.assertEqual(len(self.chatwoot.sent), 1)
        self.tick_at(timedelta(hours=2, minutes=1))
        self.assertEqual(len(self.chatwoot.sent), 2)
        self.tick_at(timedelta(hours=23, minutes=31))
        self.assertEqual(len(self.chatwoot.sent), 3)
        # Release 40: cada lembrete tem um ângulo novo; o último oferece botões.
        self.assertEqual(len({sent['text'] for sent in self.chatwoot.sent}), 3)
        self.assertEqual(self.chatwoot.sent[2]['buttons'], ['Quero entrar', 'Agora não'])
        self.tick_at(timedelta(hours=23, minutes=50))
        self.assertEqual(len(self.chatwoot.sent), 3)
        self.assertTrue(self.repo.load_session(self.CONV)['cycle']['arroba_pedido'])

    def test_missed_steps_collapse_into_one_nudge(self):
        self.tick_at(timedelta(hours=3))
        self.tick_at(timedelta(hours=3, minutes=20))
        self.assertEqual(len(self.chatwoot.sent), 1)

    def test_never_while_blocked_answered_or_busy(self):
        self.allowed = {'allowed': False, 'reason': 'human_control_blocked'}
        self.tick_at(timedelta(minutes=16))
        self.allowed = {'allowed': True}
        self.chatwoot.messages.append({'id': 702, 'message_type': 0, 'private': False, 'content': 'oi?'})
        self.tick_at(timedelta(minutes=17))
        self.assertEqual(self.chatwoot.sent, [])

    def test_disabled_and_settings_default(self):
        self.settings['retomada_enabled'] = False
        self.tick_at(timedelta(minutes=16))
        self.assertEqual(self.chatwoot.sent, [])
        self.assertTrue(load_settings({})['retomada_enabled'])
        self.assertFalse(load_settings({'V5_RETOMADA_ENABLED': 'false'})['retomada_enabled'])
        self.assertFalse(load_settings({'V5_POS_PAUSA_ENABLED': 'false'})['pos_pausa_enabled'])

    def test_messages_per_stage(self):
        state = deepcopy(self.state)
        state['cycle'].update(phase='form', real_operations={'invite': {'status': 'sent', 'cycle_id': 'cycle-1'}})
        text, buttons = retomada.message(state, 1, POLICY)
        self.assertIn('me manda “aceitei”', text)
        self.assertEqual(buttons, ['Já aceitei'])
        state['cycle']['real_operations']['relationship'] = {'status': 'linked'}
        text, buttons = retomada.message(state, 1, POLICY)
        self.assertIn(URL, text)
        self.assertEqual(buttons, [])
        state['cadastro_situacao'] = 'confirmado'
        self.assertIsNone(retomada.message(state, 1, POLICY))


class PosPausaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='release39-')
        self.addCleanup(tmp.cleanup)
        self.repo = Repository(Path(tmp.name) / 'state.sqlite3')
        self.now = datetime.now(timezone.utc)
        self.chatwoot = FakeChatwoot()
        old = (self.now - timedelta(hours=2)).timestamp()
        self.chatwoot.listing = [{'id': 40002, 'inbox_id': 3, 'meta': {'sender': {'id': 77, 'phone_number': PHONE}},
                                  'last_non_activity_message': {'id': 812, 'message_type': 0, 'private': False,
                                                                'content': 'Quero conhecer a Amplify', 'created_at': old}}]
        self.chatwoot.messages = [
            {'id': 810, 'message_type': 0, 'private': False, 'content': 'Olá, tenho interesse'},
            {'id': 811, 'message_type': 1, 'private': False, 'content': 'Estamos em manutenção',
             'content_attributes': {}},
            {'id': 812, 'message_type': 0, 'private': False, 'content': 'Quero conhecer a Amplify'}]
        self.calls, self.allowed = [], {'allowed': True}
        self.subject = retomada.PosPausa(self.repo, {'pos_pausa_enabled': True, 'tiktok_mode': 'real',
                                         'real_worker_enabled': True, 'conversation_enabled': True, 'gate': GATE},
                                         self.chatwoot, lambda _: self.allowed,
                                         lambda event, resumed: self.calls.append((event, resumed)) or {'status': 'completed'},
                                         now=lambda: self.now)

    def test_unanswered_lead_is_resumed_with_every_pending_text(self):
        self.assertEqual(self.subject.tick()['status'], 'resumed')
        event, resumed = self.calls[0]
        self.assertEqual(event['source_ref'], 'chatwoot:1:812')
        self.assertEqual(event['text'], 'Quero conhecer a Amplify')
        self.assertEqual(resumed['texts'], ['Olá, tenho interesse', 'Quero conhecer a Amplify'])

    def test_skips_answered_fresh_blocked_and_foreign(self):
        cases = []
        recent = deepcopy(self.chatwoot.listing)
        recent[0]['last_non_activity_message']['created_at'] = (self.now - timedelta(seconds=30)).timestamp()
        cases.append(('fresh', recent, {'allowed': True}))
        foreign = deepcopy(self.chatwoot.listing)
        foreign[0]['meta']['sender']['phone_number'] = '+5511999990000'
        cases.append(('foreign', foreign, {'allowed': True}))
        cases.append(('maintenance', deepcopy(self.chatwoot.listing), {'allowed': False, 'reason': 'human_control_blocked'}))
        for name, listing, allowed in cases:
            with self.subTest(name=name):
                self.chatwoot.listing, self.allowed = listing, allowed
                self.subject.next_scan_at = None
                self.subject.tick()
                self.assertEqual(self.calls, [])
        self.allowed = {'allowed': True}
        self.chatwoot.listing = self.subject_listing = deepcopy(listing)
        self.repo.reserve_event('chatwoot:1:812', 'chatwoot:1:40002', 'webhook')
        self.subject.next_scan_at = None
        self.subject.tick()
        self.assertEqual(self.calls, [])


class TenLeadsAfterMaintenanceTests(unittest.TestCase):
    """Os 10 leads de 31/10 só receberam o aviso de manutenção (regra de automação do Chatwoot)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='release39-')
        self.addCleanup(tmp.cleanup)
        self.repo = Repository(Path(tmp.name) / 'state.sqlite3')
        self.now = datetime.now(timezone.utc)
        self.leads = ['+55119876543' + format(index, '02d') for index in range(10)]
        phones, issue = contracts.parse_pilot_phones(','.join([PHONE] + self.leads), PHONE)
        self.assertIsNone(issue)
        self.gate = {**GATE, 'phones': phones}
        self.chatwoot = FakeChatwoot()
        self.history = {}
        for index, phone in enumerate(self.leads):
            conv, incoming, notice = 41000 + index, 9000 + 10 * index, 9001 + 10 * index
            arrived = (self.now - timedelta(minutes=50 - 5 * index)).timestamp()
            last = {'id': notice, 'message_type': 1, 'private': False, 'content': 'Estamos em manutenção',
                    'content_attributes': {'automation_rule_id': 3}, 'created_at': arrived + 2}
            self.chatwoot.listing.append({'id': conv, 'inbox_id': 3, 'meta': {'sender': {'id': 500 + index, 'phone_number': phone}},
                                          'last_non_activity_message': deepcopy(last)})
            self.history[conv] = [{'id': incoming, 'message_type': 0, 'private': False,
                                   'content': 'Olá! Tenho interesse e queria mais informações.', 'created_at': arrived},
                                  last]
        self.chatwoot.http = self.http
        self.calls = []
        self.subject = retomada.PosPausa(self.repo, {'pos_pausa_enabled': True, 'tiktok_mode': 'real',
                                         'real_worker_enabled': True, 'conversation_enabled': True, 'gate': self.gate},
                                         self.chatwoot, lambda _: {'allowed': True}, self.process, now=lambda: self.now)

    def http(self, *, method, url, headers, timeout, json_body=None):
        if '/conversations?' in url:
            return {'data': {'payload': deepcopy(self.chatwoot.listing)}}
        return {'payload': deepcopy(self.history[int(url.rsplit('/', 2)[-2])])}

    def process(self, event, resumed):
        # O caminho do webhook registra o evento antes de responder.
        self.assertTrue(self.repo.reserve_event(event['source_ref'], 'chatwoot:1:' + str(event['conversation_id']), 'webhook'))
        self.calls.append((event, resumed))
        return {'status': 'completed'}

    def scan(self):
        self.subject.next_scan_at = None
        return self.subject.tick()

    def test_each_lead_is_answered_once_with_its_own_request(self):
        for _ in range(15):
            self.scan()
        self.assertEqual(len(self.calls), 10)
        self.assertEqual(sorted(event['message_id'] for event, _ in self.calls), [9000 + 10 * i for i in range(10)])
        for event, resumed in self.calls:
            self.assertEqual(resumed['texts'], ['Olá! Tenho interesse e queria mais informações.'])
            self.assertEqual(event['text'], 'Olá! Tenho interesse e queria mais informações.')
        self.assertEqual(self.scan()['status'], 'idle')

    def test_attendant_reply_is_not_skipped_over(self):
        for conversation in self.history.values():
            conversation[-1]['content_attributes'] = {}
            conversation[-1]['sender'] = {'id': 9, 'type': 'user'}
        for listed in self.chatwoot.listing:
            listed['last_non_activity_message'].update(content_attributes={}, sender={'id': 9, 'type': 'user'})
        self.scan()
        self.assertEqual(self.calls, [])


class PilotCapTests(unittest.TestCase):
    def test_one_hundred_phones_accepted_one_hundred_one_refused(self):
        # Release 40.1 (02/11): o limite subiu de 21 para 100 para liberar novos lotes sem novo pacote.
        self.assertEqual(contracts.MAX_PILOT_PHONES, 100)
        numbers = [PHONE] + ['+551198765' + format(index, '04d') for index in range(100)]
        phones, issue = contracts.parse_pilot_phones(','.join(numbers[:100]), PHONE)
        self.assertIsNone(issue)
        self.assertEqual(len(phones), 100)
        self.assertEqual(contracts.parse_pilot_phones(','.join(numbers), PHONE), (None, 'pilot_phones_invalid'))
        settings = load_settings({'V5_TEST_PHONE': PHONE, 'V5_ENABLED': 'true', 'CHATWOOT_ACCOUNT_ID': '1',
                                  'CHATWOOT_INBOX_ID': '3', 'V5_PILOT_PHONES': ','.join(numbers)})
        self.assertIn('pilot_phones_invalid', settings['readiness_issues'])


class ServerWiringTests(unittest.TestCase):
    """O worker roda retomada + pós-pausa; a pós-pausa usa o mesmo caminho do webhook."""

    def test_catch_up_goes_through_the_webhook_path_and_apologizes(self):
        from server import create_app
        from test_real_executor import FakeClient, FakeGateway
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='release39-')
        self.addCleanup(tmp.cleanup)
        repo = Repository(Path(tmp.name) / 'state.sqlite3')
        chatwoot = FakeChatwoot()
        chatwoot.ready = lambda: True
        sent = []
        chatwoot.send_reply = lambda event, text, buttons, key, **_: (sent.append(text)
                                                                      or {'status': 'accepted', 'message_id': '9901'})
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
        chatwoot.listing = [{'id': 40003, 'inbox_id': 3, 'meta': {'sender': {'id': 88, 'phone_number': PHONE}},
                             'last_non_activity_message': {'id': 901, 'message_type': 0, 'private': False,
                                                           'content': 'Olá, tenho interesse', 'created_at': old}}]
        chatwoot.messages = [{'id': 901, 'message_type': 0, 'private': False, 'content': 'Olá, tenho interesse'}]
        settings = {'tiktok_mode': 'real', 'real_worker_enabled': True, 'gate': dict(GATE), 'state_dir': tmp.name,
                    'webhook_token': 'w' * 40, 'conversation_enabled': True, 'ai_enabled': True,
                    'contact_sync_enabled': True, 'instance_id': 'offline-test', 'readiness_issues': [],
                    'relationship_check_in_form': True, 'retomada_enabled': True, 'pos_pausa_enabled': True}
        unknown = {'provider_status': 'unknown', 'claims': [], 'reply': '', 'intent': 'clarify'}
        app = create_app(settings, repo, chatwoot, planner=lambda *_: dict(unknown),
                         real_client=FakeClient(), real_guard=lambda _: {'allowed': True})
        app.extensions['v5_data_gateway'] = FakeGateway()
        executor = app.extensions['v5_real_executor']
        self.assertEqual(executor.followup_tick.__name__, 'conduct_tick')
        self.assertIn('retomada', executor.followup_status())
        executor.followup_tick()
        self.assertEqual(len(sent), 1)
        self.assertIn('Desculpa a demora', sent[0])
        self.assertIn('Me manda seu @ do TikTok', sent[0])
        self.assertEqual(repo.event('chatwoot:1:901')['status'], 'completed')
        self.assertTrue(repo.followup_source('chatwoot:1:40003'))
        app.extensions['v5_pos_pausa'].next_scan_at = None
        executor.followup_tick()
        self.assertEqual(len(sent), 1)  # já respondida: não repete


if __name__ == '__main__':
    unittest.main()
