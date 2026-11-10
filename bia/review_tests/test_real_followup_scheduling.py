"""Deterministic worker scheduling, synthetic clock/provider and no network."""
import unittest
from datetime import timedelta
from unittest.mock import Mock

from real_operations import RealExecutor
from demo_followup import tick_all
import test_demo_followup as fixtures


class WorkerScheduling(unittest.TestCase):
    setUp = fixtures.Reminders.setUp

    def run_worker(self, statuses, callback=None):
        worker = RealExecutor(Mock(), Mock(), {}, Mock(), Mock(), Mock(), clock=lambda: self.at)
        worker.sessions_checked_at = self.at.isoformat()
        worker.probe_sessions = Mock()
        worker.maintain_retention = Mock()
        worker.followup_tick = Mock()
        worker.demo_followup_tick = callback
        outcomes = iter(statuses)
        worker.tick = Mock(side_effect=lambda: {'status': next(outcomes)})
        waits = []
        def wait(seconds):
            waits.append(seconds)
            self.at += timedelta(seconds=seconds)
            if len(waits) == len(statuses):
                worker.stop_event.set()
        worker.wake_event = Mock()
        worker.wake_event.wait.side_effect = wait
        worker._ownership_file = Mock()
        handle = worker._ownership_file
        worker._run()
        self.assertEqual(waits, [2] * len(statuses))
        handle.close.assert_called_once()
        self.assertIsNone(worker._ownership_file)
        self.assertEqual(worker.followup_tick.call_count, statuses.count('idle'))
        return worker

    def test_busy_queue_checks_followups_each_iteration_without_retention(self):
        callback = Mock()
        worker = self.run_worker(['completed', 'polling'] * 5, callback)
        self.assertEqual(callback.call_count, 10)
        worker.maintain_retention.assert_not_called()

    def test_idle_still_checks_once_and_retains_maintenance(self):
        callback = Mock()
        worker = self.run_worker(['idle'] * 3, callback)
        self.assertEqual(callback.call_count, 3)
        self.assertEqual(worker.maintain_retention.call_count, 3)

    def test_disabled_does_not_start_followups(self):
        callback = Mock()
        worker = self.run_worker(['disabled'] * 3, callback)
        callback.assert_not_called()
        worker.maintain_retention.assert_not_called()

    def test_guarded_or_rejected_job_does_not_starve_other_due_sessions(self):
        callback = Mock()
        self.run_worker(['cancelled', 'poll_limit_reached', 'blocked', 'outcome_unknown',
                         'stale_result', 'human_control_blocked',
                         'application_outcome_unknown', 'result_rejected'], callback)
        self.assertEqual(callback.call_count, 8)

    def test_missing_callback_is_safe(self):
        worker = self.run_worker(['completed', 'idle'])
        self.assertIsNone(worker.last_error)

    def test_callback_failure_keeps_loop_alive_and_is_reported(self):
        callback = Mock(side_effect=RuntimeError('synthetic'))
        worker = self.run_worker(['completed'] * 2, callback)
        self.assertEqual(callback.call_count, 2)
        self.assertEqual(worker.last_error, 'demo_followup_step_unconfirmed')

    def test_demo_failure_does_not_skip_real_followup_on_idle(self):
        worker = self.run_worker(['idle'], Mock(side_effect=RuntimeError('synthetic')))
        worker.followup_tick.assert_called_once()
        self.assertEqual(worker.last_error, 'demo_followup_step_unconfirmed')

    def test_stopping_during_job_skips_demo_hook(self):
        worker = RealExecutor(Mock(), Mock(), {}, Mock(), Mock(), Mock(), clock=lambda: self.at)
        worker.sessions_checked_at = self.at.isoformat()
        worker.demo_followup_tick = Mock()
        def job():
            worker.stop_event.set()
            return {'status': 'completed'}
        worker.tick = job
        worker.wake_event = Mock()
        worker._run()
        worker.demo_followup_tick.assert_not_called()

    def test_busy_queue_delivers_warning_at_300_and_closes_at_600_once(self):
        started = self.at
        deliveries = []
        def callback():
            before = len(self.gateway.sent)
            tick_all(self.router)
            if len(self.gateway.sent) > before:
                deliveries.append(int((self.at - started).total_seconds()))
            closure = self.store.db.execute('SELECT * FROM demo_closures').fetchone()
            if closure:
                self.gateway.preflight.return_value = {'after_message_id': closure['warning_message_id']}
        self.run_worker(['completed', 'polling'] * 156, callback)
        self.assertEqual(deliveries, [300, 600])
        self.assertEqual(len(self.gateway.sent), 3)
        self.assertEqual(len(self.gateway.resolved), 1)
        self.assertEqual(self.store.current(self.router.scope.slot)['step'], 'closed')

    def test_disabled_router_stays_disabled_under_busy_queue(self):
        self.router.followup_enabled = False
        self.run_worker(['completed'] * 310, lambda: tick_all(self.router))
        self.assertEqual(len(self.gateway.sent), 1)
        self.assertEqual(self.gateway.resolved, [])

    def test_new_message_still_cancels_under_busy_queue(self):
        self.gateway.preflight.return_value = {'after_message_id': '999999'}
        self.run_worker(['completed'] * 310, lambda: tick_all(self.router))
        self.assertEqual(len(self.gateway.sent), 1)
        self.assertEqual(self.gateway.resolved, [])


class ServerHookIsolation(unittest.TestCase):
    def make_app(self, enabled):
        import tempfile
        from pathlib import Path
        from repository import Repository
        from server import create_app
        from test_demo_multi_scope import multi_settings
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = multi_settings(directory.name)
        settings['demo_followup_enabled'] = enabled
        repo = Repository(Path(directory.name) / 'production.sqlite3')
        transport = Mock()
        transport.ready.return_value = True
        transport.supports_reply_fencing = False
        app = create_app(settings, repository=repo, transport=transport,
                         real_guard=Mock(return_value={'allowed': True}), real_client=Mock())
        self.addCleanup(app.extensions['v5_demo_router'].store.close)
        return app

    def test_server_separates_demo_and_real_hooks(self):
        from unittest.mock import patch
        with patch('demo_followup.tick_all', return_value=[]) as demo:
            app = self.make_app(True)
            executor = app.extensions['v5_real_executor']
            original_real = executor.followup_tick
            self.assertEqual(original_real, app.extensions['v5_followup_tick'])
            executor.demo_followup_tick()
            demo.assert_called_once_with(app.extensions['v5_demo_router'])
            self.assertEqual(executor.followup_tick, original_real)

    def test_server_disabled_feature_leaves_demo_hook_unset(self):
        executor = self.make_app(False).extensions['v5_real_executor']
        self.assertIsNone(executor.demo_followup_tick)
