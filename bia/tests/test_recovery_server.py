"""Technical recovery schedules reads without replaying a lead message."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import engine
from repository import Repository
from server import create_app


class RecoveryServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(self.temp.name + '/state.sqlite3')
        now = datetime.now(timezone.utc)
        self.event = dict(provider='chatwoot', account_id=1, inbox_id=3, conversation_id=26097,
            contact_id='3', message_id=123, sender_phone='+5547991154859', sender_type='contact',
            message_type='incoming', private=False, text='Não sei se está', created_at=now.isoformat(),
            event='message_created', source_ref='chatwoot:1:123')
        self.state = engine._state({})
        cycle = engine._open(self.state, now)
        cycle.update(mode='real', phase='shop')
        cycle['facts'].update(interesse_agenciamento=True, origem_declarada='anuncio', tiktok_declarado='@teste')
        engine._history(self.state, 'inbound', self.event['text'], now)
        self.state.update(revision=28, creator_id='22222222-2222-4222-8222-222222222222',
                          processed_inbound=['chatwoot:1:123'])
        receipt = dict(creator_id=self.state['creator_id'], atendimento_id=cycle['id'],
                       event_id='chatwoot:1:123', revision=28)
        self.state['contact_sync_proof'] = receipt
        self.repo.reserve_event('chatwoot:1:123', 'chatwoot:1:26097', hashlib.sha256(json.dumps(self.event).encode()).hexdigest())
        self.repo.finish_event('chatwoot:1:123', 'completed')
        self.repo.reserve_operation('chatwoot:1:123:contact:28', 'chatwoot:1:123', 'contact_sync')
        self.repo.complete_operation('chatwoot:1:123:contact:28', receipt)
        self.repo.save_session('chatwoot:1:26097', self.state)
        self.entries = []
        entries = self.entries
        class Gateway:
            def register_contact(inner, entry):
                entries.append(deepcopy(entry))
                return dict(creator_id='22222222-2222-4222-8222-222222222222',
                            atendimento_id=entry['atendimento_id'], event_id=entry['event_id'], revision=entry['revision'])
        class Client:
            def configuration(inner, *args): return {'configured': True}
        class Transport:
            def ready(inner): return True
            def send_reply(inner, *args): raise AssertionError('Recovery must not send a planned reply')
        self.allowed = True
        settings = dict(gate=dict(enabled=True, provider='chatwoot', account_id='1', inbox_id='3', phone='+5547991154859'),
            webhook_token='offline-test-token-long-enough', instance_id='test', readiness_issues=[],
            conversation_enabled=True, ai_enabled=True, contact_sync_enabled=True, tiktok_mode='real', real_worker_enabled=True)
        self.app = create_app(settings, self.repo, Transport(), real_client=Client(),
                              real_guard=lambda *_: {'allowed': self.allowed})
        self.app.extensions['v5_data_gateway'] = Gateway()
        self.callback = self.app.extensions['v5_reconcile_initial']

    def call(self, state=None):
        return self.callback(event=self.event, state=state or self.state, recovery_key='a'*64,
                             provenance='revalidated_chatwoot_source')

    def test_projects_same_source_and_window_then_schedules_reads_exactly_once(self):
        result = self.call()
        self.assertEqual(result['status'], 'scheduled')
        self.assertEqual(set(result['operations']), {'lookup', 'precheck', 'relationship'})
        current = self.repo.load_session('chatwoot:1:26097')
        self.assertEqual(current['cycle']['phase'], 'checking')
        self.assertEqual(current['revision'], 29)
        for key in ('history', 'processed_inbound'):
            self.assertEqual(current[key], self.state[key])
        for key in ('last_inbound_at', 'expires_at'):
            self.assertEqual(current['cycle'][key], self.state['cycle'][key])
        self.assertEqual(self.entries[0]['event_id'], 'chatwoot:1:123')
        self.assertEqual(self.call(current)['status'], 'noop')
        self.assertEqual(len(self.entries), 1)
        with self.repo._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM real_jobs').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)

    def test_human_control_and_stale_state_block_before_database_projection(self):
        self.allowed = False
        self.assertEqual(self.call()['status'], 'blocked')
        self.assertEqual(self.entries, [])
        self.allowed = True
        state = deepcopy(self.state)
        state['revision'] += 1
        self.assertEqual(self.call(state)['status'], 'noop')
        self.assertEqual(self.repo.load_session('chatwoot:1:26097'), self.state)

    def test_pending_profile_change_does_not_resume_old_profile(self):
        self.state['cycle']['pending_profile_changes'] = {'tiktok_declarado': '@outro'}
        self.repo.save_session('chatwoot:1:26097', self.state)
        self.assertEqual(self.call()['status'], 'noop')
        self.assertEqual(self.entries, [])
