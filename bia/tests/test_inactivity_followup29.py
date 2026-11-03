"""Fake-clock 5+5 pilot pauses; all transports and callbacks are local fakes."""
from copy import deepcopy
from datetime import timedelta
import unittest

from followup import Followup, CONVERSATION, sequence_keys
from tests import test_followup as fixtures


class InactivityFollowup29Tests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.FollowupTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.f = fixture
        fixture.settings.update(inactivity_close_enabled=True, inactivity_close_delay_seconds='300')
        self.closed = []
        self.callback_failure = False
        def close(event, cycle_id, source_key, warning_key, closure_key, *, now):
            if self.callback_failure:
                raise RuntimeError('local callback interrupted')
            state = fixture.repo.load_session(CONVERSATION)
            if state['cycle']['id'] != cycle_id or state['processed_inbound'][-1] != source_key:
                return {'status': 'stale'}
            self.closed.append((cycle_id, source_key, warning_key, closure_key, now))
            state['cycle'].update(status='closed', reason='inactivity_timeout', closed_at=now.isoformat(),
                inactivity_closure={'source_key':source_key, 'warning_key':warning_key, 'closure_key':closure_key})
            fixture.repo.save_session(CONVERSATION, state)
            return {'status': 'closed'}
        self.close = close
        self.make_followup()

    def make_followup(self, **kwargs):
        f = self.f
        f.followup = Followup(f.repo, f.settings, f.transport, lambda _: f.lock,
            lambda _: f.guard_result, now=lambda: f.now, close_for_inactivity=kwargs.get('callback', self.close))
        return f.followup

    def warn(self):
        result = self.f.followup.tick()
        self.assertEqual(result, {'status': 'accepted', 'stage': 'warning'})
        self.assertEqual(len(self.f.transport.sent), 1)
        return sequence_keys(self.f.state['cycle']['id'], self.f.event['source_ref'])

    def test_before_five_minutes_no_warning_or_provider_read(self):
        self.f.now -= timedelta(microseconds=1)
        self.assertEqual(self.f.followup.tick()['status'], 'idle')
        self.assertEqual(self.f.transport.sent, [])
        self.assertEqual(self.f.transport.reads, [])

    def test_warning_has_two_real_actions_and_durable_source_bound_accepted_time(self):
        before = self.f.repo.load_session(CONVERSATION)
        warning, closure = self.warn()
        sent = self.f.transport.sent[0]
        self.assertEqual(sent['buttons'], ['Seguir atendimento', 'Encerrar agora'])
        self.assertEqual(sent['text'].count('?'), 1)
        self.assertLess(len(sent['text']), 350)
        self.assertIn('sem resposta por mais 5 minutos', sent['text'])
        receipt = self.f.repo.get_operation(warning)['result']
        self.assertEqual(receipt['accepted_at'], self.f.now.isoformat())
        self.assertEqual(receipt['source_key'], 'chatwoot:1:777')
        self.assertEqual(receipt['cycle_id'], self.f.state['cycle']['id'])
        self.assertEqual(self.f.repo.load_session(CONVERSATION), before)
        self.assertIsNone(self.f.repo.get_operation(closure))

    def test_close_waits_five_additional_minutes_from_accepted_warning(self):
        self.warn()
        self.f.now += timedelta(seconds=300, microseconds=-1)
        self.assertEqual(self.f.followup.tick()['status'], 'awaiting_close')
        self.assertEqual(self.closed, [])
        self.assertEqual(len(self.f.transport.sent), 1)

    def test_exact_five_plus_five_sends_closure_once_and_closes_via_callback(self):
        warning, closure = self.warn()
        self.f.now += timedelta(seconds=300)
        self.assertEqual(self.f.followup.tick()['status'], 'closed')
        self.assertEqual(len(self.f.transport.sent), 2)
        self.assertEqual(self.f.transport.sent[1]['key'], closure)
        self.assertEqual(self.f.transport.sent[1]['buttons'], [])
        self.assertIn('encerrei', self.f.transport.sent[1]['text'])
        self.assertEqual(len(self.closed), 1)
        self.assertEqual(self.closed[0][:4], (self.f.state['cycle']['id'], 'chatwoot:1:777', warning, closure))
        self.assertEqual(self.f.repo.load_session(CONVERSATION)['cycle']['status'], 'closed')

    def test_slow_warning_acceptance_moves_closure_deadline_not_lead_clock(self):
        initial = self.f.now
        def delay():
            self.f.now += timedelta(seconds=20)
        self.f.transport.before_send = delay
        warning, _ = self.warn()
        self.f.transport.before_send = None
        self.assertEqual(self.f.repo.get_operation(warning)['result']['accepted_at'], self.f.now.isoformat())
        self.f.now = initial + timedelta(seconds=300)
        self.assertEqual(self.f.followup.tick()['status'], 'awaiting_close')
        self.f.now += timedelta(seconds=20)
        self.assertEqual(self.f.followup.tick()['status'], 'closed')

    def test_new_worker_and_duplicate_ticks_do_not_repeat_warning_or_closure(self):
        self.warn()
        self.make_followup()
        self.assertEqual(self.f.followup.tick()['status'], 'awaiting_close')
        self.f.now += timedelta(seconds=300)
        self.f.followup.tick()
        read_count = len(self.f.transport.reads)
        self.f.followup.tick()
        self.make_followup().tick()
        self.assertEqual(len(self.f.transport.sent), 2)
        self.assertEqual(len(self.f.transport.reads), read_count)
        self.assertEqual(len(self.closed), 1)

    def test_new_provider_inbound_before_warning_blocks_it(self):
        message = deepcopy(self.f.transport.messages[0]); message['id'] = 800
        self.f.transport.messages.append(message)
        self.assertEqual(self.f.followup.tick()['status'], 'source_changed')
        self.assertEqual(self.f.transport.sent, [])

    def test_new_provider_inbound_after_warning_cancels_closure_without_replay(self):
        self.warn()
        message = deepcopy(self.f.transport.messages[0]); message['id'] = 800
        self.f.transport.messages.append(message)
        self.f.now += timedelta(seconds=300)
        self.assertEqual(self.f.followup.tick()['status'], 'source_changed')
        self.assertEqual(self.closed, [])
        self.assertEqual(len(self.f.transport.sent), 1)

    def test_processed_new_inbound_rearms_a_distinct_pause_in_same_cycle(self):
        first_warning, _ = self.warn()
        f = self.f
        f.now += timedelta(seconds=20)
        event = {**f.event, 'message_id': '888', 'source_ref': 'chatwoot:1:888', 'created_at': f.now.isoformat()}
        state = f.repo.load_session(CONVERSATION)
        state['revision'] += 1; state['processed_inbound'].append(event['source_ref'])
        state['cycle'].update(last_inbound_at=f.now.isoformat(), expires_at=(f.now+timedelta(hours=24)).isoformat())
        state['contact_sync_proof'].update(event_id=event['source_ref'], revision=state['revision'])
        f.repo.reserve_event(event['source_ref'], CONVERSATION, 'new-source')
        f.repo.reserve_operation(event['source_ref']+':contact:4', event['source_ref'], 'contact_sync')
        f.repo.complete_operation(event['source_ref']+':contact:4', state['contact_sync_proof'])
        f.repo.prepare_reply(event['source_ref'], CONVERSATION, state, 'second-reply', {'text':'Qual é seu @?', 'buttons':[]})
        f.repo.finish_outbox('second-reply', 'accepted', {'status':'accepted','message_id':'889'})
        with f.repo._connection() as db:
            db.execute('UPDATE outbox SET updated_at=? WHERE outbox_key=?', (f.now.isoformat(), 'second-reply'))
        f.repo.finish_event(event['source_ref'], 'completed')
        self.assertTrue(f.repo.remember_followup_source(CONVERSATION, event, state))
        f.transport.messages = [fixtures.FakeTransport.message(event)]
        f.now += timedelta(seconds=300)
        self.assertEqual(f.followup.tick()['stage'], 'warning')
        self.assertEqual(len(f.transport.sent), 2)
        self.assertNotEqual(f.transport.sent[1]['key'], first_warning)
        self.assertEqual(self.closed, [])

    def test_failed_warning_never_arms_closure_or_retries(self):
        self.f.transport.receipt = {'status':'failed','reason':'provider_rejected'}
        self.f.followup.tick()
        self.f.now += timedelta(minutes=10)
        self.f.followup.tick()
        self.assertEqual(len(self.f.transport.sent), 1)
        self.assertEqual(self.closed, [])

    def test_unknown_warning_never_arms_closure_or_retries(self):
        self.f.transport.receipt = {'status':'outcome_unknown','reason':'lost_ack'}
        self.f.followup.tick()
        self.f.now += timedelta(minutes=10)
        self.make_followup().tick()
        self.assertEqual(len(self.f.transport.sent), 1)
        self.assertEqual(self.closed, [])

    def test_unknown_closure_is_not_retried_or_projected(self):
        self.warn()
        self.f.transport.receipt = {'status':'outcome_unknown','reason':'lost_ack'}
        self.f.now += timedelta(seconds=300)
        self.f.followup.tick()
        self.make_followup().tick()
        self.assertEqual(len(self.f.transport.sent), 2)
        self.assertEqual(self.closed, [])

    def test_failed_closure_is_not_retried_or_projected(self):
        self.warn()
        self.f.transport.receipt = {'status':'failed','reason':'provider_rejected'}
        self.f.now += timedelta(seconds=300)
        self.f.followup.tick()
        self.f.followup.tick()
        self.assertEqual(len(self.f.transport.sent), 2)
        self.assertEqual(self.closed, [])

    def test_callback_interruption_reconciles_accepted_closure_without_resending(self):
        self.warn()
        self.f.now += timedelta(seconds=300)
        self.callback_failure = True
        self.assertEqual(self.f.followup.tick()['status'], 'unconfirmed')
        self.callback_failure = False
        self.assertEqual(self.make_followup().tick()['status'], 'closed')
        self.assertEqual(len(self.f.transport.sent), 2)
        self.assertEqual(len(self.closed), 1)

    def test_human_control_or_new_message_at_last_moment_prevents_closure_post(self):
        self.warn()
        self.f.now += timedelta(seconds=300)
        def human():
            self.f.guard_result = {'allowed':False,'reason':'human_control'}
        self.f.transport.before_send = human
        self.assertEqual(self.f.followup.tick()['status'], 'failed')
        self.assertEqual(len(self.f.transport.sent), 1)
        self.assertEqual(self.closed, [])

    def test_intro_gets_neutral_warning_without_presuming_agency_interest(self):
        self.f.state['cycle']['phase'] = 'intro'; self.f.save()
        self.warn()
        self.assertIn('conhecendo a Amplify', self.f.transport.sent[0]['text'])
        self.assertNotIn('seu agenciamento', self.f.transport.sent[0]['text'])

    def test_baseline_still_blocks_old_inputs(self):
        self.f.settings['followup_start_at'] = self.f.source_at.isoformat()
        self.assertEqual(self.f.followup.tick()['status'], 'idle')
        self.assertEqual(self.f.transport.sent, [])

    def test_provider_unknown_state_does_not_become_timeout(self):
        self.f.state['effects'] = {'pending':{'cycle_id':'cycle','status':'outcome_unknown'}}
        self.f.save()
        self.f.followup.tick()
        self.assertEqual(self.f.transport.sent, [])
        self.assertEqual(self.closed, [])

    def test_no_close_callback_means_no_partial_new_mode(self):
        self.make_followup(callback=None).tick()
        self.assertEqual(self.f.transport.sent, [])

    def test_legacy_reminder_key_never_counts_as_new_warning_proof(self):
        import hashlib
        key = 'followup:'+hashlib.sha256(('pilot-followup-v1:'+self.f.state['cycle']['id']).encode()).hexdigest()
        self.f.repo.reserve_operation(key, 'chatwoot:1:777', 'followup')
        self.f.repo.complete_operation(key, {'status':'accepted','message_id':'700'})
        self.warn()
        self.assertEqual(self.closed, [])


if __name__ == '__main__':
    unittest.main()
