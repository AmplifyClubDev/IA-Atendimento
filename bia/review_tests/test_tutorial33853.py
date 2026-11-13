import unittest
from copy import deepcopy
from test_real_journey import inbound, NOW, POLICY
import tutorial_videos, retomada

class Tutorial33853(unittest.TestCase):
 def test_educational_invite_in_intro_has_native_selector_without_status_claim(self):
  r=inbound('como aceitar o convite do tiktok?',approved_experience_enabled=True,same_engine_enabled=True)
  self.assertEqual(r['state']['cycle']['phase'],'intro')
  self.assertEqual(r.get('effects',[]),[])
  asset=tutorial_videos.select_attachment(r['reply'],r['buttons'])
  self.assertEqual(asset['key'],'accept_invite')
  self.assertNotIn('seu convite',r['reply'].lower())
  self.assertIsNone(retomada.message(r['state'],1,POLICY))
  self.assertIsNone(retomada.message(r['state'],2,POLICY))
 def test_tutorial_preserves_qualification_and_authority(self):
  state=inbound('oi',approved_experience_enabled=True,same_engine_enabled=True)['state']
  state['cycle']['phase']='validation'
  old=deepcopy(state['cycle']['facts'])
  r=inbound('tem video de como aceitar o convite?',state,approved_experience_enabled=True,same_engine_enabled=True)
  self.assertEqual(r['state']['cycle']['phase'],'validation')
  self.assertEqual(r['state']['cycle']['facts'],old)
  self.assertEqual(r.get('effects',[]),[])

 def test_pause_has_priority_over_tutorial_in_intro(self):
  state=inbound('oi',approved_experience_enabled=True,same_engine_enabled=True)['state']
  r=inbound('Quero pensar em como aceitar o convite depois',state,approved_experience_enabled=True,same_engine_enabled=True)
  self.assertEqual(r['state']['cycle']['status'],'closed')
  self.assertEqual(r['state']['cycle']['reason'],'lead_pause')
  self.assertFalse(r['state']['cycle'].get('educational_invite_help'))
  self.assertFalse(r['effects'])
 def test_holds_and_cancellation_do_not_trigger_tutorial(self):
  for hold in ['human_control','opt_out','qualification_paused','cancellation']:
   state=inbound('oi',approved_experience_enabled=True,same_engine_enabled=True)['state']
   text='como aceitar o convite?'
   if hold=='qualification_paused': state['cycle'][hold]=True
   elif hold=='cancellation': text='Cancelei o convite, como aceitar o convite?'
   else: state[hold]=True
   r=inbound(text,state,approved_experience_enabled=True,same_engine_enabled=True)
   self.assertFalse(r['state']['cycle'].get('educational_invite_help'),hold)
   self.assertFalse(r['effects'],hold)
