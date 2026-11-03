"""Release 41: regressão erro a erro das duas auditorias (31/10 e 01/11), com as conversas reais.

Cada classe cobre um erro e cita o item da auditoria: A10-n (10 atendimentos) e C20-n (conversão, 20 atendimentos).
Os textos do lead são os das conversas reais do Chatwoot; o @ é o real quando a auditoria o cita.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
import unittest

import contracts
import conversao
import conversation
import real_journey as journey
import reconferencia
import retomada
from repository import Repository
from test_release40 import EMY, THAINA, RealCasesTests
from test_relationship_form_chat30 import AT, POLICY

URL = journey.PUBLIC_FORM_URL
AD = 'Oi, quero saber mais sobre agenciamento de creators'
INTERNAL = ('por si só', 'não devem ser prometid', 'Diamond em diante', 'nesta referência', 'não estão informad',
            'Ainda não tenho confirmação de envio', 'não confirma', 'vou pedir para o time', 'Não consegui consultar',
            'Não consegui confirmar os benefícios')


def say(text, state=None, at=AT, planner=None):
    return conversation.handle(state or {}, text, planner, now=at, real_mode=True, operation_policy=POLICY,
                               relationship_check_in_form=True)


def settle(state, effect, status, at=AT, **updates):
    result = dict(operation=effect['operation'], creator=effect['creator'].lstrip('@'), status=status,
                  confirmed=True, observed_at=at.isoformat(), evidence={'source': 'offline', 'complete': True})
    result.update(updates)
    return conversation.resolve_tiktok_result(state, effect['id'], result, now=at, operation_policy=POLICY)


def effect(result, operation):
    return next(item for item in result['effects'] if item['operation'] == operation)


def eligible(handle):
    first = say(AD)
    checking = say(handle, first['state'])
    return settle(checking['state'], effect(checking, 'precheck'), 'eligible')


def invited(handle):
    asked = say('Pode mandar', eligible(handle)['state'])
    return settle(asked['state'], effect(asked, 'invite'), 'sent')


def bridge_down(handle):
    checking = say(handle, say(AD)['state'])
    return settle(checking['state'], effect(checking, 'precheck'), 'verification_pending', confirmed=False,
                  evidence={}, reason='human_verification_required')


def model(reply):
    """Resposta do modelo como chega em produção (o texto é o da conversa real quando a auditoria o cita)."""
    return lambda text, context: {'provider_status': 'completed', 'claims': [], 'intent': 'question', 'reply': reply,
                                  'next_phase': context['phase'], 'topic_ids': []}


class Assertions(unittest.TestCase):
    def clean(self, text):
        for phrase in INTERNAL:
            self.assertNotIn(phrase, text)

    def one_question(self, text):
        self.assertLessEqual(text.count('?'), 1, text)


class GabiosantanaTests(Assertions):
    """A10-3, A10-4, A10-5: pediu o formulário 4 vezes, disse "aceitei" 3 vezes e "Não apareceu o convite"."""

    def test_every_form_request_carries_the_link(self):
        state = invited('@gabiosantana1')['state']
        for text in ('Onde fica o formulário?', 'Não apareceu o formulário', 'Onde fica o formulário?', 'Cadê o link?'):
            with self.subTest(text=text):
                turn = say(text, state)
                self.assertIn(URL, turn['reply'])
                state = turn['state']

    def test_missing_invite_is_checked_and_explained_not_the_form(self):
        turn = say('Não apareceu o convite', invited('@gabiosantana1')['state'])
        # Release 41 (02/11): a Bia confere o convite no TikTok na hora e explica onde aceitar.
        self.assertEqual(turn['reply'], conversao.INVITE_CHECK)
        self.assertNotIn(URL, turn['reply'])
        self.assertEqual([item['operation'] for item in turn['effects']], ['relationship'])
        pending = settle(turn['state'], turn['effects'][0], 'pending')
        self.assertIn('Parcerias', pending['reply'])
        self.assertNotIn(URL, pending['reply'])

    def test_aceitei_checks_once_and_never_says_no_confirmation(self):
        state = invited('@gabiosantana1')['state']
        first = say('aceitei', state)
        self.assertEqual([item['operation'] for item in first['effects']], ['relationship'])
        again = say('aceitei', first['state'])
        self.assertEqual(again['effects'], [])
        for turn in (first, again):
            self.clean(turn['reply'])
        linked = settle(again['state'], first['effects'][0], 'linked')
        self.assertIn(URL, linked['reply'])


class LemosalyceeTests(Assertions):
    """A10-3, A10-7: "Feito" depois do convite ouviu "sem confirmação"; o vínculo saiu e ninguém avisou."""

    def test_feito_checks_the_link_and_the_result_brings_the_form(self):
        turn = say('Feito', invited('@lemosalycee')['state'])
        self.assertEqual([item['operation'] for item in turn['effects']], ['relationship'])
        self.clean(turn['reply'])
        linked = settle(turn['state'], turn['effects'][0], 'linked')
        self.assertIn('vínculo com a Amplify está ativo', linked['reply'])
        self.assertIn(URL, linked['reply'])

    def test_invite_sent_is_never_contradicted(self):
        state = invited('@lemosalycee')['state']
        for text in ('E o convite?', 'Foi enviado?'):
            turn = say(text, state, AT + timedelta(hours=2))
            self.assertNotIn('não tenho confirmação', turn['reply'].lower())

    def test_linked_without_registration_gets_two_reminders_with_the_button(self):
        """C20-5: lembretes em 2 h e 23h30, cada um com o link do cadastro."""
        turn = say('Feito', invited('@lemosalycee')['state'])
        state = settle(turn['state'], turn['effects'][0], 'linked')['state']
        self.assertEqual(retomada.steps_for(state), retomada.LINKED_STEPS)
        texts = [retomada.message(state, step, POLICY)[0] for step in (1, 2)]
        self.assertNotEqual(texts[0], texts[1])
        for text in texts:
            self.assertIn(URL, text)
        state['cadastro_situacao'] = 'confirmado'
        self.assertIsNone(retomada.message(state, 1, POLICY))


class MaRibeirohTests(Assertions):
    """A10-8, C20-6: botão "Fazer cadastro" 4 vezes em 1 minuto; 4 dúvidas sem resposta com convite pendente."""

    def test_button_goes_once_for_four_messages_in_a_row(self):
        state = invited('@ma.ribeiroh')['state']
        links = 0
        for text in ('ok', 'obrigada', 'tá bom', 'certo'):
            turn = say(text, state)
            links += URL in turn['reply']
            state = turn['state']
        self.assertEqual(links, 0)

    def test_each_question_is_answered_cleanly_and_ends_with_the_acceptance_path(self):
        state = invited('@ma.ribeiroh')['state']
        expected = {'Conhecer a Amplify': 'agência', 'Como funciona': 'parceria', 'Benefícios': 'campanhas com marcas',
                    'Comissão': '10%'}
        for text, fragment in expected.items():
            with self.subTest(text=text):
                turn = say(text, deepcopy(state))
                self.assertIn(fragment, turn['reply'])
                self.assertTrue(turn['reply'].endswith(journey._ACCEPT_NEXT_STEP))
                self.assertNotIn('Qual assunto', turn['reply'])
                self.clean(turn['reply'])
                self.one_question(turn['reply'])

    def test_internal_guidance_from_the_model_never_reaches_the_lead(self):
        leaked = ('A Amplify atua com campanhas com marcas e comunidade de creators. O acompanhamento individual e a '
                  'análise de perfil são benefícios de Diamond em diante; não devem ser prometidos às categorias inferiores.')
        turn = say('Benefícios', invited('@ma.ribeiroh')['state'], planner=model(leaked))
        self.assertIn('campanhas com marcas', turn['reply'])
        self.clean(turn['reply'])
        self.assertEqual(turn['state']['history'][-1]['text'], turn['reply'])


class PriscilaTests(Assertions):
    """A10-6, A10-8, C20-1: nome no lugar do @, ponte em verificação, respostas que não respondiam."""

    def test_name_instead_of_handle_explains_where_to_find_it(self):
        state = say(AD)['state']
        for text in ('Priscila Matias', '@Priscila Matias'):
            with self.subTest(text=text):
                turn = say(text, state)
                self.assertEqual(turn['reply'], journey._HANDLE_UNKNOWN)
                self.assertEqual(turn['effects'], [])
                state = turn['state']
        checking = say('@priscila.matias44', state)
        self.assertEqual(checking['reply'], conversao.RECEIVED.format(handle='@priscila.matias44'))

    def test_questions_while_the_bridge_is_down_are_answered(self):
        down = bridge_down('@priscila.matias44')
        self.assertEqual(down['reply'], conversao.BRIDGE_WAIT)
        turn = say('Quero saber sobre os benefícios', down['state'])
        self.assertIn('campanhas com marcas', turn['reply'])
        self.assertTrue(turn['reply'].endswith(conversao.BRIDGE_NOTE))
        paid = say('Recebe pra isso?', down['state'],
                   planner=model('Você ganha a comissão das vendas que fizer como creator no TikTok Shop.'))
        self.assertIn('comissão das vendas', paid['reply'])
        self.assertNotIn('vínculo', paid['reply'])
        for result in (turn, paid):
            self.clean(result['reply'])
            self.assertEqual(result['effects'], [])

    def test_the_bridge_back_continues_without_asking_the_handle_again(self):
        down = bridge_down('@priscila.matias44')
        retry = journey.bridge_retry_effect(down['state'], AT + timedelta(minutes=1))
        back = settle(down['state'], retry, 'eligible')
        self.assertTrue(back['reply'].startswith(conversao.BRIDGE_BACK))
        self.assertNotIn('Qual é o seu @', back['reply'])
        self.assertEqual(back['buttons'], conversao.CONSENT_BUTTONS)


class SarahTests(Assertions):
    """C20-4: o bloco das condições saiu 4 vezes (31/10 17:37, 17:53, 19:38 e 01/11 17:08)."""

    def test_block_once_short_question_after_and_reminders_answer_objections(self):
        first = eligible('@sarahellen.off')
        self.assertIn('prazo de 2 meses', first['reply'])
        state, replies = first['state'], [first['reply']]
        for text in ('ok', 'hm', 'vou ver'):
            turn = say(text, state)
            replies.append(turn['reply'])
            state = turn['state']
        replies += [retomada.message(state, step, POLICY)[0] for step in (1, 2, 3)]
        self.assertEqual(sum('prazo de 2 meses' in text for text in replies), 1)
        self.assertEqual(len(set(replies[-3:])), 3)
        for text in replies:
            self.assertNotIn('de verdade', text)
            self.assertNotIn('convite real', text)

    def test_doubt_button_answers_and_can_send_sends(self):
        state = eligible('@sarahellen.off')['state']
        doubt = say('Tenho uma dúvida', state)
        self.assertEqual(doubt['reply'], conversao.DOUBT)
        sent = say('Pode mandar', doubt['state'])
        self.assertEqual([item['operation'] for item in sent['effects']], ['invite'])
        self.assertEqual(sent['reply'], conversao.INVITING)


class NeverSentHandleTests(Assertions):
    """A10-1, C20-2: 56754, 56750, 56749 e 56745 não responderam nenhuma das 4 mensagens."""

    def test_first_reply_sells_and_three_reminders_each_with_a_new_angle(self):
        first = say(AD)
        self.assertIn('campanhas com marcas', first['reply'])
        self.assertTrue(first['reply'].rstrip().endswith('👇'))
        self.assertEqual(first['buttons'], conversao.FIRST_BUTTONS)
        texts = [first['reply']] + [retomada.message(first['state'], step, POLICY)[0] for step in (1, 2, 3)]
        self.assertEqual(len(set(texts)), 4)
        self.assertEqual(retomada.message(first['state'], 3, POLICY)[1], ['Quero entrar', 'Agora não'])

    def test_the_reminder_buttons_work(self):
        state = say(AD)['state']
        wants = say('Quero entrar', deepcopy(state))
        self.assertEqual(wants['reply'], conversao.WANTS_IN)
        stop = say('Agora não', deepcopy(state))
        self.assertEqual(stop['state']['cycle']['status'], 'closed')


class InformationWithoutNextStepTests(Assertions):
    """A10-5/6/7 (8497, 0346, 4153) e C20-2: informação sem pergunta no fim; o botão "Como funciona?" da 40."""

    def test_each_answer_ends_with_the_handle_request(self):
        for text in ('Como funciona?', 'Quais os benefícios?', 'Conhecer a Amplify', 'Benefícios', 'Comissão'):
            with self.subTest(text=text):
                turn = say(text, say(AD)['state'])
                self.clean(turn['reply'])
                self.one_question(turn['reply'])
                self.assertIn('@ do TikTok', turn['reply'])

    def test_how_it_works_button_is_answered_without_the_model(self):
        turn = say(conversao.FIRST_BUTTONS[1], say(AD)['state'])
        self.assertIn('parceria entre o creator e a agência', turn['reply'])


class AfterMaintenanceTests(Assertions):
    """A10-2: a volta da pausa retoma o pedido de cada lead (39: TenLeadsAfterMaintenanceTests, pós-pausa)."""

    def test_resumed_ad_message_gets_the_selling_reply_with_the_apology(self):
        turn = journey.handle_real({}, AD, None, resumed={'pending': [AD]}, now=AT, operation_policy=POLICY,
                                   relationship_check_in_form=True)
        self.assertIn(journey._RESUME_SORRY, turn['reply'])
        self.assertIn('Me manda seu @ do TikTok', turn['reply'])


class FiveBridgeLeadsTests(RealCasesTests):
    """C20-1: os 5 da ponte (31/10) pelo caminho inteiro, com o anúncio e o @, sem perguntar nome nem origem."""

    LEADS = (EMY, {'conversation': '56746', 'contact': '8803', 'phone': '+5511987654303', 'handle': '@aninharocha.ofc'},
             {'conversation': '56751', 'contact': '8804', 'phone': '+5511987654304', 'handle': '@fabi_augusta'},
             {'conversation': '56748', 'contact': '8805', 'phone': '+5511987654305', 'handle': '@larvitrine'}, THAINA)

    def setUp(self):
        original = contracts.parse_pilot_phones
        extra = ','.join(lead['phone'] for lead in self.LEADS if lead not in (EMY, THAINA))
        patched = lambda value, test: original(value + ',' + extra, test)
        contracts.parse_pilot_phones = patched
        self.addCleanup(setattr, contracts, 'parse_pilot_phones', original)
        super().setUp()

    def reach_precheck(self, lead):
        for text in (AD, lead['handle']):
            self.say(lead, text)
        self.drain()
        return self.repo.load_session('chatwoot:1:' + lead['conversation'])

    def test_all_five_are_rechecked_once_and_continue(self):
        for lead in self.LEADS:
            state = self.reach_precheck(lead)
            self.assertEqual(state['cycle']['phase'], 'blocked')
            texts = self.texts(lead)
            self.assertFalse(any('Como posso te chamar' in text or 'como conheceu' in text.lower() for text in texts))
        thaina = self.repo.load_session('chatwoot:1:56752')
        thaina['cycle'].pop('bridge_wait')  # parou na 39, sem a marca
        self.repo.save_session('chatwoot:1:56752', thaina)
        order = [row['conversation'] for row in reconferencia.candidates(self.repo, self.executor.clock())]
        self.assertEqual(sorted(order), ['chatwoot:1:' + key for key in ('56746', '56747', '56748', '56751', '56752')])
        self.client.up = True
        self.probe()
        for _ in self.LEADS:
            self.assertEqual(self.run_scan()['status'], 'queued')
            self.assertEqual(self.executor.tick()['status'], 'completed')
        self.assertEqual(self.run_scan()['status'], 'idle')
        for lead in self.LEADS:
            with self.subTest(lead=lead['handle']):
                state = self.repo.load_session('chatwoot:1:' + lead['conversation'])
                self.assertEqual(state['cycle']['phase'], 'consent_real')
                texts = self.texts(lead)
                self.assertTrue(texts[-1].startswith(conversao.BRIDGE_BACK))
                self.assertEqual(sum(text == conversao.BRIDGE_WAIT for text in texts), 1)
                self.assertFalse(any('pedir para o time' in text for text in texts))

    test_emy_and_thaina_are_rechecked_once_each_when_the_bridge_returns = None
    test_bridge_flapping_during_the_retry_stays_silent_and_waits_ten_minutes = None
    test_switch_and_status = None


if __name__ == '__main__':
    unittest.main()


class PosPausaPagesTests(unittest.TestCase):
    """02/11, 40.1 no ar: a pós-pausa respondeu 6 de 8 leads e pulou 56866 e 56865.

    O lead de 56866 escreveu em 01/11 às 16:12 e o de 56865 às 13:09 (Brasília). Nos dois casos a última
    mensagem era o aviso de manutenção. As duas conversas estavam abertas, sem etiqueta e sem responsável.
    Elas estavam além das 25 conversas da primeira página do Chatwoot, a única que a 40 lia.
    """
    NOW = datetime(2026, 11, 2, 8, 30, tzinfo=timezone.utc)          # 05:30 de Brasília
    REAL = {56866: datetime(2026, 11, 1, 19, 12, tzinfo=timezone.utc),  # 16:12 de Brasília
            56865: datetime(2026, 11, 1, 16, 9, tzinfo=timezone.utc)}   # 13:09 de Brasília

    def setUp(self):
        from test_release39 import FakeChatwoot, GATE, PHONE
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='regressao41-')
        self.addCleanup(tmp.cleanup)
        self.repo = Repository(Path(tmp.name) / 'state.sqlite3')
        conversations, self.history, phones = [], {}, []
        # 30 conversas abertas mais recentes, de leads fora da lista (receberam só a manutenção).
        for index in range(30):
            conversations.append(self.conversation(57000 + index, '+551190000' + format(index, '04d'),
                                                   self.NOW - timedelta(minutes=10 + 20 * index)))
        for conv, arrived in self.REAL.items():
            phone = '+5511988' + str(conv)[1:] + '0'
            phones.append(phone)
            conversations.append(self.conversation(conv, phone, arrived))
        conversations.sort(key=lambda item: -item['last_activity_at'])
        parsed, issue = contracts.parse_pilot_phones(','.join([PHONE] + phones), PHONE)
        self.assertIsNone(issue)
        self.chatwoot, self.pages = FakeChatwoot(), []
        self.chatwoot.http = lambda **request: self.http(conversations, **request)
        self.calls = []
        self.subject = retomada.PosPausa(self.repo, {'pos_pausa_enabled': True, 'tiktok_mode': 'real',
                                         'real_worker_enabled': True, 'conversation_enabled': True,
                                         'gate': {**GATE, 'phones': parsed}},
                                         self.chatwoot, lambda _: {'allowed': True}, self.process, now=lambda: self.NOW)

    def conversation(self, conv, phone, arrived):
        notice = {'id': conv * 10 + 1, 'message_type': 1, 'private': False, 'content': 'Estamos em manutenção',
                  'content_attributes': {'automation_rule_id': 3}, 'created_at': arrived.timestamp() + 2}
        self.history[conv] = [{'id': conv * 10, 'message_type': 0, 'private': False, 'content': AD,
                               'created_at': arrived.timestamp()}, notice]
        return {'id': conv, 'inbox_id': 3, 'meta': {'sender': {'id': conv, 'phone_number': phone}},
                'last_activity_at': int(arrived.timestamp()) + 2, 'last_non_activity_message': deepcopy(notice)}

    def http(self, conversations, *, method, url, headers, timeout, json_body=None):
        if '/conversations?' in url:
            page = int(re.search(r'[?&]page=(\d+)', url).group(1)) if 'page=' in url else 1
            self.pages.append(page)
            return {'data': {'payload': deepcopy(conversations[25 * (page - 1):25 * page])}}
        return {'payload': deepcopy(self.history[int(url.rsplit('/', 2)[-2])])}

    def process(self, event, resumed):
        self.assertTrue(self.repo.reserve_event(event['source_ref'], 'chatwoot:1:' + str(event['conversation_id']), 'webhook'))
        self.calls.append((event['conversation_id'], resumed['texts']))
        return {'status': 'completed'}

    def scan(self):
        self.subject.next_scan_at = None
        return self.subject.tick()

    def test_both_leads_beyond_the_first_page_are_answered_once(self):
        for _ in range(4):
            self.scan()
        self.assertEqual(sorted(conv for conv, _ in self.calls), [56865, 56866])
        for _, texts in self.calls:
            self.assertEqual(texts, [AD])
        self.pages.clear()
        self.assertEqual(self.scan()['status'], 'idle')
        self.assertEqual(self.pages, [1, 2, 3])  # 32 conversas: a página 3 vem vazia e a leitura para
