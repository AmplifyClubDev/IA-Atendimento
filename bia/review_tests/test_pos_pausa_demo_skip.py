"""A production-excluded demo must not abort the catch-up scan. Offline only."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from retomada import PosPausa, Decisoes, valid_reason


class DemoSkipScan(unittest.TestCase):
    def make(self):
        now = datetime(2026, 11, 12, 18, tzinfo=timezone.utc)
        sent, examined = [], []
        rows = [{'id': '1', 'last_activity_at': now.isoformat()},
                {'id': '2', 'last_activity_at': now.isoformat()}]
        def http(**kw):
            return {'data': {'payload': rows if kw['url'].endswith('page=1') else []}}
        settings = {'pos_pausa_enabled': True, 'tiktok_mode': 'real', 'real_worker_enabled': True,
                    'conversation_enabled': True,
                    'gate': {'enabled': True, 'account_id': '1', 'inbox_id': '2'}}
        def process(event, **kwargs):
            sent.append(event['conversation_id'])
            return {'status': 'completed'}
        worker = PosPausa(None, settings,
            SimpleNamespace(base_url='https://example.invalid', token='offline-fake', http=http),
            lambda event: {'allowed': True}, process, now=lambda: now)
        worker.monotonic = lambda: 0
        worker.decisions = Decisoes()
        real_candidate = worker._candidate
        def candidate(conversation, *args):
            examined.append(conversation['id'])
            if conversation['id'] == '1':
                # Exercise the actual production exclusion before any profile/history read.
                with patch('retomada.production_blocked', return_value=True):
                    return real_candidate(conversation, *args)
            return {'provider': 'chatwoot', 'account_id': '1', 'message_id': '200',
                    'conversation_id': '2', '_texts': ['offline synthetic hello']}, None
        worker._candidate = candidate
        return worker, sent, examined

    def test_demo_is_skipped_and_next_regular_conversation_is_processed(self):
        worker, sent, examined = self.make()
        result = worker.tick()
        self.assertEqual(result['status'], 'resumed')
        self.assertEqual(examined, ['1', '2'])
        self.assertEqual(sent, ['2'])
        self.assertEqual(result['puladas_por_motivo']['demo_contact_excluded_from_production'], 1)
        self.assertEqual(worker.decisions.for_conversation('1')['pos_pausa']['motivo'],
                         'demo_contact_excluded_from_production')
        self.assertEqual(worker.counts['respondidas'], 1)
        self.assertIsNone(worker._progress)
        self.assertNotIn('1', worker.seen)  # scope exclusions are not cached as permanent

    def test_reason_allowlist_stays_closed(self):
        self.assertTrue(valid_reason('demo_contact_excluded_from_production'))
        self.assertFalse(valid_reason('arbitrary_new_reason'))
        with self.assertRaises(ValueError):
            Decisoes().record('pos_pausa', '1', 'arbitrary_new_reason',
                              datetime(2026, 11, 12, tzinfo=timezone.utc))


if __name__ == '__main__':
    unittest.main()
