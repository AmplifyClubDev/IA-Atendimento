import unittest
from test_real_journey import inbound
from lead_validation import QUESTIONS, THRESHOLD_CENTS, stage
from amplify_answer_profile import amplify_instructions

class NeutralGMV(unittest.TestCase):
 def start(self,shop='Sim'):
  r=inbound('Oi',approved_experience_enabled=True,same_engine_enabled=True)
  for text in ['Quero fazer parte','Não',shop]:
   r=inbound(text,r['state'],approved_experience_enabled=True,same_engine_enabled=True)
  return r
 def test_initial_retry_unknown_shop_do_not_suggest_value(self):
  for shop in ['Sim','Não sei']:
   r=self.start(shop)
   for text in [None,'aproximadamente']:
    if text:r=inbound(text,r['state'],approved_experience_enabled=True,same_engine_enabled=True)
    self.assertIn(QUESTIONS['gmv'][0],r['reply'])
    self.assertNotRegex(r['reply'].lower(),r'50\s*(?:mil|k)|50[.,]?000|por exemplo|exemplo:')
    self.assertNotIn('gmv_30d_declarado_centavos',r['state']['cycle']['facts'])
 def test_internal_inclusive_threshold_unchanged(self):
  self.assertEqual(THRESHOLD_CENTS,5_000_000)
  for amount,expected in [('49.999,99','complete'),('50.000','choice'),('50.000,01','choice')]:
   r=self.start();r=inbound(amount,r['state'],approved_experience_enabled=True,same_engine_enabled=True)
   self.assertEqual(stage(r['state']['cycle']),expected)
 def test_same_profile_instructions_neutral_in_test_and_real(self):
  for mode in ['demo','real']:
   text=amplify_instructions(mode)
   self.assertIn('Não sugira valores, faixas ou exemplos numéricos de resposta',text)
   self.assertIn('Não revele o corte interno',text)
