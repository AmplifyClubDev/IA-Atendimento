"""Synthetic-only coverage for the opt-in demo knowledge reader and its boundary."""
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import Mock, patch

import answers
import config
from context_ia import ContextUnavailable, load_context, load_demo_context
from demo_answers import build_answerer

VERSION = 'amplify_doc_20261106_v1'
BASE_URL = 'https://' + config.PROJECT_REF + '.supabase.co'


def settings(**overrides):
    return {'v5_url': BASE_URL, 'v5_service_key': 'synthetic-test-only',
            'demo_enabled': True, 'demo_context_version': VERSION, **overrides}


def payload():
    return {'version': 'contextos-ia-v1:' + '0' * 32, 'cards': [
        {'id': 'personality', 'tipo': 'personalidade', 'titulo': 'Tom',
         'conteudo': 'Seja breve e clara.', 'atualizado_em': '2026-11-06T00:00:00Z'},
        {'id': 'lives', 'tipo': 'conhecimento', 'titulo': 'Lives',
         'conteudo': 'Fazer live não é obrigatório para participar da parceria.',
         'atualizado_em': '2026-11-06T00:00:00Z'},
        {'id': 'limits', 'tipo': 'limites', 'titulo': 'Limites',
         'conteudo': 'Não garantir resultados.', 'atualizado_em': '2026-11-06T00:00:00Z'}]}


