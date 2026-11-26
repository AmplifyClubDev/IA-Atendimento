import unittest
from datetime import datetime,timezone
import lead_validation as v
from retomada import FOLLOWUP_CHOICE, message
AT=datetime(2026,11,13,18,tzinfo=timezone.utc)
class GenericAgency(unittest.TestCase):
 def cycle(self):return {'phase':'intro','facts':{'interesse_agenciamento':True}}
 def test_first_question_generic_and_yes_no(self):
  c=self.cycle();q=v.begin(c,AT)
  self.assertEqual(q,('Você já é agenciado por alguma agência?',['Sim','Não']))
  self.assertNotIn('Amplify',q[0])
  self.assertEqual(message({'cycle':c},1,{}),(q[0]+'\n\n'+FOLLOWUP_CHOICE,q[1]))
 def test_yes_asks_which_agency_without_assuming_amplify(self):
  for answer in ['Sim','Sou agenciada','já sou agenciado','sim sou agenciada','tenho agência']:
   c=self.cycle();v.begin(c,AT);q=v.advance(c,answer,AT)
   self.assertEqual(v.stage(c),'agency_kind');self.assertEqual(q,v.QUESTIONS['agency_kind'])
   self.assertNotIn('existing_amplify_declared',c['bia_validation'])
 def test_no_goes_shop(self):
  for answer in ['Não','Não tenho agência','não sou agenciada por nenhuma agência']:
   c=self.cycle();v.begin(c,AT);self.assertEqual(v.advance(c,answer,AT),v.QUESTIONS['shop'])
   self.assertFalse(c['facts']['possui_agencia_declarada'])
 def test_other_agency_requires_unlink_and_amplify_keeps_own_path(self):
  c=self.cycle();v.begin(c,AT);v.advance(c,'Sim',AT)
  self.assertEqual(v.advance(c,'Outra agência',AT),v.QUESTIONS['unlink'])
  self.assertTrue(c['facts']['possui_agencia_declarada'])
  c=self.cycle();v.begin(c,AT);v.advance(c,'Sim',AT)
  self.assertEqual(v.advance(c,'Já sou Amplify',AT),v.QUESTIONS['existing_profile'])
  self.assertTrue(c['bia_validation']['existing_amplify_declared'])
 def test_legacy_direct_buttons_remain_accepted(self):
  for answer,stage in [('Já sou Amplify','existing_profile'),('Outra agência','unlink'),('Não sou agenciado','shop')]:
   c=self.cycle();v.begin(c,AT);v.advance(c,answer,AT);self.assertEqual(v.stage(c),stage)
