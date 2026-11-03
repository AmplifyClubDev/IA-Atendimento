"""Responses contract and factual fallbacks; injected provider, no paid calls."""
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import guided_ai as subject
import receipt_grounding

NOW = datetime(2026, 10, 29, 21, tzinfo=timezone.utc)
POLICY = {'approved': True, 'commission': 10, 'commission_unit': 'percent',
          'duration_fixed_months': 2, 'duration_label': '2 meses', 'version': 'approved-test31'}
KNOWLEDGE = {'source': 'database', 'personality': 'Bia acolhe e responde brevemente.',
    'limits': 'Sem promessas ou condições inventadas.', 'knowledge_version': 'context31:fixture',
    'topics': [
        {'id': 'custos', 'title': 'Comissão', 'answer': 'Taxa de 10% sobre comissões. Exemplo: R$100 de comissão gera R$10 para a agência.',
         'patterns': ['comissao', 'taxa', 'quanto custa']},
        {'id': 'funcionamento', 'title': 'Como funciona', 'answer': 'A Amplify orienta creators em sua jornada no TikTok Shop.\n\nMais detalhes pertencem ao material aprovado.',
         'patterns': ['como funciona', 'parceria']},
        {'id': 'beneficios', 'title': 'Benefícios', 'answer': 'Os benefícios dependem da categoria e das condições da parceria.', 'patterns': ['beneficios', 'vantagens']},
    ]}


def wire(reply='A parceria inclui orientação.', **updates):
    plan = {'reply': reply, 'intent': 'question', 'claims': [], 'next_phase': 'intro', 'topic_ids': []}
    plan.update(updates)
    return {'id': 'resp_offline31', 'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
        'status': 'completed', 'content': [{'type': 'output_text', 'text': json.dumps(plan)}]}],
        'usage': {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150}}


