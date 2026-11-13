import unittest
import real_journey as j
from approved_experience import OPENING
class InactivityReceipt(unittest.TestCase):
 def test_return_restarts_but_keeps_confirmed_invite_fence(self):
  s=j.handle_real({},'Oi',now='2026-11-13T15:00:00Z',approved_experience_enabled=True)['state']; c=s['cycle']; old=c['id']
  r={'job_id':'confirmed-invite','creator':'@synthetic','cycle_id':old,'status':'sent','confirmed':True,'evidence':{'create_accepted':True}}
  c.update(status='closed',reason='inactivity_timeout',phase='await_acceptance',facts={'tiktok_declarado':'@synthetic','consentimento_convite':True},real_operations={'invite':r})
  s['effects']['confirmed-invite']={'id':'confirmed-invite','type':'tiktok_operation','operation':'invite','creator':'@synthetic','cycle_id':old,'status':'done','result_receipt':r}
  a=j.handle_real(s,'sim',now='2026-11-13T15:30:00Z',approved_experience_enabled=True)
  self.assertEqual(a['reply'],OPENING); self.assertNotEqual(a['state']['cycle']['id'],old)
  self.assertEqual(a['state']['cycle']['facts'],{})
  self.assertEqual(a['state']['closed_cycles'][-1]['real_operations']['invite'],r)
  self.assertTrue(j._prior_invite_requires_reconciliation(a['state'],'@synthetic'))
  self.assertFalse(a['effects'])
