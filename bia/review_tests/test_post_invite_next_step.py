from copy import deepcopy
from datetime import timedelta
from unittest import TestCase
from unittest.mock import Mock

import conversation
from real_journey import PUBLIC_FORM_URL, _post_invite_next_step, invite_acceptance_proven
from test_relationship_form_chat30 import AT, POLICY, invited
from tutorial_videos import ACCEPT_INVITE_URL


class PostInviteNextStepTests(TestCase):
    def state(self):
        state = invited('sent')['state']
        state['cycle']['experience_version'] = 'bia-approved-v1'
        return state

    def turn(self, text, state, planner, at=AT):
        return conversation.handle(
            state, text, planner, now=at, real_mode=True, operation_policy=POLICY,
            relationship_check_in_form=True, same_engine_enabled=True)

    def assert_read_only_turn(self, result, before):
        self.assertEqual(result['effects'], [])
        self.assertEqual(result['buttons'], [])
        self.assertEqual(result['state']['effects'], before['effects'])
        for field in ('phase', 'facts', 'bia_validation', 'real_operations', 'form_url'):
            self.assertEqual(result['state']['cycle'].get(field), before['cycle'].get(field))
        self.assertNotIn(PUBLIC_FORM_URL, result['reply'])
        self.assertNotIn('gmv', result['reply'].lower())
        self.assertNotIn('@', result['reply'])

    def test_natural_help_is_acceptance_only_even_with_stale_qualification(self):
        for stage in (None, 'gmv'):
            for text in ('Como eu começo?', 'Não sei como começar.', 'Queria saber como começar',
                         'Qual é o meu próximo passo?', 'E agora?'):
                with self.subTest(stage=stage, text=text):
                    state = self.state()
                    if stage:
                        state['cycle']['bia_validation'] = {'version': 1, 'stage': stage}
                    planner = Mock(return_value={'reply': 'Me mande seu @ e GMV.'})
                    self.assertTrue(invite_acceptance_proven(state, AT))
                    result = self.turn(text, state, planner)
                    planner.assert_not_called()
                    self.assertIn('O próximo passo é aceitar o convite', result['reply'])
                    self.assert_read_only_turn(result, state)

    def test_missing_expired_uncertain_or_negative_proof_is_conditional(self):
        for issue in ('absent', 'unconfirmed', 'expired', 'future', 'wrong_creator',
                      'wrong_job', 'cancelled', 'newer_negative'):
            with self.subTest(issue=issue):
                state = self.state()
                cycle = state['cycle']
                cycle['bia_validation'] = {'version': 1, 'stage': 'gmv'}
                record = cycle['real_operations']['invite']
                at = AT
                if issue == 'absent':
                    cycle['phase'] = 'await_acceptance'
                    cycle['real_operations'].pop('invite')
                elif issue == 'unconfirmed':
                    record.update(status='pending_verification', confirmed=False)
                elif issue == 'expired':
                    at += timedelta(seconds=901)
                elif issue == 'future':
                    record['observed_at'] = (AT + timedelta(seconds=1)).isoformat()
                elif issue == 'wrong_creator':
                    record['creator'] = 'different_test_profile'
                elif issue == 'wrong_job':
                    record['job_id'] = 'absent-test-job'
                elif issue == 'cancelled':
                    cycle['invite_cancellation_reported'] = {'at': AT.isoformat()}
                elif issue == 'newer_negative':
                    job_id = 'negative-test-receipt'
                    observed = AT + timedelta(seconds=1)
                    state['effects'][job_id] = dict(state['effects'][record['job_id']], operation='relationship')
                    cycle['real_operations']['relationship'] = dict(
                        record, status='not_found', job_id=job_id, observed_at=observed.isoformat())
                    at = observed
                self.assertFalse(invite_acceptance_proven(state, at))
                planner = Mock()
                result = self.turn('Como eu começo?', state, planner, at)
                planner.assert_not_called()
                self.assertIn('Não tenho confirmação', result['reply'])
                self.assert_read_only_turn(result, state)

    def test_verified_relationship_and_reported_acceptance_never_ask_to_accept_twice(self):
        for phase, declared, status in (
                ('form', True, 'sent'), ('checking_acceptance', False, 'sent'), ('form', False, 'linked')):
            with self.subTest(phase=phase, declared=declared, receipt=status):
                state = self.state()
                cycle = state['cycle']
                cycle['phase'] = phase
                cycle['facts']['aceite_declarado'] = declared
                cycle['real_operations']['invite']['status'] = status
                planner = Mock()
                result = self.turn('Qual o próximo passo?', state, planner)
                planner.assert_not_called()
                self.assertIn('concluir o cadastro' if status == 'linked' else 'confirmar o vínculo', result['reply'])
                self.assertNotIn('é aceitar o convite', result['reply'])
                self.assert_read_only_turn(result, state)

    def test_scope_does_not_intercept_faq_tutorial_or_explicit_commands(self):
        state = self.state()
        for text in ('como funciona', 'como comeco a vender', 'como comeco e qual e a comissao',
                     'como aceitar o convite', 'ja aceitei', 'verificar novamente', 'quero o link',
                     'nao apareceu o convite', 'cancelei o convite', 'quero agenciar', '5000'):
            with self.subTest(text=text):
                self.assertIsNone(_post_invite_next_step(state, text, AT))
        result = self.turn('Como aceitar o convite?', state, Mock())
        self.assertIn(ACCEPT_INVITE_URL, result['reply'])
        planner = Mock(return_value={'intent': 'question', 'shared_answer': {
            'engine': 'shared-answer-v1', 'status': 'supported', 'profile_id': 'amplify-v1',
            'text': 'Os benefícios variam por categoria.'}})
        result = self.turn('Conhecer benefícios', state, planner)
        planner.assert_called_once()
        self.assertIn('Os benefícios variam por categoria', result['reply'])

    def test_approved_topic_does_not_append_stale_gmv_after_invitation(self):
        state = self.state()
        state['cycle']['bia_validation'] = {'version': 1, 'stage': 'gmv'}
        planner = Mock(return_value={'intent': 'question', 'shared_answer': {
            'engine': 'shared-answer-v1', 'status': 'supported', 'profile_id': 'amplify-v1',
            'text': 'Os benefícios variam por categoria.'}})
        result = self.turn('Conhecer benefícios', state, planner)
        planner.assert_called_once()
        self.assertIn('Os benefícios variam por categoria', result['reply'])
        self.assertEqual(result['state']['cycle']['phase'], 'form')
        self.assertEqual(result['state']['effects'], state['effects'])
        self.assertNotIn('GMV', result['reply'])

    def test_pre_invite_qualification_and_ownership_guards_unchanged(self):
        base = self.state()
        cycle = base['cycle']
        for flag in ('human_control', 'opt_out', 'qualification_paused',
                     'pending_profile_changes', 'answer_clarification'):
            with self.subTest(flag=flag):
                state = deepcopy(base)
                target = state if flag == 'human_control' else state['cycle']
                target[flag] = True
                self.assertIsNone(_post_invite_next_step(state, 'como eu comeco', AT))
        state = {}
        for text in ('Quero fazer parte', '@perfil_qa', 'Não', 'Sim'):
            result = conversation.handle(
                state, text, now=AT, real_mode=True, operation_policy=POLICY,
                relationship_check_in_form=True, same_engine_enabled=True,
                approved_experience_enabled=True, qualification_enabled=True)
            state = result['state']
        self.assertEqual(state['cycle']['bia_validation']['stage'], 'gmv')
        self.assertIsNone(_post_invite_next_step(state, 'como eu comeco', AT))
        result = self.turn('2500', state, Mock())
        self.assertEqual(result['state']['cycle']['facts']['tiktok_declarado'], '@perfil_qa')
        self.assertEqual(result['state']['cycle']['facts']['gmv_30d_declarado_centavos'], 250000)
