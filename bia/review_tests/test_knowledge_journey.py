# Structural tests isolate generation; semantic gating has dedicated integration coverage.
"""Offline regression tests: no model, database, WhatsApp or provider IO."""
import io
import json
import unittest
from unittest.mock import Mock

from demo_answers import build_answerer, _evidence_catalog
from demo_flow import safe_context_text
from demo_router import DemoRouter
import test_demo_flow


class JourneyMemoryCases(unittest.TestCase):
    setUp = test_demo_flow.FlowCases.setUp
    def source(self, action=None, *, text=None, correlated=True):
        if action and action != 'use_profile':
            state = self.store.current(self.router.scope.slot)
            row = self.store.db.execute('SELECT payload FROM demo_outbox WHERE key=?', (state['outbox_key'],)).fetchone()
            payload = json.loads(row['payload'])
            text = next(i['title'] for i in payload['content_attributes']['items'] if i['value'].endswith(':' + action))
            action = None
        return test_demo_flow.FlowCases.source(self, action, text=text, correlated=correlated)
    choose = test_demo_flow.FlowCases.choose

    def grounded(self):
        return {'answer': 'A informação vem da base aprovada.',
                'evidence': [{'id': 'synthetic', 'quote': 'base aprovada'}],
                'knowledge_version': 'synthetic-only'}

    def ask(self, text='Como funciona a parceria?'):
        self.router.question_answerer = Mock(return_value=self.grounded())
        return self.router.handle(self.source(text=text, correlated=False))[0]

    def test_question_after_profile_opens_topics_and_explicit_join_preserves_conditions(self):
        self.choose('join'); self.choose('use_profile')
        self.assertEqual(self.ask()['step'], 'faq_context')
        self.assertEqual(self.choose('question'), 'about')
        self.assertEqual(self.choose('faq_benefits'), 'faq_context')
        self.assertEqual(self.choose('join'), 'conditions')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 1)

    def test_multiple_questions_return_to_invite_not_profile(self):
        for action in ('join', 'use_profile', 'continue_test'):self.choose(action)
        self.ask('É obrigatório fazer live?')
        self.ask('E sobre as amostras?')
        self.assertEqual(self.choose('join'), 'invite')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 2)

    def test_short_yes_is_noop_without_resuming_or_accepting_invite(self):
        for action in ('join', 'use_profile', 'continue_test'):self.choose(action)
        self.ask()
        before = self.store.current(self.router.scope.slot)['step']
        result = self.router.handle(self.source(text='sim', correlated=False))[0]
        self.assertEqual(result['status'], 'demo_acknowledged')
        self.assertEqual(result['step'], before)  # No menu reset or implied consent.
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 2)

    def test_resume_survives_router_recreation(self):
        self.choose('join'); self.choose('use_profile'); self.ask()
        self.router = DemoRouter(self.router.scope, self.store, self.gateway, now=self.router.now,
                                 continuation_enabled=True, question_answerer=self.router.question_answerer)
        self.assertEqual(self.choose('question'), 'about')
        self.assertEqual(self.choose('faq_benefits'), 'faq_context')
        self.assertEqual(self.choose('join'), 'conditions')

    def test_unknown_delivery_reconciles_with_resume_metadata(self):
        self.choose('join'); self.choose('use_profile')
        self.router.question_answerer = Mock(return_value=self.grounded())
        send = self.gateway.send
        self.gateway.send = Mock(side_effect=TimeoutError())
        result = self.router.handle(self.source(text='Como funciona?', correlated=False))[0]
        self.assertEqual(result['status'], 'demo_delivery_unconfirmed')
        self.gateway.lookup = lambda scope, key: {'status': 'accepted', 'message_id': '202', 'simulated': True}
        self.router.reconcile(); self.gateway.send = send
        self.assertEqual(self.choose('question'), 'about')
        self.assertEqual(self.choose('faq_benefits'), 'faq_context')
        self.assertEqual(self.choose('join'), 'conditions')

    def test_technical_failure_is_not_missing_business_knowledge(self):
        self.choose('join')
        self.router.question_answerer = Mock(side_effect=TimeoutError())
        result = self.router.handle(self.source(text='Como funciona?', correlated=False))[0]
        self.assertEqual(result['step'], 'faq_unavailable')
        self.assertNotIn('informação confirmada', self.gateway.sent[-1]['payload']['content'])
        self.assertEqual(self.choose('back'), 'about')

    def test_last_question_and_answer_context_are_available_without_contact_identity(self):
        self.choose('join'); self.choose('use_profile'); self.ask('Como funciona?')
        seen = []
        def answer(question, *, conversation):
            seen.append(conversation)
            return self.grounded()
        answer.accepts_dialogue_context = True
        self.router.question_answerer = answer
        self.router.handle(self.source(text='E nesse caso?', correlated=False))
        self.assertEqual(seen[0]['return_step'], 'conditions')
        self.assertEqual(seen[0]['last_question'], 'Como funciona?')
        self.assertIn('base aprovada', seen[0]['last_answer'])
        self.assertEqual(set(seen[0]), {'current_step','return_step','last_question','last_answer',
                                      'recent_dialogue','prior_questions','pending_clarification','operational_facts'})


