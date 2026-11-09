# Structural tests isolate generation; semantic gating has dedicated integration coverage.
"""Opt-in AI smoke checks: synthetic model IO, durable claims, no message transport."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import config
from context_ia import load_demo_context
from demo_answers import build_answerer, schedule_smoke_check, SMOKE_QUESTIONS, _evidence_catalog
from demo_router import DemoStore, build_demo_router
from test_demo_router import settings as router_settings, SCOPE
from test_demo_context import payload as context_payload, settings as context_settings

VERSION = 'contextos-ia-v1:' + '0' * 32 + '+' + 'a' * 12


def values(**changes):
    return {'demo_smoke_check': True, 'demo_smoke_check_id': 'review-check-1', 'demo_enabled': True,
            'demo_context_version': 'amplify_doc_20261106_v1', 'ai_enabled': True, **changes}


def grounded():
    return {'answer': 'Private synthetic answer.', 'knowledge_version': VERSION,
            'evidence': [{'id': 'topic', 'quote': 'Private synthetic quote.'}]}


class ImmediateThread:
    def __init__(self, *, target, name, daemon):
        assert name == 'bia-demo-ai-smoke' and daemon is True
        self.target = target
    def start(self):
        self.target()


class SmokeCases(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / 'demo.sqlite')
        self.store = DemoStore(self.path)
        self.addCleanup(self.store.close)
        self.answerer = Mock(return_value=grounded())

    def run_check(self, settings=None, **kwargs):
        return schedule_smoke_check(settings or values(), self.store, SCOPE.slot, self.answerer,
                                    thread_factory=kwargs.pop('thread_factory', ImmediateThread),
                                    verifier=kwargs.pop('verifier', lambda question, answer: 'supported'), **kwargs)

    def test_default_is_disabled_without_storage_model_thread_or_logging(self):
        settings = config.load_settings({})
        self.assertFalse(settings['demo_smoke_check'])
        self.assertEqual(settings['demo_smoke_check_id'], '')
        store, thread = Mock(), Mock()
        with patch('builtins.print') as log:
            result = schedule_smoke_check(settings, store, SCOPE.slot, self.answerer, thread_factory=thread)
        self.assertEqual(result['status'], 'disabled')
        self.assertEqual(store.mock_calls, [])
        thread.assert_not_called(); self.answerer.assert_not_called(); log.assert_not_called()

    def test_explicit_opt_in_and_check_identifier_are_parsed(self):
        settings = config.load_settings({'V5_DEMO_SMOKE_CHECK': 'true', 'V5_DEMO_SMOKE_CHECK_ID': 'commit-123'})
        self.assertTrue(settings['demo_smoke_check'])
        self.assertEqual(settings['demo_smoke_check_id'], 'commit-123')
        self.assertFalse(any(issue.startswith('demo_smoke') for issue in settings['readiness_issues']))

    def test_invalid_config_never_calls_model_storage_or_thread(self):
        for change in ({'demo_enabled': False}, {'demo_context_version': ''}, {'demo_context_version': 'unknown'},
                       {'ai_enabled': False}, {'demo_smoke_check_id': ''}, {'demo_smoke_check_id': 'bad\nid'},
                       {'demo_smoke_check_id': None}):
            with self.subTest(change=change):
                store, thread = Mock(), Mock()
                result = schedule_smoke_check(values(**change), store, SCOPE.slot, self.answerer, thread_factory=thread)
                self.assertEqual(result['status'], 'configuration_invalid')
                self.assertEqual(store.mock_calls, [])
                thread.assert_not_called()
        self.answerer.assert_not_called()

    def test_memory_store_is_refused_to_avoid_restart_repeats(self):
        store = DemoStore(':memory:')
        self.addCleanup(store.close)
        result = schedule_smoke_check(values(), store, SCOPE.slot, self.answerer, thread_factory=ImmediateThread)
        self.assertEqual(result['status'], 'durable_store_required')
        self.answerer.assert_not_called()

    def test_only_six_fixed_questions_and_safe_metadata_are_used(self):
        with patch('builtins.print') as log:
            self.assertEqual(self.run_check()['status'], 'scheduled')
        self.assertEqual([call.args for call in self.answerer.call_args_list], [(q,) for _, q in SMOKE_QUESTIONS])
        rows = [json.loads(call.args[0]) for call in log.call_args_list]
        self.assertEqual([row['category'] for row in rows], ['run', 'benefits', 'benefits_paraphrase', 'lives', 'lives_paraphrase', 'partnership_exit', 'partnership_exit_paraphrase', 'run'])
        self.assertTrue(all(set(row) <= {'event', 'category', 'status', 'candidate_version',
                                        'knowledge_version', 'evidence_count', 'semantic_verdict'} for row in rows))
        record = self.store.db.execute("SELECT result FROM demo_starts WHERE slot LIKE 'smoke:%'").fetchone()
        self.assertEqual(json.loads(record['result'])['status'], 'passed')
        combined = json.dumps(rows) + record['result']
        for private in (grounded()['answer'], grounded()['evidence'][0]['quote'], *(q for _, q in SMOKE_QUESTIONS)):
            self.assertNotIn(private, combined)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_runs').fetchone()[0], 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_outbox').fetchone()[0], 0)

    def test_completed_check_does_not_repeat_and_survives_store_reopen(self):
        self.run_check()
        self.assertEqual(self.run_check()['status'], 'already_claimed')
        reopened = DemoStore(self.path)
        try:
            result = schedule_smoke_check(values(), reopened, SCOPE.slot, self.answerer, thread_factory=ImmediateThread)
            self.assertEqual(result['status'], 'already_claimed')
        finally:
            reopened.close()
        self.assertEqual(self.answerer.call_count, len(SMOKE_QUESTIONS))

    def test_claim_is_committed_before_thread_starts_and_unknown_never_repeats(self):
        factory = Mock()
        def observe_start():
            self.assertFalse(self.store.db.in_transaction)
            row = self.store.db.execute("SELECT result FROM demo_starts WHERE slot LIKE 'smoke:%'").fetchone()
            self.assertEqual(json.loads(row['result'])['status'], 'claimed')
        factory.return_value.start.side_effect = observe_start
        self.assertEqual(self.run_check(thread_factory=factory)['status'], 'scheduled')
        factory.assert_called_once()
        self.assertTrue(factory.call_args.kwargs['daemon'])
        self.answerer.assert_not_called()
        self.assertEqual(self.run_check()['status'], 'already_claimed')
        self.answerer.assert_not_called()

    def test_thread_start_failure_keeps_claim_and_does_not_block_caller(self):
        factory = Mock(side_effect=RuntimeError('private failure'))
        self.assertEqual(self.run_check(thread_factory=factory)['status'], 'start_unconfirmed')
        self.assertEqual(self.run_check()['status'], 'already_claimed')
        self.answerer.assert_not_called()

    def test_failures_run_once_and_only_explicit_new_id_retries(self):
        self.answerer.side_effect = [TimeoutError('private failure'), 'faq_unavailable', 'faq_unknown', 'faq_unavailable', 'faq_unavailable', 'faq_unknown'] + [grounded() for _ in SMOKE_QUESTIONS]
        with patch('builtins.print') as log:
            self.run_check()
        self.assertNotIn('private failure', str(log.call_args_list))
        self.assertEqual(json.loads(self.store.db.execute("SELECT result FROM demo_starts WHERE slot LIKE 'smoke:%'").fetchone()[0])['status'], 'failed')
        self.assertEqual(self.run_check()['status'], 'already_claimed')
        self.run_check(values(demo_smoke_check_id='review-check-2'))
        self.assertEqual(self.answerer.call_count, 2 * len(SMOKE_QUESTIONS))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM demo_starts WHERE slot LIKE 'smoke:%'").fetchone()[0], 2)

    def test_candidate_version_separates_markers(self):
        self.run_check()
        self.run_check(values(demo_context_version='amplify_circle_20261106_v2'))
        self.assertEqual(self.answerer.call_count, 2 * len(SMOKE_QUESTIONS))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM demo_starts WHERE slot LIKE 'smoke:%'").fetchone()[0], 2)

    def test_build_router_never_calls_message_gateway_or_effects_for_smoke(self):
        settings = {**router_settings(Path(self.path).parent), **values(), 'demo_state_path': self.path}
        gateway = Mock()
        with patch('demo_answers.build_answerer', return_value=self.answerer), \
                patch('demo_answers.threading.Thread', ImmediateThread):
            router = build_demo_router(settings, gateway=gateway)
        try:
            self.assertEqual(self.answerer.call_count, len(SMOKE_QUESTIONS))
            self.assertEqual(gateway.mock_calls, [])
            for table in ('demo_runs', 'demo_events', 'demo_outbox', 'demo_simulations'):
                self.assertEqual(router.store.db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0)
            self.assertEqual(router.store.db.execute('SELECT count(*) FROM demo_starts WHERE slot=?', (SCOPE.slot,)).fetchone()[0], 0)
        finally:
            router.store.close()

    def test_smoke_uses_normal_answerer_limits_and_evidence_validation(self):
        knowledge = {'source': 'database', 'knowledge_version': VERSION, 'card_count': 3,
                     'personality': 'Brief', 'limits': 'Do not guarantee.',
                     'topics': [{'id': 'topic', 'answer': 'Literal synthetic supporting evidence.'}]}
        reference = next(ref for ref, item in _evidence_catalog(knowledge).items() if item['id'] == 'topic')
        content = {'answer': 'Synthetic answer.', 'evidence': [reference]}
        response = {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': json.dumps(content)}]}]}
        opener = Mock()
        opener.open.side_effect = lambda *args, **kwargs: io.BytesIO(json.dumps(response).encode())
        self.answerer = build_answerer({'ai_enabled': True, 'openai_api_key': 'synthetic', 'ai_model': 'test'},
                                      opener=opener, context_loader=lambda _: knowledge, semantic_verifier=lambda *_: 'supported')
        self.run_check()
        self.assertEqual(opener.open.call_count, len(SMOKE_QUESTIONS))
        for call in opener.open.call_args_list:
            self.assertEqual(call.kwargs['timeout'], 12)
            body = json.loads(call.args[0].data)
            self.assertEqual(body['max_output_tokens'], 1500)
            self.assertFalse(body['store'])
            self.assertNotIn('tools', body)
        self.assertEqual(json.loads(self.store.db.execute("SELECT result FROM demo_starts WHERE slot LIKE 'smoke:%'").fetchone()[0])['status'], 'passed')


class CandidateV2Cases(unittest.TestCase):
    def test_circle_v2_is_exactly_allowlisted_for_demo_only(self):
        values = context_settings(demo_context_version='amplify_circle_20261106_v2')
        self.assertIsNone(config.demo_context_issue(values))
        transport = Mock(return_value=context_payload())
        self.assertEqual(load_demo_context(values, transport=transport)['card_count'], 3)
        self.assertEqual(transport.call_args.kwargs['json'], {'p_version': 'amplify_circle_20261106_v2'})
        self.assertTrue(transport.call_args.kwargs['url'].endswith('/ler_contexto_ia_ensaio_v5'))
        for version in ('amplify_circle_20261106_v2 ', 'amplify_circle_20261106_v4'):
            self.assertEqual(config.demo_context_issue({**values, 'demo_context_version': version}), 'demo_context_version_invalid')
        self.assertEqual(config.demo_context_issue({**values, 'demo_enabled': False}), 'demo_context_requires_demo')
