"""54457: reconcile an interrupted invitation before asking for acceptance."""
from copy import deepcopy
from datetime import timedelta
import unittest
from unittest.mock import patch

import real_journey as journey
import test_convite42 as fixtures
from test_relationship_form_chat30 import AT, POLICY, invited, inbound
from test_regressao41 import settle, say

LIST = {'source': 'partner_relations', 'fresh': True, 'complete': True}


class InterruptedInvitationTests(unittest.TestCase):
    def interrupted(self):
        result = invited('outcome_unknown', confirmed=False, evidence={},
                         reason='interrupted_write_reconcile')
        state = result['state']
        # The initial tracking read has finished or been superseded by a lead turn.
        for effect in state['effects'].values():
            if effect.get('operation') == 'relationship' and effect.get('status') == 'pending':
                effect['status'] = 'superseded'
        return state

    def acceptance_result(self, status='not_found', evidence=None, minutes=6, state=None):
        at = AT + timedelta(minutes=minutes)
        turn = say('Verificar aceite', self.interrupted() if state is None else state, at)
        read = next(e for e in turn['effects'] if e['operation'] == 'relationship')
        return settle(turn['state'], read, status, at, evidence=dict(LIST if evidence is None else evidence)), at

    def test_missing_invite_after_interruption_starts_a_read(self):
        for text in ('Não apareceu o convite', 'Não chegou convite não', 'Reenviar', 'Até agora nada', 'Não tem nada'):
            with self.subTest(text=text):
                turn = say(text, self.interrupted(), AT + timedelta(minutes=6))
                self.assertEqual([e['operation'] for e in turn['effects']], ['relationship'])
                self.assertNotIn('Quando aceitar', turn['reply'])

    def test_complete_absence_after_acceptance_check_recovers_delivery(self):
        result, at = self.acceptance_result()
        if [e['operation'] for e in result['effects']] == ['precheck']:
            result = settle(result['state'], result['effects'][0], 'eligible', at)
        self.assertEqual([e['operation'] for e in result['effects']], ['invite'])
        self.assertTrue(result['effects'][0]['payload']['list_proof'])
        self.assertNotIn('aceite o convite', result['reply'].lower())
        self.assertEqual(result['state']['cycle']['phase'], 'inviting')

    def test_unknown_effect_is_preserved_and_never_blindly_retried(self):
        state = self.interrupted()
        before = deepcopy(next(e for e in state['effects'].values() if e.get('operation') == 'invite'))
        self.assertIsNone(journey._effect(state, 'invite', AT + timedelta(minutes=6), policy=POLICY))
        result, at = self.acceptance_result(state=state)
        old = result['state']['effects'][before['id']]
        self.assertEqual(old, before)

    def test_incomplete_absence_does_not_authorize_a_write(self):
        for evidence in ({'source': 'partner_relations', 'fresh': True, 'complete': False},
                         {'source': 'partner_relations', 'fresh': False, 'complete': True}):
            with self.subTest(evidence=evidence):
                result, _ = self.acceptance_result(evidence=evidence)
                self.assertNotIn('invite', [e['operation'] for e in result['effects']])
                self.assertNotIn('aceite o convite', result['reply'].lower())

    def test_absence_too_soon_does_not_authorize_a_write(self):
        result, _ = self.acceptance_result(minutes=1)
        self.assertNotIn('invite', [e['operation'] for e in result['effects']])

    def test_pending_invitation_is_not_sent_again(self):
        evidence = dict(LIST, relation_id='7300000000000000001', status='solicitada', tiktok_status=2)
        result, _ = self.acceptance_result('pending', evidence)
        self.assertNotIn('invite', [e['operation'] for e in result['effects']])

    def test_linked_creator_gets_registration_without_new_invitation(self):
        evidence = dict(LIST, relation_id='7300000000000000002', status='vinculado', tiktok_status=1)
        result, _ = self.acceptance_result('linked', evidence)
        self.assertEqual(result['state']['cycle']['phase'], 'form')
        self.assertNotIn('invite', [e['operation'] for e in result['effects']])

    def test_resend_limit_is_kept(self):
        state = self.interrupted()
        creator = state['cycle']['facts']['tiktok_declarado']
        state['invite_resends'] = {creator: {'count': journey.INVITE_RESEND_LIMIT}}
        at = AT + timedelta(minutes=6)
        turn = say('Verificar aceite', state, at)
        result = settle(turn['state'], turn['effects'][0], 'not_found', at, evidence=dict(LIST))
        self.assertNotIn('invite', [e['operation'] for e in result['effects']])

    def test_running_invitation_still_blocks_another_write(self):
        result, at = self.acceptance_result()
        state = result['state']
        old = next(e for e in state['effects'].values() if e.get('operation') == 'invite')
        old['status'] = 'running'
        self.assertIsNone(journey._effect(state, 'invite', at, policy=POLICY, list_proof='unlanded'))

    def test_stalled_acceptance_is_reconciled_without_a_new_lead_message(self):
        with patch('retomada.send_hour', return_value=True):
            self.assertTrue(journey.list_proof_due(self.interrupted(), AT + timedelta(minutes=6)))


