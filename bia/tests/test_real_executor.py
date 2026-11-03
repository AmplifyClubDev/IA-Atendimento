"""Offline executor contracts: no remote provider, token or deployed service."""
import copy
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repository import Repository
from real_operations import (RealExecutor, build_jobs, business_key, chatwoot_control_guard,
                             policy_for)
from real_journey import _policy_fingerprint


NOW = datetime(2026, 10, 28, 22, 0, tzinfo=timezone.utc)
CYCLE = '11111111-1111-4111-8111-111111111111'
EVENT = {'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
         'conversation_id': '26097', 'contact_id': '3', 'message_id': '777',
         'sender_phone': '+5547991154859', 'message_type': 'incoming', 'private': False,
         'text': 'Autorizo o convite real', 'sender_type': 'contact'}
CONV = 'chatwoot:1:26097'
GATE = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
        'phone': '+5547991154859'}
CREATOR_ID = '22222222-2222-4222-8222-222222222222'


class FakeGateway:
    def register_contact(self, entry):
        return {'creator_id': CREATOR_ID, 'atendimento_id': entry['atendimento_id'],
                'event_id': entry['event_id'], 'revision': entry['revision']}


class FakeClient:
    def __init__(self, result=None, hook=None):
        self.calls, self.result, self.hook = [], result, hook
        self.probes = []
        self.ready = True
    def configuration(self, operation=None):
        return {'configured': self.ready, 'issues': []}
    def _ready(self, role):
        self.probes.append(role)
        return None
    def execute(self, operation, creator, **kwargs):
        self.calls.append((operation, creator, kwargs))
        if self.hook:
            return self.hook(operation, creator, kwargs)
        return self.result or {'operation': operation, 'creator': creator, 'status': 'eligible',
                               'confirmed': True, 'observed_at': NOW.isoformat(), 'evidence': {'exact': True}}


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        fixture_root = Path(__file__).resolve().parents[2]
        self.tmp = tempfile.TemporaryDirectory(dir=fixture_root, prefix='executor-fixture-')
        assert Path(self.tmp.name).resolve().is_relative_to(fixture_root)
        self.addCleanup(self.tmp.cleanup)
        timestamp_patch = patch('repository._now', return_value=NOW.isoformat())
        timestamp_patch.start()
        self.addCleanup(timestamp_patch.stop)
        self.repository = Repository(Path(self.tmp.name) / 'test.sqlite3')
        self.settings = {'tiktok_mode': 'real', 'real_worker_enabled': True, 'gate': dict(GATE),
                         'contact_sync_enabled': True,
                         'state_dir': self.tmp.name, 'tiktok_policy_approved': True,
                         'tiktok_invite_commission': '10', 'tiktok_policy_version': 'test-approved-v1',
                         'tiktok_commission_unit': 'percent', 'tiktok_duration_fixed_months': '2',
                         'tiktok_duration_label': '2 meses'}
        self.locks = {}
        self.now = NOW
        self.applied = []
        self.guard_allowed = True
    def lock_for(self, key):
        return self.locks.setdefault(key, threading.RLock())
    def guard(self, event):
        return {'allowed': self.guard_allowed,
                'reason': 'automation_control_confirmed' if self.guard_allowed else 'human_assignee_blocked'}
    def state(self, operation='precheck'):
        state = {'session_id': 'a', 'revision': 1, 'effects': {}, 'creator_id': CREATOR_ID,
                 'cycle': {'id': CYCLE, 'mode': 'real', 'status': 'open', 'phase': 'checking',
                           'number': 1, 'opened_at': NOW.isoformat(), 'last_inbound_at': NOW.isoformat(),
                           'expires_at': (NOW + timedelta(hours=24)).isoformat(),
                           'facts': {'tiktok_declarado': '@alice'}}}
        effect = {'id': 'effect:' + operation, 'type': 'tiktok_operation', 'operation': operation,
                  'cycle_id': CYCLE, 'creator': '@alice', 'status': 'pending', 'confirmed': operation == 'invite',
                  'payload': {'operation': operation, 'creator': '@alice', 'cycle_id': CYCLE}}
        if operation == 'invite':
            fingerprint = _policy_fingerprint(policy_for(self.settings))
            consent = {'cycle_id': CYCLE, 'creator': '@alice', 'policy_hash': fingerprint, 'at': NOW.isoformat()}
            state['cycle']['facts']['consentimento_convite'] = True
            state['cycle']['invite_consent'] = consent
            effect.update(consent=copy.deepcopy(consent), policy_hash=fingerprint)
            effect['payload'].update(confirmed=True, commission=10.0, duration_fixed_months=2)
            state['effects']['precheck:proof'] = {'id': 'precheck:proof', 'type': 'tiktok_operation',
                'operation': 'precheck', 'cycle_id': CYCLE, 'creator': '@alice', 'status': 'done'}
            state['cycle']['real_operations'] = {'precheck': {'job_id': 'precheck:proof', 'operation': 'precheck',
                'cycle_id': CYCLE, 'creator': '@alice', 'status': 'eligible', 'confirmed': True,
                'observed_at': NOW.isoformat(), 'evidence': {'exact': True}}}
        state['effects'][effect['id']] = effect
        return state, effect
    def certify_projection(self, state):
        proof = {'creator_id': CREATOR_ID, 'atendimento_id': CYCLE,
                 'event_id': 'chatwoot:1:777', 'revision': state['revision']}
        operation = proof['event_id'] + ':contact:' + str(state['revision'])
        self.repository.reserve_operation(operation, proof['event_id'], 'contact_sync')
        self.repository.complete_operation(operation, proof)
        state['contact_sync_proof'] = proof
    def enqueue(self, operation='precheck'):
        state, effect = self.state(operation)
        self.repository.reserve_event('chatwoot:1:777', CONV, 'fixture')
        self.certify_projection(state)
        jobs = build_jobs(EVENT, state, [effect])
        self.repository.prepare_reply('chatwoot:1:777', CONV, state, 'inbound:reply', None, real_jobs=jobs)
        return jobs[0]
    def apply(self, job, state, result, event_key):
        self.applied.append(copy.deepcopy(result))
        state['revision'] += 1
        state['effects'][job['effect_id']]['status'] = ('pending' if job['operation'] == 'relationship'
                                                       and result['status'] in {'pending', 'not_found'} else 'done')
        self.certify_projection(state)
        self.repository.save_session(CONV, state)
        self.repository.finish_event(event_key, 'completed')
        return {'state': state}
    def executor(self, client):
        return RealExecutor(self.repository, client, self.settings, self.lock_for, self.guard, self.apply,
                            clock=lambda: self.now)

    def test_one_business_row_for_same_cycle_handle_action(self):
        job = self.enqueue()
        state = self.repository.load_session(CONV)
        effect = state['effects'][job['effect_id']]
        self.repository.prepare_reply('chatwoot:1:777', CONV, state, 'unused', None,
                                      real_jobs=build_jobs(EVENT, state, [effect]))
        with self.repository._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM real_jobs').fetchone()[0], 1)
        self.assertEqual(job['job_key'], business_key(CYCLE, 'alice', 'precheck'))

    def test_commit_intent_before_call_and_one_result_application(self):
        job = self.enqueue()
        def execute(operation, creator, kwargs):
            self.assertEqual(self.repository.real_job(job['job_key'])['status'], 'running')
            return {'operation': operation, 'creator': creator, 'status': 'eligible', 'confirmed': True,
                    'observed_at': NOW.isoformat(), 'evidence': {'exact': True}}
        client = FakeClient(hook=execute)
        executor = self.executor(client)
        self.assertEqual(executor.tick()['status'], 'completed')
        self.assertEqual(executor.tick()['status'], 'idle')
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(self.applied), 1)

    def test_no_automatic_worker_thread_on_construction(self):
        executor = self.executor(FakeClient())
        self.assertIsNone(executor.thread)
        self.assertFalse(executor.status()['worker_running'])

    def test_session_preflight_is_three_readers_and_has_explicit_expiry(self):
        client = FakeClient()
        executor = self.executor(client)
        snapshot = executor.probe_sessions()
        self.assertEqual(client.probes, ['precheck', 'agency', 'invites'])
        self.assertEqual(client.calls, [])
        self.assertTrue(snapshot['ready'])
        self.now += timedelta(seconds=61)
        self.assertFalse(executor.status()['sessions']['fresh'])
        self.assertFalse(executor.status()['sessions']['ready'])

    def test_session_preflight_failure_is_sanitized_and_never_grants_ready(self):
        client = FakeClient()
        def fail(role):
            if role == 'agency': raise RuntimeError('secret-that-must-not-appear')
        client._ready = fail
        snapshot = self.executor(client).probe_sessions()
        self.assertFalse(snapshot['ready'])
        self.assertNotIn('secret-that-must-not-appear', json.dumps(snapshot))
        self.assertEqual(snapshot['functions']['agency']['reason'], 'probe_unconfirmed')

    def test_simulated_session_preflight_does_not_call_bridges(self):
        self.settings['tiktok_mode'] = 'simulated'
        client = FakeClient()
        self.assertFalse(self.executor(client).probe_sessions()['ready'])
        self.assertEqual(client.probes, [])

    def test_simulated_or_disabled_configuration_never_calls_provider(self):
        self.enqueue()
        client = FakeClient()
        executor = self.executor(client)
        for mode, enabled, configured in [('simulated', True, True), ('real', False, True), ('real', True, False)]:
            self.settings.update(tiktok_mode=mode, real_worker_enabled=enabled)
            client.ready = configured
            self.assertEqual(executor.tick()['status'], 'disabled')
        self.assertEqual(client.calls, [])

    def test_pause_reset_expired_handle_change_all_block_before_call(self):
        for mutation in ['pause', 'reset', 'expiry', 'handle', 'scope']:
            with self.subTest(mutation=mutation):
                with self.repository._connection() as db:
                    db.execute('DELETE FROM real_jobs')
                job = self.enqueue()
                state = self.repository.load_session(CONV)
                if mutation == 'pause': state['cycle']['status'] = 'closed'
                if mutation == 'reset': state['cycle']['id'] = 'another-cycle'
                if mutation == 'expiry': state['cycle']['expires_at'] = (NOW - timedelta(seconds=1)).isoformat()
                if mutation == 'handle': state['cycle']['facts']['tiktok_declarado'] = '@bob'
                if mutation == 'scope': self.settings['gate']['enabled'] = False
                self.repository.save_session(CONV, state)
                client = FakeClient()
                self.assertEqual(self.executor(client).tick()['status'], 'cancelled')
                self.assertEqual(client.calls, [])
                self.settings['gate']['enabled'] = True

    def test_human_takeover_before_effect_or_after_response_blocks(self):
        self.enqueue()
        self.guard_allowed = False
        client = FakeClient()
        executor = self.executor(client)
        self.assertEqual(executor.tick()['status'], 'cancelled')
        self.assertEqual(client.calls, [])
        with self.repository._connection() as db: db.execute('DELETE FROM real_jobs')
        self.enqueue()
        self.guard_allowed = True
        def execute(operation, creator, kwargs):
            self.guard_allowed = False
            return {'operation': operation, 'creator': creator, 'status': 'eligible', 'confirmed': True,
                    'observed_at': NOW.isoformat(), 'evidence': {'exact': True}}
        self.assertEqual(self.executor(FakeClient(hook=execute)).tick()['status'], 'human_control_blocked')
        self.assertEqual(self.applied, [])

    def test_provider_io_does_not_hold_conversation_lock_and_stale_result_is_discarded(self):
        self.enqueue()
        entered, release = threading.Event(), threading.Event()
        def execute(operation, creator, kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return {'operation': operation, 'creator': creator, 'status': 'eligible', 'confirmed': True,
                    'observed_at': NOW.isoformat(), 'evidence': {'exact': True}}
        executor = self.executor(FakeClient(hook=execute))
        outcomes = []
        thread = threading.Thread(target=lambda: outcomes.append(executor.tick()))
        thread.start()
        self.assertTrue(entered.wait(2))
        with self.lock_for(CONV):
            state = self.repository.load_session(CONV)
            state['cycle']['facts']['tiktok_declarado'] = '@bob'
            self.repository.save_session(CONV, state)
        release.set(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes[0]['status'], 'stale_result')
        self.assertEqual(self.applied, [])

    def test_polling_reuses_row_has_backoff_and_does_not_repeat_same_pending_reply(self):
        job = self.enqueue('relationship')
        result = {'operation': 'relationship', 'creator': 'alice', 'status': 'pending',
                  'confirmed': True, 'observed_at': NOW.isoformat(), 'evidence': {'exact': True}}
        client = FakeClient(result)
        executor = self.executor(client)
        self.assertEqual(executor.tick()['status'], 'polling')
        self.assertEqual(executor.tick()['status'], 'idle')
        self.now += timedelta(seconds=15)
        client.result = {**result, 'observed_at': self.now.isoformat(),
                         'evidence': {'exact': True, 'checked_at': self.now.isoformat()}}
        self.assertEqual(executor.tick()['status'], 'polling')
        self.assertEqual(len(self.applied), 1)
        self.assertEqual(self.repository.real_job(job['job_key'])['attempts'], 2)
        with self.repository._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM real_jobs').fetchone()[0], 1)
        self.now += timedelta(seconds=30)
        client.result = {**result, 'status': 'linked', 'evidence': {'exact': True, 'active': True}}
        self.assertEqual(executor.tick()['status'], 'completed')
        self.assertEqual(len(self.applied), 2)

    def test_poll_limit_is_bounded(self):
        job = self.enqueue('relationship')
        client = FakeClient({'operation': 'relationship', 'creator': 'alice', 'status': 'pending',
                             'confirmed': True, 'observed_at': NOW.isoformat(), 'evidence': {'exact': True}})
        executor = self.executor(client)
        for _ in range(6):
            executor.tick(); self.now += timedelta(minutes=10)
        self.assertEqual(executor.tick()['status'], 'idle')
        self.assertEqual(len(client.calls), 6)
        self.assertEqual(self.repository.real_job(job['job_key'])['status'], 'completed')

    def test_acceptance_after_six_polls_reuses_read_row_and_reaches_form(self):
        import conversation
        job = self.enqueue('relationship')
        state = self.repository.load_session(CONV)
        state['cycle']['phase'] = 'await_acceptance'
        state['cycle']['real_operations'] = {'invite': {'status': 'sent'}}
        self.repository.save_session(CONV, state)
        forms = []

        def apply(job, state, result, event_key):
            transition = conversation.resolve_tiktok_result(state, job['effect_id'], result,
                now=self.now, operation_policy=policy_for(self.settings))
            self.assertFalse(transition.get('ignored'))
            live = transition['state']
            forms.extend(effect for effect in transition.get('effects', []) if effect.get('type') == 'generate_form_link')
            self.certify_projection(live)
            self.repository.save_session(CONV, live)
            self.repository.finish_event(event_key, 'completed')
            return transition

        client = FakeClient(hook=lambda operation, creator, kwargs: {
            'operation': operation, 'creator': creator, 'status': 'pending', 'confirmed': True,
            'observed_at': self.now.isoformat(), 'evidence': {'exact': True}})
        executor = RealExecutor(self.repository, client, self.settings, self.lock_for, self.guard, apply,
                                clock=lambda: self.now)
        for index in range(6):
            before = self.repository.load_session(CONV)
            outcome = executor.tick()
            if index == 5:
                parked = self.repository.load_session(CONV)
                self.assertEqual(outcome['status'], 'completed')
                self.assertEqual(parked['effects'][job['effect_id']]['status'], 'waiting_for_inbound')
                for key in ['revision', 'contact_sync_proof', 'cycle']:
                    self.assertEqual(parked[key], before[key])
            self.now += timedelta(minutes=10)
        self.assertEqual(executor.tick()['status'], 'idle')
        self.assertEqual(len(client.calls), 6)

        inbound = {**EVENT, 'message_id': '778', 'text': 'Já aceitei o convite'}
        transition = conversation.handle_event(self.repository.load_session(CONV), inbound, GATE,
            now=self.now, real_mode=True, operation_policy=policy_for(self.settings))
        reads = [effect for effect in transition['effects'] if effect.get('operation') == 'relationship']
        self.assertEqual(len(reads), 1)
        self.assertNotEqual(reads[0]['id'], job['effect_id'])
        self.repository.reserve_event('chatwoot:1:778', CONV, 'acceptance-fixture')
        self.certify_projection(transition['state'])
        self.repository.prepare_reply('chatwoot:1:778', CONV, transition['state'], 'acceptance:reply', None,
            real_jobs=build_jobs(inbound, transition['state'], reads))
        self.assertEqual(self.repository.real_job(job['job_key'])['attempts'], 0)
        client.hook = lambda operation, creator, kwargs: {
            'operation': operation, 'creator': creator, 'status': 'linked', 'confirmed': True,
            'observed_at': self.now.isoformat(), 'evidence': {'exact': True, 'active': True}}
        self.assertEqual(executor.tick()['status'], 'completed')
        self.assertEqual(self.repository.load_session(CONV)['cycle']['phase'], 'form')
        self.assertEqual(len(forms), 1)
        self.assertTrue(all(call[0] == 'relationship' for call in client.calls))
        with self.repository._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM real_jobs').fetchone()[0], 1)

    def test_invitation_is_not_retried_after_restart_or_uncertain_ack(self):
        job = self.enqueue('invite')
        self.repository.claim_real_job(NOW.isoformat())
        self.repository.recover_real_jobs(NOW.isoformat())
        client = FakeClient()
        self.assertEqual(self.executor(client).tick()['status'], 'completed')
        self.assertEqual(client.calls, [])
        self.assertEqual(self.applied[0]['status'], 'outcome_unknown')
        self.assertEqual(self.repository.real_job(job['job_key'])['attempts'], 1)

    def test_invitation_final_write_fence_revalidates_human_control(self):
        self.enqueue('invite')
        writes = []
        def execute(operation, creator, kwargs):
            self.guard_allowed = False
            if kwargs['before_write'](): writes.append(creator)
            return {'operation': operation, 'creator': creator, 'status': 'verification_pending',
                    'confirmed': False, 'observed_at': NOW.isoformat(), 'evidence': {}}
        self.executor(FakeClient(hook=execute)).tick()
        self.assertEqual(writes, [])
        self.assertEqual(self.applied, [])

    def test_policy_change_revokes_previous_invitation_consent(self):
        self.enqueue('invite')
        self.settings['tiktok_invite_commission'] = '20'
        client = FakeClient()
        self.assertEqual(self.executor(client).tick()['status'], 'cancelled')
        self.assertEqual(client.calls, [])

    def test_pending_profile_change_blocks_write_until_confirmed(self):
        self.enqueue('invite')
        state = self.repository.load_session(CONV)
        state['cycle']['pending_profile_changes'] = {'tiktok_declarado': '@bob'}
        self.repository.save_session(CONV, state)
        client = FakeClient()
        self.assertEqual(self.executor(client).tick()['status'], 'cancelled')
        self.assertEqual(client.calls, [])

    def test_stale_precheck_blocks_write_even_with_valid_consent(self):
        self.enqueue('invite')
        state = self.repository.load_session(CONV)
        state['cycle']['real_operations']['precheck']['observed_at'] = (NOW - timedelta(minutes=16)).isoformat()
        self.repository.save_session(CONV, state)
        client = FakeClient()
        self.assertEqual(self.executor(client).tick()['status'], 'cancelled')
        self.assertEqual(client.calls, [])

    def test_lost_sqlite_ack_after_provider_does_not_repeat_write(self):
        job = self.enqueue('invite')
        client = FakeClient({'operation': 'invite', 'creator': 'alice', 'status': 'sent',
                             'confirmed': True, 'observed_at': NOW.isoformat(), 'evidence': {'exact': True}})
        executor = self.executor(client)
        with patch.object(self.repository, 'set_real_result', side_effect=OSError('fake-lost-ACK')):
            with self.assertRaises(OSError): executor.tick()
        self.assertEqual(self.repository.real_job(job['job_key'])['status'], 'running')
        self.repository.recover_real_jobs(NOW.isoformat())
        executor.tick()
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(self.applied[0]['status'], 'outcome_unknown')

    def test_webhook_enqueues_without_provider_then_worker_chains_real_proof_and_form(self):
        from server import create_app
        state, effect = self.state('precheck')
        class Transport:
            def __init__(self): self.sent = []
            def ready(self): return True
            def send_reply(self, event, text, buttons, key):
                self.sent.append((text, key)); return {'status': 'accepted', 'message_id': '900'}
        transport = Transport()
        settings = {**self.settings, 'webhook_token': 'w' * 40, 'conversation_enabled': True,
                    'ai_enabled': True, 'contact_sync_enabled': True, 'instance_id': 'offline-test', 'readiness_issues': []}
        client = FakeClient()
        app = create_app(settings, self.repository, transport, real_client=client, real_guard=self.guard)
        app.extensions['v5_data_gateway'] = FakeGateway()
        payload = {'event': 'message_created', 'id': 777, 'account': {'id': 1}, 'inbox': {'id': 3},
                   'conversation': {'id': 26097, 'account_id': 1, 'inbox_id': 3},
                   'sender': {'id': 3, 'type': 'contact', 'phone_number': EVENT['sender_phone']},
                   'message_type': 'incoming', 'private': False, 'content': 'oi'}
        with patch('conversation.handle_event', return_value={'state': state, 'reply': 'Vou conferir seu perfil.',
                                                             'buttons': [], 'effects': [effect]}):
            response = app.test_client().post('/webhook/chatwoot', json=payload,
                                             headers={'X-Amplify-Webhook-Token': 'w' * 40})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.calls, [])
        executor = app.extensions['v5_real_executor']
        self.assertIsNone(executor.thread)
        observed = datetime.now(timezone.utc).isoformat()
        client.result = {'operation': 'precheck', 'creator': 'alice', 'status': 'eligible',
                         'confirmed': True, 'observed_at': observed, 'evidence': {'exact': True}}
        self.assertEqual(executor.tick()['status'], 'completed')
        after = self.repository.load_session(CONV)
        self.assertEqual(after['cycle']['real_operations']['precheck']['status'], 'eligible')
        forms = []
        app.extensions['v5_form_link_factory'] = lambda state, effect, event: (forms.append(effect) or 'https://form.invalid/private')
        client.result = {'operation': 'relationship', 'creator': 'alice', 'status': 'linked',
                         'confirmed': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
                         'evidence': {'exact': True, 'active': True}}
        self.assertEqual(executor.tick()['status'], 'completed')
        after = self.repository.load_session(CONV)
        self.assertEqual(after['cycle']['phase'], 'form')
        self.assertEqual(after['cycle']['form_url'], 'https://form.invalid/private')
        self.assertEqual(len(forms), 1)
        self.assertEqual(len(client.calls), 2)
        self.assertGreaterEqual(len(transport.sent), 3)

    def test_confirmed_name_projects_only_to_form_draft_not_qualification(self):
        from server import create_app
        state, _ = self.state('precheck')
        state['cycle']['facts']['nome_declarado'] = 'Pessoa Teste'
        creator_id = '22222222-2222-4222-8222-222222222222'
        entries = []
        class Gateway:
            def register_contact(self, entry):
                entries.append(copy.deepcopy(entry))
                allowed = {'interesse_agenciamento', 'origem_declarada', 'tiktok_declarado', 'shop_ativo_declarado',
                           'possui_agencia_declarada', 'consentimento_ensaio', 'aceite_no_ensaio',
                           'consentimento_convite', 'aceite_declarado'}
                assert not set(entry.get('qualificacao') or {}) - allowed
                return {'creator_id': creator_id, 'atendimento_id': entry['atendimento_id'],
                        'event_id': entry['event_id'], 'revision': entry['revision']}
        class Transport:
            def ready(self): return True
            def send_reply(self, *args): return {'status': 'accepted', 'message_id': '900'}
        settings = {**self.settings, 'webhook_token': 'w' * 40, 'conversation_enabled': True,
                    'ai_enabled': True, 'contact_sync_enabled': True, 'instance_id': 'offline-test',
                    'readiness_issues': []}
        app = create_app(settings, self.repository, Transport(), real_client=FakeClient(), real_guard=self.guard)
        app.extensions['v5_data_gateway'] = Gateway()
        payload = {'event': 'message_created', 'id': 777, 'account': {'id': 1}, 'inbox': {'id': 3},
                   'conversation': {'id': 26097, 'account_id': 1, 'inbox_id': 3},
                   'sender': {'id': 3, 'type': 'contact', 'phone_number': EVENT['sender_phone']},
                   'message_type': 'incoming', 'private': False, 'content': 'meu nome é Pessoa Teste'}
        with patch('conversation.handle_event', return_value={'state': state, 'reply': 'Nome registrado.',
                                                             'buttons': [], 'effects': []}):
            response = app.test_client().post('/webhook/chatwoot', json=payload,
                                             headers={'X-Amplify-Webhook-Token': 'w' * 40})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(entries), 2)
        self.assertNotIn('nome_declarado', entries[-1]['qualificacao'])
        self.assertEqual(entries[-1]['rascunho']['nome'], 'Pessoa Teste')

    def test_result_application_reservation_is_not_replayed(self):
        job = self.enqueue()
        client = FakeClient()
        self.repository.claim_real_job(NOW.isoformat())
        result = client.execute('precheck', 'alice')
        self.repository.set_real_result(job['job_key'], result, NOW.isoformat())
        key = job['job_key'] + ':result:' + job['effect_id'] + ':1'
        self.repository.reserve_event(key, CONV, self.executor(client)._signature(result))
        self.assertEqual(self.executor(client).tick()['status'], 'application_outcome_unknown')
        self.assertEqual(self.applied, [])
        self.assertEqual(len(client.calls), 1)

    def test_worker_lock_prevents_second_executor_owner(self):
        first, second = self.executor(FakeClient()), self.executor(FakeClient())
        with patch.object(first, '_run', side_effect=lambda: first.stop_event.wait(2)):
            self.assertTrue(first.start())
            self.assertFalse(second.start())
            self.assertEqual(second.last_error, 'worker_already_owned')
            first.stop(); first.thread.join(2)
        # mocked _run doesn't release the ownership file as the real finally does.
        first._ownership_file.close(); first._ownership_file = None


