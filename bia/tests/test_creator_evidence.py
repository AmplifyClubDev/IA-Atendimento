"""Registration and local alert intent never prove external delivery."""
from datetime import datetime, timezone
import unittest

import conversation
import conversao
import engine
import real_journey as journey

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


class CreatorEvidenceTests(unittest.TestCase):
    def registered(self, delivery):
        state = conversation.handle({}, 'oi', now=NOW, real_mode=True)['state']
        state['cadastro_situacao'] = 'confirmado'
        # Synthetic unrelated input, NOT a Bia delivery-receipt contract.
        # Bia currently receives cadastro_situacao only; this must be ignored.
        if delivery is not None:
            state['untrusted_delivery_hint'] = {'status': delivery}
        return state

    def assert_no_access_claim(self, turn):
        self.assertIn(conversao.REGISTRATION_CONFIRMED, turn['reply'])
        self.assertNotIn('foi liberado', turn['reply'])
        self.assertNotIn('já está liberado', turn['reply'])
        self.assertNotIn('foi para esse e-mail', turn['reply'])
        self.assertFalse(turn['state']['cycle']['acesso_liberado'])
        self.assertEqual(turn['effects'], [])
        self.assertEqual(turn['buttons'], [])

    def test_registration_with_unavailable_failed_or_unknown_delivery(self):
        for delivery in ('unavailable', 'failed', 'outcome_unknown', None):
            with self.subTest(delivery=delivery):
                state = self.registered(delivery)
                turn = conversation.handle(state, 'Já aceitei', now=NOW, real_mode=True)
                self.assert_no_access_claim(turn)
                cycle_id = turn['state']['cycle']['id']
                turn = conversation.handle(turn['state'], 'E meu acesso?', now=NOW, real_mode=True)
                self.assert_no_access_claim(turn)
                self.assertEqual(turn['state']['cycle']['id'], cycle_id)

    def test_registered_creator_still_gets_factual_topic_answers(self):
        for question in ('Qual é a comissão da Amplify?', 'Como funciona?', 'Benefícios'):
            with self.subTest(question=question):
                expected = journey._local_topic_answer(question)
                self.assertTrue(expected, 'fixture must match a factual topic')
                turn = conversation.handle(self.registered(None), question, now=NOW, real_mode=True)
                self.assert_no_access_claim(turn)
                self.assertTrue(turn['reply'].startswith(expected + '\n\n'))

    def test_historical_inferred_access_flag_does_not_prove_delivery(self):
        state = self.registered('failed')
        state['cycle'].update(acesso_liberado=True, phase='acesso')
        self.assert_no_access_claim(conversation.handle(state, 'oi', now=NOW, real_mode=True))

    def test_closed_registered_cycle_and_missions_do_not_restart_funnel(self):
        state = self.registered('unavailable')
        state['cycle']['status'] = 'closed'
        turn = conversation.handle(state, 'Quais missões?', now=NOW, real_mode=True)
        self.assert_no_access_claim(turn)
        self.assertIn('Quando seu acesso estiver disponível', turn['reply'])

    def test_failed_second_invite_also_does_not_claim_team_notified(self):
        state = engine._state({})
        engine._open(state, NOW)
        state['cycle'].update(mode='real', invite_failed_retry={'at': NOW.isoformat()})
        turn = journey._settle_invite_code(state, NOW, {}, 'failed',
                                           {'reason': 'provider_failed'}, {}, None)
        self.assertEqual(turn['reply'], conversao.INVITE_FAILED_TEAM)
        self.assertNotIn('Já avisei', turn['reply'])
        self.assertEqual(turn['effects'], [])

    def test_failed_invite_without_alert_receipt_has_no_notification_promise(self):
        for alert_status in (None, 'failed', 'outcome_unknown'):
            with self.subTest(alert_status=alert_status):
                state = engine._state({})
                engine._open(state, NOW)
                state['cycle']['mode'] = 'real'
                if alert_status:
                    state['cycle']['team_alert'] = {'status': alert_status}
                # Exercise the actual failed resend settlement, not an alert mock
                # returning a fabricated receipt. There is no dispatcher here.
                turn = journey._settle_list_proof_invite(state, NOW, {}, 'failed')
                self.assertEqual(turn['reply'], conversao.INVITE_FAILED_TEAM)
                self.assertNotIn('Já avisei', turn['reply'])
                self.assertNotIn('a gente te chama', turn['reply'])
                self.assertIn('não tenho confirmação', turn['reply'])
                self.assertEqual(turn['state']['cycle']['block_reason'], 'invite_failed_twice')
                self.assertEqual(turn['effects'], [])


if __name__ == '__main__':
    unittest.main()