class ModelContextCases(unittest.TestCase):
    def test_model_receives_only_sanitized_bounded_dialogue_fields(self):
        knowledge = {'source':'database','knowledge_version':'synthetic','personality':'Seja breve',
                     'limits':'Não prometer.', 'topics':[{'id':'offer','answer':'Conteúdo aprovado da base.'}]}
        fake = Mock()
        reference = next(ref for ref, item in _evidence_catalog(knowledge).items() if item['id'] == 'offer')
        payload = {'answer':'Conteúdo aprovado da base.', 'evidence':[reference]}
        fake.open.return_value = io.BytesIO(json.dumps({'status':'completed','output':[{'type':'message','role':'assistant',
            'content':[{'type':'output_text','text':json.dumps(payload)}]}]}).encode())
        answer=build_answerer({'ai_enabled':True,'openai_api_key':'synthetic','ai_model':'test'},opener=fake,context_loader=lambda _:knowledge, semantic_verifier=lambda *_: 'supported')
        result=answer('Dúvida @perfil', conversation={'current_step':'faq_context','return_step':'conditions',
            'last_question':'email teste@example.com, @perfil, +55 11 99999-9999',
            'last_answer':'A'*1000, 'api_key':'must-never-leak','phone':'must-never-leak'})
        self.assertIsInstance(result, dict)
        body=json.loads(fake.open.call_args.args[0].data)
        contents=json.loads(body['input'])
        self.assertNotIn('must-never-leak',body['input'])
        self.assertNotIn('teste@example.com',body['input'])
        self.assertNotIn('@perfil',body['input'])
        self.assertEqual(len(contents['conversation']['last_answer']),900)
        self.assertEqual(contents['context'],knowledge)
        self.assertIn('não é fonte de fatos',body['instructions'])
        self.assertFalse(body['store'])

    def test_redaction_and_length(self):
        self.assertEqual(safe_context_text('hi @person https://example.com'), 'hi [dado removido] [dado removido]')
        self.assertEqual(len(safe_context_text('x'*1000,500)),500)


class FailureClassificationCases(unittest.TestCase):
    def test_missing_knowledge_is_separate_from_invalid_provider_output(self):
        knowledge = {'source':'database','knowledge_version':'synthetic','personality':'Seja breve',
                     'limits':'Não prometer.', 'topics':[{'id':'offer','answer':'Conteúdo aprovado da base.'}]}
        for value, expected in [({'answer':'','evidence':[]}, 'faq_unknown'),
                ({'answer':'Sem suporte factual.','evidence':[]}, 'faq_unavailable'),
                ({'answer':'Outra afirmação.','evidence':[{'id':'offer','quote':'Citação inexistente aqui'}]}, 'faq_unavailable')]:
            with self.subTest(value=value):
                fake=Mock()
                fake.open.return_value=io.BytesIO(json.dumps({'status':'completed','output':[{'type':'message','role':'assistant',
                    'content':[{'type':'output_text','text':json.dumps(value)}]}]}).encode())
                answer=build_answerer({'ai_enabled':True,'openai_api_key':'synthetic','ai_model':'test'},opener=fake,context_loader=lambda _:knowledge, semantic_verifier=lambda *_: 'supported')
                self.assertEqual(answer('Como funciona?'),expected)

    def test_noncompleted_response_is_technical_failure(self):
        fake=Mock();fake.open.return_value=io.BytesIO(b'{"status":"incomplete"}')
        answer=build_answerer({'ai_enabled':True,'openai_api_key':'synthetic','ai_model':'test'},opener=fake,
                             context_loader=lambda _: {'source':'database'}, semantic_verifier=lambda *_: 'supported')
        self.assertEqual(answer('Como funciona?'),'faq_unavailable')
