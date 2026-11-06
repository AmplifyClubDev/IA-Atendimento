"""Strict generic response schema and plain-language guidance, with synthetic model IO."""
import io
import json
import unittest
from unittest.mock import Mock, patch

from demo_answers import build_answerer, SMOKE_QUESTIONS, _evidence_catalog
from demo_flow import format_answer


class StructuredAnswerCases(unittest.TestCase):
    def setUp(self):
        self.knowledge = {'source': 'database', 'knowledge_version': 'contextos-ia-v1:' + 'a' * 32 + '+' + 'b' * 12,
                          'card_count': 3, 'personality': 'Seja breve.', 'limits': 'Não garantir resultados.',
                          'topics': [{'id': 'benefits', 'answer': 'Os benefícios dependem da disponibilidade e da categoria.'},
                                     {'id': 'lives', 'answer': 'Fazer live não é obrigatório.'}]}
        self.catalog = _evidence_catalog(self.knowledge)
        self.reference = next(ref for ref, item in self.catalog.items() if item['id'] == 'benefits')
        self.expected_evidence = [self.catalog[self.reference]]
        self.value = {'answer': 'Os benefícios dependem da disponibilidade e da categoria.', 'evidence': [self.reference]}

    def run_answer(self, *, question='Quais benefícios?', value=None, output_text=None, envelope=None, conversation=None):
        if envelope is None:
            envelope = {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': output_text if output_text is not None else
                             json.dumps(self.value if value is None else value)}]}]}
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(envelope).encode())
        answer = build_answerer({'ai_enabled': True, 'openai_api_key': 'private-synthetic-key', 'ai_model': 'test'},
                                opener=opener, context_loader=lambda _: self.knowledge)
        with patch('builtins.print') as log:
            outcome = answer(question, conversation=conversation)
        opener.open.assert_called_once()
        body = json.loads(opener.open.call_args.args[0].data)
        return outcome, body, [json.loads(call.args[0]) for call in log.call_args_list]

    def test_all_paraphrases_send_the_same_strict_general_schema(self):
        self.assertEqual(len(SMOKE_QUESTIONS), 6)
        self.assertIn(('lives', 'Sou obrigado a fazer live para ser agenciado?'), SMOKE_QUESTIONS)
        formats = []
        for _, question in (*SMOKE_QUESTIONS, ('other', 'Como funciona a comunidade?')):
            with self.subTest(question=question):
                outcome, body, _ = self.run_answer(question=question)
                self.assertIsInstance(outcome, dict)
                self.assertEqual(json.loads(body['input'])['question'], question)
                formats.append(body['text']['format'])
                self.assertEqual(body['max_output_tokens'], 1500)
                self.assertFalse(body['store'])
                self.assertNotIn('tools', body)
        self.assertTrue(all(item == formats[0] for item in formats))
        fmt = formats[0]
        self.assertEqual(fmt['type'], 'json_schema')
        self.assertTrue(fmt['strict'])
        self.assertEqual(fmt['name'], 'bia_demo_answer')
        schema = fmt['schema']
        self.assertEqual(schema['type'], 'object')
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(set(schema['required']), {'answer', 'evidence'})
        self.assertEqual(schema['properties']['answer'], {'type': 'string', 'minLength': 0, 'maxLength': 600})
        evidence = schema['properties']['evidence']
        self.assertEqual(evidence['type'], 'array')
        self.assertEqual(evidence['items']['type'], 'string')
        self.assertEqual(evidence['items']['enum'], sorted(self.catalog))

    def test_schema_does_not_replace_client_shape_and_evidence_checks(self):
        cases = [({**self.value, 'extra': True}, 'answer_schema'),
                 ({'answer': self.value['answer']}, 'answer_schema'),
                 ({**self.value, 'evidence': [{'id': 'benefits', 'quote': 'legacy object', 'extra': True}]}, 'evidence_schema'),
                 ({**self.value, 'evidence': ['unknown-reference']}, 'evidence_source'),
                 ({**self.value, 'answer': 'x' * 601}, 'answer_length')]
        for value, category in cases:
            with self.subTest(category=category):
                outcome, _, rows = self.run_answer(value=value)
                self.assertEqual(outcome, 'faq_unavailable')
                self.assertEqual(rows[-1]['category'], category)

    def test_answer_length_schema_and_client_bounds_agree_without_truncation(self):
        outcome, body, _ = self.run_answer(value={**self.value, 'answer': 'x' * 599 + '.'})
        self.assertIsInstance(outcome, dict)
        self.assertIn('x' * 599 + '.', outcome['answer'])
        self.assertEqual(body['text']['format']['schema']['properties']['answer']['maxLength'], 600)
        outcome, _, rows = self.run_answer(value={**self.value, 'answer': 'x' * 601})
        self.assertEqual(outcome, 'faq_unavailable')
        self.assertEqual(rows[-1]['category'], 'answer_length')
        outcome, _, rows = self.run_answer(value={'answer': '', 'evidence': []})
        self.assertEqual(outcome, 'faq_unknown')
        self.assertEqual(rows[-1]['category'], 'knowledge_not_supported')

    def test_markdown_or_extra_prose_is_not_tolerantly_reparsed(self):
        for text in ('```json\n' + json.dumps(self.value) + '\n```',
                     'Aqui está: ' + json.dumps(self.value), json.dumps(self.value) + ' Texto extra.'):
            with self.subTest(text=text[:12]):
                outcome, _, rows = self.run_answer(output_text=text)
                self.assertEqual(outcome, 'faq_unavailable')
                self.assertEqual(rows[-1]['category'], 'model_json')

    def test_refusal_and_incomplete_remain_fail_closed_without_retry(self):
        for envelope, category in [
                ({'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                    'content': [{'type': 'refusal', 'refusal': 'private refusal text'}]}]}, 'provider_refusal'),
                ({'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}}, 'provider_incomplete')]:
            with self.subTest(category=category):
                outcome, body, rows = self.run_answer(envelope=envelope)
                self.assertEqual(outcome, 'faq_unavailable')
                self.assertEqual(rows[-1]['category'], category)
                self.assertTrue(body['text']['format']['strict'])
                self.assertNotIn('private refusal text', json.dumps(rows))

    def test_plain_portuguese_prompt_keeps_facts_quotes_and_optional_closing(self):
        previous = 'Se quiser, podemos continuar ou tirar outra dúvida.'
        outcome, body, _ = self.run_answer(conversation={'current_step': 'faq_context', 'return_step': 'about',
                                                        'last_question': 'O que está incluído?', 'last_answer': previous})
        instructions = body['instructions']
        for required in ('português simples, natural e acolhedor', 'processo operacional, base, contexto',
                         'validação interna ou roteamento', 'Preserve todos os fatos, condições e limites',
                         'Escolha evidências apenas pelas referências fornecidas', 'é opcional, sem pressão',
                         'omita esse convite se já apareceu na última resposta', 'não acrescente rodapé fixo'):
            self.assertIn(required, instructions)
        self.assertNotIn('O sistema acrescenta os botões e a pergunta final.', instructions)
        self.assertEqual(json.loads(body['input'])['conversation']['last_answer'], previous)
        self.assertEqual(outcome['answer'], format_answer(self.value['answer']))
        self.assertEqual(outcome['evidence'], self.expected_evidence)
        self.assertNotIn(previous, outcome['answer'])

    def test_jargon_is_advisory_boolean_only_not_a_new_fallback_or_edit(self):
        for text, flagged in [('O processo operacional depende da disponibilidade.', True),
                              ('A validação interna depende da disponibilidade.', True),
                              ('O contexto da base usa roteamento.', True),
                              ('As opções dependem da disponibilidade.', False)]:
            with self.subTest(flagged=flagged):
                value = {**self.value, 'answer': text}
                outcome, _, rows = self.run_answer(value=value)
                self.assertIsInstance(outcome, dict)
                self.assertEqual(outcome['answer'], format_answer(text))
                self.assertEqual(outcome['evidence'], self.expected_evidence)
                self.assertIs(rows[-1]['jargon_present'], flagged)
                self.assertEqual(rows[-1]['category'], 'answer_accepted')
                self.assertNotIn(text, json.dumps(rows))

    def test_visual_brevity_applies_to_every_topic_without_removing_qualifiers(self):
        for question in ('Quais benefícios?', 'O que eu ganho na parceria?', 'Preciso fazer lives?',
                         'Posso sair da parceria?', 'Como funciona a comunidade?'):
            with self.subTest(question=question):
                _, body, _ = self.run_answer(question=question)
                instructions = body['instructions']
                for phrase in ('entre 180 e 280 caracteres', 'não há mínimo', 'até 3 pontos essenciais',
                               'uma ideia por frase', 'palavras próprias', 'duas quebras de linha',
                               'um item curto por linha', '1 a 3 emojis pertinentes', 'a última resposta',
                               'Não despeje todos os cards', 'não as condições dos fatos que mantiver',
                               'Nunca corte frase, palavra, ressalva', 'o teto é 600, não uma meta'):
                    self.assertIn(phrase, instructions)
                self.assertNotIn('300 e 450', instructions)
                self.assertNotIn('300 a 450', instructions)
                self.assertEqual(body['text']['format']['schema']['properties']['answer']['maxLength'], 600)

    def test_short_visual_answers_keep_spacing_emoji_and_complete_source_evidence(self):
        examples = (
            '📚 *As opções variam.*\n\n- Por categoria.\n- Conforme a disponibilidade.',
            '🤝 *Depende da sua categoria.*\n\nE também da disponibilidade de cada benefício.',
            '📋 *A categoria e a disponibilidade definem as opções.*',
        )
        for text in examples:
            with self.subTest(text=text):
                outcome, _, rows = self.run_answer(value={**self.value, 'answer': text})
                self.assertEqual(outcome['answer'], format_answer(text))
                self.assertIn(text, outcome['answer'])
                self.assertEqual(outcome['evidence'], self.expected_evidence)
                self.assertEqual(rows[-1]['category'], 'answer_accepted')

    def test_soft_brevity_target_does_not_cut_or_retry_a_complete_longer_answer(self):
        text = ('Cada benefício depende da categoria e da disponibilidade. ' * 6).strip()
        self.assertGreater(len(text), 280)
        self.assertLess(len(text), 600)
        outcome, _, rows = self.run_answer(value={**self.value, 'answer': text})
        self.assertEqual(outcome['answer'], format_answer(text))
        self.assertEqual([row['category'] for row in rows], ['context_loaded', 'answer_accepted'])

    def test_jargon_inside_literal_evidence_is_not_treated_as_answer_jargon(self):
        quote = 'O processo operacional preserva as condições.'
        self.knowledge['topics'][0]['answer'] = quote
        reference = next(ref for ref, item in _evidence_catalog(self.knowledge).items() if item['id'] == 'benefits')
        value = {'answer': 'As condições são mantidas.', 'evidence': [reference]}
        outcome, _, rows = self.run_answer(value=value)
        self.assertIsInstance(outcome, dict)
        self.assertEqual(outcome['evidence'][0]['quote'], quote)
        self.assertFalse(rows[-1]['jargon_present'])
