"""Synthetic qualification, inclusive threshold, no external calls."""
import unittest
from copy import deepcopy
import engine
import real_journey
from lead_validation import parse_gmv, stage, permitted
from demo_real_bridge import isolated_settings
from review_tests.test_demo_real_bridge import SCOPE

NOW='2026-11-12T14:00:00Z'
class Amounts(unittest.TestCase):
    def test_formats_exact_threshold(self):
        for text in ['50000','50.000','50.000,00','R$ 50.000,00','50k','50 mil','50,0 mil','0,05 milhão','fiz 50k']:
            with self.subTest(text=text):self.assertEqual(parse_gmv(text),5000000)
        self.assertEqual(parse_gmv('49.999,99'),4999999)
        self.assertEqual(parse_gmv('50.000,01'),5000001)
        self.assertEqual(parse_gmv('0'),0)
    def test_invalid_and_ambiguous_never_high(self):
        for text in ['-50k','50-60k','mais de 50k','50k?','50000 USD','US$ 50000','50.00.00','NaN','inf','50k por mês','50000000000','50k e 3 vendas','cinquenta mil']:
            with self.subTest(text=text):self.assertIsNone(parse_gmv(text))

class Flow(unittest.TestCase):
    def setUp(self):self.state={}
    def send(self,text,enabled=True):
        r=real_journey.handle_real(self.state,text,now=NOW,qualification_enabled=enabled)
        self.state=r['state'];return r
    def test_demo_join_starts_questions(self):
        r=self.send('Quero fazer parte');self.assertEqual(stage(self.state['cycle']),'agency');self.assertFalse(r['effects'])
    def test_three_questions_before_any_provider(self):
        for text, expected in [('Quero me agenciar','agency'),('Não','shop'),('Sim','gmv')]:
            r=self.send(text);self.assertEqual(stage(self.state['cycle']),expected);self.assertFalse(r['effects'])
        r=self.send('49.999,99');self.assertTrue(permitted(self.state['cycle']));self.assertEqual(self.state['cycle']['phase'],'tiktok')
        r=self.send('@synthetic');self.assertTrue(r['effects'])
    def test_handle_does_not_skip_validation(self):
        r=self.send('@synthetic');self.assertEqual(stage(self.state['cycle']),'agency');self.assertFalse(r['effects'])
        for text in ['Não','Sim','50k']:r=self.send(text);self.assertFalse(r['effects'])
        self.assertEqual(stage(self.state['cycle']),'choice')
        self.assertTrue(self.state['cycle']['bia_validation']['alert_requested'])
        r=self.send('Seguir com a Bia');self.assertEqual(self.state['cycle']['phase'],'checking');self.assertTrue(r['effects'])
    def test_exact_threshold_specialist_pauses_no_effects(self):
        for text in ['Quero me agenciar','Não','Sim','50000','Especialista']:
            r=self.send(text);self.assertFalse(r['effects'])
        self.assertEqual(stage(self.state['cycle']),'specialist')
        for text in ['@synthetic','Pode mandar','sim','aceitei']:
            r=self.send(text);self.assertFalse(r['effects']);self.assertEqual(stage(self.state['cycle']),'specialist')
        r=self.send('Seguir com a Bia');self.assertEqual(stage(self.state['cycle']),'complete')
    def test_agency_requires_declaration_unlink(self):
        self.send('Quero me agenciar');r=self.send('Outra agência')
        self.assertIn('desvincular',r['reply']);self.assertEqual(stage(self.state['cycle']),'unlink')
        r=self.send('@synthetic');self.assertFalse(r['effects']);self.assertEqual(stage(self.state['cycle']),'unlink')
        r=self.send('Já me desvinculei');self.assertEqual(stage(self.state['cycle']),'shop')
    def test_existing_amplify_never_unlinks_or_invites(self):
        self.send('Quero me agenciar');r=self.send('Já sou Amplify')
        self.assertEqual(stage(self.state['cycle']),'existing_profile')
        r=self.send('@synthetic');self.assertEqual(self.state['cycle']['phase'],'form');self.assertFalse(r['effects'])
        self.assertIn('confere seu agenciamento',r['reply'])
        self.assertNotIn('desvincular',r['reply'])
    def test_existing_member_followup_never_requests_acceptance(self):
        for text in ['Quero me agenciar','Já sou Amplify','@synthetic']:self.send(text)
        for text in ['Pode mandar','sim','@other']:
            r=self.send(text);self.assertFalse(r['effects']);self.assertNotIn('aceitar o convite',r['reply'])
    def test_button_titles_fit_chatwoot_roundtrip(self):
        from lead_validation import QUESTIONS
        for _,buttons in QUESTIONS.values():
            for label in buttons:self.assertLessEqual(len(label),20)
        for text in ['Quero me agenciar','Não','Sim','50k']:self.send(text)
        label=QUESTIONS['choice'][1][1][:20]
        self.send(label);self.assertEqual(stage(self.state['cycle']),'specialist')
    def test_bare_yes_requires_identify_agency(self):
        self.send('Quero me agenciar');r=self.send('Sim')
        self.assertEqual(stage(self.state['cycle']),'agency_kind');self.assertNotIn('desvincular',r['reply'])
        self.send('Outra agência');self.assertEqual(stage(self.state['cycle']),'unlink')
    def test_inactive_shop_holds_then_proceeds(self):
        for text in ['Quero me agenciar','Não','Não']:r=self.send(text)
        self.assertEqual(stage(self.state['cycle']),'activate');self.assertFalse(r['effects'])
        self.send('Já está ativo');self.assertEqual(stage(self.state['cycle']),'gmv')
    def test_unknown_fields_are_declarations_not_truth(self):
        for text in ['Quero me agenciar','Não sei','Não sei','Não sei']:self.send(text)
        facts=self.state['cycle']['facts'];self.assertIsNone(facts['shop_ativo_declarado']);self.assertIsNone(facts['gmv_30d_declarado_centavos'])
        self.assertNotIn('high_gmv',self.state['cycle']['bia_validation'])
    def test_default_existing_flow_unchanged(self):
        r=self.send('@synthetic',False);self.assertIsNone(stage(self.state['cycle']));self.assertTrue(r['effects'])
    def test_scope_flag_only_enabled_child(self):
        parent={'state_dir':'/tmp/synthetic','gate':{'mode':'todos'}}
        self.assertTrue(isolated_settings(parent,[SCOPE])['qualification_enabled']);self.assertNotIn('qualification_enabled',parent)
    def test_reset_and_pause_do_not_create_invite(self):
        for text in ['Quero me agenciar','Não','Sim','50k','Falar com especialista']:self.send(text)
        r=self.send('resetar');self.assertFalse(r['effects']);self.assertIsNone(stage(self.state['cycle']))
        self.send('Quero me agenciar');r=self.send('pausar');self.assertFalse(r['effects']);self.assertEqual(self.state['cycle']['status'],'closed')
    def test_block_effect_even_if_external_logic_attempts(self):
        self.send('@synthetic');r=real_journey._effect(self.state,'precheck',engine._clock(NOW));self.assertIsNone(r)
    def test_reset_does_not_retroactively_discard_outcome_unknown(self):
        self.send('Quero me agenciar');self.state['effects']['old']={'cycle_id':self.state['cycle']['id'],'operation':'invite','status':'running'}
        self.send('resetar');self.assertEqual(self.state['effects']['old']['status'],'outcome_unknown')

if __name__=='__main__':unittest.main()
