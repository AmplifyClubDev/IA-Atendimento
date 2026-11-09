# Structural tests isolate generation; semantic gating has dedicated integration coverage.
"""Complete demo answers, bounded rewrite, and explicit separation of facts and simulated steps."""
import io
import json
import unittest
from unittest.mock import Mock, patch

import config
from demo_answers import build_answerer, _evidence_catalog, _answer_integrity_issue, SMOKE_QUESTIONS
from demo_flow import format_answer
import test_demo_flow as fixtures

VERSION = 'contextos-ia-v1:' + '0' * 32 + '+' + 'a' * 12
EXIT_RULE = 'A pessoa pode sair da parceria a qualquer momento, sem burocracia ou taxas adicionais.'


def knowledge():
    return {'source': 'database', 'knowledge_version': VERSION, 'card_count': 4, 'personality': 'Fale de forma acolhedora.',
            'limits': ('A regra de saída não define gratuidade geral. Procedimento e prazo de efetivação não estão confirmados. '
                       'Conhecimento não comprova convite enviado, aceite ou vínculo real.'),
            'topics': [{'id': 'partnership_exit', 'answer': EXIT_RULE},
                       {'id': 'benefits', 'answer': 'A parceria pode incluir treinamentos e comunidade, conforme categoria e disponibilidade.'}]}


def opener_for(texts, *, source_id='benefits', evidence=None):
    catalog = _evidence_catalog(knowledge())
    ref = next(ref for ref, item in catalog.items() if item['id'] == source_id)
    opener = Mock()
    responses = []
    for text in texts:
        value = {'answer': text, 'evidence': [ref] if evidence is None else evidence}
        envelope = {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}
        responses.append(io.BytesIO(json.dumps(envelope).encode()))
    opener.open.side_effect = responses
    return opener


def answerer(opener):
    loader = Mock(return_value=knowledge())
    return build_answerer({'ai_enabled': True, 'openai_api_key': 'synthetic', 'ai_model': 'test'},
                          opener=opener, context_loader=loader, semantic_verifier=lambda *_: 'supported'), loader


class IntegrityCases(unittest.TestCase):
    def test_formatter_preserves_the_reported_fragment_instead_of_truncating(self):
        fragment = 'Os benefícios variam pelas *'
        self.assertIn(fragment, format_answer(fragment))
        self.assertEqual(_answer_integrity_issue(fragment), 'unbalanced_emphasis')

    def test_guard_catches_unbalanced_or_unfinished_and_preserves_complete_answers(self):
        for text, reason in [('Os benefícios variam pelas *', 'unbalanced_emphasis'),
                             ('Os benefícios dependem de', 'unfinished_ending'),
                             ('A parceria inclui:', 'unfinished_ending'),
                             ('x' * 600, 'length_boundary'),
                             ('x' * 590 + ' 🎥', 'length_boundary')]:
            with self.subTest(text=text[:25]):
                self.assertEqual(_answer_integrity_issue(text), reason)
        for text in ('*Você escolhe.*', 'Não é obrigatório fazer live', 'Você escolhe. 🎥',
                     'Pode sair a qualquer momento, sem burocracia nem taxas adicionais.', 'x' * 599 + '.'):
            with self.subTest(text=text[:25]):
                self.assertIsNone(_answer_integrity_issue(text))

    def test_one_rewrite_uses_same_snapshot_without_truncation_or_added_facts(self):
        broken = 'Os benefícios variam pelas *'
        complete = 'A parceria pode incluir treinamentos e comunidade, conforme sua categoria e a disponibilidade.'
        opener = opener_for([broken, complete])
        answer, loader = answerer(opener)
        with patch('builtins.print') as log:
            result = answer('Quais benefícios tenho?')
        self.assertEqual(result['answer'], format_answer(complete))
        self.assertNotIn(broken, result['answer'])
        self.assertEqual(opener.open.call_count, 2)
        loader.assert_called_once()
        bodies = [json.loads(call.args[0].data) for call in opener.open.call_args_list]
        self.assertEqual(bodies[0]['input'], bodies[1]['input'])
        self.assertEqual(bodies[0]['text'], bodies[1]['text'])
        self.assertEqual(bodies[0]['max_output_tokens'], bodies[1]['max_output_tokens'])
        self.assertIn('180 a 280 caracteres', bodies[1]['instructions'])
        self.assertNotIn(broken, bodies[1]['input'])
        rows = [json.loads(call.args[0]) for call in log.call_args_list]
        self.assertEqual([row['category'] for row in rows], ['context_loaded', 'answer_rewrite_requested', 'answer_accepted'])
        self.assertEqual(rows[1]['integrity_issue'], 'unbalanced_emphasis')
        self.assertNotIn(broken, json.dumps(rows))

    def test_second_incomplete_answer_is_closed_without_a_third_attempt(self):
        opener = opener_for(['Os benefícios variam pelas *', 'Os benefícios dependem de', 'Should never run.'])
        answer, loader = answerer(opener)
        with patch('builtins.print') as log:
            self.assertEqual(answer('Quais benefícios?'), 'faq_unavailable')
        self.assertEqual(opener.open.call_count, 2)
        loader.assert_called_once()
        self.assertEqual(json.loads(log.call_args.args[0])['category'], 'answer_integrity')

    def test_unknown_evidence_never_triggers_rewrite(self):
        opener = opener_for(['Os benefícios variam pelas *'], evidence=['unknown'])
        answer, _ = answerer(opener)
        self.assertEqual(answer('Quais benefícios?'), 'faq_unavailable')
        opener.open.assert_called_once()

    def test_complete_600_character_answer_is_not_cut_or_rewritten(self):
        text = 'x' * 599 + '.'
        opener = opener_for([text])
        answer, _ = answerer(opener)
        result = answer('Quais benefícios?')
        self.assertIn(text, result['answer'])
        self.assertEqual(result['answer'], format_answer(text))
        opener.open.assert_called_once()

    def test_provider_error_in_rewrite_is_closed_without_retry(self):
        opener = opener_for(['Os benefícios variam pelas *'])
        first = next(iter(opener.open.side_effect))
        opener.open.side_effect = [first, TimeoutError('private failure')]
        answer, loader = answerer(opener)
        self.assertEqual(answer('Quais benefícios?'), 'faq_unavailable')
        self.assertEqual(opener.open.call_count, 2)
        loader.assert_called_once()


