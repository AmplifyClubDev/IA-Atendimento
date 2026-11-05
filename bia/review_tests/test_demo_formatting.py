import re
import unittest
from demo_flow import format_answer, payload, new_key, TEMPLATES
from demo_router import OPENING, CHOICES


class FormattingCases(unittest.TestCase):
    def test_every_scripted_step_uses_common_formatter_without_changing_words(self):
        for step, (original, choices) in TEMPLATES.items():
            if step == 'faq_context':
                continue
            message = payload(new_key('a' * 32, step), OPENING, CHOICES)
            self.assertEqual(re.findall(r'\w+', message['content']), re.findall(r'\w+', original))
            self.assertNotIn('**', message['content'])
            self.assertEqual(message['content'].count('*') % 2, 0)
            self.assertEqual([i['title'] for i in message['content_attributes']['items']], list(choices.values()))
            self.assertLessEqual(len(message['content'].encode('utf-16-le')) // 2, 1024)

    def test_dense_benefits_keep_conditions_and_become_list(self):
        original = ('A parceria pode oferecer treinamentos, campanhas, suporte e comunidade no Circle. '
                    'Os recursos variam por categoria e disponibilidade. '
                    'Acompanhamento individual depende da categoria Diamond.')
        result = format_answer(original)
        for fact in ('treinamentos', 'campanhas', 'suporte', 'comunidade no Circle',
                     'Os recursos variam por categoria e disponibilidade.',
                     'Acompanhamento individual depende da categoria Diamond.'):
            self.assertIn(fact, result)
        self.assertEqual(result.count('\n- '), 4)
        self.assertIn('\n\nOs recursos', result)
        self.assertNotIn('**', result)
        self.assertEqual(format_answer(result), result)

    def test_markdown_conversion_preserves_numbers_and_whatsapp_envelope(self):
        answer = '**Referência de comissão:** 10% sobre comissões.\n\nConfira as condições do convite.'
        key = new_key('a' * 32, 'faq_context')
        message = payload(key, OPENING, CHOICES, answer)
        self.assertIn('*Referência de comissão:* 10%', message['content'])
        self.assertTrue(message['content'].endswith('\n\nFicou mais claro?'))
        self.assertEqual([i['title'] for i in message['content_attributes']['items']],
                         ['Quero me agenciar', 'Tenho outra dúvida'])
        self.assertLessEqual(len(message['content'].encode('utf-16-le')) // 2, 1024)
        self.assertEqual(message['content'].count('*') % 2, 0)

    def test_overflow_is_rejected_not_truncated(self):
        with self.assertRaises(ValueError):
            format_answer('Condição essencial. ' * 100)

    def test_decimals_and_simple_answers_remain_intact(self):
        self.assertIn('R$ 4.999', format_answer('Categoria sintética até R$ 4.999.'))
        answer = format_answer('Fazer live não é obrigatório para participar da parceria.')
        self.assertIn('🎥', answer)
        self.assertIn('*Fazer live não é obrigatório', answer)
