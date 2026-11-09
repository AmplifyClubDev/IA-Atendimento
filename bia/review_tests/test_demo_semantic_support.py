"""Real answer/review pipeline, with synthetic HTTP and no external effects."""
import io
import json
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from demo_answers import build_answerer, _evidence_catalog
from demo_support import build_semantic_verifier, clarification_question

SETTINGS = {'ai_enabled': True, 'openai_api_key': 'private-synthetic-key', 'ai_model': 'test'}
VERSION = 'contextos-ia-v1:' + 'a' * 32 + '+' + 'b' * 12


def context():
    return {'source': 'database', 'knowledge_version': VERSION, 'card_count': 5,
            'personality': 'Seja breve e acolhedora.',
            'limits': 'Não prometa vendas, amostras, campanha ou acesso. Uma pergunta não é consentimento.',
            'topics': [
                {'id': 'beneficios', 'title': 'Benefícios',
                 'answer': 'A parceria pode incluir treinamentos e oportunidades, conforme categoria e disponibilidade.'},
                {'id': 'excecoes', 'title': 'Condições das oportunidades',
                 'answer': 'Acompanhamento individual não é benefício geral. Amostras dependem de aprovação da marca.'},
                {'id': 'saida', 'title': 'Saída da parceria',
                 'answer': 'É possível sair da parceria a qualquer momento, sem burocracia ou taxas adicionais. '
                           'Isso não confirma procedimento nem prazo de efetivação.'}]}


def envelope(value, **changes):
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
            'content': [{'type': 'output_text', 'text': json.dumps(value)}]}], **changes}


def response(value):
    return io.BytesIO(json.dumps(value).encode())


