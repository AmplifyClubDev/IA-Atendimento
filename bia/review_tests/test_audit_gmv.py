from datetime import datetime, timezone
import unittest
import lead_validation as lv

class AuditedGMV(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 14, tzinfo=timezone.utc)
        self.c = {'bia_validation': {'stage': 'gmv'}, 'phase': 'validation', 'facts': {}}

    def test_clear_no_sales_despite_beginner_clause(self):
        for text in ('Ainda não vendi nada, estou começando mas não sei como',
                     'Nunca vendi no TikTok Shop. Quero aprender a vender.',
                     'Eu não fiz nenhuma venda; ainda não sei como começar'):
            with self.subTest(text=text):
                self.assertEqual(lv.parse_gmv(text), 0)

    def test_no_inferred_zero(self):
        for text in ('Ainda não vendi nada, mas fiz 400 mês passado',
                     'Não vendi nada no TikTok Shop? Quero aprender',
                     'Estou começando e quero vender 500',
                     'Irei começar a vender amanhã'):
            with self.subTest(text=text):
                self.assertIsNone(lv.parse_gmv(text))

    def test_future_start_prompts_confirm_not_recorded_as_zero(self):
        for text in ('Irei começar a vender amanhã', 'Irie começar a vender amanhã', 'Vou começar a vender'):
            with self.subTest(text=text):
                self.setUp()
                self.assertEqual(lv.advance(self.c, text, self.now), lv.QUESTIONS['gmv_zero_confirmation'])
                self.assertEqual(self.c['facts'], {})
                self.assertEqual(self.c['bia_validation']['stage'], 'gmv_zero_confirmation')
                self.assertIsNone(lv.advance(self.c, 'Sim, nenhuma venda', self.now))
                self.assertEqual(self.c['facts']['gmv_30d_declarado_centavos'], 0)

    def test_explicit_no_sales_with_beginner_clause_completes_gmv(self):
        self.assertIsNone(lv.advance(self.c, 'Ainda não vendi nada, estou começando mas não sei como', self.now))
        self.assertEqual(self.c['facts']['gmv_30d_declarado_centavos'], 0)
        self.assertEqual(self.c['bia_validation']['stage'], 'complete')

    def test_large_declared_value_still_prompts_existing_choice(self):
        self.assertEqual(lv.advance(self.c, 'R$ 60.000', self.now), lv.QUESTIONS['priority_profile'])
        self.assertEqual(self.c['facts']['gmv_30d_declarado_centavos'], 6_000_000)