class GuardTests(unittest.TestCase):
    def detail(self):
        return {'id': 26097, 'account_id': 1, 'inbox_id': 3, 'status': 'open', 'can_reply': True,
                'meta': {'sender': {'id': 3, 'phone_number': '+5547991154859'}, 'assignee': None},
                'custom_attributes': {}}
    def guard(self, detail):
        transport = SimpleNamespace(token='not-printed', _conversation_url=lambda _event: 'https://chatwoot.invalid',
                                    http=lambda **kwargs: detail)
        return chatwoot_control_guard(transport, GATE, EVENT)
    def test_none_or_agent_bot_is_allowed_human_is_blocked(self):
        detail = self.detail()
        self.assertTrue(self.guard(detail)['allowed'])
        detail['meta']['assignee'] = {'id': 123, 'type': 'user', 'name': 'private'}
        result = self.guard(detail)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['reason'], 'human_assignee_blocked')
        self.assertNotIn('private', json.dumps(result))
        detail['meta']['assignee']['type'] = 'agent_bot'
        self.assertTrue(self.guard(detail)['allowed'])
    def test_manual_maintenance_snoozed_and_recipient_mismatch_are_blocked(self):
        for flag in ['manual', 'maintenance', 'automacao_pause']:
            detail = self.detail(); detail['custom_attributes'][flag] = True
            self.assertFalse(self.guard(detail)['allowed'])
        detail = self.detail(); detail['status'] = 'snoozed'
        self.assertFalse(self.guard(detail)['allowed'])
        detail = self.detail(); detail['meta']['sender']['id'] = 4
        self.assertFalse(self.guard(detail)['allowed'])


