"""A yes/no answers the actual warning, never an older boolean/consent."""
from copy import deepcopy
from datetime import timedelta
import unittest

import conversation
from followup import sequence_keys
import test_cycle_closure29 as closure_tests
from test_cycle_closure29 import waiting, NOW, SOURCE, CONVERSATION
from test_real_journey import eligible_state, POLICY, NOW as JOURNEY_NOW, GATE


def notice(state, *, uncertain=False):
    key, _ = sequence_keys(state['cycle']['id'], SOURCE)
    moment = JOURNEY_NOW+timedelta(seconds=60) if state['cycle']['phase'] == 'consent_real' else NOW-timedelta(minutes=5)
    return {'source': 'uncertain_outbox' if uncertain else 'accepted_outbox',
            'cycle_id': state['cycle']['id'], 'source_key': SOURCE, 'warning_key': key,
            'observed_at' if uncertain else 'accepted_at': moment.isoformat()}


def phase_state(phase):
    state = eligible_state()['state'] if phase == 'consent_real' else waiting(phase)
    state['processed_inbound'] = [SOURCE]
    return state


class InactivityAnswerTests(unittest.TestCase):
    def test_accepted_yes_resumes_without_boolean_claim_or_invite_in_each_phase(self):
        for phase in ('consent_real', 'shop', 'agency'):
            with self.subTest(phase=phase):
                state = phase_state(phase)
                now = JOURNEY_NOW+timedelta(seconds=120) if phase == 'consent_real' else NOW
                result = conversation.handle(state, 'Sim', lambda *_: self.fail('Warning answer is deterministic'),
                    now=now, real_mode=True, operation_policy=POLICY, inactivity_notice=notice(state))
                self.assertFalse(result['state']['cycle'].get('invite_consent'))
                self.assertNotIn('consentimento_convite', result['state']['cycle']['facts'])
                self.assertNotIn('shop_ativo_declarado', result['state']['cycle']['facts'])
                self.assertNotIn('possui_agencia_declarada', result['state']['cycle']['facts'])
                self.assertFalse(any(effect.get('operation') == 'invite' for effect in result['effects']))
                if phase == 'consent_real':
                    self.assertEqual(result['state']['cycle']['phase'], 'consent_real')
                    self.assertIn('Posso te mandar o convite no TikTok', result['reply'])

    def test_accepted_no_closes_without_answering_previous_boolean_or_consent(self):
        for phase in ('consent_real', 'shop', 'agency'):
            with self.subTest(phase=phase):
                state = phase_state(phase)
                now = JOURNEY_NOW+timedelta(seconds=120) if phase == 'consent_real' else NOW
                result = conversation.handle(state, 'Não', lambda *_: self.fail('No AI'), now=now,
                    real_mode=True, operation_policy=POLICY, inactivity_notice=notice(state))
                self.assertEqual(result['state']['cycle']['reason'], 'inactivity_user_close')
                self.assertEqual(result['state']['cycle']['status'], 'closed')
                self.assertNotIn('consentimento_convite', result['state']['cycle']['facts'])
                self.assertNotIn('shop_ativo_declarado', result['state']['cycle']['facts'])
                self.assertNotIn('possui_agencia_declarada', result['state']['cycle']['facts'])
                self.assertEqual(result['effects'], [])

    def test_unknown_warning_reasks_instead_of_claiming_yes_or_no(self):
        for phase in ('consent_real', 'shop', 'agency'):
            for text in ('Sim', 'Não'):
                with self.subTest(phase=phase, text=text):
                    state = phase_state(phase)
                    now = JOURNEY_NOW+timedelta(seconds=120) if phase == 'consent_real' else NOW
                    result = conversation.handle(state, text, lambda *_: self.fail('No AI'), now=now,
                        real_mode=True, operation_policy=POLICY, inactivity_notice=notice(state, uncertain=True))
                    self.assertEqual(result['state']['cycle']['status'], 'open')
                    self.assertNotIn('consentimento_convite', result['state']['cycle']['facts'])
                    self.assertNotIn('shop_ativo_declarado', result['state']['cycle']['facts'])
                    self.assertNotIn('possui_agencia_declarada', result['state']['cycle']['facts'])
                    self.assertFalse(any(effect.get('operation') == 'invite' for effect in result['effects']))

    def test_failed_absent_and_other_cycle_warnings_do_not_replace_real_consent_question(self):
        for kind in ('absent', 'other_cycle', 'old_source'):
            with self.subTest(kind=kind):
                state = phase_state('consent_real')
                context = None if kind == 'absent' else notice(state)
                if kind == 'other_cycle': context['cycle_id'] = 'old-cycle'
                if kind == 'old_source': context['source_key'] = 'chatwoot:1:700'
                result = conversation.handle(state, 'Sim', now=JOURNEY_NOW+timedelta(seconds=120),
                    real_mode=True, operation_policy=POLICY, inactivity_notice=context)
                self.assertEqual(result['state']['cycle']['phase'], 'inviting')
                self.assertEqual([effect['operation'] for effect in result['effects']], ['invite'])

    def test_normal_event_ingress_preserves_actual_yes_and_uses_previous_source_binding(self):
        state = phase_state('consent_real')
        event = dict(provider='chatwoot', account_id='1', inbox_id='3', conversation_id='26097',
            message_id='901', contact_id='3', sender_phone=GATE['phone'], sender_type='contact',
            message_type='incoming', private=False, text='Sim', source_ref='chatwoot:1:901',
            created_at=(JOURNEY_NOW+timedelta(seconds=120)).isoformat())
        result = conversation.handle_event(state, event, GATE, lambda *_: self.fail('No AI'),
            now=JOURNEY_NOW+timedelta(seconds=120), real_mode=True, operation_policy=POLICY,
            inactivity_notice=notice(state))
        self.assertEqual(result['state']['processed_inbound'][-1], 'chatwoot:1:901')
        self.assertEqual(result['state']['history'][-2]['text'], 'Sim')
        self.assertEqual(result['state']['cycle']['phase'], 'consent_real')
        self.assertEqual(result['effects'], [])


class InactivityNoticeProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = closure_tests.InactivityProjectionTests('test_accepted_pair_closes_and_projects_exact_sql_snapshot_once')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.case = self.fixture
        with self.case.repo._connection() as db:
            db.execute('DELETE FROM outbox WHERE outbox_key=?', (self.case.closure_key,))
            db.execute('DELETE FROM operations WHERE operation_key=?', (self.case.closure_key,))
            db.execute('UPDATE outbox SET updated_at=? WHERE outbox_key=?',
                ((NOW-timedelta(minutes=4)).isoformat(), self.case.warning_key))
        self.project = self.case.app.extensions['v5_inactivity_notice']

    def test_accepted_warning_requires_durable_pair_and_last_actual_bia_reply(self):
        projected = self.project(self.case.state)
        self.assertEqual(projected['source'], 'accepted_outbox')
        self.assertEqual(projected['accepted_at'], self.case.warning['accepted_at'])
        # A later canonical consent reply supersedes the warning question.
        self.case.repo.prepare_reply(SOURCE, CONVERSATION, self.case.state, 'later-reply',
                                    {'text': 'Você autoriza este convite?', 'buttons': []})
        self.case.repo.finish_outbox('later-reply', 'accepted', {'status': 'accepted', 'message_id': '903'})
        with self.case.repo._connection() as db:
            db.execute('UPDATE outbox SET updated_at=? WHERE outbox_key=?', (NOW.isoformat(), 'later-reply'))
        self.assertIsNone(self.project(self.case.state))

    def test_failed_unknown_old_source_and_old_cycle_projections_are_distinct(self):
        for status in ('failed', 'outcome_unknown'):
            receipt = {**self.case.warning, 'status': status}
            receipt.pop('accepted_at', None)
            self.case.repo.finish_outbox(self.case.warning_key, status, receipt)
            self.case.repo.complete_operation(self.case.warning_key, receipt, status)
            with self.case.repo._connection() as db:
                db.execute('UPDATE outbox SET updated_at=? WHERE outbox_key=?',
                           ((NOW-timedelta(minutes=4)).isoformat(), self.case.warning_key))
            result = self.project(self.case.state)
            if status == 'failed':
                self.assertIsNone(result)
            else:
                self.assertEqual(result['source'], 'uncertain_outbox')
                self.assertNotIn('accepted_at', result)
        changed = deepcopy(self.case.state)
        changed['processed_inbound'].append('chatwoot:1:999')
        self.assertIsNone(self.project(changed))
        changed = deepcopy(self.case.state)
        changed['cycle']['id'] = 'old-cycle'
        self.assertIsNone(self.project(changed))
