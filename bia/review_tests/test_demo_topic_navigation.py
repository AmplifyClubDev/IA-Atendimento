"""Topic menus, existing-session compatibility, and unchanged isolated egress fences."""
from copy import deepcopy
import json
import unittest
from unittest.mock import Mock

import demo_flow
from demo_router import (CHOICES, OPENING, DemoRouter, DemoStore, DemoMultiplexer,
                         RecordingGateway, message_payload)
import test_demo_flow as flow_fixtures
import test_demo_retry as retry_fixtures
from test_demo_router import SCOPE, NOW
from test_demo_multi_scope import SECOND, source as scoped_source
from test_demo_review_boundaries import FakeChatwoot, REVIEW_SCOPE


def grounded():
    return {'answer': 'Uma resposta curta sobre o assunto. 📚',
            'evidence': [{'id': 'synthetic', 'quote': 'Uma fonte sintética completa.'}],
            'knowledge_version': 'synthetic-navigation'}


class TopicNavigationCases(unittest.TestCase):
    setUp = flow_fixtures.FlowCases.setUp
    source = retry_fixtures.RetryCases.source
    choose = flow_fixtures.FlowCases.choose

    def test_menus_are_static_short_and_use_only_existing_input_select_contract(self):
        self.router.question_answerer = Mock(side_effect=AssertionError('Menu must not invoke AI'))
        self.assertEqual(self.choose('know'), 'about')
        self.assertEqual(self.choose('topic_partnership'), 'faq_partnership')
        self.assertEqual(self.choose('back'), 'about')
        self.assertEqual(self.choose('topic_more'), 'faq_more')
        self.assertEqual(self.choose('back'), 'about')
        self.router.question_answerer.assert_not_called()
        for sent in self.gateway.sent[1:]:
            payload = sent['payload']
            self.assertLess(len(payload['content']), 150)
            self.assertEqual(payload['content_type'], 'input_select')
            self.assertEqual(set(payload['content_attributes']), {'items'})
            self.assertLessEqual(len(payload['content_attributes']['items']), 3)
            self.assertNotIn('Retomar etapa', str(payload))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 0)

    def test_all_topic_buttons_ask_the_specific_question_and_return_only_two_choices(self):
        self.choose('know')
        answer = self.router.question_answerer = Mock(return_value=grounded())
        for path in (('faq_benefits',), ('topic_partnership', 'faq_terms'),
                     ('topic_partnership', 'faq_invite'), ('topic_more', 'topic_lives'),
                     ('topic_more', 'topic_club')):
            with self.subTest(path=path):
                for action in path:
                    self.choose(action)
                answer.assert_called_with(demo_flow.TOPIC_QUESTIONS[path[-1]])
                self.assertEqual(self.store.current(SCOPE.slot)['step'], 'faq_context')
                payload = self.gateway.sent[-1]['payload']
                self.assertEqual([item['title'] for item in payload['content_attributes']['items']],
                                 ['Quero me agenciar', 'Tenho outra dúvida'])
                self.assertNotIn('Retomar etapa', str(payload))
                self.assertEqual(self.choose('question'), 'about')
        self.assertEqual(answer.call_count, 5)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 0)

    def test_new_topics_without_ai_fail_closed_instead_of_inventing_static_facts(self):
        self.choose('know')
        for action in ('topic_lives', 'topic_club'):
            self.choose('topic_more')
            self.assertEqual(self.choose(action), 'faq_unavailable')
            self.assertEqual(self.choose('back'), 'about')

    def test_topic_retry_repeats_its_saved_question_and_menu_return_never_resumes_collection(self):
        self.choose('join')
        self.choose('use_profile')
        self.choose('question')
        self.choose('topic_more')
        answer = self.router.question_answerer = Mock(side_effect=['faq_unavailable', grounded()])
        self.assertEqual(self.choose('topic_club'), 'faq_unavailable')
        self.assertEqual(self.choose('retry'), 'faq_context')
        self.assertEqual([call.args[0] for call in answer.call_args_list],
                         [demo_flow.TOPIC_QUESTIONS['topic_club']] * 2)
        self.assertEqual(self.choose('question'), 'about')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 1)

    def test_existing_retornar_button_is_correlated_deduplicated_and_returns_topics(self):
        self.choose('join')
        self.router.question_answerer = Mock(return_value=grounded())
        self.router.handle(self.source(text='Como funciona?', correlated=False))
        state = self.store.current(SCOPE.slot)
        key = state['outbox_key']
        original_run = state['run']
        row = self.store.db.execute('SELECT payload FROM demo_outbox WHERE key=?', (key,)).fetchone()
        old_payload = json.loads(row['payload'])
        old_payload['content_attributes']['items'].append({'title': 'Retomar etapa', 'value': key + ':back'})
        self.store.db.execute('UPDATE demo_outbox SET payload=? WHERE key=?', (json.dumps(old_payload), key))
        count = len(self.gateway.sent)
        uncorrelated = self.source('back', correlated=False)
        self.assertEqual(self.router.handle(uncorrelated)[0]['status'], 'demo_choice_not_current')
        self.assertEqual(len(self.gateway.sent), count)
        event = self.source('back')
        result = self.router.handle(event)
        self.assertEqual(result[0]['step'], 'about')
        self.assertEqual(self.router.handle(event), result)
        self.assertEqual(len(self.gateway.sent), count + 1)
        self.assertEqual(self.store.current(SCOPE.slot)['run'], original_run)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 0)

    def test_existing_about_buttons_remain_usable_without_resetting_the_run(self):
        self.choose('know')
        state = self.store.current(SCOPE.slot)
        key = state['outbox_key']
        old_payload = message_payload(key, continuation_enabled=True)
        old_payload['content_attributes']['items'] = [
            {'title': title, 'value': key + ':' + action} for action, title in
            {'join': 'Quero me agenciar', 'faq_benefits': 'Conhecer benefícios', 'question': 'Tenho dúvidas'}.items()]
        self.store.db.execute('UPDATE demo_outbox SET payload=? WHERE key=?', (json.dumps(old_payload), key))
        self.assertEqual(self.choose('question'), 'about')
        self.assertEqual(self.store.current(SCOPE.slot)['run'], state['run'])
        self.assertEqual(len(self.gateway.sent[-1]['payload']['content_attributes']['items']), 3)

    def test_stage_is_preserved_across_submenus_and_router_restart_until_explicit_join(self):
        for action in ('join', 'use_profile', 'continue_test'):
            self.choose(action)
        self.choose('question')
        self.choose('topic_partnership')
        self.choose('back')
        self.choose('topic_more')
        self.router = DemoRouter(SCOPE, self.store, self.gateway, now=lambda: NOW,
                                 continuation_enabled=True, question_answerer=Mock(return_value=grounded()))
        self.choose('topic_lives')
        self.assertEqual(self.choose('join'), 'invite')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 2)

    def test_unshown_uncorrelated_stale_and_wrong_scope_menu_choices_cannot_advance(self):
        stale = self.source('know')
        self.router.handle(stale)
        self.router.question_answerer = Mock(return_value=grounded())
        count = len(self.gateway.sent)
        for event in (self.source('topic_more', correlated=False),
                      {**self.source('topic_more'), 'demo_reply_to': stale['demo_reply_to']},
                      {**self.source('topic_more'), 'contact_id': '88'},
                      self.source(text='Retomar etapa', correlated=True)):
            self.assertFalse(self.router.handle(event)[0]['accepted'])
        self.assertEqual(len(self.gateway.sent), count)
        self.router.question_answerer.assert_not_called()

    def test_unknown_menu_delivery_blocks_duplicate_and_later_navigation_without_resend(self):
        self.choose('know')
        self.router.question_answerer = Mock(return_value=grounded())
        send = self.gateway.send
        def uncertain(scope, payload, key):
            send(scope, payload, key)
            raise TimeoutError()
        self.gateway.send = Mock(side_effect=uncertain)
        event = self.source('topic_more')
        first = self.router.handle(event)
        self.assertEqual(first[0]['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(self.router.handle(event), first)
        self.assertEqual(self.router.handle(self.source(text='Lives e conteúdo', correlated=False))[0]['status'],
                         'demo_delivery_unconfirmed')
        self.gateway.send.assert_called_once()
        self.router.question_answerer.assert_not_called()


class MenuBoundaryCases(unittest.TestCase):
    def test_persisted_choices_require_exact_key_known_actions_and_unique_short_labels(self):
        key = demo_flow.new_key('a' * 32, 'about')
        payload = message_payload(key, continuation_enabled=True)
        self.assertEqual(demo_flow.presented_choices(key, payload), demo_flow.TEMPLATES['about'][1])
        for change in ({'title': 'x' * 21}, {'value': 'other:faq_benefits'},
                       {'value': key + ':not_authorized'}, {'value': key + ':faq_benefits:join'}):
            invalid = deepcopy(payload)
            invalid['content_attributes']['items'][0].update(change)
            self.assertEqual(demo_flow.presented_choices(key, invalid), {})
        invalid = deepcopy(payload)
        invalid['content_attributes']['items'][1] = invalid['content_attributes']['items'][0]
        self.assertEqual(demo_flow.presented_choices(key, invalid), {})

    def test_reconciliation_matches_persisted_old_menu_but_cannot_send_it_again(self):
        key = demo_flow.new_key('a' * 32, 'about')
        old_payload = message_payload(key, continuation_enabled=True)
        old_payload['content'] = 'Menu anterior aprovado.'
        fake = FakeChatwoot()
        gateway = fake.gateway()
        gateway.continuation_enabled = True
        gateway.context_payload = lambda requested: old_payload if requested == key else None
        fake.messages = [{**old_payload, 'id': '201', 'message_type': 'outgoing',
                          'account_id': REVIEW_SCOPE.account_id, 'inbox_id': REVIEW_SCOPE.inbox_id,
                          'conversation_id': REVIEW_SCOPE.conversation_id}]
        self.assertEqual(gateway.lookup(REVIEW_SCOPE, key)['message_id'], '201')
        self.assertEqual([method for method, _, _ in fake.calls], ['GET'])
        fake.messages[0]['content'] = 'Not the persisted content.'
        self.assertIsNone(gateway.lookup(REVIEW_SCOPE, key))
        with self.assertRaisesRegex(ValueError, 'approved'):
            gateway.send(REVIEW_SCOPE, old_payload, key)
        self.assertNotIn('POST', [method for method, _, _ in fake.calls])

    def test_two_contacts_have_independent_topic_menus_and_saved_stages(self):
        store = DemoStore(':memory:')
        self.addCleanup(store.close)
        routers = [DemoRouter(scope, store, RecordingGateway(), now=lambda: NOW, continuation_enabled=True)
                   for scope in (SCOPE, SECOND)]
        mux = DemoMultiplexer(routers)
        for index, router in enumerate(routers):
            router.start('synthetic-menu-' + str(index))
        first, second = routers
        event = scoped_source(SCOPE, message_id='201', text=CHOICES['know'],
                              demo_reply_to=store.current(SCOPE.slot)['parent_id'])
        self.assertEqual(mux.handle(event)[0]['step'], 'about')
        self.assertEqual(store.current(SECOND.slot)['step'], 'opening')
        next_event = scoped_source(SCOPE, message_id='202', text='Mais assuntos',
                                   demo_reply_to=store.current(SCOPE.slot)['parent_id'])
        self.assertEqual(mux.handle(next_event)[0]['step'], 'faq_more')
        self.assertEqual(len(second.gateway.sent), 1)
        self.assertEqual(store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0], 0)
