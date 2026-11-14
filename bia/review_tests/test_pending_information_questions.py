"""Regression: dropped lead FAQ is recovered by the answerer, not control logic."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import answer_engine
from amplify_answer_profile import amplify_instructions
from real_answer_adapter import (build_real_planner, clear_answered_questions, dialogue_from_context,
                                 pending_information_questions, remember_suppressed_question)
from server import create_app
import test_audit_turn_fencing31 as fencing

EARLIER = 'Mais como funciona onde fica agência?'
FOLLOWUP = 'Eu nunca fiz live'
COMBINED = ('A Amplify orienta creators no TikTok Shop.\n\nAinda não tenho o endereço da agência confirmado.\n\n'
            'Fazer *live não é obrigatório*. 🎥')
QUOTE = 'Fazer live não é obrigatório para participar da parceria.'


def _answer(text):
    return {'answer': text, 'evidence': [{'id': 'lives', 'quote': QUOTE}],
            'knowledge_version': 'offline-v1'}


class PendingQuestions(unittest.TestCase):
    def setUp(self):
        self.at = datetime.now(timezone.utc)
        self.state = {'cycle': {'id': 'first', 'status': 'open'}}
        self.event = {'message_id': '201', 'text': EARLIER}
        self.newer = {'message_id': '202', 'text': FOLLOWUP}

    def test_recent_earlier_same_cycle_only_and_cleared_once(self):
        self.assertTrue(remember_suppressed_question(self.state, self.event, now=self.at))
        self.assertEqual(pending_information_questions(self.state, self.newer, now=self.at)[0]['text'], EARLIER)
        self.assertFalse(pending_information_questions(self.state, self.event, now=self.at))
        self.assertFalse(pending_information_questions(self.state, self.newer, now=self.at+timedelta(seconds=121)))
        self.assertFalse(pending_information_questions({**self.state, 'cycle': {'id': 'reset', 'status': 'open'}},
                                                      self.newer, now=self.at))
        self.assertTrue(clear_answered_questions(self.state, [201]))
        self.assertFalse(pending_information_questions(self.state, self.newer, now=self.at))

    def test_controls_ambiguous_statements_and_private_data_not_carried(self):
        for value in ('Pode mandar', 'Meu convite já chegou?', 'Como funciona meu convite?',
                      'Onde fica a agência? Meu e-mail é lead@example.invalid', 'Como funciona? @handle',
                      'Como funciona aceitar o cadastro?', 'Sou iniciante'):
            self.assertFalse(remember_suppressed_question(self.state, {**self.event, 'text': value}, now=self.at), value)

    def test_only_answer_engine_receives_combined_text_and_marker_not_forgeable(self):
        calls = []
        def classifier(q, c, s):
            calls.append(('classifier', q))
            self.assertNotIn('pending_information_questions', c)
            return {'intent': 'question', 'claims': [], 'carried_information_sources': [999]}
        def answerer(q, **kwargs):
            calls.append(('answerer', q))
            return _answer(COMBINED)
        remember_suppressed_question(self.state, self.event, now=self.at)
        rows = pending_information_questions(self.state, self.newer, now=self.at)
        result = build_real_planner({}, classifier, answerer=answerer)(
            FOLLOWUP, {'real_mode': True, 'pending_information_questions': rows}, {})
        self.assertEqual(calls, [('classifier', FOLLOWUP), ('answerer', EARLIER+'\n'+FOLLOWUP)])
        self.assertEqual(result['carried_information_sources'], [201])
        self.assertEqual(result['claims'], [])
        self.assertIn('não tenho o endereço', result['reply'])
        self.assertIn('Nunca infira uma cidade', amplify_instructions('real'))

    def test_public_reply_context_is_redacted_and_requires_outbox_evidence(self):
        row = {'last_accepted_reply': {'text': 'Conteúdo dirigido a @private ou lead@example.invalid'}}
        self.assertEqual(dialogue_from_context({'delivery_context':row})['last_accepted_public_reply'], '')
        proven = dialogue_from_context({'delivery_context':{'source':'outbox',**row}})
        self.assertEqual(proven['last_accepted_public_reply'], 'Conteúdo dirigido a [dado removido] ou [dado removido]')

    def test_engine_failure_is_not_treated_as_answered(self):
        remember_suppressed_question(self.state, self.event, now=self.at)
        rows = pending_information_questions(self.state, self.newer, now=self.at)
        result = build_real_planner({}, lambda *a: {}, answerer=lambda *a, **k:'faq_unavailable')(
            FOLLOWUP, {'real_mode': True, 'pending_information_questions': rows}, {})
        self.assertNotIn('carried_information_sources', result)


class RealIngress(unittest.TestCase):
    def setUp(self):
        self.f = fencing.TurnFencing31Tests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.model_calls = []
        self.classifier_calls = []
        def classifier(question, context, settings):
            self.assertNotIn('pending_information_questions', context)
            self.classifier_calls.append(question)
            return {'provider_status': 'completed', 'intent': 'question', 'claims': [], 'reply': ''}
        def answerer(question, *, conversation=None):
            self.model_calls.append(question)
            if question == EARLIER and self.mode == 'engine':
                self.f.entered.set()
                if not self.f.release.wait(5):
                    raise AssertionError('offline answer engine not released')
            return _answer(COMBINED if '\n' in question else 'Fazer *live não é obrigatório*. 🎥')
        self.mode = 'engine'
        self.f.settings.update(same_engine_enabled=True, approved_experience_enabled=True,
                               qualification_enabled=True)
        with patch.object(answer_engine, 'build_answerer', return_value=answerer):
            self.f.app = create_app(self.f.settings, self.f.repo, self.f.transport,
                planner=classifier, real_client=fencing.Client(), real_guard=lambda event: {'allowed': True})
        self.f.app.extensions['v5_data_gateway'] = fencing.Gateway()

    def run_race(self):
        old = self.f.payload(201, EARLIER)
        newer = self.f.payload(202, FOLLOWUP, seconds=6)
        if self.mode == 'engine':
            self.f.start('old', old)
            self.assertTrue(self.f.entered.wait(3))
            self.f.start('newer', newer)
            self.f.wait_new_source(old)
        else:
            def during_get():
                self.f.start('newer', newer)
                self.f.wait_new_source(old)
            self.f.http.before_get = during_get
            self.f.start('old', old)
            self.assertTrue(self.f.entered.wait(0.05) is False)
        self.f.join()
        self.assertEqual(self.f.source_posts(201), [])
        posted = self.f.source_posts(202)
        self.assertEqual(len(posted), 1, self.f.responses)
        self.assertIn('endereço da agência', posted[0]['json_body']['content'])
        self.assertIn('live não é obrigatório', posted[0]['json_body']['content'])
        self.assertEqual(self.classifier_calls, [EARLIER, FOLLOWUP])
        self.assertEqual(self.model_calls, [EARLIER, EARLIER+'\n'+FOLLOWUP])
        self.assertNotIn('pending_information_questions', self.f.repo.load_session(fencing.CONV))
        self.assertTrue(self.f.post(newer)[1]['duplicate'])
        self.assertEqual(len(self.f.source_posts(202)), 1)

    def test_supersession_during_generation_groups_both_questions_once(self):
        self.run_race()

    def test_supersession_during_recipient_get_groups_both_questions_once(self):
        self.mode = 'recipient'
        self.run_race()
