"""Operational failures remain visible without exposing provider payloads."""
import unittest
from unittest.mock import patch

from tests import test_real_executor as fixtures


class WorkerDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExecutorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_application_failure_reports_safe_reason_and_never_logs_payload(self):
        job = self.fixture.enqueue('relationship')
        executor = self.fixture.executor(fixtures.FakeClient())
        executor.apply_result = lambda *_: (_ for _ in ()).throw(RuntimeError('secret-token-and-full-provider-body'))
        with self.assertLogs('real_operations', level='WARNING') as captured:
            self.assertEqual(executor.tick()['status'], 'application_outcome_unknown')
        logs = ' '.join(captured.output)
        self.assertIn('operation=relationship', logs)
        self.assertIn('error_type=RuntimeError', logs)
        self.assertNotIn('secret-token', logs)
        self.assertNotIn('alice', logs)
        self.assertEqual(executor.status()['last_error'], 'result_application_unconfirmed')
        self.assertEqual(self.fixture.repository.real_job(job['job_key'])['status'], 'outcome_unknown')
        self.assertEqual(executor.tick()['status'], 'idle')
        self.assertEqual(executor.status()['last_error'], 'result_application_unconfirmed')

    def test_worker_does_not_clear_application_failure_while_idle(self):
        executor = self.fixture.executor(fixtures.FakeClient())
        executor.sessions_checked_at = fixtures.NOW.isoformat()
        executor.last_error = 'result_application_unconfirmed'
        def tick():
            executor.stop_event.set()
            return {'status': 'idle'}
        with patch.object(executor, 'tick', side_effect=tick), patch.object(executor.wake_event, 'wait'):
            executor._run()
        self.assertEqual(executor.last_error, 'result_application_unconfirmed')

    def test_successful_settlement_clears_previous_worker_error(self):
        executor = self.fixture.executor(fixtures.FakeClient())
        executor.sessions_checked_at = fixtures.NOW.isoformat()
        executor.last_error = 'result_application_unconfirmed'
        def tick():
            executor.stop_event.set()
            return {'status': 'completed'}
        with patch.object(executor, 'tick', side_effect=tick), patch.object(executor.wake_event, 'wait'):
            executor._run()
        self.assertIsNone(executor.last_error)
