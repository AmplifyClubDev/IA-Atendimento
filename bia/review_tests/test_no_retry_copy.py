import unittest
from unittest.mock import patch
import conversao
import real_journey as journey
import engine

class NoRetryCopy(unittest.TestCase):
    def test_operational_copy_has_no_retry_narration_or_unproved_cause(self):
        for name in ('BRIDGE_WAIT','BRIDGE_STILL','BRIDGE_NOTE','INVITING','INVITE_WAIT',
                     'INVITE_STILL','PRIOR_INVITE_RESENT','INVITE_NOT_LANDED',
                     'INVITE_STILL_MISSING','OPERATION_FALLBACK','INVITE_CONFIRMING',
                     'INVITE_RETRYING','INVITE_FAILED_TEAM'):
            with self.subTest(name=name):
                text=getattr(conversao,name).lower()
                for forbidden in ('tentando','tentar','reenviar','envio sozinha','lento','não aceitou','enviado!'):
                    self.assertNotIn(forbidden,text)
    def test_retry_is_silent_and_preserves_effect_and_marker(self):
        state=journey.handle_real({},'Oi',now='2026-11-12T21:00:00Z')['state']
        state['cycle']['phase']='blocked'
        effect={'id':'synthetic-invite'}
        queued={'id':'synthetic-precheck','operation':'precheck'}
        before=len(state['history']); rev=state['revision']
        with patch.object(journey,'_invite_no_write',return_value=False), \
             patch.object(journey,'_invite_attempts',return_value=[effect]), \
             patch.object(journey,'_schedule_invite_retry',return_value=queued) as schedule:
            result=journey._settle_invite_code(state,engine._clock('2026-11-12T21:00:00Z'),
                    effect,'failed',{'reason':'technical_failure'},{},{})
        self.assertEqual(result['reply'],'')
        self.assertEqual(result['effects'],[queued])
        self.assertEqual(len(result['state']['history']),before)
        self.assertGreater(result['state']['revision'],rev)
        self.assertIn('invite_failed_retry',result['state']['cycle'])
        self.assertEqual(schedule.call_args.kwargs['delay'],journey.INVITE_FAILED_RETRY_SECONDS)
    def test_success_and_actionable_profile_guidance_kept(self):
        self.assertIn('foi enviado',conversao.invite_sent_now(''))
        self.assertIn('Aceitar',conversao.INVITE_STEPS)
        self.assertIn('TikTok',conversao.PROFILE_INELIGIBLE)
