"""Recover uncertain LOCAL read applications by a fresh read, never a write."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import test_real_executor as fixtures


class RecoveryReadJobTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExecutorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.repository = self.fixture.repository
        self.at = (fixtures.NOW + timedelta(seconds=1)).isoformat()

    def uncertain(self, operation='relationship'):
        job = self.fixture.enqueue(operation)
        running = self.repository.claim_real_job(fixtures.NOW.isoformat())
        result = {'operation': operation, 'creator': 'alice', 'status': 'linked' if operation == 'relationship' else 'eligible',
                  'confirmed': True, 'observed_at': fixtures.NOW.isoformat(), 'evidence': {'exact': True}}
        self.repository.set_real_result(job['job_key'], result, fixtures.NOW.isoformat())
        key = job['job_key'] + ':result:' + job['effect_id'] + ':' + str(running['attempts'])
        signature = self.fixture.executor(fixtures.FakeClient())._signature(result)
        self.repository.reserve_event(key, fixtures.CONV, signature)
        self.repository.finish_real_job(job['job_key'], 'outcome_unknown', fixtures.NOW.isoformat())
        return job, key

    def test_pending_unknown_read_is_requeued_once_without_changing_business_state(self):
        job, application = self.uncertain()
        before = self.repository.load_session(fixtures.CONV)
        summary = self.repository.recover_real_jobs(self.at)
        after = self.repository.real_job(job['job_key'])
        self.assertEqual(summary, {'requeued_reads': 1, 'interrupted_writes': 0})
        self.assertEqual(after['status'], 'queued')
        self.assertEqual(after['attempts'], 1)
        self.assertIsNone(after['result'])
        self.assertIsNone(after['last_signature'])
        self.assertEqual(self.repository.load_session(fixtures.CONV), before)
        self.assertEqual(self.repository.event(application)['status'], 'outcome_unknown')
        self.assertEqual(self.repository.outbox(application), [])
        self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)

    def test_recovered_read_gets_fresh_result_and_new_attempt_application(self):
        job, prior_application = self.uncertain()
        self.repository.recover_real_jobs(self.at)
        self.fixture.now = fixtures.NOW + timedelta(seconds=2)
        fresh = {'operation': 'relationship', 'creator': 'alice', 'status': 'linked', 'confirmed': True,
                 'observed_at': self.fixture.now.isoformat(), 'evidence': {'fresh': True, 'exact': True}}
        client = fixtures.FakeClient(fresh)
        outcome = self.fixture.executor(client).tick()
        self.assertEqual(outcome['status'], 'completed')
        self.assertEqual([call[0] for call in client.calls], ['relationship'])
        recovered = self.repository.real_job(job['job_key'])
        self.assertEqual(recovered['attempts'], 2)
        self.assertEqual(recovered['effect_id'], job['effect_id'])
        self.assertEqual(recovered['result']['observed_at'], fresh['observed_at'])
        self.assertEqual(self.repository.event(prior_application)['status'], 'outcome_unknown')
        new_application = job['job_key'] + ':result:' + job['effect_id'] + ':2'
        self.assertEqual(self.repository.event(new_application)['status'], 'completed')

    def test_invitation_unknown_and_cancelled_reads_never_requeue(self):
        job, _ = self.uncertain('invite')
        self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)
        self.assertEqual(self.repository.real_job(job['job_key'])['status'], 'outcome_unknown')
        with self.repository._connection() as db:
            db.execute("UPDATE real_jobs SET operation='relationship',status='cancelled' WHERE job_key=?", (job['job_key'],))
        self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)

    def test_any_created_reply_outbox_preserves_uncertainty_without_repeating(self):
        job, application = self.uncertain()
        state = self.repository.load_session(fixtures.CONV)
        self.repository.prepare_reply(application, fixtures.CONV, state, application + ':reply', {'text': 'already attempted'})
        self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)
        self.assertEqual(self.repository.real_job(job['job_key'])['status'], 'outcome_unknown')
        self.assertEqual(self.repository.outbox(application)[0]['status'], 'outcome_unknown')

    def test_application_event_must_exist_match_conversation_and_remain_unknown(self):
        job, application = self.uncertain()
        self.repository.finish_event(application, 'completed')
        self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)
        with self.repository._connection() as db:
            db.execute("UPDATE inbound_events SET status='outcome_unknown',conversation_key='chatwoot:1:other' WHERE event_key=?", (application,))
        self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)
        with self.repository._connection() as db:
            db.execute('DELETE FROM inbound_events WHERE event_key=?', (application,))
        self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)
        self.assertEqual(self.repository.real_job(job['job_key'])['status'], 'outcome_unknown')

    def test_same_cycle_profile_effect_payload_and_open_window_are_required(self):
        job, _ = self.uncertain()
        original = self.repository.load_session(fixtures.CONV)
        mutations = [lambda s: s['cycle'].update(status='closed'),
                     lambda s: s['cycle'].update(expires_at=fixtures.NOW.isoformat()),
                     lambda s: s['cycle'].update(mode='simulated'),
                     lambda s: s['cycle'].update(id='other-cycle'),
                     lambda s: s['cycle']['facts'].update(tiktok_declarado='@other'),
                     lambda s: s.update(human_control=True),
                     lambda s: s['cycle'].update(qualification_paused=True),
                     lambda s: s['cycle'].update(pending_profile_changes={'tiktok_declarado': '@other'}),
                     lambda s: s['effects'][job['effect_id']].update(status='done'),
                     lambda s: s['effects'][job['effect_id']].update(creator='@other'),
                     lambda s: s['effects'][job['effect_id']].update(payload={'other': True})]
        for mutate in mutations:
            state = deepcopy(original)
            mutate(state)
            self.repository.save_session(fixtures.CONV, state)
            self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)
            self.assertEqual(self.repository.real_job(job['job_key'])['status'], 'outcome_unknown')

    def test_malformed_or_wrong_operation_result_is_not_reused(self):
        job, _ = self.uncertain()
        for raw in ('null', '[]', '{"operation":"invite","creator":"alice"}', '{"operation":"relationship","creator":"other"}'):
            with self.repository._connection() as db:
                db.execute('UPDATE real_jobs SET result_json=? WHERE job_key=?', (raw, job['job_key']))
            self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)

    def test_six_attempt_budget_never_resets(self):
        job, old_application = self.uncertain()
        # This fixture represents the fifth failed local application.
        with self.repository._connection() as db:
            db.execute('UPDATE real_jobs SET attempts=5 WHERE job_key=?', (job['job_key'],))
        fifth = job['job_key'] + ':result:' + job['effect_id'] + ':5'
        self.repository.reserve_event(fifth, fixtures.CONV, 'fixture-fifth')
        self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 1)
        self.fixture.now = fixtures.NOW + timedelta(seconds=2)
        executor = self.fixture.executor(fixtures.FakeClient({'operation': 'relationship', 'creator': 'alice',
            'status': 'linked', 'confirmed': True, 'observed_at': fixtures.NOW.isoformat(), 'evidence': {'fresh': True}}))
        def local_failure(*args):
            raise RuntimeError('local_application_failed')
        executor.apply_result = local_failure
        self.assertEqual(executor.tick()['status'], 'application_outcome_unknown')
        self.assertEqual(self.repository.real_job(job['job_key'])['attempts'], 6)
        self.assertEqual(self.repository.recover_real_jobs(self.at)['requeued_reads'], 0)
        self.assertEqual(self.repository.event(old_application)['status'], 'outcome_unknown')

    def test_fresh_guard_still_blocks_after_startup_requeue(self):
        job, _ = self.uncertain()
        self.repository.recover_real_jobs(self.at)
        self.fixture.guard_allowed = False
        self.fixture.now = fixtures.NOW + timedelta(seconds=2)
        client = fixtures.FakeClient()
        self.assertEqual(self.fixture.executor(client).tick()['status'], 'cancelled')
        self.assertEqual(client.calls, [])
        self.assertEqual(self.repository.real_job(job['job_key'])['attempts'], 2)

    def test_interrupted_invite_is_still_unknown_and_summary_is_nonidentifying(self):
        job = self.fixture.enqueue('invite')
        self.repository.claim_real_job(fixtures.NOW.isoformat())
        summary = self.repository.recover_real_jobs(self.at)
        self.assertEqual(summary, {'requeued_reads': 0, 'interrupted_writes': 1})
        self.assertEqual(self.repository.real_job(job['job_key'])['status'], 'result_ready')
        self.assertEqual(self.repository.real_job(job['job_key'])['result']['status'], 'outcome_unknown')


if __name__ == '__main__':
    unittest.main()
