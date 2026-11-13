import unittest
from datetime import datetime, timezone
import lead_validation as lv
import real_journey as rj
import tutorial_videos as tv
class AuditGuidance(unittest.TestCase):
 def test_explicit_natural_zero(self):
  for s in ['Compro as coisas pra mim mesmo, nunca vendi nada pelo tiktok shop','Nunca vendi nada pelo TikTok Shop','Eu ainda não vendi nada no TikTok Shop.']:
   self.assertEqual(lv.parse_gmv(s),0,s)
 def test_no_inference_or_contradiction(self):
  for s in ['compro as coisas pra mim mesmo','sou novo','nunca vendi nada?','nunca vendi nada, mas fiz 50 mil','minha amiga nunca vendi nada','nunca vendi nada no TikTok Shop em 2025']:
   self.assertIsNone(lv.parse_gmv(s),s)
 def test_unknown_shop_guides_without_negative_inference(self):
  c={'facts':{},'bia_validation':{'stage':'shop'}}
  text,buttons=lv.advance(c,'Não sei',datetime(2026,11,13,10,tzinfo=timezone.utc))
  self.assertIsNone(c['facts']['shop_ativo_declarado']);self.assertEqual(lv.stage(c),'gmv')
  self.assertIn('caso ainda não esteja ativo',text);self.assertIn(lv.QUESTIONS['gmv'][0],text)
  a=tv.select_attachment(text,buttons);self.assertEqual(a['key'],'activate_shop');self.assertLessEqual(len(a['caption']),1024)
 def test_no_button_assumption_link_always_usable(self):
  c={'relationship_check_in_form':True,'phase':'form','form_button_stage':'direct'}
  for text in ['Faça seu cadastro por aqui:\n'+rj.PUBLIC_FORM_URL,'Acesse '+rj.PUBLIC_FORM_URL]:
   out,_=rj._form_button_once(c,text,[])
   self.assertNotIn('te mandei acima',out);self.assertNotIn('botão',out)
   self.assertEqual(out.count(rj.PUBLIC_FORM_URL),1);self.assertEqual(out.count('pelo link de cadastro:'),1)
if __name__=='__main__':unittest.main()
