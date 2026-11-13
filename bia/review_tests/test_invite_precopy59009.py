import unittest
from unittest.mock import patch
import conversao
import real_journey as j
from test_regressao41 import eligible
from test_relationship_form_chat30 import AT,POLICY

class PreInviteCopy(unittest.TestCase):
 def test_conditions_without_attempt_narration_or_unproven_delivery(self):
  text=conversao.auto_invite('Teste','@synthetic',POLICY)
  self.assertIn('@synthetic',text)
  self.assertIn('10%',text)
  self.assertIn('2 meses',text)
  self.assertNotRegex(text.lower(),r'enviando|tentando|te aviso|foi enviado|convite.*(?:disponível|esperando)')
 def test_queue_unchanged_and_no_delivery_claim_before_receipt(self):
  with patch.object(j,'AUTO_INVITE',False): s=eligible('@synthetic')['state']
  with patch.object(j,'AUTO_INVITE',True): result=j._auto_invite(s,AT,POLICY)
  self.assertIsNotNone(result)
  self.assertEqual([e['operation'] for e in result['effects']],['invite'])
  self.assertEqual(result['state']['cycle']['phase'],'inviting')
  self.assertNotRegex(result['reply'].lower(),r'enviando|tentando|te aviso|foi enviado')