class ContextBoundaryCases(unittest.TestCase):
    def test_v3_is_exactly_allowlisted_and_stays_demo_only(self):
        self.assertIsNone(config.demo_context_issue({'demo_enabled': True, 'demo_context_version': 'amplify_circle_20261106_v3'}))
        self.assertEqual(config.demo_context_issue({'demo_enabled': False, 'demo_context_version': 'amplify_circle_20261106_v3'}),
                         'demo_context_requires_demo')
        self.assertEqual(config.demo_context_issue({'demo_enabled': True, 'demo_context_version': 'amplify_circle_20261106_v3 '}),
                         'demo_context_version_invalid')

    def test_exit_paraphrases_use_source_not_fixed_phrase_or_presumed_stage(self):
        natural = 'Sim, você pode sair da parceria a qualquer momento, sem burocracia nem taxas adicionais. Fique à vontade para decidir no seu ritmo.'
        for question in ('Posso sair a qualquer hora?', 'Se eu quiser deixar a parceria, tem burocracia?',
                         'Preciso pagar alguma taxa adicional para sair?'):
            with self.subTest(question=question):
                opener = opener_for([natural], source_id='partnership_exit')
                answer, _ = answerer(opener)
                result = answer(question, conversation={'current_step': 'faq_context', 'return_step': 'invite',
                    'last_answer': 'O convite que você aceitou.', 'invitation_accepted': True,
                    'operational_context': {'confirmed_real_actions': ['invitation_accepted']}})
                body = json.loads(opener.open.call_args.args[0].data)
                inputs = json.loads(body['input'])
                self.assertEqual(inputs['question'], question)
                self.assertEqual(inputs['operational_context'], {'mode': 'demo', 'confirmed_real_actions': [],
                                                               'real_membership_status': 'unverified'})
                self.assertNotIn('invitation_accepted', inputs['conversation'])
                self.assertIn(EXIT_RULE, json.dumps(inputs, ensure_ascii=False))
                self.assertNotIn(EXIT_RULE, body['instructions'])
                self.assertEqual(result['evidence'][0]['quote'], EXIT_RULE)
                self.assertEqual(result['answer'], format_answer(natural))
                for phrase in ('não comprovam ações', 'não comprovam convite enviado',
                               'Mantenha o assunto perguntado', 'Não deduza um do outro',
                               'sem acrescentar restrições hipotéticas', 'Não diga que o material não confirma'):
                    self.assertIn(phrase, body['instructions'])

    def test_smoke_covers_six_cases_including_exit_without_expanding_unboundedly(self):
        self.assertEqual(len(SMOKE_QUESTIONS), 6)
        self.assertEqual({name for name, _ in SMOKE_QUESTIONS}, {'benefits', 'benefits_paraphrase', 'lives',
                         'lives_paraphrase', 'partnership_exit', 'partnership_exit_paraphrase'})


class RewriteDeliveryCases(unittest.TestCase):
    setUp = fixtures.FlowCases.setUp
    source = fixtures.FlowCases.source
    choose = fixtures.FlowCases.choose

    def test_rewrite_does_not_duplicate_message_or_retry_uncertain_delivery(self):
        self.choose('know')
        opener = opener_for(['Os benefícios variam pelas *',
                            'A parceria pode incluir treinamentos e comunidade, conforme categoria e disponibilidade.'])
        self.router.question_answerer, loader = answerer(opener)
        send = self.gateway.send
        def uncertain(scope, payload, key):
            send(scope, payload, key)
            raise TimeoutError()
        self.gateway.send = Mock(side_effect=uncertain)
        source = self.source('faq_benefits')
        first = self.router.handle(source)
        self.assertEqual(first[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.router.handle(source), first)
        self.assertEqual(self.router.handle(self.source(text='Tentar novamente', correlated=False))[0]['status'],
                         'demo_delivery_unconfirmed')
        self.assertEqual(opener.open.call_count, 2)
        loader.assert_called_once()
        self.gateway.send.assert_called_once()
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 0)
