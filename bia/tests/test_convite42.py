"""Release 42: a lista de vínculos da ponte de Agenciamento como prova e o acompanhamento do convite.

Casos reais de 02/11, lidos na lista de vínculos (status not_found, pending ou linked, com evidência completa e recente):
- @gabinaresse (56933): not_found. O convite nunca chegou ao TikTok; a Bia tinha o convite em verification_pending,
  sem evidência, e não reenviava;
- @viralstoresbr (56932): linked. Aceitou e não avisou; nunca recebeu o cadastro;
- @ma.ribeiroh (56629) e @sabrinasalazar33 (56931): pending.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
import unittest

import conversao
import real_journey as journey
import reconferencia
import retomada
from test_regressao41 import AD, eligible, invited, say, settle
from test_release40 import RealCasesTests
from test_relationship_form_chat30 import AT

URL = journey.PUBLIC_FORM_URL
DOWN = 'human_verification_required'
LIST = {'source': 'partner_relations', 'fresh': True, 'complete': True}
PENDING = {'relation_id': '7300000000000000001', 'status': 'solicitada', 'tiktok_status': 2,
           'source': 'partner_relations', 'fresh': True, 'complete': True}
LINKED = {'relation_id': '7300000000000000002', 'status': 'vinculado', 'tiktok_status': 1,
          'source': 'partner_relations', 'fresh': True, 'complete': True}
TEXT_1 = ('Pronto! Seu convite da Amplify foi enviado agora 🎉 Abra o TikTok Shop Creator → Parcerias ou Notificações → '
          'aceite o convite da Amplify. Quando aceitar, eu já fico sabendo e te mando o cadastro 😊')
TEXT_2 = ('Vi aqui que você aceitou o convite! 🎉 Agora falta só o cadastro, e seu acesso ao Club sai na hora em que '
          'você envia.\n\n' + URL)
TEXT_3 = ('Seu convite está lá, sim! 😊 Para achar:\n1. Abra o TikTok Shop Creator (não é o TikTok comum)\n'
          '2. Toque em Parcerias (ou no sininho de Notificações)\n3. Procure o convite da Amplify e toque em Aceitar.\n\n'
          'Se não achar mesmo, me avisa que eu envio de novo.')


def invite_unknown(handle):
    """Como ficou @gabinaresse: autorizou e o convite voltou "em verificação", sem nenhuma evidência."""
    asked = say('Pode mandar', eligible(handle)['state'])
    return settle(asked['state'], next(item for item in asked['effects'] if item['operation'] == 'invite'),
                  'verification_pending', confirmed=False, evidence={}, reason=DOWN)


def operations(result):
    return [item['operation'] for item in result['effects']]


def outbound(state):
    return [item['text'] for item in state['history'] if item['direction'] == 'outbound']


class DaytimeTests(unittest.TestCase):
    """As leituras viram mensagem, então só correm das 8h às 21h; aqui o relógio é sempre de dia."""

    def setUp(self):
        original = retomada.send_hour
        retomada.send_hour = lambda now: True
        self.addCleanup(setattr, retomada, 'send_hour', original)


class Gabinaresse56933Tests(DaytimeTests):
    """@gabinaresse (56933): not_found na lista; o convite incerto é reenviado uma vez, com o texto 1."""

    def resend(self, status='sent'):
        state = invite_unknown('@gabinaresse')['state']
        at = AT + timedelta(minutes=20)
        read = journey.agency_read_effect(state, at)
        gone = settle(state, read, 'not_found', at, evidence=dict(LIST))
        fresh = settle(gone['state'], gone['effects'][0], 'eligible', at)
        return read, gone, fresh, settle(fresh['state'], fresh['effects'][0], status, at)

    def test_uncertain_invite_is_resent_once_when_the_list_shows_nothing(self):
        down = invite_unknown('@gabinaresse')
        state = down['state']
        self.assertEqual(state['cycle']['phase'], 'blocked')
        self.assertFalse(journey.invite_retry_due(state, AT, forced=True))  # sem prova de "nada chegou", a 41 não reenviava
        self.assertFalse(journey.list_proof_due(state, AT + timedelta(minutes=4)))  # a lista só vale 5 min depois (43)
        self.assertEqual(journey.agency_read_due(state, AT + timedelta(minutes=15)), 'invite_list_proof')
        read, gone, fresh, sent = self.resend()
        self.assertEqual((read['operation'], read['payload']['source']), ('relationship', 'invite_list_proof'))
        self.assertEqual((gone['reply'], operations(gone)), ('', ['precheck']))  # validação vencida: refaz em silêncio
        self.assertEqual((fresh['reply'], operations(fresh)), ('', ['invite']))
        self.assertTrue(fresh['effects'][0]['payload']['list_proof'])
        self.assertEqual(sent['reply'], TEXT_1)
        self.assertEqual(outbound(sent['state'])[-1], TEXT_1)  # os dois emojis, exatamente como aprovado
        self.assertEqual(sent['state']['cycle']['phase'], 'await_acceptance')
        self.assertIn('@gabinaresse', sent['state']['invite_resends'])

    def test_the_name_goes_in_text_1(self):
        state = invite_unknown('@gabinaresse')['state']
        state['cycle']['facts']['nome_declarado'] = 'Gabriela Naresse'
        at = AT + timedelta(minutes=20)
        gone = settle(state, journey.agency_read_effect(state, at), 'not_found', at, evidence=dict(LIST))
        fresh = settle(gone['state'], gone['effects'][0], 'eligible', at)
        sent = settle(fresh['state'], fresh['effects'][0], 'sent', at)
        self.assertEqual(sent['reply'], TEXT_1.replace('Pronto!', 'Pronto, Gabriela!'))

    def test_pending_or_linked_on_the_list_never_resends(self):
        at = AT + timedelta(minutes=15)
        state = invite_unknown('@gabinaresse')['state']
        pending = settle(state, journey.agency_read_effect(state, at), 'pending', at, evidence=dict(PENDING))
        self.assertEqual((pending['reply'], operations(pending)), (conversao.INVITE_STEPS, []))
        self.assertFalse(journey.list_proof_due(pending['state'], at + timedelta(hours=1)))
        state = invite_unknown('@gabinaresse')['state']
        linked = settle(state, journey.agency_read_effect(state, at), 'linked', at, evidence=dict(LINKED))
        self.assertEqual((linked['reply'], operations(linked)), (TEXT_2, []))
        for result in (pending, linked):
            self.assertNotIn('invite_resends', result['state'])

    def test_an_incomplete_or_stale_list_is_not_proof(self):
        at = AT + timedelta(minutes=15)
        state = invite_unknown('@gabinaresse')['state']
        partial = settle(state, journey.agency_read_effect(state, at), 'not_found', at,
                         evidence={'source': 'partner_relations', 'fresh': True, 'complete': False})
        self.assertEqual((partial['reply'], operations(partial)), ('', []))
        state = invite_unknown('@gabinaresse')['state']
        gone = settle(state, journey.agency_read_effect(state, at), 'not_found', at, evidence=dict(LIST))
        late = settle(gone['state'], gone['effects'][0], 'eligible', at + timedelta(minutes=31)) if gone['effects'] else gone
        self.assertEqual((late['reply'], operations(late)), ('', []))  # a leitura passou de 30 min: não vale mais

    def test_profile_bridge_down_during_the_resend_reads_the_list_again_later(self):
        state = invite_unknown('@gabinaresse')['state']
        at = AT + timedelta(minutes=20)
        gone = settle(state, journey.agency_read_effect(state, at), 'not_found', at, evidence=dict(LIST))
        down = settle(gone['state'], gone['effects'][0], 'verification_pending', at, confirmed=False, evidence={},
                      reason=DOWN)
        self.assertEqual((down['reply'], operations(down)), ('', []))
        self.assertFalse(journey.list_proof_due(down['state'], at + timedelta(minutes=14)))
        self.assertTrue(journey.list_proof_due(down['state'], at + timedelta(minutes=15)))
        self.assertNotIn('invite_resends', down['state'])

    def test_only_one_resend_per_lead(self):
        sent = self.resend('failed')[-1]
        self.assertEqual((sent['reply'], sent['state']['cycle']['phase']), (conversao.INVITE_FAILED_TEAM, 'blocked'))
        later = AT + timedelta(hours=2)
        self.assertIsNone(journey.agency_read_due(sent['state'], later))
        self.assertFalse(journey.invite_retry_due(sent['state'], later, forced=True))

    def test_a_failed_read_stays_silent_waits_15_minutes_and_stops_after_three(self):
        state = invite_unknown('@gabinaresse')['state']
        at = AT + timedelta(minutes=15)
        for attempt in range(journey.LIST_PROOF_READ_LIMIT):
            self.assertFalse(journey.list_proof_due(state, at - timedelta(minutes=1)) and attempt, attempt)
            read = journey.agency_read_effect(state, at)
            self.assertIsNotNone(read, attempt)
            failed = settle(state, read, 'verification_pending', at, confirmed=False, evidence={}, reason=DOWN)
            self.assertEqual(failed['reply'], '')
            state, at = failed['state'], at + journey.AGENCY_READ_GAP
        self.assertIsNone(journey.agency_read_due(state, at))

    def test_reads_only_from_8_to_21_brasilia(self):
        state = invite_unknown('@gabinaresse')['state']
        state['cycle']['expires_at'] = (AT + timedelta(days=3)).isoformat()
        retomada.send_hour = type(self).real_send_hour
        night = (AT + timedelta(minutes=20)).astimezone(retomada.BRASILIA)
        night = night.replace(hour=23, minute=0) if night.hour < 23 else night
        morning = (night + timedelta(days=1)).replace(hour=8, minute=0)
        self.assertFalse(journey.list_proof_due(state, night))
        self.assertFalse(journey.list_proof_due(state, morning.replace(hour=20, minute=50)))  # o resultado sairia depois das 21h
        self.assertTrue(journey.list_proof_due(state, morning))

    real_send_hour = staticmethod(retomada.send_hour)


class Viralstoresbr56932Tests(DaytimeTests):
    """@viralstoresbr (56932): linked na lista; aceitou e não avisou. A Bia vê e manda o texto 2 com o botão."""

    def test_acceptance_seen_by_the_bia_sends_text_2_with_the_button(self):
        state = invited('@viralstoresbr')['state']
        self.assertFalse(journey.tracking_due(state, AT + timedelta(minutes=10)))
        at = AT + timedelta(minutes=15)
        read = journey.agency_read_effect(state, at)
        self.assertEqual(read['payload']['source'], 'invite_tracking')
        linked = settle(state, read, 'linked', at, evidence=dict(LINKED))
        self.assertEqual((linked['reply'], linked['buttons']), (TEXT_2, []))
        self.assertEqual(linked['state']['cycle']['phase'], 'form')
        self.assertIsNone(journey.agency_read_due(linked['state'], at + timedelta(hours=3)))

    def test_nothing_changed_sends_nothing(self):
        state = invited('@viralstoresbr')['state']
        at = AT + timedelta(minutes=15)
        same = settle(state, journey.agency_read_effect(state, at), 'pending', at, evidence=dict(PENDING))
        self.assertEqual((same['reply'], operations(same)), ('', []))
        self.assertFalse(journey.tracking_due(same['state'], at + timedelta(minutes=14)))
        self.assertTrue(journey.tracking_due(same['state'], at + timedelta(minutes=15)))

    def test_registered_lead_is_not_read(self):
        state = invited('@viralstoresbr')['state']
        state['cadastro_situacao'] = 'confirmado'
        self.assertIsNone(journey.agency_read_due(state, AT + timedelta(hours=1)))

    def test_linked_after_the_registration_sends_nothing(self):
        state = invited('@viralstoresbr')['state']
        at = AT + timedelta(minutes=15)
        read = journey.agency_read_effect(state, at)
        state['cadastro_situacao'] = 'confirmado'
        linked = settle(state, read, 'linked', at, evidence=dict(LINKED))
        self.assertEqual(linked['reply'], '')


class PendingInvite56629And56931Tests(DaytimeTests):
    """@ma.ribeiroh (56629) e @sabrinasalazar33 (56931): pending na lista."""

    def keep_open(self, state, until):
        state['cycle']['expires_at'] = (until + timedelta(days=1)).isoformat()
        return state

    def test_schedule_15_minutes_2_hours_then_daily_for_7_days(self):
        self.assertEqual(journey.tracking_interval(timedelta(minutes=119)), timedelta(minutes=15))
        self.assertEqual(journey.tracking_interval(timedelta(hours=2)), timedelta(hours=2))
        self.assertEqual(journey.tracking_interval(timedelta(hours=47, minutes=59)), timedelta(hours=2))
        self.assertEqual(journey.tracking_interval(timedelta(hours=48)), timedelta(days=1))
        state = self.keep_open(invited('@sabrinasalazar33')['state'], AT + timedelta(days=8))
        reads, at, sent = [], AT, len(outbound(state))
        while at < AT + timedelta(days=8):
            read = journey.agency_read_effect(state, at)
            if read:
                reads.append(at)
                state = settle(state, read, 'pending', at, evidence=dict(PENDING))['state']
                self.assertEqual(len(outbound(state)), sent)  # leitura sem novidade: nenhuma mensagem
            at += timedelta(minutes=5)
        gaps = [(later - AT, later - earlier) for earlier, later in zip([AT] + reads, reads)]
        for age, gap in gaps:
            self.assertEqual(gap, journey.tracking_interval(age), age)
        self.assertEqual(sum(age < timedelta(hours=2) for age, _ in gaps), 7)
        self.assertLess(reads[-1] - AT, timedelta(days=7))
        self.assertEqual(len(reads), 7 + 23 + 5)  # 15 a 105 min; 3h45 a 47h45; 71h45 a 167h45

    def test_nao_aparece_with_a_pending_invite_gets_text_3(self):
        state = invited('@ma.ribeiroh')['state']
        turn = say('não aparece nada para eu aceitar', state, AT + timedelta(minutes=20))
        self.assertEqual(turn['reply'], conversao.INVITE_CHECK)
        pending = settle(turn['state'], turn['effects'][0], 'pending', AT + timedelta(minutes=20), evidence=dict(PENDING))
        self.assertEqual((pending['reply'], operations(pending)), (TEXT_3, []))
        self.assertEqual(outbound(pending['state'])[-1], TEXT_3)

    def test_after_48_hours_saying_it_again_repeats_text_3_without_a_new_invite(self):
        state = invited('@sabrinasalazar33')['state']
        for hours in (20, 40):
            state = say('Oi, ainda estou esperando', state, AT + timedelta(hours=hours))['state']
        at = AT + timedelta(hours=49)
        for text in ('Não apareceu o convite', 'Ainda não aparece o convite'):
            turn = say(text, state, at)
            again = settle(turn['state'], turn['effects'][0], 'pending', at, evidence=dict(PENDING))
            self.assertEqual((again['reply'], operations(again)), (TEXT_3, []))
            state, at = again['state'], at + timedelta(minutes=30)
        invites = [e for e in state['effects'].values() if e.get('operation') == 'invite']
        self.assertEqual(len(invites), 1)  # a ponte não cancela convite: nada de reenvio com o convite pendente

    def test_invite_gone_when_the_lead_says_it_is_missing_is_resent_once(self):
        state = invited('@sabrinasalazar33')['state']
        at = AT + timedelta(minutes=20)
        turn = say('Não apareceu o convite', state, at)
        gone = settle(turn['state'], turn['effects'][0], 'not_found', at, evidence=dict(LIST))
        fresh = settle(gone['state'], gone['effects'][0], 'eligible', at)
        sent = settle(fresh['state'], fresh['effects'][0], 'sent', at)
        self.assertEqual(sent['reply'], TEXT_1)
        at += timedelta(hours=1)
        turn = say('Não apareceu o convite', sent['state'], at)
        gone = settle(turn['state'], turn['effects'][0], 'not_found', at, evidence=dict(LIST))
        self.assertNotIn('invite', operations(gone))  # 1 reenvio por lead
        self.assertNotIn('enviado agora', gone['reply'])

    def test_old_invite_found_pending_is_followed_until_linked(self):
        # 56629: o convite é de um atendimento anterior; "Pode mandar" confere e acha o convite pendente.
        old = invited('@ma.ribeiroh')['state']
        first = say(AD, say('resetar', old)['state'])
        checking = say('@ma.ribeiroh', first['state'])
        ready = settle(checking['state'], next(e for e in checking['effects'] if e['operation'] == 'precheck'), 'eligible')
        turn = say('Pode mandar', ready['state'])
        pending = settle(turn['state'], turn['effects'][0], 'pending', evidence=dict(PENDING))
        self.assertEqual(pending['reply'], conversao.INVITE_STEPS)
        at = AT + timedelta(minutes=15)
        read = journey.agency_read_effect(pending['state'], at)
        self.assertEqual(read['payload']['source'], 'invite_tracking')
        linked = settle(pending['state'], read, 'linked', at, evidence=dict(LINKED))
        self.assertEqual(linked['reply'], TEXT_2)


class ScanTests(DaytimeTests):
    def test_scan_reads_the_agency_bridge_one_lead_at_a_time(self):
        states = {'chatwoot:1:56932': invited('@viralstoresbr')['state'],
                  'chatwoot:1:56933': invite_unknown('@gabinaresse')['state']}

        class Repo:
            def precheck_conversations(self):
                return sorted(states)

            def load_session(self, conv):
                return deepcopy(states[conv])

        at = AT + timedelta(minutes=15)
        rows = reconferencia.candidates(Repo(), at)
        self.assertEqual([(row['conversation'], row['kind'], row['reason']) for row in rows],
                         [('chatwoot:1:56933', 'agency', 'invite_list_proof'),  # 56933 vem primeiro desde a 41
                          ('chatwoot:1:56932', 'agency', 'invite_tracking')])
        seen, started = [], []
        settings = {'reconferencia_enabled': True, 'tiktok_mode': 'real', 'real_worker_enabled': True,
                    'conversation_enabled': True, 'gate': {'enabled': True}}
        scan = reconferencia.Reconferencia(Repo(), settings, lambda kind: seen.append(kind) or True,
                                           lambda conv, reason, forced=False, kind='precheck':
                                           started.append(conv) or {'status': 'queued'}, now=lambda: at)
        self.assertEqual(scan.tick()['status'], 'queued')
        self.assertEqual((seen, started), (['agency'], ['chatwoot:1:56933']))


class GabinaresseServerTests(RealCasesTests):
    """56933 pelo caminho inteiro: webhook → convite incerto → varredura lê a lista → reenvio → texto 1 → vínculo → texto 2."""

    LEAD = {'conversation': '56933', 'contact': '8933', 'phone': '+5511987654333', 'handle': '@gabinaresse'}

    def setUp(self):
        import contracts
        original = contracts.parse_pilot_phones
        contracts.parse_pilot_phones = lambda value, test: original(value + ',' + self.LEAD['phone'], test)
        self.addCleanup(setattr, contracts, 'parse_pilot_phones', original)
        hours = retomada.send_hour
        retomada.send_hour = lambda now: True
        self.addCleanup(setattr, retomada, 'send_hour', hours)
        super().setUp()
        test = self
        self.relations = ['not_found']
        self.invites = [{'status': 'verification_pending', 'confirmed': False, 'evidence': {}, 'reason': DOWN},
                        {'status': 'sent', 'confirmed': True, 'reason': 'invitation_verified',
                         'evidence': {'post_attempted': True, 'create_accepted': True, **PENDING}}]

        class Gateway:
            situacao = 'pendente'

            def register_contact(self, entry):
                return {'creator_id': '22222222-2222-4222-8222-222222222233', 'atendimento_id': entry['atendimento_id'],
                        'event_id': entry['event_id'], 'revision': entry['revision'], 'cadastro_situacao': self.situacao}

        self.gateway = Gateway()
        self.app.extensions['v5_data_gateway'] = self.gateway

        def execute(operation, creator, **kwargs):
            test.client.calls.append((operation, creator))
            observed = datetime.now(timezone.utc).isoformat()
            if operation == 'invite':
                result = test.invites.pop(0)
            elif operation == 'relationship':
                status = test.relations.pop(0)
                result = {'status': status, 'confirmed': True, 'reason': 'relations_observed',
                          'evidence': {'not_found': LIST, 'pending': PENDING, 'linked': LINKED}[status]}
            else:
                result = {'status': 'eligible', 'confirmed': True, 'reason': 'precheck_observed',
                          'evidence': {'source': 'partner_precheck', 'shop_account_status': 1}}
            return {'operation': operation, 'creator': creator, 'observed_at': observed, **result}
        self.client.execute = execute
        self.client.up = True

    def earlier(self, minutes):
        """O tempo passa: todos os horários gravados no atendimento recuam (o executor aplica no relógio real)."""
        conv = 'chatwoot:1:' + self.LEAD['conversation']

        def shift(value):
            if isinstance(value, dict):
                # O payload é o mesmo do trabalho na fila: não recua (o executor compara os dois).
                return {key: item if key == 'payload' else shift(item) for key, item in value.items()}
            if isinstance(value, list):
                return [shift(item) for item in value]
            if isinstance(value, str) and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?\+00:00', value):
                return (datetime.fromisoformat(value) - timedelta(minutes=minutes)).isoformat()
            return value
        self.repo.save_session(conv, shift(self.repo.load_session(conv)))

    def test_resent_once_then_followed_until_linked(self):
        lead, conv = self.LEAD, 'chatwoot:1:' + self.LEAD['conversation']
        self.say(lead, AD)
        self.say(lead, lead['handle'])
        self.drain()
        self.say(lead, 'Pode mandar')
        self.drain()
        state = self.repo.load_session(conv)
        self.assertEqual(state['cycle']['real_operations']['invite']['status'], 'verification_pending')
        self.assertEqual(self.run_scan()['status'], 'idle')  # nada antes de 10 min
        self.earlier(15)
        self.assertEqual(self.run_scan()['status'], 'queued')
        self.drain()
        self.assertEqual(self.texts(lead)[-1], TEXT_1)
        self.assertEqual([call[0] for call in self.client.calls].count('invite'), 2)
        self.assertEqual(self.run_scan()['status'], 'idle')  # a próxima leitura só daqui a 15 min
        self.earlier(16)
        self.relations.append('linked')
        self.assertEqual(self.run_scan()['status'], 'queued')
        self.drain()
        self.assertEqual(self.texts(lead)[-1], TEXT_2)
        self.assertEqual(self.repo.load_session(conv)['cycle']['phase'], 'form')
        self.earlier(180)
        self.assertEqual(self.run_scan()['status'], 'idle')
        self.assertEqual(self.texts(lead).count(TEXT_1), 1)
        self.assertEqual([call[0] for call in self.client.calls].count('relationship'), 2)

    def test_registered_lead_is_never_read(self):
        lead = self.LEAD
        self.say(lead, AD)
        self.say(lead, lead['handle'])
        self.drain()
        self.invites[0] = self.invites[1]
        self.say(lead, 'Pode mandar')
        self.drain()
        self.gateway.situacao = 'confirmado'
        self.earlier(20)
        self.assertNotEqual(self.run_scan()['status'], 'queued')
        self.assertEqual(self.repo.load_session('chatwoot:1:56933')['cadastro_situacao'], 'confirmado')
        self.assertIsNone(self.run_scan().get('result'))
        self.assertNotIn('relationship', [call[0] for call in self.client.calls])

    test_emy_and_thaina_are_rechecked_once_each_when_the_bridge_returns = None
    test_bridge_flapping_during_the_retry_stays_silent_and_waits_ten_minutes = None
    test_switch_and_status = None


if __name__ == '__main__':
    unittest.main()
