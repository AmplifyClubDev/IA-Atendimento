"""Release 40: ajustes de conversão da auditoria de 01/11 (20 atendimentos do piloto).

Conversas reais usadas como roteiro:
- 56754, 56750, 56749 e 56745: não responderam nenhuma das 4 mensagens (pedido do @ repetido);
- 56748 (@larvitrine): levou 1h45 para responder a origem; recebeu "verificação" às 22:16 com a ponte de volta;
- 56751 (@fabi_augusta): não respondeu o nome;
- 56747, 56746, 56751, 56748 e 56752: parados na conferência do perfil desde 31/10;
- @sarahellen.off: recebeu o mesmo bloco da autorização 4 vezes;
- ma.ribeiroh: 4 perguntas sem resposta com o convite pendente;
- lemosalycee: vínculo confirmado em 31/10 13:33, cadastro não preenchido.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
import unittest

import conversao
import conversation
import real_journey as journey
import reconferencia
import retomada
from repository import Repository
from test_relationship_form_chat30 import AT, POLICY, eligible, inbound, invited, qualified, settle

AD = 'Oi, quero saber mais sobre agenciamento de creators'


def all_texts():
    texts = [conversao.first_reply(POLICY, True), conversao.first_reply(None, False), conversao.CTA,
             conversao.HANDLE_HELP, conversao.WANTS_IN, conversao.NOT_NOW, conversao.RECEIVED, conversao.RETURNED,
             conversao.BRIDGE_WAIT, conversao.BRIDGE_STILL, conversao.BRIDGE_BACK, conversao.SHOP_UNKNOWN,
             conversao.DOUBT, conversao.consent_full('Sarah', '@sarahellen.off', POLICY)]
    texts += [conversao.consent_reminder(step, POLICY) for step in (1, 2, 3)]
    texts += [conversao.intro_reminder(step)[0] for step in (1, 2, 3)]
    texts += [conversao.registration_reminder(step, 'Alyce', journey.PUBLIC_FORM_URL) for step in (1, 2)]
    return texts


class RestrictionTests(unittest.TestCase):
    """As 3 restrições do usuário valem para todos os textos novos."""

    def test_no_club_size_no_rule_after_the_term_and_no_sales_or_income_promise(self):
        for text in all_texts():
            with self.subTest(text=text[:40]):
                self.assertNotRegex(text, r'\d[\d.]*\s*(?:mil\s+)?creators')
                self.assertNotRegex(text.lower(), r'depois d[oe]s? 2 meses|ap[oó]s (?:os )?2 meses|renova')
                self.assertNotRegex(text.lower(), r'garant|renda|vender mais|vai vender|vai ganhar|lucro')

    def test_benefits_are_only_the_approved_card_items(self):
        card = next(topic['answer'] for topic in __import__('answers').load_knowledge()['topics']
                    if topic['id'] == 'beneficios')
        for item in ('campanhas com marcas', 'orientação sobre produtos e conteúdos', 'apoio em lives',
                     'comunidade de creators'):
            self.assertIn(item, card)
            self.assertIn(item, conversao.BENEFITS)


class FirstContactTests(unittest.TestCase):
    """Ponto 2: a primeira resposta vende e termina pedindo o @ (10 de 20 nunca mandaram)."""

    def test_ad_message_gets_the_selling_reply_and_the_origin_from_the_ad(self):
        turn = inbound(AD)
        self.assertEqual(turn['reply'], conversao.first_reply(POLICY, True))
        self.assertTrue(turn['reply'].endswith('Me manda seu @ do TikTok 👇'))
        self.assertIn('10%', turn['reply'])
        self.assertIn('agente de IA', turn['reply'])
        self.assertEqual(turn['buttons'], ['Mandar meu @', 'Como funciona?'])
        cycle = turn['state']['cycle']
        self.assertEqual(cycle['facts']['origem_declarada'], 'anuncio')
        self.assertTrue(cycle['arroba_pedido'])

    def test_handle_button_explains_where_the_handle_is(self):
        turn = inbound('Mandar meu @', inbound(AD)['state'])
        self.assertEqual(turn['reply'], conversao.HANDLE_HELP)

    def test_knowing_amplify_always_ends_with_the_next_step(self):
        turn = inbound('Conhecer a Amplify')
        self.assertTrue(turn['reply'].endswith(conversao.CTA))
        self.assertNotIn('O que você busca desenvolver', turn['reply'])

    def test_handle_goes_straight_to_the_profile_check_without_name_or_origin(self):
        # 56748 (@larvitrine) e 56751 (@fabi_augusta) pararam nas perguntas de nome e origem.
        turn = inbound('@larvitrine', inbound(AD)['state'])
        self.assertEqual(turn['reply'], 'Recebi, @larvitrine! Já tô conferindo seu perfil 🔎 Leva menos de 1 minuto.')
        self.assertEqual({effect['operation'] for effect in turn['effects']}, {'lookup', 'precheck'})
        self.assertEqual(turn['state']['cycle']['phase'], 'checking')
        self.assertNotIn('Como posso te chamar', turn['reply'])
        self.assertNotIn('conheceu', turn['reply'])

    def test_bare_handle_also_works(self):
        turn = inbound('fabi_augusta', inbound(AD)['state'])
        self.assertEqual(turn['state']['cycle']['facts']['tiktok_declarado'], '@fabi_augusta')
        self.assertEqual(turn['state']['cycle']['phase'], 'checking')


class FirstContactRemindersTests(unittest.TestCase):
    """56754, 56750, 56749 e 56745: cada lembrete com um ângulo novo, nunca o mesmo pedido."""

    def test_three_reminders_are_different_and_the_last_offers_buttons(self):
        state = inbound(AD)['state']
        messages = [retomada.message(state, step, POLICY) for step in (1, 2, 3)]
        texts = [text for text, _ in messages]
        self.assertEqual(len(set(texts)), 3)
        self.assertNotIn(conversao.first_reply(POLICY, True), texts)
        self.assertIn('campanhas com marcas', texts[0])
        self.assertIn('1 minutinho', texts[1])
        self.assertIn('em pausa', texts[2])
        self.assertEqual(messages[2][1], ['Quero entrar', 'Agora não'])

    def test_last_reminder_buttons(self):
        state = inbound(AD)['state']
        wants = inbound('Quero entrar', state)
        self.assertEqual(wants['reply'], conversao.WANTS_IN)
        self.assertTrue(wants['state']['cycle']['facts']['interesse_agenciamento'])
        self.assertEqual(inbound('@emytododiademaria', wants['state'])['state']['cycle']['phase'], 'checking')
        later = inbound('Agora não', state)
        self.assertEqual(later['reply'], conversao.NOT_NOW)
        self.assertEqual(later['state']['cycle']['status'], 'closed')


class ConsentTests(unittest.TestCase):
    """Ponto 4: linguagem de convite; a @sarahellen.off recebeu o mesmo bloco 4 vezes."""

    def test_full_block_once_then_short_question_and_new_buttons(self):
        offer = eligible()
        self.assertTrue(offer['reply'].startswith('Boa notícia'))
        self.assertIn('• prazo de 2 meses', offer['reply'])
        self.assertIn('se não vender, não paga nada', offer['reply'])
        self.assertTrue(offer['reply'].endswith('Posso te mandar o convite no TikTok (@teste)?'))
        self.assertEqual(offer['buttons'], ['Pode mandar', 'Tenho uma dúvida'])
        again = inbound('ok', offer['state'])
        self.assertNotIn('• prazo', again['reply'])
        self.assertIn('Posso te mandar o convite', again['reply'])

    def test_reminders_answer_an_objection_and_never_repeat_the_block(self):
        state = eligible()['state']
        texts = [retomada.message(state, step, POLICY) for step in (1, 2, 3)]
        self.assertEqual(len({text for text, _ in texts}), 3)
        self.assertIn('e se eu não vender?', texts[0][0])
        self.assertIn('preciso fazer live?', texts[1][0])
        for text, buttons in texts:
            self.assertNotIn('• prazo', text)
            self.assertEqual(buttons, ['Pode mandar', 'Tenho uma dúvida'])

    def test_can_send_button_sends_the_invite_and_doubt_button_answers(self):
        state = eligible()['state']
        sent = inbound('Pode mandar', state)
        self.assertEqual([effect['operation'] for effect in sent['effects']], ['invite'])
        doubt = inbound('Tenho uma dúvida', eligible()['state'])
        self.assertEqual(doubt['reply'], conversao.DOUBT)
        self.assertEqual(doubt['effects'], [])
        self.assertEqual(doubt['state']['cycle']['phase'], 'consent_real')


class PendingInviteTests(unittest.TestCase):
    """Ponto 6: ma.ribeiroh mandou 4 perguntas sem resposta com o convite pendente."""

    def test_each_question_is_answered_and_ends_with_the_acceptance_path(self):
        state = invited()['state']
        for question in ('Conhecer a Amplify', 'Como funciona', 'Benefícios', 'Comissão'):
            with self.subTest(question=question):
                turn = inbound(question, deepcopy(state))
                self.assertNotIn('Não consegui consultar', turn['reply'])
                self.assertTrue(turn['reply'].endswith(journey._ACCEPT_NEXT_STEP))
                self.assertGreater(len(turn['reply']), len(journey._ACCEPT_NEXT_STEP) + 20)
                self.assertFalse([effect for effect in turn['effects'] if effect.get('operation') == 'invite'])


class RegistrationReminderTests(unittest.TestCase):
    """Ponto 5: lemosalycee tem vínculo desde 31/10 13:33 e não fez o cadastro."""

    def linked_state(self):
        state = invited()['state']
        state['cycle']['real_operations']['relationship'] = {'status': 'linked', 'confirmed': True}
        state['cycle']['phase'] = 'form'
        return state

    def test_two_and_twenty_three_and_a_half_hours_with_the_button_link(self):
        state = self.linked_state()
        self.assertEqual(retomada.steps_for(state), retomada.LINKED_STEPS)
        self.assertEqual([after for _, after in retomada.LINKED_STEPS],
                         [timedelta(hours=2), timedelta(hours=23, minutes=30)])
        texts = [retomada.message(state, step, POLICY)[0] for step in (1, 2)]
        self.assertEqual(len(set(texts)), 2)
        for text in texts:
            self.assertIn(journey.PUBLIC_FORM_URL, text)
            self.assertIn('acesso ao Club sai na hora', text)
        state['cadastro_situacao'] = 'confirmado'
        self.assertIsNone(retomada.message(state, 1, POLICY))


class BridgeTextsAndInitialListTests(unittest.TestCase):
    """Ponto 1: textos aprovados, lista inicial dos 5 e quem volta depois das 24 h."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='release40c-')
        self.addCleanup(tmp.cleanup)
        self.repo = Repository(Path(tmp.name) / 'state.sqlite3')

    def stuck(self, reason):
        result = qualified()
        effect = next(item for item in result['effects'] if item['operation'] == 'precheck')
        return settle(result['state'], effect, 'verification_pending', confirmed=False, evidence={}, reason=reason)

    def test_bridge_down_and_back_texts(self):
        down = self.stuck('human_verification_required')
        self.assertEqual(down['reply'], conversao.BRIDGE_WAIT)
        now = datetime.now(timezone.utc)
        effect = journey.bridge_retry_effect(down['state'], now)
        back = settle(down['state'], effect, 'eligible')
        self.assertTrue(back['reply'].startswith('Pronto, conferi! ✅\n\nBoa notícia'))

    def test_shop_unknown_is_honest_and_the_lead_can_ask_again(self):
        stuck = self.stuck('shop_unknown')
        self.assertEqual(stuck['reply'], conversao.SHOP_UNKNOWN)
        again = inbound('pronto', stuck['state'])
        self.assertEqual([effect['operation'] for effect in again['effects']], ['precheck'])
        self.assertIn('conferir seu perfil de novo', again['reply'])
        self.assertEqual(inbound('e aí?', again['state'])['effects'], [])  # no máximo a cada 10 min

    def store(self, conv, state, reason):
        record = state['cycle']['real_operations']['precheck']
        self.repo.reserve_event('chatwoot:1:' + conv + '0', 'chatwoot:1:' + conv, 'test')
        with self.repo._connection() as db:
            db.execute("INSERT INTO real_jobs(job_key,conversation_key,event_key,effect_id,cycle_id,creator,operation,"
                       "event_json,payload_json,status,attempts,next_run_at,result_json,updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ('job-' + conv, 'chatwoot:1:' + conv, 'chatwoot:1:' + conv + '0', record['job_id'],
                        state['cycle']['id'], record['creator'].lstrip('@'), 'precheck', '{}', '{}', 'completed', 1,
                        AT.isoformat(), '{"reason": "' + reason + '"}', AT.isoformat()))
        self.repo.save_session('chatwoot:1:' + conv, state)

    def test_the_five_listed_chats_are_rechecked_once_whatever_the_old_reason(self):
        now = datetime.now(timezone.utc)
        # 56748 (@larvitrine): "verificação" às 22:16 com a ponte de volta; o motivo não era ponte fora.
        self.store('56748', self.stuck('shop_unknown')['state'], 'shop_unknown')
        self.store('56746', self.stuck('human_verification_required')['state'], 'human_verification_required')
        self.store('60000', self.stuck('shop_unknown')['state'], 'shop_unknown')  # fora da lista: não entra
        ineligible = qualified()
        effect = next(item for item in ineligible['effects'] if item['operation'] == 'precheck')
        self.store('56751', settle(ineligible['state'], effect, 'ineligible')['state'], 'precheck_observed')
        rows = reconferencia.candidates(self.repo, now)
        self.assertEqual([(row['conversation'], row['forced']) for row in rows],
                         [('chatwoot:1:56746', False), ('chatwoot:1:56748', True)])
        state = self.repo.load_session('chatwoot:1:56748')
        self.assertTrue(journey.bridge_retry_effect(state, now, reason='shop_unknown', forced=True))
        self.repo.save_session('chatwoot:1:56748', state)
        self.assertFalse(journey.bridge_retry_due(state, now + timedelta(hours=1), reason='shop_unknown', forced=True))

    def test_bridge_is_read_live_and_only_when_someone_waits(self):
        calls = []
        scan = reconferencia.Reconferencia(self.repo, {'reconferencia_enabled': True, 'tiktok_mode': 'real',
                                                       'real_worker_enabled': True, 'conversation_enabled': True,
                                                       'gate': {'enabled': True}},
                                           lambda kind: calls.append(kind) or True, lambda *_, **__: {'status': 'queued'})
        self.assertEqual(scan.tick()['status'], 'idle')
        self.assertEqual(calls, [])
        self.store('56746', self.stuck('human_verification_required')['state'], 'human_verification_required')
        for _ in range(2):
            scan.next_scan_at = None
            self.assertEqual(scan.tick()['status'], 'queued')
        # Uma leitura nova a cada varredura, nunca guardada (release 41: a varredura diz qual ponte lê).
        self.assertEqual(calls, ['precheck', 'precheck'])

    def test_lead_who_returns_after_24h_is_not_asked_for_the_handle_again(self):
        state = self.stuck('human_verification_required')['state']
        later = AT + timedelta(hours=30)
        turn = conversation.handle(state, 'Oi, e aí?', now=later, real_mode=True, operation_policy=POLICY,
                                   relationship_check_in_form=True)
        self.assertEqual(turn['reply'], conversao.RETURNED.format(handle='@teste'))
        self.assertEqual({effect['operation'] for effect in turn['effects']}, {'lookup', 'precheck'})
        self.assertEqual(turn['state']['cycle']['phase'], 'checking')
        self.assertEqual(turn['state']['cycle']['number'], 2)


if __name__ == '__main__':
    unittest.main()
