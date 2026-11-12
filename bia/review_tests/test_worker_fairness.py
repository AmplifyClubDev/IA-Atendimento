"""Deterministic no-network bounded maintenance and real-job fairness tests."""
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from retomada import Retomada
from reconferencia import Reconferencia
from real_operations import RealExecutor

NOW = datetime(2026, 11, 12, 18, tzinfo=timezone.utc)
BASE = {'tiktok_mode': 'real', 'real_worker_enabled': True, 'conversation_enabled': True, 'gate': {'enabled': True}}

class FairnessTests(unittest.TestCase):
    def test_retomada_yields_and_eventually_visits_every_contact_once(self):
        ids = ['chatwoot:1:' + str(i) for i in range(103)]
        seconds, seen = [0], []
        obj = Retomada(SimpleNamespace(followup_conversations=lambda: ids),
            {**BASE, 'retomada_enabled': True}, None, None, None,
            now=lambda: NOW + timedelta(seconds=seconds[0]))
        obj.monotonic = lambda: seconds[0]
        def visit(conv, now):
            seen.append(conv); seconds[0] += 3
            return {'status': 'idle', 'motivo': 'sem_atendimento'}
        obj._conversation = visit
        batches = []
        for _ in range(40):
            result = obj.tick(); batches.append(result)
            if result['status'] == 'completed': break
        self.assertEqual(seen, ids)
        self.assertGreater(len(batches), 20)
        self.assertTrue(all(x['processed_in_batch'] <= 4 for x in batches))
        self.assertEqual(result['puladas_por_motivo']['sem_atendimento'], 103)
        self.assertEqual(obj.tick()['status'], 'cooldown')

    def test_retomada_count_budget_and_failed_item_do_not_starve_tail(self):
        ids = [str(i) for i in range(70)]
        obj = Retomada(SimpleNamespace(followup_conversations=lambda: ids),
            {**BASE, 'retomada_enabled': True}, None, None, None, now=lambda: NOW)
        seen = []
        def visit(conv, _):
            seen.append(conv)
            if conv == '1': raise ValueError('fixture failure')
            return {'status': 'idle', 'motivo': 'sem_atendimento'}
        obj._conversation = visit
        self.assertEqual(obj.tick()['processed_in_batch'], 25)
        self.assertEqual(obj.tick()['processed_in_batch'], 25)
        self.assertEqual(obj.tick()['status'], 'completed')
        self.assertEqual(seen, ids)

    def test_reconferencia_batches_preserve_one_queued_job_per_complete_scan(self):
        rows = [{'conversation': 'chatwoot:1:' + str(i), 'reason': 'offline', 'forced': False}
                for i in range(80)]
        calls = []
        subject = Reconferencia(SimpleNamespace(precheck_conversations=lambda: [r['conversation'] for r in rows]),
            {**BASE, 'reconferencia_enabled': True}, lambda _: True,
            lambda conv, *args, **kwargs: calls.append(conv) or {'status': 'queued'}, now=lambda: NOW)
        with patch('reconferencia.candidates', return_value=rows):
            for _ in range(5):
                result = subject.tick()
                if result['status'] != 'scanning': break
        self.assertEqual(result['status'], 'queued')
        self.assertEqual(calls, ['chatwoot:1:0'])
        self.assertEqual(result['puladas_por_motivo']['outro_lead_nesta_varredura'], 79)

    def test_worker_rechecks_jobs_between_maintenance_slices_and_probes_stay_fresh(self):
        seconds, checks, jobs, maintenance = [0], [], [], []
        stop = threading.Event()
        worker = SimpleNamespace(stop_event=stop, sessions_checked_at=NOW.isoformat(),
            clock=lambda: NOW + timedelta(seconds=seconds[0]), _ownership_file=None,
            demo_followup_tick=None, last_error=None)
        def probe():
            checks.append(seconds[0]); worker.sessions_checked_at=worker.clock().isoformat()
        def tick():
            jobs.append(seconds[0]); return {'status': 'idle'}
        def batch():
            maintenance.append(seconds[0]); seconds[0] += 10
        def wait(_):
            seconds[0] += 2
            if len(jobs) == 12: stop.set()
        worker.probe_sessions=probe; worker.tick=tick
        worker.maintain_retention=lambda: None; worker.followup_tick=batch
        worker.wake_event=SimpleNamespace(wait=wait, clear=lambda: None)
        RealExecutor._run(worker)
        self.assertEqual(len(jobs), 12)
        self.assertEqual(len(maintenance), 12)
        self.assertTrue(checks)
        self.assertLessEqual(max(b-a for a,b in zip([0]+checks,checks+[seconds[0]])), 36)
        self.assertTrue(all(b-a <= 12 for a,b in zip(jobs,jobs[1:])))

if __name__ == '__main__': unittest.main()