class SemanticPipeline(unittest.TestCase):
    def pipeline(self, text, verdict='supported', *, review=None, error=None, source='beneficios'):
        snapshot = context()
        ref = next(ref for ref, row in _evidence_catalog(snapshot).items() if row['id'] == source)
        opener = Mock()
        opener.open.side_effect = [response(envelope({'answer': text, 'evidence': [ref]})),
                                  error or response(review or envelope({'verdict': verdict}))]
        loader = Mock(return_value=snapshot)
        answerer = build_answerer(SETTINGS, opener=opener, context_loader=loader)
        return answerer, opener, loader

    def test_default_runtime_reviews_exact_snapshot_before_returning_answer(self):
        answerer, opener, loader = self.pipeline('A parceria pode incluir treinamentos, conforme categoria e disponibilidade.')
        result = answerer('Quais benefícios tenho?')
        self.assertIsInstance(result, dict)
        self.assertEqual(opener.open.call_count, 2)
        loader.assert_called_once()
        generation, review = [json.loads(c.args[0].data) for c in opener.open.call_args_list]
        self.assertEqual(generation['text']['format']['name'], 'bia_demo_answer')
        self.assertEqual(review['text']['format']['name'], 'bia_demo_turn_support')
        inputs = json.loads(review['input'])
        self.assertEqual(inputs['answer'], result['answer'])
        self.assertIn('excecoes', inputs['sources'])
        self.assertIn('aprovação da marca', inputs['sources']['excecoes'])
        self.assertEqual(inputs['operational_context']['confirmed_real_actions'], [])
        for body in (generation, review):
            self.assertFalse(body['store'])
            self.assertNotIn('tools', body)

    def test_existing_citation_is_not_enough_when_semantics_are_unsupported(self):
        for text in ('Você tem amostras e acompanhamento individual garantidos.',
                     'O vínculo já foi confirmado e seu convite foi aceito.',
                     'Pode sair sem custo, então a parceria inteira é gratuita.'):
            answerer, opener, _ = self.pipeline(text, 'unsupported')
            with patch('builtins.print') as log:
                self.assertEqual(answerer('Quais são os benefícios e custos?'), 'faq_unavailable')
            self.assertEqual(opener.open.call_count, 2)
            self.assertEqual(json.loads(log.call_args.args[0])['category'], 'semantic_unsupported')
            self.assertNotIn(text, str(log.call_args_list))

    def test_uncertain_timeout_refusal_or_incomplete_never_deliver_or_retry(self):
        cases = [{'verdict': 'uncertain'}, {'verdict': 'unexpected'}, {'verdict': 'supported', 'extra': True}]
        envelopes = [envelope(value) for value in cases] + [
            envelope({'verdict': 'supported'}, status='incomplete'),
            {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                'content': [{'type': 'refusal', 'refusal': 'private-provider-reason'}]}]}]
        for review in envelopes:
            with self.subTest(review=review):
                answerer, opener, _ = self.pipeline('Pode incluir treinamentos.', review=review)
                self.assertEqual(answerer('Quais benefícios?'), 'faq_unavailable')
                self.assertEqual(opener.open.call_count, 2)
        answerer, opener, _ = self.pipeline('Pode incluir treinamentos.', error=TimeoutError('private'))
        self.assertEqual(answerer('Quais benefícios?'), 'faq_unavailable')
        self.assertEqual(opener.open.call_count, 2)

    def test_malformed_generation_never_reaches_reviewer(self):
        opener = Mock()
        opener.open.return_value = response(envelope({'answer': 'Acesso garantido.', 'evidence': ['invented']}))
        answerer = build_answerer(SETTINGS, opener=opener, context_loader=lambda _: context())
        self.assertEqual(answerer('Quais benefícios?'), 'faq_unavailable')
        opener.open.assert_called_once()

    def test_checker_rejects_changed_snapshot_evidence_without_provider_call(self):
        opener = Mock()
        check = build_semantic_verifier(SETTINGS, opener=opener)
        good = {'answer': 'Pode incluir treinamentos.', 'knowledge_version': VERSION,
                'evidence': [{'id': 'beneficios', 'quote': context()['topics'][0]['answer']}]}
        for candidate in ({**good, 'knowledge_version': 'different'},
                          {**good, 'evidence': [{'id': 'beneficios', 'quote': 'quote removed its conditions'}]},
                          {**good, 'evidence': good['evidence'] * 2}):
            self.assertEqual(check('Quais benefícios?', candidate, context(), {}), 'uncertain')
        opener.open.assert_not_called()

    def test_structured_dialogue_is_bounded_redacted_and_never_authorizes_actions(self):
        answerer, opener, _ = self.pipeline('A parceria pode incluir treinamentos, conforme categoria e disponibilidade.')
        conversation = {'current_step': 'faq_context', 'return_step': 'invite',
                        'recent_dialogue': [{'question': '@secret_user mail@example.com ' + 'x' * 500,
                                             'answer': 'https://private.example ' + 'y' * 1000}] * 30,
                        'prior_questions': ['+55 11 99999-9999 ' + 'z' * 500] * 30,
                        'pending_clarification': 'Você se refere à parceria? @secret_user',
                        'operational_facts': {'real_membership_status': 'confirmed', 'consent': True}}
        self.assertIsInstance(answerer('Me chamo Pessoa Privada. @secret_user mail@example.com 123.456.789-00 sim', conversation=conversation), dict)
        for call in opener.open.call_args_list:
            inputs = json.loads(json.loads(call.args[0].data)['input'])
            dialogue = inputs['conversation']
            self.assertEqual(len(dialogue['recent_dialogue']), 6)
            self.assertEqual(len(dialogue['prior_questions']), 6)
            self.assertEqual(dialogue['operational_facts']['real_membership_status'], 'unverified')
            self.assertNotIn('consent', dialogue['operational_facts'])
            self.assertLessEqual(len(dialogue['recent_dialogue'][0]['answer']), 600)
            for private in ('@secret_user', 'mail@example.com', 'private.example', '99999-9999', 'Pessoa Privada', '123.456.789-00'):
                self.assertNotIn(private, json.dumps(inputs))

    def test_only_semantically_approved_disambiguation_has_clarification_metadata(self):
        answerer, _, _ = self.pipeline('Você se refere à parceria ou à comunidade?')
        result = answerer('Como funciona a saída?')
        self.assertIn('Você se refere', result['clarification_question'])
        answerer, _, _ = self.pipeline('Você se refere à parceria ou à comunidade?', 'unsupported')
        self.assertEqual(answerer('Como funciona a saída?'), 'faq_unavailable')

    def test_clarification_excludes_consent_data_requests_and_generic_cta(self):
        for text in ('Você autoriza o envio do convite?', 'Quer continuar?', 'Você confirma o aceite?',
                     'Qual dos seus emails devo usar?', 'Você quer saber se pode me mandar seu arroba?',
                     'Ficou mais claro?', 'Você se refere à parceria? Então envie seu email.'):
            self.assertEqual(clarification_question(text), '', text)
        for text in ('Você se refere à parceria ou à comunidade?',
                     'Há regras diferentes. Sua dúvida é sobre a parceria?'):
            self.assertTrue(clarification_question(text), text)

    def test_duplicate_assistant_message_is_uncertain(self):
        review = envelope({'verdict': 'supported'})
        review['output'] *= 2
        answerer, opener, _ = self.pipeline('Pode incluir treinamentos.', review=review)
        self.assertEqual(answerer('Quais benefícios?'), 'faq_unavailable')
        self.assertEqual(opener.open.call_count, 2)

    def test_review_prompt_covers_conditions_compound_questions_and_scope(self):
        answerer, opener, _ = self.pipeline('Pode incluir treinamentos, conforme categoria e disponibilidade.')
        answerer('Posso ganhar amostras, quanto pago e posso sair?')
        prompt = json.loads(opener.open.call_args.args[0].data)['instructions']
        for requirement in ('cada parte da pergunta', 'exceções', 'categoria', 'faixa de valores', 'comissão',
                            'parceria e comunidade', 'condição omitida', 'certeza sem suporte'):
            self.assertIn(requirement, prompt)

    def test_context_exhausting_turn_budget_never_calls_model(self):
        now = [0.0]
        def loader(_):
            now[0] = 29.0
            return context()
        opener = Mock()
        answerer = build_answerer(SETTINGS, opener=opener, context_loader=loader, clock=lambda: now[0])
        self.assertEqual(answerer('Quais benefícios?'), 'faq_unavailable')
        opener.open.assert_not_called()

    def test_rewrite_and_review_share_remaining_budget(self):
        now = [0.0]
        ref = next(ref for ref, row in _evidence_catalog(context()).items() if row['id'] == 'beneficios')
        values = [envelope({'answer': 'Os benefícios dependem de', 'evidence': [ref]}),
                  envelope({'answer': 'Pode incluir treinamentos, conforme categoria e disponibilidade.', 'evidence': [ref]}),
                  envelope({'verdict': 'supported'})]
        opener = Mock()
        def open_response(request, timeout):
            value = values.pop(0)
            now[0] += 12.0 if values else 1.0
            return response(value)
        opener.open.side_effect = open_response
        answerer = build_answerer(SETTINGS, opener=opener, context_loader=lambda _: context(), clock=lambda: now[0])
        self.assertIsInstance(answerer('Quais benefícios?'), dict)
        self.assertEqual([call.kwargs['timeout'] for call in opener.open.call_args_list], [12, 12, 4.0])

    def test_late_supported_review_is_not_delivered(self):
        now = [0.0]
        ref = next(ref for ref, row in _evidence_catalog(context()).items() if row['id'] == 'beneficios')
        opener = Mock()
        def open_response(request, timeout):
            if 'turn_support' in json.loads(request.data)['text']['format']['name']:
                now[0] = 29.0
                return response(envelope({'verdict': 'supported'}))
            return response(envelope({'answer': 'Pode incluir treinamentos.', 'evidence': [ref]}))
        opener.open.side_effect = open_response
        answerer = build_answerer(SETTINGS, opener=opener, context_loader=lambda _: context(), clock=lambda: now[0])
        self.assertEqual(answerer('Quais benefícios?'), 'faq_unavailable')
        self.assertEqual(opener.open.call_count, 2)