def model_opener():
    value = {'answer': 'Não, fazer live não é obrigatório.',
             'evidence': [{'id': 'lives', 'quote': 'Fazer live não é obrigatório'}]}
    opener = Mock()
    opener.open.side_effect = lambda *args, **kwargs: io.BytesIO(json.dumps({
        'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}).encode())
    return opener


class DemoContextConfigCases(unittest.TestCase):
    def test_absent_or_empty_version_keeps_current_default(self):
        for environ in ({}, {'V5_DEMO_CONTEXT_VERSION': ''},
                        {'V5_DEMO_ROUTER_ENABLED': 'true'}):
            with self.subTest(environ=environ):
                actual = config.load_settings(environ)
                self.assertEqual(actual['demo_context_version'], '')
                self.assertIsNone(config.demo_context_issue(actual))
                self.assertFalse(any(issue.startswith('demo_context_')
                                     for issue in actual['readiness_issues']))

    def test_exact_candidate_is_accepted_only_with_enabled_demo(self):
        actual = config.load_settings({'V5_DEMO_ROUTER_ENABLED': 'true',
                                       'V5_DEMO_CONTEXT_VERSION': VERSION})
        self.assertEqual(actual['demo_context_version'], VERSION)
        self.assertTrue(actual['demo_enabled'])
        self.assertIsNone(config.demo_context_issue(actual))
        self.assertFalse(any(issue.startswith('demo_context_')
                             for issue in actual['readiness_issues']))

    def test_candidate_without_enabled_demo_blocks_readiness(self):
        for flag in ('', 'false', '1', 'invalid'):
            with self.subTest(flag=flag):
                actual = config.load_settings({'V5_DEMO_ROUTER_ENABLED': flag,
                                               'V5_DEMO_CONTEXT_VERSION': VERSION})
                self.assertIn('demo_context_requires_demo', actual['readiness_issues'])

    def test_unknown_or_normalized_version_blocks_readiness(self):
        for version in ('other', VERSION.upper(), ' ' + VERSION, VERSION + '\n',
                        VERSION + ',other', ' ', None, False):
            with self.subTest(version=version):
                actual = config.load_settings({'V5_DEMO_ROUTER_ENABLED': 'true',
                                               'V5_DEMO_CONTEXT_VERSION': version})
                self.assertIn('demo_context_version_invalid', actual['readiness_issues'])


class DemoContextReaderCases(unittest.TestCase):
    def assert_request(self, transport, rpc, body):
        transport.assert_called_once()
        request = transport.call_args.kwargs
        self.assertEqual(request['method'], 'POST')
        self.assertEqual(request['url'], BASE_URL + '/rest/v1/rpc/' + rpc)
        self.assertEqual(request['json'], body)

    def test_production_always_ignores_candidate_setting_and_demo_gate(self):
        for version in ('', VERSION, 'invalid', None, [], {'rpc': 'arbitrary'}):
            for enabled in (True, False):
                with self.subTest(version=version, enabled=enabled):
                    transport = Mock(return_value=payload())
                    actual = load_context(settings(demo_context_version=version,
                                                   demo_enabled=enabled), transport=transport)
                    self.assertEqual(actual['source'], 'database')
                    self.assert_request(transport, 'ler_contexto_ia_v5', {})

    def test_demo_defaults_to_current_when_candidate_is_not_selected(self):
        for values in ({}, {'demo_context_version': ''}):
            for enabled in (True, False):
                with self.subTest(values=values, enabled=enabled):
                    actual_settings = settings(demo_enabled=enabled)
                    actual_settings.pop('demo_context_version')
                    actual_settings.update(values)
                    transport = Mock(return_value=payload())
                    actual = load_demo_context(actual_settings, transport=transport)
                    self.assertEqual(actual['card_count'], 3)
                    self.assert_request(transport, 'ler_contexto_ia_v5', {})

    def test_candidate_uses_only_exact_rpc_and_version_parameter(self):
        transport = Mock(return_value=payload())
        candidate = load_demo_context(settings(), transport=transport)
        self.assert_request(transport, 'ler_contexto_ia_ensaio_v5', {'p_version': VERSION})
        active = load_context(settings(), transport=Mock(return_value=payload()))
        self.assertEqual(candidate, active)
        self.assertRegex(candidate['knowledge_version'], r'^contextos-ia-v1:[a-f0-9]{32}\+[a-f0-9]{12}$')

    def test_invalid_settings_fail_before_database_access(self):
        updates = [{'demo_enabled': value} for value in (False, None, 1, 'true')]
        updates += [{'demo_context_version': value} for value in
                    ('other', ' ' + VERSION, VERSION + ' ', None, False, [], {})]
        updates += [{'demo_enabled': None, 'demo_context_version': 'other'}]
        for update in updates:
            with self.subTest(update=update):
                transport = Mock()
                with self.assertRaisesRegex(ContextUnavailable, '^context_ia_unavailable$'):
                    load_demo_context(settings(**update), transport=transport)
                transport.assert_not_called()
        values = settings()
        values.pop('demo_enabled')
        transport = Mock()
        with self.assertRaises(ContextUnavailable):
            load_demo_context(values, transport=transport)
        transport.assert_not_called()

    def test_missing_candidate_never_falls_back_to_current(self):
        for value in (None, {}, [], {'version': 'contextos-ia-v1:' + '0' * 32, 'cards': []}):
            with self.subTest(value=value):
                transport = Mock(return_value=value)
                with self.assertRaisesRegex(ContextUnavailable, '^context_ia_unavailable$'):
                    load_demo_context(settings(), transport=transport)
                self.assert_request(transport, 'ler_contexto_ia_ensaio_v5', {'p_version': VERSION})

    def test_provider_failure_is_sanitized_without_retry_or_fallback(self):
        for error in (TimeoutError('private-provider-details'), ValueError('private-provider-details'),
                      RuntimeError('private-provider-details')):
            with self.subTest(error=type(error).__name__):
                transport = Mock(side_effect=error)
                with self.assertRaisesRegex(ContextUnavailable, '^context_ia_unavailable$'):
                    load_demo_context(settings(), transport=transport)
                self.assert_request(transport, 'ler_contexto_ia_ensaio_v5', {'p_version': VERSION})

    def test_both_readers_enforce_the_same_strict_card_contract(self):
        malformed = []
        for change in ({'extra': True}, {'version': VERSION}, {'cards': {}}, {'cards': []}):
            malformed.append({**payload(), **change})
        for change in ({'extra': True}, {'id': 'invalid-id'}, {'tipo': 'other'},
                       {'titulo': ''}, {'titulo': 'x' * 121}, {'conteudo': ''},
                       {'conteudo': 'x' * 8001}, {'atualizado_em': None}):
            value = payload()
            value['cards'][1].update(change)
            malformed.append(value)
        value = payload()
        del value['cards'][1]['atualizado_em']
        malformed.append(value)
        value = payload()
        value['cards'][1]['id'] = 'limits'
        malformed.append(value)
        value = payload()
        value['cards'][2]['tipo'] = 'conhecimento'
        malformed.append(value)
        value = payload()
        value['cards'] += [dict(value['cards'][1], id='topic_' + str(i)) for i in range(62)]
        malformed.append(value)
        value = payload()
        value['cards'] += [dict(value['cards'][1], id='topic_' + str(i), conteudo='x' * 8000)
                           for i in range(5)]
        malformed.append(value)
        for index, value in enumerate(malformed):
            for loader, rpc, body in ((load_context, 'ler_contexto_ia_v5', {}),
                                     (load_demo_context, 'ler_contexto_ia_ensaio_v5', {'p_version': VERSION})):
                with self.subTest(case=index, loader=loader.__name__):
                    transport = Mock(return_value=deepcopy(value))
                    with self.assertRaises(ContextUnavailable):
                        loader(settings(), transport=transport)
                    self.assert_request(transport, rpc, body)


class DemoContextIntegrationCases(unittest.TestCase):
    def test_demo_answerer_selects_candidate_and_reloads_each_question(self):
        opener = model_opener()
        values = settings(ai_enabled=True, openai_api_key='synthetic-only', ai_model='test')
        answer = build_answerer(values, opener=opener)
        with patch('context_ia.Gateway._rpc', return_value=payload()) as rpc:
            for _ in range(2):
                result = answer('É obrigatório fazer live?')
                self.assertIsInstance(result, dict)
            self.assertEqual(rpc.call_count, 2)
            self.assertTrue(all(call.args == ('ler_contexto_ia_ensaio_v5', {'p_version': VERSION})
                                for call in rpc.call_args_list))
        model_context = json.loads(json.loads(opener.open.call_args.args[0].data)['input'])['context']
        self.assertEqual(model_context['knowledge_version'], result['knowledge_version'])

    def test_demo_answerer_defaults_to_current(self):
        opener = model_opener()
        values = settings(ai_enabled=True, openai_api_key='synthetic-only', ai_model='test')
        values.pop('demo_context_version')
        with patch('context_ia.Gateway._rpc', return_value=payload()) as rpc:
            self.assertIsInstance(build_answerer(values, opener=opener)('É obrigatório fazer live?'), dict)
            rpc.assert_called_once_with('ler_contexto_ia_v5', {})

    def test_invalid_candidate_prevents_database_and_model_calls(self):
        for update in ({'demo_enabled': False}, {'demo_context_version': 'invalid'}):
            with self.subTest(update=update):
                opener = model_opener()
                values = settings(ai_enabled=True, openai_api_key='synthetic-only', ai_model='test', **update)
                with patch('context_ia.Gateway._rpc') as rpc:
                    with self.assertRaises(ContextUnavailable):
                        build_answerer(values, opener=opener)('É obrigatório fazer live?')
                    rpc.assert_not_called()
                opener.open.assert_not_called()

    def test_production_answers_continue_to_use_only_current_reader(self):
        values = settings(context_db_enabled=True)
        with patch('context_ia.Gateway._rpc', return_value=payload()) as rpc, \
                patch('context_ia.load_demo_context', side_effect=AssertionError('demo reader in production')):
            actual = answers.load_knowledge(values)
            rpc.assert_called_once_with('ler_contexto_ia_v5', {})
            self.assertEqual(actual['version'], payload()['version'])
