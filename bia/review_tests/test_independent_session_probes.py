"""Authenticated read probes never run a second operational job."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import unittest
from real_operations import RealExecutor

class ProbeConcurrency(unittest.TestCase):
    def test_real_job_block_does_not_block_authenticated_probes_or_hide_step_age(self):
        with TemporaryDirectory() as folder:
            now=[datetime(2026,11,12,20,tzinfo=timezone.utc)]
            job_started=threading.Event(); release_job=threading.Event(); second_probe=threading.Event()
            calls=[]; jobs=[]
            class Client:
                def configuration(self,*args):return {'configured':True}
                def _ready(self,role):
                    calls.append(role)
                    if len(calls)>=6:second_probe.set()
            repo=SimpleNamespace(recover_real_jobs=lambda at:{})
            executor=RealExecutor(repo,Client(),{'tiktok_mode':'real','real_worker_enabled':True,
                'state_dir':folder},lambda _:threading.RLock(),lambda _:{'allowed':True},lambda *_:None,
                clock=lambda:now[0])
            def job():
                jobs.append('one');job_started.set();release_job.wait(5);return {'status':'completed'}
            executor.tick=job
            try:
                self.assertTrue(executor.start());self.assertTrue(job_started.wait(2))
                self.assertFalse(executor.start())
                now[0]+=timedelta(seconds=100)
                self.assertTrue(second_probe.wait(3))
                state=executor.status()
                self.assertTrue(state['sessions']['ready'])
                self.assertEqual(state['worker_step'],'real_job')
                self.assertEqual(state['worker_step_elapsed_seconds'],100)
                self.assertTrue(state['session_probe_running'])
                self.assertEqual(jobs,['one'])
                self.assertEqual(set(calls),{'precheck','agency','invites'})
            finally:
                executor.stop();release_job.set()
                executor.thread.join(3);executor.probe_thread.join(3)
            self.assertFalse(executor.thread.is_alive());self.assertFalse(executor.probe_thread.is_alive())
    def test_probe_failure_does_not_extend_or_invent_success(self):
        now=[datetime(2026,11,12,20,tzinfo=timezone.utc)]
        class Client:
            def configuration(self,*args):return {'configured':True}
            def _ready(self,role):raise RuntimeError('not a proof')
        executor=RealExecutor(None,Client(),{'tiktok_mode':'real'},None,None,None,clock=lambda:now[0])
        executor.probe_sessions()
        self.assertFalse(executor.status()['sessions']['ready'])
        executor.session_checks={role:{'ready':True} for role in ('precheck','agency','invites')}
        now[0]+=timedelta(seconds=61)
        self.assertFalse(executor.status()['sessions']['fresh'])
        self.assertFalse(executor.status()['sessions']['ready'])
    def test_unexpected_worker_exit_stops_probe_and_releases_ownership(self):
        with TemporaryDirectory() as folder:
            class Client:
                def configuration(self,*args):return {'configured':True}
                def _ready(self,role):return None
            executor=RealExecutor(SimpleNamespace(recover_real_jobs=lambda _:{}),Client(),
                {'tiktok_mode':'real','real_worker_enabled':True,'state_dir':folder},None,None,None)
            def exit_job():raise SystemExit()
            executor.tick=exit_job
            self.assertTrue(executor.start())
            executor.thread.join(3);executor.probe_thread.join(3)
            self.assertTrue(executor.stop_event.is_set())
            self.assertFalse(executor.probe_thread.is_alive())
            self.assertIsNone(executor._ownership_file)
    def test_thread_start_failure_cleans_probe_and_lock(self):
        from unittest.mock import patch
        real_thread=threading.Thread
        with TemporaryDirectory() as folder:
            class Client:
                def configuration(self,*args):return {'configured':True}
                def _ready(self,role):return None
            executor=RealExecutor(SimpleNamespace(recover_real_jobs=lambda _:{}),Client(),
                {'tiktok_mode':'real','real_worker_enabled':True,'state_dir':folder},None,None,None)
            class Fails:
                def start(self):raise RuntimeError('synthetic startup failure')
                def is_alive(self):return False
            def factory(*args,**kwargs):
                return Fails() if kwargs.get('name')=='v5-real-operations' else real_thread(*args,**kwargs)
            with patch('real_operations.threading.Thread',side_effect=factory):
                self.assertFalse(executor.start())
            self.assertTrue(executor.stop_event.is_set())
            self.assertFalse(executor.probe_thread.is_alive())
            self.assertIsNone(executor._ownership_file)
