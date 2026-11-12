"""Independent concurrency and readiness checks; synthetic identities, no I/O providers."""
import threading
import unittest
from unittest.mock import Mock
import test_demo_real_bridge as fixtures
from server import create_app


class IndependentBridgeReview(unittest.TestCase):
    setUp = fixtures.Cases.setUp

    def test_concurrent_join_next_inbound_and_worker_guard_do_not_deadlock(self):
        entered, release = threading.Event(), threading.Event()
        errors, processed = [], []
        def process(ev):
            if ev['message_id'] == '101':
                entered.set()
                if not release.wait(2):
                    raise AssertionError('test release timed out')
            processed.append(ev['message_id'])
            return {'accepted': True, 'status': 'synthetic'}, 200
        self.runtime.extensions['v5_process_inbound'] = process
        def invoke(ev, begin=False):
            try:
                self.bridge.dispatch(self.router, ev, begin=begin)
            except Exception as exc:
                errors.append(exc)
        join = threading.Thread(target=invoke, args=(fixtures.event(), True), daemon=True)
        join.start()
        self.assertTrue(entered.wait(2))
        second = threading.Thread(target=invoke, args=(fixtures.event(message_id='102'),), daemon=True)
        second.start()
        guard_result = []
        guard = threading.Thread(target=lambda: guard_result.append(self.bridge.authorized_event(fixtures.event())), daemon=True)
        guard.start(); guard.join(2)
        release.set()
        join.join(2); second.join(2)
        self.assertFalse(guard.is_alive(), 'worker guard blocked by runtime call')
        self.assertFalse(join.is_alive(), 'join deadlocked')
        self.assertFalse(second.is_alive(), 'second inbound deadlocked')
        self.assertFalse(errors)
        self.assertEqual(guard_result, [True])
        self.assertEqual(processed, ['101', '102'])

    def test_child_readiness_requires_worker_and_sessions_together(self):
        executor = self.runtime.extensions['v5_real_executor']
        for running, sessions in ((False,False),(False,True),(True,False),(True,True)):
            executor.status.return_value = {'worker_running': running, 'sessions': {'ready':sessions}}
            status = self.bridge.status()
            self.assertEqual(status['ready'], running and sessions)
            self.assertEqual(status['selected_count'], 1)

    def test_parent_ready_reports_child_failure_without_exposing_contact(self):
        settings = {**self.settings, 'demo_enabled': False, 'demo_real_enabled':False}
        for key in ('demo_scope','demo_scopes','demo_pending_scope'):
            settings.pop(key, None)
        app = create_app(settings=settings)
        app.extensions['v5_demo_real_bridge'] = Mock(status=lambda: {'enabled':True,'ready':False,'worker_running':False,'sessions_ready':False,'selected_count':1})
        result = app.test_client().get('/ready')
        self.assertEqual(result.status_code,503)
        self.assertIn('demo_real_not_ready',result.json['issues'])
        self.assertNotIn(fixtures.PHONE,result.get_data(as_text=True))
