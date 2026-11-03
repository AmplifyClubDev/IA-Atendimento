"""Real SQLite, fixed clocks and fake providers. No network or user data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repository import Repository
from real_operations import RealExecutor
from retention import fingerprint
from gateway import Gateway, SubmissionUnknown
from engine import _open
from forms import FormStore

NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=40)
CONV = 'chatwoot:1:88'
EVENT = 'chatwoot:1:777'


def cleanup_receipt(**updates):
    value = {'status': 'completed', 'technical_deleted': 0, 'summaries_deleted': 0, 'total_deleted': 0,
             'has_more': False, 'detail_cutoff': (NOW - timedelta(days=30)).isoformat(),
             'summary_cutoff': (NOW - timedelta(days=90)).isoformat()}
    value.update(updates)
    return value


def clean_counts(**updates):
    return {key: value for key, value in cleanup_receipt(**updates).items()
            if key in {'technical_deleted', 'summaries_deleted', 'total_deleted', 'has_more'}}


class RetentionTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2]
        self.tmp = tempfile.TemporaryDirectory(dir=root, prefix='retention-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.repository = Repository(Path(self.tmp.name) / 'state.sqlite3')
        self.state = {'schema_version': 1, 'session_id': 's', 'creator_id': 'stable-person-id',
                      'revision': 6, 'cycle': {'id': 'c', 'number': 7, 'status': 'expired',
                      'mode': 'real', 'phase': 'qualification', 'reason': '24h_since_last_inbound',
                      'closed_at': OLD.isoformat(), 'opened_at': (OLD - timedelta(days=1)).isoformat(),
                      'expires_at': OLD.isoformat(), 'facts': {'tiktok_declarado': '@private', 'nome_declarado': 'Name'}},
                      'closed_cycles': [], 'history': [{'cycle_id': 'c', 'text': 'private transcript'}],
                      'effects': {}, 'processed_inbound': [EVENT], 'observations': {}}
        self.seed(self.state)

    def seed(self, state, at=OLD, conversation=CONV, event=EVENT):
        with patch('repository._now', return_value=at.isoformat()):
            self.repository.save_session(conversation, state)
            self.repository.reserve_event(event, conversation, 'digest', source_at=at.isoformat())
            self.repository.reserve_operation(event + ':conversation', event, 'conversation_turn')
            self.repository.complete_operation(event + ':conversation', {'text': 'private reply'})
            self.repository.prepare_reply(event, conversation, state, event + ':reply', {'text': 'private reply'})
            self.repository.finish_outbox(event + ':reply', 'accepted', {'accepted': True})
            self.repository.finish_event(event, 'completed')

    def sweep(self, **kwargs):
        return self.repository.retention_pass(NOW.isoformat(), **kwargs)

    def count(self, table):
        with self.repository._connection() as db:
            return db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def change(self, table, **values):
        with self.repository._connection() as db:
            db.execute('UPDATE ' + table + ' SET ' + ','.join(key + '=?' for key in values), tuple(values.values()))

    def test_compacts_after_30_days_in_fk_order(self):
        result = self.sweep()
        self.assertEqual((result['compacted'], result['events_deleted'], result['operations_deleted'], result['outbox_deleted']), (1, 1, 1, 1))
        summary = self.repository.load_session(CONV)
        self.assertEqual(summary['creator_id'], 'stable-person-id')
        self.assertEqual(summary['revision'], 6)
        self.assertEqual(summary['cycle_number'], 7)
        self.assertEqual(summary['history'], [])
        self.assertNotIn('private', json.dumps(summary))
        with self.repository._connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT updated_at FROM sessions').fetchone()[0], OLD.isoformat())

    def test_before_30_days_preserves_everything(self):
        self.change('sessions', updated_at=(NOW - timedelta(days=29)).isoformat())
        self.assertEqual(self.sweep()['examined'], 0)
        self.assertEqual(self.count('inbound_events'), 1)

    def test_90_days_deletes_summary_keeps_one_hashed_watermark(self):
        state = deepcopy(self.state)
        state['cycle']['closed_at'] = (NOW - timedelta(days=91)).isoformat()
        self.change('sessions', state_json=json.dumps(state))
        result = self.sweep()
        self.assertEqual(result['summaries_deleted'], 1)
        self.assertEqual(self.repository.load_session(CONV), {})
        with self.repository._connection() as db:
            rows = db.execute('SELECT * FROM retention_watermarks').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['conversation_hash'], fingerprint(CONV))
        self.assertNotIn(CONV, json.dumps(dict(rows[0])))

    def test_replay_old_timestamp_is_blocked_after_details_deleted(self):
        self.sweep()
        for source_at in (OLD.isoformat(), None, 'bad', (NOW + timedelta(days=1)).isoformat()):
            with self.subTest(source_at=source_at), patch('repository._now', return_value=NOW.isoformat()):
                result = self.repository.reserve_event('chatwoot:1:999', CONV, 'old', source_at=source_at)
            self.assertFalse(result['reserved'])
            self.assertEqual(result['status'], 'retention_replay_blocked')
        self.assertEqual(self.count('inbound_events'), 0)

    def test_old_id_is_blocked_even_with_new_timestamp(self):
        self.sweep()
        with patch('repository._now', return_value=NOW.isoformat()):
            result = self.repository.reserve_event(EVENT, CONV, 'changed', source_at=NOW.isoformat())
        self.assertFalse(result['reserved'])

    def test_fresh_return_can_start_new_cycle(self):
        self.sweep()
        with patch('repository._now', return_value=NOW.isoformat()):
            result = self.repository.reserve_event('chatwoot:1:778', CONV, 'fresh', source_at=NOW.isoformat())
        self.assertTrue(result['reserved'])
        state = self.repository.load_session(CONV)
        next_cycle = _open(state, NOW)
        self.assertEqual(next_cycle['number'], 8)

    def test_90_day_return_still_blocks_replay(self):
        state = deepcopy(self.state)
        state['cycle']['closed_at'] = (NOW - timedelta(days=91)).isoformat()
        self.change('sessions', state_json=json.dumps(state))
        self.sweep()
        with patch('repository._now', return_value=NOW.isoformat()):
            self.assertFalse(self.repository.reserve_event(EVENT, CONV, 'd', source_at=NOW.isoformat())['reserved'])
            self.assertTrue(self.repository.reserve_event('chatwoot:1:800', CONV, 'n', source_at=NOW.isoformat())['reserved'])

    def test_repeated_sweep_is_idempotent_and_does_not_extend_retention(self):
        self.sweep()
        self.assertEqual(self.sweep()['compacted'], 0)
        self.assertEqual(self.count('retention_watermarks'), 1)
        later = self.repository.retention_pass((NOW + timedelta(days=51)).isoformat())
        self.assertEqual(later['summaries_deleted'], 1)

    def test_renewed_state_gets_compacted_again_after_later_close(self):
        self.sweep()
        state = self.repository.load_session(CONV)
        state['history'] = [{'text': 'new private message'}]
        self.change('sessions', state_json=json.dumps(state))
        self.assertEqual(self.sweep()['compacted'], 1)
        self.assertEqual(self.repository.load_session(CONV)['history'], [])

    def test_open_and_missing_closed_clock_are_preserved(self):
        for change in ({'status': 'open'}, {'closed_at': None}):
            state = deepcopy(self.state)
            state['cycle'].update(change)
            self.change('sessions', state_json=json.dumps(state))
            self.assertEqual(self.sweep()['protected'], 1)

    def test_unknown_pending_and_waiting_effects_are_preserved(self):
        for status in ('pending', 'outcome_unknown', 'verification_pending', 'unknown', 'waiting_for_inbound'):
            state = deepcopy(self.state)
            state['effects']['e'] = {'type': 'tiktok_operation', 'status': status}
            self.change('sessions', state_json=json.dumps(state))
            self.assertEqual(self.sweep()['protected'], 1)

    def test_business_proofs_and_forms_are_preserved(self):
        variants = []
        state = deepcopy(self.state); state['cadastro_situacao'] = 'confirmado'; variants.append(state)
        state = deepcopy(self.state); state['acessos_entregues'] = True; variants.append(state)
        state = deepcopy(self.state); state['cycle']['real_operations'] = {'relationship': {'status': 'linked'}}; variants.append(state)
        state = deepcopy(self.state); state['cycle']['real_operations'] = {'invite': {'status': 'sent'}}; variants.append(state)
        state = deepcopy(self.state); state['cycle']['form_effect_id'] = 'f'; variants.append(state)
        for state in variants:
            self.change('sessions', state_json=json.dumps(state))
            self.assertEqual(self.sweep()['protected'], 1)

    def test_form_even_expired_draft_and_otp_are_never_removed(self):
        FormStore(self.repository.path)
        with self.repository._connection() as db:
            db.execute('INSERT INTO v5_forms(token_hash,form_id,creator_id,event_id,conversation_key,session_id,cycle_id,'
                'account_id,inbox_id,phone_hash,created_at,expires_at,receipt_email_operation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('token', 'form', 'creator', EVENT, CONV, 's', 'c', '1', '3', 'hash', OLD.isoformat(), OLD.isoformat(), 'mail'))
            db.execute('INSERT INTO v5_form_otp_operations VALUES(?,?,?,?,?,?)', ('otp', 'form', 'hash', 'outcome_unknown', OLD.isoformat(), OLD.isoformat()))
        self.assertEqual(self.sweep()['protected'], 1)
        self.assertEqual(self.count('v5_forms'), 1)
        self.assertEqual(self.count('v5_form_otp_operations'), 1)

    def test_unknown_events_operations_outbox_are_preserved(self):
        for table in ('inbound_events', 'operations', 'outbox'):
            self.change(table, status='outcome_unknown')
            self.assertEqual(self.sweep()['protected'], 1)
            self.change(table, status='accepted' if table == 'outbox' else 'completed')

    def test_nested_unknown_and_conversion_receipts_are_preserved(self):
        for value in ({'result': {'status': 'outcome_unknown'}}, {'status': 'linked'}, {'cadastro_situacao': 'confirmado'},
                      {'evidence': {'post_attempted': True}}, {'evidence': {'create_accepted': True}},
                      {'provider_status': 'unknown'}):
            self.change('operations', result_json=json.dumps(value))
            self.assertEqual(self.sweep()['protected'], 1)

    def test_recent_activity_blocks_deletion(self):
        self.change('outbox', updated_at=(NOW - timedelta(days=1)).isoformat())
        self.assertEqual(self.sweep()['protected'], 1)

    def test_real_job_read_receipt_deleted_but_invite_and_unknown_preserved(self):
        job = {'job_key': 'job', 'conversation_key': CONV, 'event_key': EVENT,
               'effect_id': 'effect', 'cycle_id': 'c', 'creator': 'private', 'operation': 'relationship',
               'event': {}, 'payload': {}}
        with patch('repository._now', return_value=OLD.isoformat()):
            self.repository.prepare_reply(EVENT, CONV, self.state, 'unused', None, real_jobs=[job])
        for operation, status, receipt in (
                ('invite', 'completed', {'status': 'ineligible'}),
                ('relationship', 'polling', {'status': 'pending'}),
                ('relationship', 'outcome_unknown', {'status': 'failed'}),
                ('relationship', 'completed', {'status': 'linked', 'confirmed': True}),
                ('relationship', 'completed', {'evidence': {'post_attempted': True}})):
            self.change('real_jobs', operation=operation, status=status, result_json=json.dumps(receipt), updated_at=OLD.isoformat())
            self.assertEqual(self.sweep()['protected'], 1)
        self.change('real_jobs', operation='relationship', status='completed', result_json=json.dumps({'status': 'not_found'}))
        result = self.sweep()
        self.assertEqual(result['jobs_deleted'], 1)
        self.assertEqual(self.count('real_jobs'), 0)

    def test_inflight_new_inbound_wins_before_cleanup(self):
        with patch('repository._now', return_value=NOW.isoformat()):
            result = self.repository.reserve_event('chatwoot:1:778', CONV, 'new', source_at=NOW.isoformat())
        self.assertTrue(result['reserved'])
        self.assertEqual(self.sweep()['protected'], 1)
        self.assertEqual(self.count('inbound_events'), 2)

    def test_cleanup_failure_rolls_back_deletes_and_watermark(self):
        with self.repository._connection() as db:
            db.execute("CREATE TRIGGER prevent_delete BEFORE DELETE ON inbound_events BEGIN SELECT RAISE(ABORT,'stop'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.sweep()
        self.assertEqual(self.count('operations'), 1)
        self.assertEqual(self.count('outbox'), 1)
        self.assertEqual(self.count('inbound_events'), 1)
        self.assertEqual(self.count('retention_watermarks'), 0)

    def test_webhook_replay_is_acknowledged_before_ai_db_or_delivery(self):
        from server import create_app
        self.sweep()
        class Transport:
            def ready(self): return True
            def send(self, *args): raise AssertionError('no message')
        gate = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3', 'phone': '+5547991154859'}
        settings = {'gate': gate, 'webhook_token': 'x' * 32, 'state_dir': self.tmp.name,
                    'tiktok_mode': 'simulated', 'contact_sync_enabled': False, 'conversation_enabled': False}
        app = create_app(settings=settings, repository=self.repository, transport=Transport(),
                         planner=lambda *args: self.fail('no AI'), answerer=lambda *args: self.fail('no AI'))
        payload = {'event': 'message_created', 'id': 777, 'created_at': OLD.isoformat(), 'content': 'oi',
                   'message_type': 'incoming', 'private': False, 'account': {'id': 1}, 'inbox': {'id': 3},
                   'conversation': {'id': 88, 'inbox_id': 3, 'account_id': 1},
                   'sender': {'id': 3, 'phone_number': gate['phone'], 'type': 'contact'}}
        response = app.test_client().post('/webhook/chatwoot', json=payload,
                                          headers={'X-Amplify-Webhook-Token': settings['webhook_token']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['status'], 'retention_replay_blocked')
        self.assertEqual(self.count('inbound_events'), 0)

    def test_unknown_operation_kind_preserves_receipt(self):
        self.change('operations', kind='future_irreversible_operation')
        self.assertEqual(self.sweep()['protected'], 1)

    def test_cross_conversation_outbox_is_preserved(self):
        self.change('outbox', conversation_key='chatwoot:1:999')
        self.assertEqual(self.sweep()['protected'], 1)
        self.assertEqual(self.count('outbox'), 1)

    def test_limit_cursor_and_bounds(self):
        self.seed(self.state, conversation='chatwoot:1:99', event='chatwoot:1:888')
        first = self.sweep(limit=1)
        self.assertEqual(first['examined'], 1)
        self.assertEqual(first['next_after_key'], CONV)
        second = self.sweep(limit=1, after_key=first['next_after_key'])
        self.assertEqual(second['examined'], 1)
        for limit in (0, -1, 1001, True):
            with self.assertRaises(ValueError):
                self.sweep(limit=limit)

    def test_malformed_state_fails_closed(self):
        self.change('sessions', state_json='not json')
        self.assertEqual(self.sweep()['invalid'], 1)
        self.assertEqual(self.count('inbound_events'), 1)

    def test_claim_daily_survives_restart_and_crash(self):
        self.assertIsNotNone(self.repository.claim_maintenance('sql_retention', NOW.isoformat()))
        reopened = Repository(self.repository.path)
        self.assertIsNone(reopened.claim_maintenance('sql_retention', (NOW + timedelta(hours=23)).isoformat()))
        self.assertIsNotNone(reopened.claim_maintenance('sql_retention', (NOW + timedelta(days=1)).isoformat()))

    def test_failure_backoff_and_success_daily(self):
        self.repository.claim_maintenance('sql_retention', NOW.isoformat())
        self.repository.finish_maintenance('sql_retention', NOW.isoformat(), success=False)
        self.assertIsNone(self.repository.claim_maintenance('sql_retention', (NOW + timedelta(minutes=59)).isoformat()))
        claim = self.repository.claim_maintenance('sql_retention', (NOW + timedelta(hours=1)).isoformat())
        self.assertEqual(claim['failures'], 1)
        self.repository.finish_maintenance('sql_retention', (NOW + timedelta(hours=1)).isoformat(), success=True)
        self.assertIsNone(self.repository.claim_maintenance('sql_retention', (NOW + timedelta(hours=2)).isoformat()))

    def test_upgrade_old_six_column_schema_preserves_events(self):
        path = Path(self.tmp.name) / 'legacy.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE inbound_events(event_key TEXT PRIMARY KEY,conversation_key TEXT NOT NULL,digest TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)')
            db.execute('INSERT INTO inbound_events VALUES(?,?,?,?,?,?)', (EVENT, CONV, 'd', 'completed', OLD.isoformat(), OLD.isoformat()))
        db.close()
        upgraded = Repository(path)
        self.assertEqual(upgraded.event(EVENT)['digest'], 'd')
        with upgraded._connection() as db:
            self.assertEqual(len(db.execute('PRAGMA table_info(inbound_events)').fetchall()), 6)

    def executor(self, *, enabled=True, callback=None):
        class Client:
            def configuration(self, operation=None): return {'configured': True}
        settings = {'retention_enabled': enabled, 'tiktok_mode': 'real', 'real_worker_enabled': True,
                    'contact_sync_enabled': True}
        worker = RealExecutor(self.repository, Client(), settings, lambda key: threading.RLock(),
                              lambda event: None, lambda *args: None, clock=lambda: NOW)
        worker.retention_cleanup = callback
        return worker

    def test_executor_opt_in_daily_and_no_outbound(self):
        calls = []
        worker = self.executor(callback=lambda: calls.append('cleanup') or clean_counts())
        worker.maintain_retention(); worker.maintain_retention()
        self.assertEqual(calls, ['cleanup'])
        self.assertEqual(self.count('real_jobs'), 0)
        self.assertEqual(self.count('outbox'), 0)
        disabled = self.executor(enabled=False, callback=lambda: self.fail('not enabled'))
        self.assertEqual(disabled.maintain_retention()['status'], 'disabled')

    def test_executor_sql_independent_from_form_protection_and_failure_safe(self):
        self.state['cycle']['form_effect_id'] = 'form'
        self.change('sessions', state_json=json.dumps(self.state))
        calls = []
        def cleanup():
            calls.append(1)
            raise RuntimeError('secret provider body must not be logged')
        worker = self.executor(callback=cleanup)
        result = worker.maintain_retention()
        self.assertEqual(calls, [1])
        self.assertEqual(result['tasks']['sql_retention'], 'unconfirmed')
        self.assertEqual(self.count('inbound_events'), 1)
        self.assertNotIn('secret', json.dumps(worker.retention_status))

    def test_gateway_uses_exact_rpc_and_no_other_effect(self):
        calls = []
        settings = {'v5_url': 'https://divlvdmsqbwplervsqwu.supabase.co', 'v5_service_key': 'dummy-secret'}
        gateway = Gateway(settings, transport=lambda **kwargs: calls.append(kwargs) or cleanup_receipt(technical_deleted=3, total_deleted=3))
        self.assertEqual(gateway.cleanup_retention(), clean_counts(technical_deleted=3, total_deleted=3))
        self.assertTrue(calls[0]['url'].endswith('/rest/v1/rpc/limpar_registros_v5'))
        self.assertEqual(calls[0]['json'], {'p_limite': 1000})
        gateway.transport = lambda **kwargs: {'message': 'private'}
        with self.assertRaises(SubmissionUnknown): gateway.cleanup_retention()

    def test_more_batches_wait_at_least_60_seconds_then_return_to_daily(self):
        calls = []
        current = [NOW]
        def cleanup():
            calls.append(current[0])
            return clean_counts(technical_deleted=1000, total_deleted=1000, has_more=len(calls) < 2)
        worker = self.executor(callback=cleanup)
        worker.clock = lambda: current[0]
        worker.maintain_retention()
        current[0] += timedelta(seconds=59)
        worker.maintain_retention()
        self.assertEqual(len(calls), 1)
        current[0] += timedelta(seconds=1)
        worker.maintain_retention()
        self.assertEqual(len(calls), 2)
        current[0] += timedelta(hours=23)
        worker.maintain_retention()
        self.assertEqual(len(calls), 2)
        current[0] += timedelta(hours=1)
        worker.maintain_retention()
        self.assertEqual(len(calls), 3)

    def test_gateway_rejects_incomplete_wrong_counts_and_clock_shapes(self):
        settings = {'v5_url': 'https://divlvdmsqbwplervsqwu.supabase.co', 'v5_service_key': 'dummy-secret'}
        variants = [cleanup_receipt(total_deleted=3), cleanup_receipt(technical_deleted=True),
                    cleanup_receipt(has_more='true'), cleanup_receipt(total_deleted=1001, technical_deleted=1001),
                    cleanup_receipt(summary_cutoff=NOW.isoformat()), cleanup_receipt(status='partial')]
        for receipt in variants:
            with self.subTest(receipt=receipt):
                gateway = Gateway(settings, transport=lambda **kwargs: receipt)
                with self.assertRaises(SubmissionUnknown): gateway.cleanup_retention()


if __name__ == '__main__':
    unittest.main()
