from copy import deepcopy
from datetime import timedelta
import unittest
import real_journey as journey
from test_regressao41 import eligible, settle
from test_relationship_form_chat30 import AT, POLICY

class PriorAutomaticReconciliation(unittest.TestCase):
    def setUp(self):
        self.previous = journey.AUTO_INVITE
        journey.AUTO_INVITE = False
        self.state = eligible('@synthetic_test')['state']
        self.state['effects']['old-invite'] = dict(id='old-invite',type='tiktok_operation',operation='invite',creator='@synthetic_test',cycle_id='prior-cycle',status='done')
        journey.AUTO_INVITE = True
    def tearDown(self):
        journey.AUTO_INVITE = self.previous
    def test_prior_invite_uses_read_not_another_precheck_for_fresh_and_expired_proof(self):
        for minutes in (5,180):
            with self.subTest(minutes=minutes):
                state=deepcopy(self.state); at=AT+timedelta(minutes=minutes)
                job=journey.auto_invite_effect(state,at,POLICY)
                self.assertEqual(job['operation'],'relationship')
                self.assertEqual(state['cycle']['phase'],'checking_acceptance')
                self.assertEqual(state['cycle']['prior_invite_check']['effect_id'],job['id'])
                self.assertFalse(journey.auto_invite_due(state,at,POLICY))
                self.assertIsNone(journey.auto_invite_effect(state,at,POLICY))
    def test_pending_prior_invite_does_not_create_a_second_invite(self):
        at=AT+timedelta(minutes=5);job=journey.auto_invite_effect(self.state,at,POLICY)
        result=settle(self.state,job,'pending',at)
        self.assertFalse(any(x.get('operation')=='invite' for x in result['effects']))
        self.assertNotEqual(result['state']['cycle']['phase'],'consent_real')
    def test_linked_prior_invite_goes_to_form(self):
        at=AT+timedelta(minutes=5);job=journey.auto_invite_effect(self.state,at,POLICY)
        result=settle(self.state,job,'linked',at)
        self.assertEqual(result['state']['cycle']['phase'],'form')
        self.assertFalse(any(x.get('operation')=='invite' for x in result['effects']))

if __name__=='__main__': unittest.main()