class RealConfigTests(unittest.TestCase):
    def test_real_mode_has_no_silent_policy_or_credentials_default(self):
        from config import load_settings
        loaded = load_settings({'V5_TIKTOK_MODE': 'real'})
        self.assertFalse(loaded['simulated_checks'])
        self.assertIn('real_worker_disabled', loaded['readiness_issues'])
        self.assertIn('tiktok_commission_explicit_required', loaded['readiness_issues'])
        self.assertIn('tiktok_policy_approval_required', loaded['readiness_issues'])
        self.assertIn('tiktok_policy_units_unconfirmed', loaded['readiness_issues'])
        self.assertFalse(policy_for(loaded)['approved'])
    def test_commission_outside_actual_zero_to_ten_range_is_rejected(self):
        from config import load_settings
        for raw in ['11', '100', '-1', 'NaN', '', '10.0001']:
            loaded = load_settings({'V5_TIKTOK_MODE': 'real', 'V5_TIKTOK_INVITE_COMMISSION': raw})
            self.assertIn('tiktok_commission_explicit_required', loaded['readiness_issues'])
        loaded = load_settings({'V5_TIKTOK_MODE': 'real', 'V5_TIKTOK_INVITE_COMMISSION': '10'})
        self.assertNotIn('tiktok_commission_explicit_required', loaded['readiness_issues'])


if __name__ == '__main__':
    unittest.main()
