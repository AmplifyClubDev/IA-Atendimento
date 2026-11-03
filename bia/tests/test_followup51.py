"""Release 51: follow-ups automáticos (auditoria de 03/11/2026, 24 conversas)."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import conversao
import real_journey as journey
import retomada
import test_codigos43 as codigos
from test_regressao41 import settle
from test_relationship_form_chat30 import AT, POLICY

BRT = timezone(timedelta(hours=-3))


def brt(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=BRT)


class LastReminderInsideTheWindowTests(unittest.TestCase):
    """O lembrete de 23h30 que cairia entre 21h e 8h saía nunca (só 1 de 15 em 03/11)."""

    def test_last_reminder_moves_to_20h45_before_the_window_closes(self):
        base = brt(3, 6, 43)  # 56931: última mensagem às 06:43 → 23h30 depois seria 06:13 do dia 4
        due = retomada.due_at(base, timedelta(hours=23, minutes=30), last=True)
        self.assertEqual(due, brt(3, 20, 45))
        self.assertTrue(retomada.send_hour(due))
        self.assertLess(due, base + timedelta(hours=24))

    def test_late_evening_message_goes_to_next_day_20h45(self):
        base = brt(3, 22, 30)
        self.assertEqual(retomada.due_at(base, timedelta(hours=23, minutes=30), last=True), brt(4, 20, 45))

    def test_daytime_target_is_unchanged(self):
        base = brt(3, 12, 0)
        self.assertEqual(retomada.due_at(base, timedelta(hours=23, minutes=30), last=True), brt(4, 11, 30))

    def test_never_glued_to_the_previous_reminder(self):
        base = brt(3, 18, 0)  # 23h30 → 17:30 do dia 4, dentro do horário
        self.assertEqual(retomada.due_at(base, timedelta(hours=23, minutes=30), last=True), brt(4, 17, 30))
        base = brt(3, 19, 0)  # 20:45 seria só 1h45 depois: fica o horário original
        target = base + timedelta(hours=23, minutes=30)
        self.assertEqual(retomada.due_at(base, timedelta(hours=23, minutes=30), last=True), target if not
                         retomada.send_hour(target) else target)

    def test_earlier_steps_keep_their_time(self):
        base = brt(3, 20, 30)
        self.assertEqual(retomada.due_at(base, timedelta(minutes=15)), base + timedelta(minutes=15))


class ShopReminderTests(unittest.TestCase):
    """57030 e 56938: "ative o TikTok Shop e me manda pronto" e depois nenhum lembrete."""

    def state(self, **cycle):
        return {'cycle': {'phase': 'blocked', 'facts': {'tiktok_declarado': '@lead'}, 'shop_unknown': {'at': 'x'}, **cycle}}

    def test_each_step_has_a_new_angle_and_the_button(self):
        messages = [retomada.message(self.state(), step, POLICY) for step in (1, 2, 3)]
        self.assertEqual(len({text for text, _ in messages}), 3)
        self.assertTrue(all(buttons == ['Pronto'] and '“pronto”' in text for text, buttons in messages))

    def test_other_blocks_wait_for_the_system_without_reminder(self):
        state = self.state()
        state['cycle'].pop('shop_unknown')
        self.assertIsNone(retomada.message(state, 1, POLICY))
        state['cycle']['invite_wait'] = {'since': 'x'}
        self.assertIsNone(retomada.message(state, 1, POLICY))

    def test_blocked_is_a_waiting_phase(self):
        self.assertIn('blocked', retomada.WAITING)


class StopWordsTests(unittest.TestCase):
    """53898: "Cancelar" e a Bia seguiu mandando lembretes."""

    def test_cancel_and_stop_requests_end_the_service(self):
        for text in ('Cancelar', 'cancela', 'Pode cancelar', 'Pare', 'Para de mandar mensagem', 'Não me mande mais',
                     'Quero sair', 'Não tenho interesse'):
            with self.subTest(text):
                self.assertTrue(journey.not_interested(text))

    def test_questions_and_long_sentences_continue(self):
        for text in ('Como faço para cancelar?', 'Posso sair quando quiser?', 'pronto', 'Pode mandar'):
            with self.subTest(text):
                self.assertFalse(journey.not_interested(text))


class NoHumanHandoffTests(unittest.TestCase):
    """57026 e 57031: "atendimento humano", "avisei a equipe". Tudo é automático."""

    def test_team_and_human_sentences_never_reach_the_lead(self):
        text = 'Entendo! Vou avisar a equipe da Amplify. Seu convite está no TikTok, em Parcerias.'
        self.assertEqual(journey.lead_safe(text), 'Entendo! Seu convite está no TikTok, em Parcerias.')
        self.assertNotIn('humano', journey.lead_safe('Posso chamar um atendimento humano. Me manda seu @.'))

    def test_a_reply_made_only_of_handoff_keeps_the_conversation(self):
        self.assertEqual(journey.lead_safe('Vou passar para um atendente humano.'), journey._ONLY_INTERNAL)

    def test_fixed_texts_have_no_team_nor_time_promise(self):
        for name in dir(conversao):
            value = getattr(conversao, name)
            if isinstance(value, str):
                with self.subTest(name):
                    self.assertNotRegex(value, r'(?i)\bequipe\b|atendente|humano|minutinho|menos de 1 minuto')


class FailedInviteTextTests(codigos.BehaviourTests):
    """57031: o convite falhou 2 vezes e a Bia disse "avisei a equipe"."""

    def test_failed_twice_message_has_no_team(self):
        failed = self.invite('failed', confirmed=False, evidence={'post_attempted': True, 'http_status': 400},
                             reason='invitation_rejected')
        later = AT + timedelta(minutes=10)
        ready = settle(failed['state'], failed['effects'][0], 'eligible', later)
        again = settle(ready['state'], ready['effects'][0], 'failed', later, confirmed=False,
                       evidence={'post_attempted': True, 'http_status': 400}, reason='invitation_rejected')
        self.assertEqual(again['reply'], conversao.INVITE_FAILED_TEAM)
        self.assertNotIn('equipe', again['reply'])


if __name__ == '__main__':
    unittest.main()