class InterruptedInvitationServerTests(fixtures.GabinaresseServerTests):
    LEAD = {'conversation': '54457', 'contact': '4457', 'phone': '+5511987654457', 'handle': '@lisaindica5'}
    # The base test hardcodes its own chat ID; it is covered by the base class suite.
    test_registered_lead_is_never_read = None

    def test_worker_recovers_interrupted_delivery_without_webhook_replay(self):
        self.invites[0] = {'status': 'outcome_unknown', 'confirmed': False, 'evidence': {},
                           'reason': 'interrupted_write_reconcile'}
        lead = self.LEAD
        self.say(lead, fixtures.AD)
        self.say(lead, lead['handle'])
        self.drain()
        self.say(lead, 'Pode mandar')
        self.drain()
        self.assertEqual([c[0] for c in self.client.calls].count('invite'), 1)
        self.earlier(6)
        # Advance only the disposable local queue to the already scheduled recovery read.
        with self.repo._connection() as db:
            db.execute("UPDATE real_jobs SET next_run_at='2000-01-01T00:00:00+00:00' "
                       "WHERE conversation_key=? AND operation='relationship' AND status='queued'",
                       ('chatwoot:1:54457',))
        self.drain()
        self.assertEqual([c[0] for c in self.client.calls].count('invite'), 2)
        state = self.repo.load_session('chatwoot:1:54457')
        self.assertEqual(state['cycle']['real_operations']['invite']['status'], 'sent')
        self.assertEqual(state['cycle']['phase'], 'await_acceptance')
        self.assertIn('Seu convite da Amplify foi enviado agora', self.texts(lead)[-1])

    def test_scan_recovers_an_old_stalled_chat_without_new_inbound(self):
        self.invites[0] = {'status': 'outcome_unknown', 'confirmed': False, 'evidence': {},
                           'reason': 'interrupted_write_reconcile'}
        lead = self.LEAD
        self.say(lead, fixtures.AD)
        self.say(lead, lead['handle'])
        self.drain()
        self.say(lead, 'Pode mandar')
        self.drain()
        key = 'chatwoot:1:54457'
        state = self.repo.load_session(key)
        for effect in state['effects'].values():
            if effect.get('operation') == 'relationship' and effect.get('status') == 'pending':
                effect['status'] = 'superseded'
        state['cycle'].pop('acceptance_check', None)
        self.repo.save_session(key, state)
        with self.repo._connection() as db:
            db.execute("UPDATE real_jobs SET status='cancelled' WHERE conversation_key=? "
                       "AND operation='relationship' AND status='queued'", (key,))
        self.earlier(6)
        self.assertEqual(self.run_scan()['status'], 'queued')
        self.drain()
        self.assertEqual([c[0] for c in self.client.calls].count('invite'), 2)
        self.assertEqual(self.repo.load_session(key)['cycle']['real_operations']['invite']['status'], 'sent')


if __name__ == '__main__':
    unittest.main()
