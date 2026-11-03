"""Release 41: os 12 ajustes das conversas de 02/11 na 40.2 (ESTADO-DO-ATENDIMENTO.md, seção 5).

Os textos do lead são os citados no documento para cada conversa (56935, 56934, 56933, 56932, 56931, 56937,
56629 e 56866). Quando o documento não traz o texto exato, o teste usa um equivalente e diz isso.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
import unittest

import conversao
import real_journey as journey
import reconferencia
import retomada
from test_regressao41 import AD, Assertions, eligible, invited, model, say, settle
from test_release40 import RealCasesTests
from test_relationship_form_chat30 import AT, POLICY

URL = journey.PUBLIC_FORM_URL
DOWN = 'human_verification_required'
NO_WRITE = {'source': 'offline', 'post_attempted': False}


def invite_down(handle, reason=DOWN):
    """Autorizou, e a ponte de Convites caiu duas vezes sem nada chegar ao TikTok (a 1ª tentativa e a rápida)."""
    asked = say('Pode mandar', eligible(handle)['state'])
    first = settle(asked['state'], asked['effects'][0], 'verification_pending', confirmed=False,
                   evidence=dict(NO_WRITE), reason=reason)
    check = first['effects'][0]
    eligible_again = settle(first['state'], check, 'eligible')
    retry = eligible_again['effects'][0]
    return settle(eligible_again['state'], retry, 'verification_pending', confirmed=False,
                  evidence=dict(NO_WRITE), reason=reason)


class CristianeAfterAccessTests(Assertions):
    """1 e 2 (56935, @mydearshop8): acesso liberado às 08:21, "convite continua" às 10:03, sem resposta às 10:27 e 12:33."""

    def registered(self):
        state = invited('@mydearshop8')['state']
        # O formulário marcou o cadastro e encerrou o atendimento no banco; a ficha chega pelo registro de contato.
        state['cadastro_situacao'] = 'confirmado'
        return state

    def test_ja_aceitei_after_access_is_answered_in_a_new_attendance(self):
        state = self.registered()
        old_cycle = state['cycle']['id']
        turn = say('Já aceitei', state)
        self.assertEqual(turn['reply'], conversao.ACCESS_DONE)
        self.assertNotEqual(turn['state']['cycle']['id'], old_cycle)
        self.assertEqual(turn['state']['closed_cycles'][-1]['reason'], 'cadastro_confirmado')
        self.assertEqual(turn['state']['cycle']['phase'], 'acesso')
        self.assertEqual(turn['effects'], [])
        self.assertNotIn(URL, turn['reply'])

    def test_missions_question_is_answered_without_promising_dates(self):
        first = say('Já aceitei', self.registered())
        turn = say('Quando vou ter as minhas primeiras missões?', first['state'])
        self.assertEqual(turn['reply'], conversao.MISSIONS)
        self.assertEqual(turn['state']['cycle']['id'], first['state']['cycle']['id'])
        self.assertNotRegex(turn['reply'], r'\d+\s*(?:dias|horas|semanas)')
        self.clean(turn['reply'])

    def test_other_questions_after_access_never_restart_the_funnel(self):
        state = say('Já aceitei', self.registered())['state']
        for text in ('Como funciona?', 'Benefícios', 'Tem amostra grátis?', 'oi'):
            with self.subTest(text=text):
                turn = say(text, deepcopy(state))
                self.assertEqual(turn['effects'], [])
                self.assertNotIn('@ do TikTok', turn['reply'])
                self.assertNotIn('Posso te mandar o convite', turn['reply'])
                self.clean(turn['reply'])

    def test_no_invite_reminder_once_the_registration_is_confirmed(self):
        state = self.registered()
        for step in (1, 2, 3):
            self.assertIsNone(retomada.message(state, step, POLICY))

    def test_the_test_number_reset_still_runs_the_funnel(self):
        state = self.registered()
        reset = say('resetar', state)
        self.assertEqual(reset['state']['cycle']['phase'], 'intro')
        first = say(AD, reset['state'])
        self.assertIn('Me manda seu @ do TikTok', first['reply'])


class ReminderReadsTheRecordTests(unittest.TestCase):
    """2: a retomada lê a ficha antes de cada lembrete; 8: só das 8h às 21h (Brasília)."""

    def setUp(self):
        from test_release39 import RetomadaTests
        self.case = RetomadaTests('test_messages_per_stage')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def subject(self, registration):
        case = self.case
        return retomada.Retomada(case.repo, case.settings, case.chatwoot, lambda _: case.lock, lambda _: case.allowed,
                                 now=lambda: case.clock, policy=lambda: POLICY, registration=registration)

    def tick(self, subject, after):
        self.case.clock = self.case.inbound_at + after
        subject.next_scan_at = None
        return subject.tick()

    def test_confirmed_registration_stops_the_reminder(self):
        calls = []
        subject = self.subject(lambda event: calls.append(event['message_id']) or 'confirmado')
        self.tick(subject, timedelta(minutes=16))
        self.assertEqual(self.case.chatwoot.sent, [])
        self.assertEqual(calls, ['700'])
        self.assertEqual(self.case.repo.load_session(self.case.CONV)['cadastro_situacao'], 'confirmado')

    def test_unreadable_record_sends_nothing(self):
        subject = self.subject(lambda event: None)
        self.tick(subject, timedelta(minutes=16))
        self.assertEqual(self.case.chatwoot.sent, [])

    def test_pending_record_sends_the_reminder(self):
        subject = self.subject(lambda event: 'pendente')
        self.tick(subject, timedelta(minutes=16))
        self.assertEqual(len(self.case.chatwoot.sent), 1)



class QuietHoursTests(unittest.TestCase):
    """8: lembretes só das 8h às 21h (Brasília); o vencido de madrugada espera as 8h e sai uma vez só."""

    def test_send_hours_are_8_to_21_brasilia(self):
        # 56935, 02/11: 1ª resposta às 05:09 e lembretes às 05:24 e 07:10 (Brasília).
        for hour, allowed in ((5, False), (7, False), (8, True), (12, True), (20, True), (21, False), (23, False)):
            with self.subTest(hour=hour):
                at = datetime(2026, 11, 2, hour, 24, tzinfo=retomada.BRASILIA)
                self.assertEqual(retomada.send_hour(at), allowed)

    def test_reminder_due_at_night_waits_and_then_goes_once(self):
        from unittest.mock import patch
        from test_release39 import RetomadaTests
        case = RetomadaTests('test_messages_per_stage')
        case.setUp()
        self.addCleanup(case.doCleanups)
        with patch('retomada.send_hour', return_value=False):
            case.tick_at(timedelta(minutes=16))
            case.tick_at(timedelta(hours=2, minutes=1))
        self.assertEqual(case.chatwoot.sent, [])
        case.tick_at(timedelta(hours=2, minutes=5))  # 8h: as etapas vencidas viram um lembrete só
        self.assertEqual(len(case.chatwoot.sent), 1)


class ConsentQuestionTests(Assertions):
    """3 e 12 (56932, 56934; amostras também em 56931 e 56933): a dúvida é respondida antes do pedido."""

    def test_samples_question_is_answered_then_the_request_is_repeated_once(self):
        state = eligible('@lead56932')['state']
        turn = say('Tem amostra grátis?', state)
        self.assertTrue(turn['reply'].startswith(conversao.SAMPLES))
        self.assertTrue(turn['reply'].rstrip().endswith(conversao.CONSENT_QUESTION))
        self.assertEqual(turn['reply'].count('?'), 1)
        self.assertNotIn('não garante', turn['reply'].lower())
        self.assertEqual(turn['buttons'], conversao.CONSENT_BUTTONS)

    def test_campaigns_question_is_answered_then_the_request(self):
        turn = say('Vocês arrumam campanhas?', eligible('@lead56934')['state'])
        self.assertIn('campanhas com marcas', turn['reply'])
        self.assertTrue(turn['reply'].rstrip().endswith(conversao.CONSENT_QUESTION))

    def test_negative_model_answer_about_samples_is_replaced(self):
        negative = 'A Amplify não garante amostras grátis e não promete campanhas.'
        turn = say('Tem amostra grátis?', eligible('@lead56931')['state'], planner=model(negative))
        self.assertTrue(turn['reply'].startswith(conversao.SAMPLES))
        self.assertNotIn('não garante', turn['reply'])


class ExpiredValidationTests(Assertions):
    """4 (56933, 56934): "Pode mandar" depois que a validação venceu nunca pede a autorização de novo."""

    def test_pode_mandar_after_expiry_refreshes_silently_and_sends(self):
        state = eligible('@gabinaresse')['state']
        later = AT + timedelta(minutes=30)
        turn = say('Pode mandar', state, later)
        self.assertEqual(turn['reply'], conversao.INVITING)
        self.assertEqual([item['operation'] for item in turn['effects']], ['precheck'])
        fresh = settle(turn['state'], turn['effects'][0], 'eligible', later)
        self.assertEqual(fresh['reply'], '')
        self.assertEqual([item['operation'] for item in fresh['effects']], ['invite'])
        sent = settle(fresh['state'], fresh['effects'][0], 'sent', later)
        self.assertIn('convite foi enviado', sent['reply'])
        asks = [item['text'] for item in sent['state']['history']
                if item['direction'] == 'outbound' and conversao.CONSENT_QUESTION[:-1] in item['text']]
        self.assertEqual(len(asks), 1)  # só o pedido original


class InviteBridgeTests(Assertions):
    """5 (@gabinaresse, 56933): convite parado em "verificação de segurança" desde 10:43."""

    def test_invite_bridge_down_is_announced_once_and_retried_by_the_scan(self):
        down = invite_down('@gabinaresse')
        self.assertEqual(down['reply'], conversao.INVITE_WAIT)
        state = down['state']
        self.assertEqual(state['cycle']['phase'], 'blocked')
        self.assertTrue(journey.invite_retry_due(state, AT))
        question = say('E aí, foi?', deepcopy(state))
        self.assertIn('anotada', question['reply'])
        retry = journey.invite_retry_effect(state, AT)
        self.assertEqual(retry['operation'], 'precheck')
        checked = settle(state, retry, 'eligible')
        self.assertEqual(checked['reply'], '')
        invite = checked['effects'][0]
        self.assertEqual(invite['operation'], 'invite')
        self.assertEqual(invite['payload']['retry'], 2)
        sent = settle(checked['state'], invite, 'sent')
        self.assertIn('convite foi enviado', sent['reply'])
        self.assertNotIn('invite_wait', sent['state']['cycle'])

    def test_a_failed_retry_stays_silent_and_stops_after_three(self):
        state = invite_down('@gabinaresse')['state']
        at = AT
        for attempt in range(journey.INVITE_BRIDGE_RETRY_LIMIT):
            retry = journey.invite_retry_effect(state, at)
            self.assertIsNotNone(retry, attempt)
            checked = settle(state, retry, 'eligible', at)
            failed = settle(checked['state'], checked['effects'][0], 'verification_pending', at, confirmed=False,
                            evidence=dict(NO_WRITE), reason=DOWN)
            self.assertEqual(failed['reply'], '')
            state, at = failed['state'], at + journey.BRIDGE_RETRY_GAP
        self.assertFalse(journey.invite_retry_due(state, at))

    def test_never_resent_without_proof_that_nothing_reached_tiktok(self):
        asked = say('Pode mandar', eligible('@gabinaresse')['state'])
        unknown = settle(asked['state'], asked['effects'][0], 'outcome_unknown', confirmed=False,
                         evidence={'post_attempted': True}, reason=DOWN)
        self.assertNotIn('invite_wait', unknown['state']['cycle'])
        self.assertFalse(journey.invite_retry_due(unknown['state'], AT, forced=True))

    def test_scan_reads_the_invites_bridge_and_lists_the_lead(self):
        from test_release39 import Repository  # noqa: F401
        state = invite_down('@gabinaresse')['state']

        class Repo:
            def precheck_conversations(self):
                return ['chatwoot:1:56933']

            def load_session(self, conv):
                return deepcopy(state)

        rows = reconferencia.candidates(Repo(), AT)
        self.assertEqual([(row['conversation'], row['kind']) for row in rows], [('chatwoot:1:56933', 'invite')])
        seen = []
        scan = reconferencia.Reconferencia(Repo(), {'reconferencia_enabled': True, 'tiktok_mode': 'real',
                                                    'real_worker_enabled': True, 'conversation_enabled': True,
                                                    'gate': {'enabled': True}},
                                           lambda kind: seen.append(kind) or True,
                                           lambda conv, reason, forced=False, kind='precheck': {'status': 'queued'})
        self.assertEqual(scan.tick()['status'], 'queued')
        self.assertEqual(seen, ['invite'])


class PriorInviteTests(Assertions):
    """6 (56629, ma.ribeiroh): "Há uma solicitação anterior… vou preservar"; "não aparece nada para eu aceitar"."""

    def prior(self):
        old = invited('@ma.ribeiroh')['state']
        reset = say('resetar', old)
        first = say(AD, reset['state'])
        checking = say('@ma.ribeiroh', first['state'])
        return settle(checking['state'], next(item for item in checking['effects'] if item['operation'] == 'precheck'),
                      'eligible')

    def test_old_invite_is_checked_instead_of_blocking(self):
        turn = say('Pode mandar', self.prior()['state'])
        self.assertEqual(turn['reply'], conversao.PRIOR_INVITE_CHECK)
        self.assertEqual([item['operation'] for item in turn['effects']], ['relationship'])
        self.assertNotIn('vou preservar', turn['reply'].lower())

    def test_pending_old_invite_gets_the_step_by_step(self):
        turn = say('Pode mandar', self.prior()['state'])
        pending = settle(turn['state'], turn['effects'][0], 'pending')
        self.assertEqual(pending['reply'], conversao.INVITE_STEPS)
        self.assertEqual(pending['buttons'], ['Já aceitei'])

    def test_expired_old_invite_is_sent_again_without_a_new_consent(self):
        turn = say('Pode mandar', self.prior()['state'])
        gone = settle(turn['state'], turn['effects'][0], 'not_found')
        self.assertEqual(gone['reply'], conversao.PRIOR_INVITE_RESENT)
        self.assertEqual([item['operation'] for item in gone['effects']], ['invite'])

    def test_linked_old_invite_goes_to_the_form(self):
        turn = say('Pode mandar', self.prior()['state'])
        linked = settle(turn['state'], turn['effects'][0], 'linked')
        self.assertIn(URL, linked['reply'])

    def test_nothing_to_accept_checks_the_invite_now(self):
        turn = say('não aparece nada para eu aceitar', invited('@ma.ribeiroh')['state'])
        self.assertEqual(turn['reply'], conversao.INVITE_CHECK)
        self.assertEqual([item['operation'] for item in turn['effects']], ['relationship'])


class ProfileLinkTests(Assertions):
    """7 (56934): o link do perfil fez a lead levar 3 h para responder ("Valeu pelo link! … me manda seu @").

    O documento não traz o @ dessa lead; o teste usa um link equivalente.
    """

    def test_handle_is_taken_from_the_profile_link(self):
        for text in ('https://www.tiktok.com/@lead.56934?_t=8rT&_r=1', 'tiktok.com/@lead.56934',
                     'Esse é meu perfil: https://m.tiktok.com/@Lead.56934'):
            with self.subTest(text=text):
                turn = say(text, say(AD)['state'])
                self.assertEqual(turn['reply'], conversao.RECEIVED.format(handle='@lead.56934'))
                self.assertIn('precheck', {item['operation'] for item in turn['effects']})

    def test_short_link_without_handle_is_not_guessed(self):
        self.assertIsNone(journey.profile_link_handle('https://vm.tiktok.com/ZMabc123/'))


class FirstMessageTests(Assertions):
    """9 (56935, 56933, 56931, 56866): "como prefere ser chamada?" e "me manda seu @" na 1ª mensagem."""

    def test_model_name_question_is_removed_before_the_handle_request(self):
        text = ('Oi! Aqui é a Bia, da Amplify 💙 Que bom que você quer saber do agenciamento! '
                'Como prefere ser chamada? Me manda também seu @ do TikTok?')
        turn = say('Oi, tudo bem? Vi o anúncio', None, planner=model(text))
        self.assertNotRegex(turn['reply'].lower(), r'prefere ser chamad|como posso te chamar|seu nome')
        self.one_question(turn['reply'])
        self.assertIn('@ do TikTok', turn['reply'])


class NameInsteadOfHandleTests(Assertions):
    """10 (56937): "Andressa Tonin" duas vezes e a Bia só repetiu o pedido."""

    def test_name_twice_gets_the_explanation_twice(self):
        state = say(AD)['state']
        for _ in range(2):
            turn = say('Andressa Tonin', state)
            self.assertEqual(turn['reply'], journey._HANDLE_UNKNOWN)
            self.assertIn('@seuperfil', turn['reply'])
            state = turn['state']


class ShopStepsTests(Assertions):
    """11 (56937): "Shop sem status" e "Como faço isso?" recebeu a mesma frase."""

    def test_how_do_i_do_it_gets_the_step_by_step(self):
        checking = say('@lead56937', say(AD)['state'])
        precheck = next(item for item in checking['effects'] if item['operation'] == 'precheck')
        unknown = settle(checking['state'], precheck, 'verification_pending', confirmed=False, evidence={},
                         reason='shop_unknown')
        self.assertEqual(unknown['reply'], conversao.SHOP_UNKNOWN)
        turn = say('Como faço isso?', unknown['state'])
        self.assertEqual(turn['reply'], conversao.SHOP_STEPS)
        self.assertEqual(turn['effects'], [])
        # Release 43 (tabela 5b): o "pronto" reconfere no máximo a cada 10 min.
        soon = say('pronto', turn['state'])
        self.assertEqual((soon['reply'], soon['effects']), (conversao.SHOP_RECHECK_SOON, []))
        ready = say('pronto', soon['state'], AT + timedelta(minutes=10))
        self.assertEqual([item['operation'] for item in ready['effects']], ['precheck'])


class CristianeServerTests(RealCasesTests):
    """1 pelo caminho inteiro do servidor: o formulário encerra o atendimento no banco e a Bia segue respondendo."""

    LEAD = {'conversation': '56935', 'contact': '8935', 'phone': '+5511987654335', 'handle': '@mydearshop8'}

    def setUp(self):
        import contracts
        original = contracts.parse_pilot_phones
        contracts.parse_pilot_phones = lambda value, test: original(value + ',' + self.LEAD['phone'], test)
        self.addCleanup(setattr, contracts, 'parse_pilot_phones', original)
        super().setUp()
        test = self

        class Gateway:
            """O banco: o registro de contato recusa reabrir o atendimento que o formulário encerrou."""
            closed, situacao = set(), 'pendente'

            def register_contact(self, entry):
                if entry.get('atendimento_id') in self.closed and entry.get('situacao') == 'aberto':
                    raise ValueError('contato_terminal_or_clock_regression')
                return {'creator_id': '22222222-2222-4222-8222-222222222222', 'atendimento_id': entry['atendimento_id'],
                        'event_id': entry['event_id'], 'revision': entry['revision'], 'cadastro_situacao': self.situacao}

        self.gateway = Gateway()
        self.app.extensions['v5_data_gateway'] = self.gateway
        original_execute = self.client.execute

        def execute(operation, creator, **kwargs):
            if operation == 'invite':
                test.client.calls.append((operation, creator))
                return {'operation': operation, 'creator': creator, 'status': 'sent', 'confirmed': True,
                        'observed_at': datetime.now(timezone.utc).isoformat(),
                        'evidence': {'source': 'offline', 'complete': True, 'create_accepted': True}}
            return original_execute(operation, creator, **kwargs)
        self.client.execute = execute
        self.client.up = True

    def test_after_the_form_the_next_messages_are_answered(self):
        lead = self.LEAD
        self.say(lead, AD)
        self.say(lead, lead['handle'])
        self.drain()
        self.say(lead, 'Pode mandar')
        self.drain()
        state = self.repo.load_session('chatwoot:1:' + lead['conversation'])
        self.assertIn('convite foi enviado', self.texts(lead)[-1])
        # 08:21: o formulário confirma o cadastro e encerra o atendimento aberto no banco.
        self.gateway.closed.add(state['cycle']['id'])
        self.gateway.situacao = 'confirmado'
        self.say(lead, 'Já aceitei')
        self.assertEqual(self.texts(lead)[-1], conversao.ACCESS_DONE)
        self.say(lead, 'Quando vou ter as minhas primeiras missões?')
        self.assertEqual(self.texts(lead)[-1], conversao.MISSIONS)

    test_emy_and_thaina_are_rechecked_once_each_when_the_bridge_returns = None
    test_bridge_flapping_during_the_retry_stays_silent_and_waits_ten_minutes = None
    test_switch_and_status = None


if __name__ == '__main__':
    unittest.main()
