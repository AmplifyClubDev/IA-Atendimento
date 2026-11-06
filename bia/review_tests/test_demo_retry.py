"""Offline retry and diagnostics: no real model, provider or database calls."""
import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from demo_answers import build_answerer, _evidence_catalog
from demo_router import DemoRouter
import test_demo_flow as fixtures


class RetryCases(unittest.TestCase):
    setUp = fixtures.FlowCases.setUp
    def source(self, action=None, *, text=None, correlated=True):
        if action and action != 'use_profile':
            state = self.store.current(self.router.scope.slot)
            row = self.store.db.execute('SELECT payload FROM demo_outbox WHERE key=?', (state['outbox_key'],)).fetchone()
            text = next(item['title'] for item in json.loads(row['payload'])['content_attributes']['items']
                        if item['value'].endswith(':' + action))
            action = None
        return fixtures.FlowCases.source(self, action, text=text, correlated=correlated)
    choose = fixtures.FlowCases.choose

    def grounded(self):
        return {'answer': 'Conteúdo sintético aprovado da base.',
                'evidence': [{'id': 'synthetic', 'quote': 'Conteúdo sintético aprovado'}],
                'knowledge_version': 'synthetic'}

    def test_benefits_retry_reuses_question_instead_of_asking_again(self):
        self.choose('know')
        answer = self.router.question_answerer = Mock(side_effect=['faq_unavailable', self.grounded()])
        self.assertEqual(self.choose('faq_benefits'), 'faq_unavailable')
        source = self.source('retry')
        first = self.router.handle(source)
        self.assertEqual(first[0]['step'], 'faq_context')
        self.assertEqual([call.args[0] for call in answer.call_args_list], ['Conhecer benefícios'] * 2)
        count = len(self.gateway.sent)
        self.assertEqual(self.router.handle(source), first)
        self.assertEqual(answer.call_count, 2)
        self.assertEqual(len(self.gateway.sent), count)
        self.assertEqual(self.choose('back'), 'about')

    def test_free_question_survives_repeated_failure_and_router_recreation(self):
        self.choose('join')
        answer = Mock(side_effect=['faq_unavailable', 'faq_unavailable', self.grounded()])
        self.router.question_answerer = answer
        question = 'Sou obrigado a fazer live?'
        self.assertEqual(self.router.handle(self.source(text=question, correlated=False))[0]['step'], 'faq_unavailable')
        self.router = DemoRouter(self.router.scope, self.store, self.gateway, now=self.router.now,
                                 continuation_enabled=True, question_answerer=answer)
        self.assertEqual(self.choose('retry'), 'faq_unavailable')
        self.assertEqual(self.choose('retry'), 'faq_context')
        self.assertEqual([call.args[0] for call in answer.call_args_list], [question] * 3)
        self.assertEqual(self.choose('back'), 'profile')

    def test_retry_requires_current_button_correlation(self):
        self.choose('know')
        answer = self.router.question_answerer = Mock(return_value='faq_unavailable')
        self.choose('faq_benefits')
        for overrides in ({'demo_reply_to': None}, {'demo_reply_to': '8'}):
            source = {**self.source('retry'), **overrides}
            self.assertEqual(self.router.handle(source)[0]['status'], 'demo_choice_not_current')
        self.assertEqual(answer.call_count, 1)

    def test_uncertain_retry_delivery_never_repeats_model_or_send(self):
        self.choose('know')
        answer = self.router.question_answerer = Mock(side_effect=['faq_unavailable', self.grounded()])
        self.choose('faq_benefits')
        send = self.gateway.send
        def uncertain(scope, payload, key):
            send(scope, payload, key)
            raise TimeoutError()
        self.gateway.send = uncertain
        source = self.source('retry')
        first = self.router.handle(source)
        self.assertEqual(first[0]['status'], 'demo_delivery_unconfirmed')
        count = len(self.gateway.sent)
        self.assertEqual(self.router.handle(source), first)
        next_event = self.source(text='Tentar novamente', correlated=False)
        self.assertEqual(self.router.handle(next_event)[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(answer.call_count, 2)
        self.assertEqual(len(self.gateway.sent), count)
        self.gateway.lookup = lambda scope, key: {'status': 'accepted', 'message_id': '202', 'simulated': True}
        self.router.reconcile()
        self.assertEqual(self.router.handle(source)[0]['step'], 'faq_context')
        self.assertEqual(answer.call_count, 2)

    def test_old_benefits_failure_without_saved_question_has_narrow_compatibility(self):
        self.choose('know')
        answer = self.router.question_answerer = Mock(side_effect=['faq_unavailable', self.grounded()])
        self.choose('faq_benefits')
        key = self.store.current(self.router.scope.slot)['outbox_key']
        row = self.store.db.execute('SELECT receipt FROM demo_outbox WHERE key=?', (key,)).fetchone()
        receipt = json.loads(row['receipt']); receipt['last_question'] = ''
        self.store.db.execute('UPDATE demo_outbox SET receipt=? WHERE key=?', (json.dumps(receipt), key))
        self.assertEqual(self.choose('retry'), 'faq_context')
        self.assertEqual(answer.call_args.args, ('Conhecer benefícios',))

    def test_retry_uses_only_redacted_saved_question(self):
        self.choose('know')
        answer = self.router.question_answerer = Mock(side_effect=['faq_unavailable', self.grounded()])
        self.router.handle(self.source(text='Como funciona para @private e private@example.com?', correlated=False))
        self.choose('retry')
        self.assertNotIn('@private', answer.call_args.args[0])
        self.assertNotIn('private@example.com', answer.call_args.args[0])
        self.assertIn('[dado removido]', answer.call_args.args[0])


class DiagnosticCases(unittest.TestCase):
    def setUp(self):
        self.knowledge = {'source': 'database', 'knowledge_version': 'contextos-ia-v1:' + '0' * 32 + '+' + 'a' * 12,
                          'card_count': 29, 'personality': 'Brief', 'limits': 'No guarantees.',
                          'topics': [{'id': 'lives', 'answer': 'Fazer live não é obrigatório.'}]}
        self.reference = next(ref for ref, item in _evidence_catalog(self.knowledge).items() if item['id'] == 'lives')
        self.value = {'answer': 'Não é obrigatório fazer live.', 'evidence': [self.reference]}

    def envelope(self, value=None, **changes):
        return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': json.dumps(self.value if value is None else value)}]}], **changes}

    def invoke(self, *, result=None, raw=None, error=None, context_error=None):
        opener = Mock()
        if error:
            opener.open.side_effect = error
        else:
            opener.open.return_value = io.BytesIO(raw if raw is not None else json.dumps(result).encode())
        loader = Mock(side_effect=context_error) if context_error else Mock(return_value=self.knowledge)
        answer = build_answerer({'ai_enabled': True, 'openai_api_key': 'private-synthetic-key', 'ai_model': 'test'},
                                opener=opener, context_loader=loader)
        with patch('builtins.print') as log:
            if context_error:
                with self.assertRaises(type(context_error)):
                    answer('private-synthetic-question')
                outcome = 'raised'
            else:
                outcome = answer('private-synthetic-question')
        rows = [json.loads(call.args[0]) for call in log.call_args_list]
        encoded = json.dumps(rows)
        for forbidden in ('private-synthetic-key', 'private-synthetic-question', 'private-body', 'private-error',
                          self.value['answer'], self.knowledge['topics'][0]['answer']):
            self.assertNotIn(forbidden, encoded)
        self.assertLessEqual(opener.open.call_count, 1)
        return outcome, rows, opener

    def test_context_and_success_log_only_bounded_metadata(self):
        outcome, rows, opener = self.invoke(result=self.envelope(usage={
            'output_tokens': 123, 'output_tokens_details': {'reasoning_tokens': 50}}))
        self.assertIsInstance(outcome, dict)
        self.assertEqual([row['category'] for row in rows], ['context_loaded', 'answer_accepted'])
        self.assertEqual(rows[0]['card_count'], 29)
        self.assertEqual(rows[0]['knowledge_version'], self.knowledge['knowledge_version'])
        self.assertTrue(rows[-1]['completed'])
        self.assertEqual(rows[-1]['answer_length'], len(self.value['answer']))
        self.assertEqual(rows[-1]['reasoning_tokens'], 50)
        self.assertEqual(json.loads(opener.open.call_args.args[0].data)['max_output_tokens'], 1500)

    def test_incomplete_reason_is_allowlisted_and_not_guessed(self):
        for reason, expected in [('max_output_tokens', 'max_output_tokens'), ('content_filter', 'content_filter'),
                                 ('private-body', 'other'), ({'private-body': True}, 'other')]:
            with self.subTest(reason=reason):
                outcome, rows, _ = self.invoke(result={'status': 'incomplete', 'incomplete_details': {'reason': reason}})
                self.assertEqual(outcome, 'faq_unavailable')
                self.assertEqual(rows[-1]['category'], 'provider_incomplete')
                self.assertEqual(rows[-1]['incomplete_reason'], expected)
                self.assertFalse(rows[-1]['completed'])

    def test_http_timeout_and_transport_are_distinguished_without_error_body(self):
        for error, category in [(HTTPError('https://invalid.test', 429, 'private-error', {}, io.BytesIO(b'private-body')), 'provider_http'),
                                (TimeoutError('private-error'), 'provider_timeout'),
                                (URLError(TimeoutError('private-error')), 'provider_timeout'),
                                (URLError('private-error'), 'provider_transport')]:
            with self.subTest(category=category):
                outcome, rows, _ = self.invoke(error=error)
                self.assertEqual(outcome, 'faq_unavailable')
                self.assertEqual(rows[-1]['category'], category)
                if category == 'provider_http': self.assertEqual(rows[-1]['http_status'], 429)

    def test_json_schema_and_evidence_failures_remain_closed(self):
        cases = [({'status': 'failed'}, 'provider_not_completed'), ([], 'provider_schema'),
                 (self.envelope(output=[]), 'model_output_missing'),
                 (self.envelope(output=[{'type': 'message', 'role': 'assistant', 'content': [
                     {'type': 'output_text', 'text': 'private-body'}]}]), 'model_json'),
                 (self.envelope(value=[]), 'answer_schema'),
                 (self.envelope(value={**self.value, 'answer': 'x' * 601}), 'answer_length'),
                 (self.envelope(value={**self.value, 'answer': 'https://invalid.test'}), 'answer_forbidden_content'),
                 (self.envelope(value={**self.value, 'evidence': []}), 'evidence_schema'),
                 (self.envelope(value={**self.value, 'evidence': ['unknown-reference']}), 'evidence_source'),
                 (self.envelope(value={**self.value, 'evidence': [{'id': 'lives', 'quote': 'short'}]}), 'evidence_schema'),
                 (self.envelope(value={**self.value, 'evidence': [self.reference, self.reference]}), 'evidence_duplicate')]
        for result, category in cases:
            with self.subTest(category=category):
                outcome, rows, _ = self.invoke(result=result)
                self.assertEqual(outcome, 'faq_unavailable')
                self.assertEqual(rows[-1]['category'], category)
        outcome, rows, _ = self.invoke(raw=b'private-body')
        self.assertEqual(outcome, 'faq_unavailable')
        self.assertEqual(rows[-1]['category'], 'provider_json')

    def test_context_error_is_logged_without_exception_text(self):
        outcome, rows, opener = self.invoke(context_error=ValueError('private-error'))
        self.assertEqual(outcome, 'raised')
        self.assertEqual(rows, [{'event': 'demo_ai', 'category': 'context_unavailable'}])
        opener.open.assert_not_called()

    def test_explicit_no_evidence_remains_unknown_not_technical_failure(self):
        outcome, rows, _ = self.invoke(result=self.envelope(value={'answer': '', 'evidence': []}))
        self.assertEqual(outcome, 'faq_unknown')
        self.assertEqual(rows[-1]['category'], 'knowledge_not_supported')
