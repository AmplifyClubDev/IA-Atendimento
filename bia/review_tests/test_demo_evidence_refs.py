# Structural tests isolate generation; semantic gating has dedicated integration coverage.
"""Full-source references and smoke-only semantic review, with synthetic provider IO."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from demo_answers import (_evidence_catalog, build_answerer, build_smoke_verifier,
                          schedule_smoke_check, SMOKE_QUESTIONS)
from demo_router import DemoStore
from test_demo_smoke import ImmediateThread, values, SCOPE

VERSION = 'contextos-ia-v1:' + '0' * 32 + '+' + 'a' * 12


def knowledge():
    return {'source': 'database', 'knowledge_version': VERSION, 'card_count': 3, 'personality': 'Be kind.',
            'limits': 'Não prometa resultados nem acesso garantido.',
            'topics': [{'id': 'benefits', 'title': 'Benefícios',
                        'answer': 'A parceria pode incluir treinamentos.\n\nA disponibilidade depende da categoria e de cada ação.'}]}


def model_response(value):
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}


def settings():
    return {**values(), 'openai_api_key': 'private-synthetic-key', 'ai_model': 'test'}


class CatalogCases(unittest.TestCase):
    def test_refs_are_stable_across_order_but_change_with_source_text(self):
        context = knowledge()
        context['topics'].append({'id': 'lives', 'answer': 'Fazer live não é obrigatório.'})
        first = _evidence_catalog(context)
        context['topics'].reverse()
        self.assertEqual(_evidence_catalog(context), first)
        context['topics'][1]['answer'] += ' Outra condição importante.'
        second = _evidence_catalog(context)
        unchanged = [ref for ref, row in first.items() if row['id'] in {'lives', 'limits'}]
        self.assertTrue(all(ref in second for ref in unchanged))
        old_ref = next(ref for ref, row in first.items() if row['id'] == 'benefits')
        self.assertNotIn(old_ref, second)

    def test_full_sources_and_qualifiers_are_preserved_without_truncation(self):
        context = knowledge()
        catalog = _evidence_catalog(context)
        sources = {item['id']: item['quote'] for item in catalog.values()}
        self.assertEqual(sources['benefits'], context['topics'][0]['answer'])
        self.assertEqual(sources['limits'], context['limits'])
        self.assertIn('\n\nA disponibilidade depende', sources['benefits'])

    def test_catalog_count_and_total_budget_fail_closed_without_partial_catalog(self):
        context = knowledge()
        context['topics'] = [{'id': 'topic_' + str(i), 'answer': 'Texto sintético completo.'} for i in range(62)]
        self.assertEqual(len(_evidence_catalog(context)), 63)
        context['topics'].append({'id': 'overflow', 'answer': 'Texto sintético completo.'})
        with self.assertRaises(ValueError): _evidence_catalog(context)
        context = knowledge()
        context['topics'] = [{'id': 'topic_' + str(i), 'answer': 'x' * 8000} for i in range(6)]
        with self.assertRaises(ValueError): _evidence_catalog(context)
        context = knowledge(); context['topics'][0]['answer'] = 'x' * 8001
        with self.assertRaises(ValueError): _evidence_catalog(context)

    def test_ambiguous_source_identifiers_are_rejected(self):
        for identifier in ('limits', 'benefits'):
            context = knowledge()
            context['topics'].append({'id': identifier, 'answer': 'Outra fonte sintética longa.'})
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                _evidence_catalog(context)

    def test_schema_and_server_resolve_refs_from_same_snapshot(self):
        context = knowledge()
        reference = next(ref for ref, item in _evidence_catalog(context).items() if item['id'] == 'benefits')
        value = {'answer': 'Você pode ter treinamentos, conforme sua categoria e a disponibilidade da ação.', 'evidence': [reference]}
        opener = Mock(); opener.open.return_value = io.BytesIO(json.dumps(model_response(value)).encode())
        answer = build_answerer(settings(), opener=opener, context_loader=lambda _: context, semantic_verifier=lambda *_: 'supported')
        with patch('demo_answers.build_smoke_verifier', side_effect=AssertionError('verifier cannot run in conversation')):
            result = answer('Quais vantagens tenho?')
        self.assertEqual(result['answer'].replace('*', '').replace('📚 ', ''), value['answer'])
        self.assertEqual(result['evidence'], [{'id': 'benefits', 'quote': context['topics'][0]['answer']}])
        self.assertEqual(set(result), {'answer', 'evidence', 'knowledge_version'})
        body = json.loads(opener.open.call_args.args[0].data)
        inputs = json.loads(body['input'])
        self.assertEqual(inputs['context'], context)
        self.assertEqual(inputs['evidence_sources'][reference], 'benefits')
        self.assertTrue(all(isinstance(source_id, str) for source_id in inputs['evidence_sources'].values()))
        self.assertIn('Responda com suas próprias palavras', body['instructions'])
        enum = body['text']['format']['schema']['properties']['evidence']['items']['enum']
        self.assertEqual(enum, sorted(_evidence_catalog(context)))
        self.assertLess(len(json.dumps(body['text']['format'])), 5000)

    def test_unknown_duplicate_legacy_and_empty_evidence_do_not_pass(self):
        context = knowledge(); reference = next(iter(_evidence_catalog(context)))
        for evidence in (['unknown'], [reference, reference], [], [{'id': 'benefits', 'quote': context['topics'][0]['answer']}],
                         [reference] * 7):
            with self.subTest(evidence=evidence):
                opener = Mock()
                opener.open.return_value = io.BytesIO(json.dumps(model_response({'answer': 'Resposta sintética.', 'evidence': evidence})).encode())
                answer = build_answerer(settings(), opener=opener, context_loader=lambda _: context, semantic_verifier=lambda *_: 'supported')
                self.assertEqual(answer('Quais vantagens tenho?'), 'faq_unavailable')
                opener.open.assert_called_once()

    def test_old_reference_cannot_be_used_after_source_change(self):
        context = knowledge()
        ref = next(ref for ref, row in _evidence_catalog(context).items() if row['id'] == 'benefits')
        context['topics'][0]['answer'] += ' Condições atualizadas.'
        opener = Mock(); opener.open.return_value = io.BytesIO(json.dumps(model_response({'answer': 'Resposta.', 'evidence': [ref]})).encode())
        answer = build_answerer(settings(), opener=opener, context_loader=lambda _: context, semantic_verifier=lambda *_: 'supported')
        self.assertEqual(answer('Quais vantagens?'), 'faq_unavailable')


class SemanticVerifierCases(unittest.TestCase):
    def setUp(self):
        self.context = knowledge()
        self.answer = {'answer': 'Treinamentos podem estar disponíveis conforme a categoria e cada ação.',
                       'knowledge_version': VERSION,
                       'evidence': [{'id': 'benefits', 'quote': self.context['topics'][0]['answer']}]}
        self.question = SMOKE_QUESTIONS[0][1]

    def verifier(self, *, verdict='supported', envelope=None, error=None, context=None):
        opener = Mock()
        if error:
            opener.open.side_effect = error
        else:
            opener.open.side_effect = lambda *args, **kwargs: io.BytesIO(json.dumps(
                model_response({'verdict': verdict}) if envelope is None else envelope).encode())
        loader = Mock(return_value=self.context if context is None else context)
        return build_smoke_verifier(settings(), opener=opener, context_loader=loader), opener, loader

    def test_supported_unsupported_and_uncertain_are_closed_verdicts(self):
        for verdict in ('supported', 'unsupported', 'uncertain'):
            with self.subTest(verdict=verdict):
                verify, opener, loader = self.verifier(verdict=verdict)
                with patch('builtins.print') as log:
                    self.assertEqual(verify(self.question, self.answer), verdict)
                log.assert_not_called(); opener.open.assert_called_once(); loader.assert_called_once()
                body = json.loads(opener.open.call_args.args[0].data)
                inputs = json.loads(body['input'])
                self.assertEqual(inputs['evidence'], self.answer['evidence'])
                self.assertEqual(inputs['limits'], self.context['limits'])
                self.assertEqual(inputs['answer'], self.answer['answer'])
                self.assertFalse(body['store']); self.assertNotIn('tools', body)
                self.assertEqual(opener.open.call_args.kwargs['timeout'], 12)
                self.assertTrue(body['text']['format']['strict'])
                self.assertEqual(body['text']['format']['schema']['properties']['verdict']['enum'],
                                 ['supported', 'unsupported', 'uncertain'])
                self.assertIn('uma possibilidade não pode virar certeza', body['instructions'])
                self.assertIn('Uma fonte literal não prova concordância', body['instructions'])

    def test_changed_snapshot_is_uncertain_without_model_call(self):
        changed = deepcopy(self.context); changed['knowledge_version'] = VERSION[:-1] + 'b'
        verify, opener, _ = self.verifier(context=changed)
        self.assertEqual(verify(self.question, self.answer), 'uncertain')
        opener.open.assert_not_called()

    def test_only_exact_full_source_evidence_can_reach_verifier(self):
        for evidence in ([{'id': 'benefits', 'quote': 'Fonte alterada.'}], self.answer['evidence'] * 2,
                         [{'id': 'unknown', 'quote': self.context['limits']}], []):
            with self.subTest(evidence=evidence):
                verify, opener, _ = self.verifier()
                self.assertEqual(verify(self.question, {**self.answer, 'evidence': evidence}), 'uncertain')
                opener.open.assert_not_called()

    def test_no_arbitrary_or_personal_question_is_sent_by_smoke_verifier(self):
        verify, opener, loader = self.verifier()
        self.assertEqual(verify('Private unrelated user question', self.answer), 'uncertain')
        opener.open.assert_not_called(); loader.assert_not_called()
        for update in ({'demo_smoke_check': False}, {'demo_enabled': False}, {'demo_context_version': 'unknown'}):
            self.assertIsNone(build_smoke_verifier({**settings(), **update}))

    def test_refusal_incomplete_bad_schema_and_provider_errors_are_uncertain(self):
        cases = [{'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'}},
                 {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                    'content': [{'type': 'refusal', 'refusal': 'private reason'}]}]},
                 model_response({'verdict': 'supported', 'extra': 'private reason'}),
                 model_response({'verdict': 'unexpected'}),
                 {'status': 'completed', 'output': []}]
        for envelope in cases:
            verify, opener, _ = self.verifier(envelope=envelope)
            self.assertEqual(verify(self.question, self.answer), 'uncertain')
            opener.open.assert_called_once()
        verify, opener, _ = self.verifier(error=TimeoutError('private failure'))
        with patch('builtins.print') as log:
            self.assertEqual(verify(self.question, self.answer), 'uncertain')
        log.assert_not_called(); opener.open.assert_called_once()

    def test_smoke_logs_only_verdicts_and_does_not_replay_any_case(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DemoStore(str(Path(directory) / 'demo.sqlite'))
            try:
                answerer = Mock(return_value=self.answer)
                verify = Mock(side_effect=['supported', 'unsupported', 'uncertain', TimeoutError('private failure'), 'supported', 'supported'])
                with patch('builtins.print') as log:
                    result = schedule_smoke_check(settings(), store, SCOPE.slot, answerer,
                                                  verifier=verify, thread_factory=ImmediateThread)
                self.assertEqual(result['status'], 'scheduled')
                self.assertEqual(answerer.call_count, len(SMOKE_QUESTIONS)); self.assertEqual(verify.call_count, len(SMOKE_QUESTIONS))
                rows = [json.loads(call.args[0]) for call in log.call_args_list]
                cases = [row for row in rows if row['category'] != 'run']
                self.assertEqual([row['semantic_verdict'] for row in cases], ['supported', 'unsupported', 'uncertain', 'uncertain', 'supported', 'supported'])
                self.assertEqual(rows[-1]['status'], 'failed')
                text = json.dumps(rows)
                for private in (self.answer['answer'], self.answer['evidence'][0]['quote'], 'private failure', *[q for _, q in SMOKE_QUESTIONS]):
                    self.assertNotIn(private, text)
                self.assertEqual(schedule_smoke_check(settings(), store, SCOPE.slot, answerer,
                    verifier=verify, thread_factory=ImmediateThread)['status'], 'already_claimed')
                self.assertEqual(answerer.call_count, len(SMOKE_QUESTIONS)); self.assertEqual(verify.call_count, len(SMOKE_QUESTIONS))
                for table in ('demo_runs', 'demo_events', 'demo_outbox', 'demo_simulations'):
                    self.assertEqual(store.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
            finally:
                store.close()