class AuditAIContract31Tests(unittest.TestCase):
    def setUp(self):
        self.settings = {'ai_enabled': True, 'context_db_enabled': True, '_context_snapshot': deepcopy(KNOWLEDGE),
                         'openai_api_key': 'offline-fictional-key-not-real31', 'ai_model': 'gpt-4.1'}
        self.context = {'real_mode': True, 'phase': 'intro', 'cycle': {'id': 'cycle31'}, 'facts': {},
            'relationship_check_in_form': True, 'commercial_policy': POLICY,
            'next_action': {'kind': 'understand_interest', 'field': None},
            'delivery_context': {'accepted_history': [], 'last_accepted_reply': None}}
        self.calls = []
        for name in ('socket.create_connection', 'socket.socket.connect', 'socket.socket.connect_ex'):
            guard = patch(name, side_effect=AssertionError('network forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def run_plan(self, text='Comissão', response=None, exception=None):
        def transport(**kwargs):
            self.calls.append(kwargs)
            if exception:
                raise exception
            return deepcopy(response if response is not None else wire())
        return subject.plan_turn(text, self.context, self.settings, transport)

    def test_request_uses_exact_responses_schema_model_store_false_and_one_post(self):
        result = self.run_plan()
        self.assertEqual(result['provider_status'], 'completed')
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual((call['method'], call['url'], call['timeout']), ('POST', subject.RESPONSES_URL, 20))
        payload = call['json']
        self.assertEqual(payload['model'], 'gpt-4.1')
        self.assertIs(payload['store'], False)
        self.assertEqual(payload['input'][-1], {'role': 'user', 'content': 'Comissão'})
        schema = payload['text']['format']
        self.assertEqual(schema['type'], 'json_schema')
        self.assertIs(schema['strict'], True)
        self.assertEqual(set(schema['schema']['required']), {'reply', 'intent', 'claims', 'next_phase', 'topic_ids'})
        self.assertIs(schema['schema']['additionalProperties'], False)

    def test_valid_split_output_text_and_reasoning_item_parse_without_loosening_schema(self):
        response = wire('A taxa é 10% sobre as comissões; não sobre o GMV.', topic_ids=['custos'])
        text = response['output'][0]['content'][0]['text']
        response['output'][0]['content'] = [{'type': 'output_text', 'text': text[:20]}, {'type': 'output_text', 'text': text[20:]}]
        response['output'].insert(0, {'type': 'reasoning', 'summary': []})
        self.assertEqual(self.run_plan(response=response)['provider_status'], 'completed')

    def test_policy_is_authoritative_and_numeric_rate_formats_are_equivalent(self):
        self.settings['_context_snapshot']['topics'][0]['answer'] = 'A condição é definida pela política aprovada.'
        for rate in ['10%', '10,0 %', '10.00%']:
            with self.subTest(rate=rate):
                self.assertEqual(self.run_plan(response=wire('Taxa de ' + rate))['provider_status'], 'completed')
        self.settings['_context_snapshot']['topics'][0]['answer'] = 'Histórico antigo: taxa 15%.'
        result = self.run_plan(response=wire('Taxa de 15%.'))
        self.assertEqual((result['provider_status'], result['provider_validation_reason']), ('invalid_response', 'unsupported_rate'))

    def test_approved_monetary_example_is_explicitly_rejected_with_safe_reason_not_hidden(self):
        result = self.run_plan(response=wire('Sobre R$100 de comissão, a taxa é R$10.', topic_ids=['custos']))
        self.assertEqual((result['provider_status'], result['provider_validation_reason']), ('invalid_response', 'unsupported_currency'))
        canonical = receipt_grounding.approved_cost_reply('Como funciona a comissão? E se eu receber R$100?', result, POLICY)
        self.assertIn('10%', canonical)
        self.assertIn('comissões que você recebe', canonical)
        self.assertNotIn('R$', canonical)
        self.assertNotIn('Você gostaria de conhecer', canonical)

    def test_parser_reports_fixed_reasons_for_shape_json_keys_values_and_claims(self):
        cases = []
        response = wire(); response['output'] = {}; cases.append((response, 'output_shape'))
        response = wire(); response['output'][0]['content'] = {}; cases.append((response, 'content_shape'))
        response = wire(); response['output'][0]['content'][0]['text'] = '{bad'; cases.append((response, 'invalid_json'))
        cases.append((wire(extra='raw must not be kept'), 'plan_keys'))
        cases.append((wire(intent=['invalid']), 'plan_values'))
        cases.append((wire(claims=[{'field': [], 'value': 'true', 'quote': 'Sim'}]), 'claim_shape'))
        for response, reason in cases:
            with self.subTest(reason=reason):
                result = self.run_plan(response=response)
                self.assertEqual(result['provider_status'], 'invalid_response')
                self.assertEqual(result['provider_validation_reason'], reason)
                self.assertEqual(result['reply'], '')
                self.assertNotIn('raw must not be kept', json.dumps(result))

    def test_refusal_missing_text_and_incomplete_message_never_become_reply(self):
        response = wire(); response['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'private text'}]
        cases = [(response, 'refusal')]
        response = wire(); response['output'][0]['content'] = []; cases.append((response, 'assistant_output_missing'))
        response = wire(); response['output'][0]['status'] = 'incomplete'; cases.append((response, 'assistant_message_incomplete'))
        for response, reason in cases:
            with self.subTest(reason=reason):
                result = self.run_plan(response=response)
                self.assertEqual(result['provider_validation_reason'], reason)
                self.assertNotIn('private text', json.dumps(result))

    def test_incomplete_cancelled_failed_queued_have_no_plan_and_safe_reason(self):
        for status, details, reason in [('incomplete', {'reason': 'max_output_tokens'}, 'incomplete_max_output_tokens'),
                ('incomplete', {'reason': 'content_filter'}, 'incomplete_content_filter'),
                ('incomplete', {'reason': []}, 'provider_incomplete'), ('cancelled', None, 'provider_cancelled'),
                ('failed', None, 'provider_failed'), ('queued', None, 'provider_status_unknown')]:
            with self.subTest(status=status, reason=reason):
                result = self.run_plan(response={**wire(), 'status': status, 'incomplete_details': details})
                self.assertEqual(result['reply'], '')
                self.assertEqual(result['provider_validation_reason'], reason)

    def test_transport_timeout_or_429_never_retries_or_leaks_exception(self):
        for error, status in [(TimeoutError('private exception'), 'unknown'),
                (HTTPError(subject.RESPONSES_URL, 429, 'private error', {}, io.BytesIO(b'private body')), 'failed')]:
            before = len(self.calls)
            result = self.run_plan(exception=error)
            self.assertEqual(len(self.calls), before + 1)
            self.assertEqual(result['provider_status'], status)
            self.assertNotIn('private', json.dumps(result))

    def test_direct_output_text_without_documented_output_message_is_not_trusted(self):
        result = self.run_plan(response={'status': 'completed', 'output_text': json.dumps({'reply': 'invented'})})
        self.assertEqual((result['provider_status'], result['provider_validation_reason']), ('invalid_response', 'output_shape'))

    def test_knowledge_fallback_is_short_and_selected_from_current_text_not_model_ids(self):
        result = self.run_plan('Como funciona?', exception=TimeoutError())
        approved = result['approved_topic_answer']
        self.assertEqual((approved['id'], approved['source'], approved['knowledge_version']),
                         ('funcionamento', 'approved_context', result['knowledge_version']))
        self.assertEqual(approved['text'], 'A Amplify orienta creators em sua jornada no TikTok Shop.')
        result = self.run_plan('Oi', response=wire(topic_ids=['beneficios']))
        self.assertNotIn('approved_topic_answer', result)
        self.settings['_context_snapshot']['topics'].append({'id': 'convite_tiktok', 'title': 'Convite',
            'answer': 'Texto operacional interno não deve ser um resumo público.', 'patterns': ['convite']})
        result = self.run_plan('Onde aceito o convite?', exception=TimeoutError())
        self.assertNotIn('approved_topic_answer', result)

    def test_context_unavailable_does_not_reuse_legacy_knowledge_or_call_provider(self):
        self.settings.pop('_context_snapshot')
        self.settings['_context_unavailable'] = True
        result = self.run_plan('Benefícios')
        self.assertEqual(result['provider_status'], 'context_unavailable')
        self.assertNotIn('approved_topic_answer', result)
        self.assertEqual(self.calls, [])

    def test_current_message_is_once_and_only_same_cycle_actual_accepted_reply_is_history(self):
        self.context['history'] = [
            {'cycle_id': 'previous', 'direction': 'inbound', 'text': 'OLD_CYCLE'},
            {'cycle_id': 'cycle31', 'direction': 'outbound', 'text': 'PLANNED_UNSENT'},
            {'cycle_id': 'cycle31', 'direction': 'inbound', 'text': 'Comissão'}]
        self.context['delivery_context'] = {'accepted_history': [{'text': 'O que gostaria de conhecer?', 'at': NOW.isoformat()}],
                                          'last_accepted_reply': {'text': 'O que gostaria de conhecer?'}}
        self.run_plan()
        actual = self.calls[-1]['json']['input']
        self.assertEqual(sum(item == {'role': 'user', 'content': 'Comissão'} for item in actual), 1)
        self.assertNotIn('OLD_CYCLE', repr(actual))
        self.assertNotIn('PLANNED_UNSENT', repr(actual))
        self.assertIn({'role': 'assistant', 'content': 'O que gostaria de conhecer?'}, actual)

    def test_prompt_aligns_financial_guard_and_new_form_gate_without_action_authority(self):
        self.run_plan()
        instructions = self.calls[-1]['json']['instructions']
        self.assertIn('Não inclua exemplos ou cobranças em R$', instructions)
        self.assertIn('confirmação do vínculo é feita no próprio formulário', instructions)
        self.assertIn('Não peça que a pessoa confirme o vínculo pelo chat', instructions.replace('Nunca peça', 'Não peça'))
        self.assertIn('não executa ações', instructions)
        self.assertNotIn('Use intent=check_acceptance', instructions)

    def test_natural_commercial_questions_have_backend_policy_or_honest_missing_condition(self):
        for text in ['Quanto custa?', 'Qual comissão?', 'A taxa incide no GMV?', 'O contrato é de quanto tempo?']:
            with self.subTest(text=text):
                result = receipt_grounding.approved_cost_reply(text, {'provider_status': 'invalid_response'}, POLICY)
                self.assertIn('10%', result)
                self.assertIn('2 meses', result)
                self.assertIn('comissões que você recebe', result)
                self.assertEqual(result.count('?'), 0)
                missing = receipt_grounding.approved_cost_reply(text, {}, None)
                self.assertNotIn('10%', missing)
                self.assertIn('condições precisam estar confirmadas', missing)

    def test_legitimate_commission_clarification_and_nonfinancial_message_remain_free(self):
        plan = {'provider_status': 'completed', 'intent': 'clarify',
                'reply': 'Você está falando da comissão da Amplify ou da comissão do produto?'}
        self.assertIsNone(receipt_grounding.approved_cost_reply('Qual comissão', plan, POLICY))
        self.assertIsNone(receipt_grounding.approved_cost_reply('Qual a comissão do produto?', {}, POLICY))
        self.assertIsNone(receipt_grounding.approved_cost_reply('Oi', {'topic_ids': ['custos']}, POLICY))


if __name__ == '__main__':
    unittest.main()
