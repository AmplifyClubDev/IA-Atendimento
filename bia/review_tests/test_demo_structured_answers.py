"""Strict generic response schema and plain-language guidance, with synthetic model IO."""
import io
import json
import unittest
from unittest.mock import Mock, patch

from demo_answers import build_answerer, SMOKE_QUESTIONS
from demo_flow import format_answer


class StructuredAnswerCases(unittest.TestCase):
    def setUp(self):
        self.knowledge = {'source': 'database', 'knowledge_version': 'contextos-ia-v1:' + 'a' * 32 + '+' + 'b' * 12,
                          'card_count': 3, 'personality': 'Seja breve.', 'limits': 'Não garantir resultados.',
                          'topics': [{'id': 'benefits', 'answer': 'Os benefícios dependem da disponibilidade e da categoria.'},
                                     {'id': 'lives', 'answer': 'Fazer live não é obrigatório.'}]}
        self.value = {'answer': 'Os benefícios dependem da disponibilidade e da categoria.',
                      'evidence': [{'id': 'benefits', 'quote': 'Os benefícios dependem da disponibilidade e da categoria.'}]}

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
        self.assertEqual(len(SMOKE_QUESTIONS), 4)
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
        self.assertEqual(schema['properties']['answer'], {'type': 'string'})
        evidence = schema['properties']['evidence']
        self.assertEqual(evidence['type'], 'array')
        self.assertEqual(set(evidence['items']['required']), {'id', 'quote'})
        self.assertFalse(evidence['items']['additionalProperties'])
        self.assertEqual(evidence['items']['properties'], {'id': {'type': 'string'}, 'quote': {'type': 'string'}})

    def test_schema_does_not_replace_client_shape_and_evidence_checks(self):
        cases = [({**self.value, 'extra': True}, 'answer_schema'),
                 ({'answer': self.value['answer']}, 'answer_schema'),
                 ({**self.value, 'evidence': [{**self.value['evidence'][0], 'extra': True}]}, 'evidence_schema'),
                 ({**self.value, 'evidence': [{'id': 'lives', 'quote': 'Essa frase não está no card.'}]}, 'evidence_quote_mismatch'),
                 ({**self.value, 'answer': 'x' * 601}, 'answer_length')]
        for value, category in cases:
            with self.subTest(category=category):
                outcome, _, rows = self.run_answer(value=value)
                self.assertEqual(outcome, 'faq_unavailable')
                self.assertEqual(rows[-1]['category'], category)

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
                         'citações em evidence devem continuar literais', 'é opcional, sem pressão',
                         'omita esse convite se já apareceu na última resposta', 'não acrescente rodapé fixo'):
            self.assertIn(required, instructions)
        self.assertNotIn('O sistema acrescenta os botões e a pergunta final.', instructions)
        self.assertEqual(json.loads(body['input'])['conversation']['last_answer'], previous)
        self.assertEqual(outcome['answer'], format_answer(self.value['answer']))
        self.assertEqual(outcome['evidence'], self.value['evidence'])
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
                self.assertEqual(outcome['evidence'], self.value['evidence'])
                self.assertIs(rows[-1]['jargon_present'], flagged)
                self.assertEqual(rows[-1]['category'], 'answer_accepted')
                self.assertNotIn(text, json.dumps(rows))

    def test_jargon_inside_literal_evidence_is_not_treated_as_answer_jargon(self):
        quote = 'O processo operacional preserva as condições.'
        self.knowledge['topics'][0]['answer'] = quote
        value = {'answer': 'As condições são mantidas.', 'evidence': [{'id': 'benefits', 'quote': quote}]}
        outcome, _, rows = self.run_answer(value=value)
        self.assertIsInstance(outcome, dict)
        self.assertEqual(outcome['evidence'][0]['quote'], quote)
        self.assertFalse(rows[-1]['jargon_present'])
