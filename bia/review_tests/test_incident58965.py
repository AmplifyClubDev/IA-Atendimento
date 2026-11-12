"""Regression for incident 58965. Synthetic data; no external calls."""
import unittest
import socket
from unittest.mock import patch
import lead_validation
import receipt_grounding

POLICY = {'approved': True, 'commission': 10, 'commission_unit': 'percent',
          'duration_fixed_months': 2, 'duration_label': '2 meses', 'version': 'approved-test58965'}
NOW = '2026-11-12T21:00:00Z'

class Incident58965(unittest.TestCase):
    def setUp(self):
        self.guards = [patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')),
                       patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden'))]
        for guard in self.guards:
            guard.start()
            self.addCleanup(guard.stop)
        self.state = {'cycle': {'id': 'synthetic-cycle', 'facts': {'tiktok_declarado': '@synthetic'},
                      'real_operations': {'invite': {'status': 'failed', 'confirmed': False,
                      'evidence': {'http_status': 422, 'create_accepted': False, 'post_attempted': True}}}}}
    def ground(self, question, reply='Seu convite foi enviado. Pode aceitar!', **plan):
        return receipt_grounding.ground_reply(question, reply, {'intent':'question', **plan},
                                             self.state, policy=POLICY, now=NOW)
    def test_explicit_no_sales_is_zero(self):
        for text in ['Ainda não vendi. Quero aprender', 'Ainda não vendi', 'Não vendi nada',
                     'Nunca vendi', 'Não fiz nenhuma venda', 'nenhuma venda', 'zero']:
            with self.subTest(text=text): self.assertEqual(lead_validation.parse_gmv(text), 0)
    def test_ambiguous_no_sales_never_inferred(self):
        for text in ['Quero aprender', 'sou iniciante', 'Ainda não vendi 50k',
                     'Ainda não vendi. Mas vendi 100 ontem', 'Não sei', 'mais de 50k']:
            with self.subTest(text=text): self.assertIsNone(lead_validation.parse_gmv(text))
    def test_gmv_threshold_still_inclusive(self):
        for text in ['50k','50.000','R$ 50.000,00']:
            with self.subTest(text=text): self.assertEqual(lead_validation.parse_gmv(text), 5_000_000)
        self.assertEqual(lead_validation.parse_gmv('49.999,99'),4_999_999)
    def test_after_term_does_not_invent_renewal(self):
        for text in ['E depois de 2 meses o que acontece?', 'Após dois meses?', 'Depois de dois meses renova?']:
            with self.subTest(text=text):
                reply=self.ground(text, topic_ids=['custos','convite_tiktok'])
                self.assertIn('não tenho uma regra confirmada sobre renovação',reply)
                self.assertIn('2 meses',reply)
                self.assertNotIn('Parcerias',reply)
                self.assertNotIn('foi enviado',reply)
    def test_missing_policy_does_not_invent_terms(self):
        reply=receipt_grounding.approved_cost_reply('Depois de 2 meses?',{},None)
        self.assertIn('precisam estar confirmadas',reply)
    def test_failed_invite_never_supplies_acceptance_guide(self):
        for question in ['Como aceitar o convite?', 'Onde está meu convite?', 'Meu convite chegou?']:
            with self.subTest(question=question):
                reply=self.ground(question)
                self.assertIn('tentativa de envio falhou',reply)
                self.assertNotIn('Para aceitar, abra',reply)
                self.assertNotIn('Parcerias',reply)
                self.assertNotIn('recusada pelo TikTok',reply)
                self.assertNotIn('foi enviado',reply)
    def test_combined_cost_and_status_preserved(self):
        reply=self.ground('Qual a taxa e meu convite chegou?',topic_ids=['custos'])
        self.assertIn('10%',reply)
        self.assertIn('tentativa de envio falhou',reply)
    def test_pure_cost_does_not_append_unrelated_invitation_status(self):
        reply=self.ground('Pode explicar a taxa de 10%?',topic_ids=['custos','convite_tiktok'])
        self.assertIn('10%',reply)
        self.assertNotIn('convite',reply)

if __name__ == '__main__': unittest.main()
