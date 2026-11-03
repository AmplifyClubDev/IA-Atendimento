"""Release 52: perfil aprovado → convite automático, sem esperar o "Pode mandar" (pedido do usuário, 03/11)."""
from copy import deepcopy
from datetime import timedelta
import unittest

import conversao
import real_journey as journey
import reconferencia
from test_regressao41 import AD, eligible, say, settle
from test_relationship_form_chat30 import AT, POLICY
import test_codigos43 as codigos


class AutoInviteTests(codigos.base.DaytimeTests):
    def setUp(self):
        super().setUp()
        self._previous, journey.AUTO_INVITE = journey.AUTO_INVITE, True

    def tearDown(self):
        journey.AUTO_INVITE = self._previous
        super().tearDown()

    def test_eligible_profile_gets_conditions_and_the_invite_at_once(self):
        result = eligible('@lead5b')
        self.assertIn('Já tô enviando o convite', result['reply'])
        self.assertIn('10%', result['reply'])
        self.assertNotIn(conversao.CONSENT_QUESTION, result['reply'])
        self.assertEqual([item['operation'] for item in result['effects']], ['invite'])
        cycle = result['state']['cycle']
        self.assertEqual((cycle['phase'], cycle['facts']['consentimento_convite']), ('inviting', True))
        self.assertEqual(cycle['invite_consent']['source'], 'auto_after_eligible')

    def test_sent_invite_follows_the_normal_path(self):
        result = eligible('@lead5b')
        sent = settle(result['state'], result['effects'][0], 'sent')
        self.assertIn(sent['state']['cycle']['phase'], {'await_acceptance', 'form'})
        self.assertIn('convite', sent['reply'].lower())

    def test_a_declined_lead_never_gets_an_automatic_invite(self):
        journey.AUTO_INVITE = False
        offered = eligible('@lead5b')
        declined = say('Não', offered['state'])
        self.assertIs(declined['state']['cycle']['facts']['consentimento_convite'], False)
        journey.AUTO_INVITE = True
        self.assertFalse(journey.auto_invite_due(declined['state'], AT + timedelta(minutes=5), POLICY))

    def test_lead_already_waiting_for_authorization_gets_the_invite_from_the_scan(self):
        journey.AUTO_INVITE = False
        waiting = eligible('@lead5b')['state']
        self.assertEqual(waiting['cycle']['phase'], 'consent_real')
        journey.AUTO_INVITE = True
        at = AT + timedelta(minutes=5)
        self.assertTrue(journey.auto_invite_due(waiting, at, POLICY))
        live = deepcopy(waiting)
        job = journey.auto_invite_effect(live, at, POLICY)
        self.assertEqual(job['operation'], 'invite')
        self.assertEqual(live['cycle']['phase'], 'inviting')
        self.assertFalse(journey.auto_invite_due(live, at, POLICY))

    def test_stale_validation_is_refreshed_first_then_the_invite_goes_silently(self):
        journey.AUTO_INVITE = False
        waiting = eligible('@lead5b')['state']
        journey.AUTO_INVITE = True
        later = AT + timedelta(hours=3)
        live = deepcopy(waiting)
        check = journey.auto_invite_effect(live, later, POLICY)
        self.assertEqual(check['operation'], 'precheck')
        ready = settle(live, check, 'eligible', later)
        self.assertEqual((ready['reply'], [item['operation'] for item in ready['effects']]), ('', ['invite']))

    def test_switched_off_keeps_the_authorization_question(self):
        journey.AUTO_INVITE = False
        result = eligible('@lead5b')
        self.assertEqual(result['state']['cycle']['phase'], 'consent_real')
        self.assertIn('Posso te mandar o convite', result['reply'])

    def test_opt_out_and_human_control_block_the_scan(self):
        journey.AUTO_INVITE = False
        waiting = eligible('@lead5b')['state']
        journey.AUTO_INVITE = True
        at = AT + timedelta(minutes=5)
        self.assertFalse(journey.auto_invite_due({**waiting, 'opt_out': True}, at, POLICY))
        self.assertFalse(journey.auto_invite_due({**waiting, 'human_control': True}, at, POLICY))
        self.assertFalse(journey.auto_invite_due(waiting, AT + timedelta(hours=25), POLICY))


class ScanTests(unittest.TestCase):
    def test_consent_waiting_chat_is_a_candidate_of_kind_consent(self):
        previous, journey.AUTO_INVITE = journey.AUTO_INVITE, False
        try:
            waiting = eligible('@lead5b')['state']
            journey.AUTO_INVITE = True

            class Repo:
                def precheck_conversations(self):
                    return ['chatwoot:1:777']

                def load_session(self, conv):
                    return deepcopy(waiting)

            found = reconferencia.candidates(Repo(), AT + timedelta(minutes=5), POLICY)
            self.assertEqual([(row['kind'], row['reason']) for row in found], [('consent', 'auto_invite')])
        finally:
            journey.AUTO_INVITE = previous


if __name__ == '__main__':
    unittest.main()
