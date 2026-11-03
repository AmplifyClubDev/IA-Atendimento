"""Offline inactivity closure, exact receipt projection and fresh return."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import conversation
import conversao
import engine
from repository import Repository
from real_journey import close_inactive_cycle
from server import create_app

NOW = datetime(2026, 10, 29, 16, 0, tzinfo=timezone.utc)
CREATOR = '22222222-2222-4222-8222-222222222222'
CONVERSATION = 'chatwoot:1:26097'
SOURCE = 'chatwoot:1:777'


def waiting(phase='origin'):
    state = engine._state({'creator_id': CREATOR, 'cadastro_situacao': 'pendente'})
    cycle = engine._open(state, NOW-timedelta(minutes=11))
    cycle.update(mode='real', phase=phase, last_inbound_at=(NOW-timedelta(minutes=10)).isoformat(),
                 expires_at=(NOW-timedelta(minutes=10)+timedelta(hours=24)).isoformat())
    cycle['facts'] = {'interesse_agenciamento': True, 'nome_declarado': 'Ana Silva'}
    engine._history(state, 'inbound', 'Quero me agenciar', NOW-timedelta(minutes=10))
    state.update(processed_inbound=[SOURCE], revision=7)
    return state


def close(state, **updates):
    data = dict(expected_cycle_id=state['cycle']['id'], source_key=SOURCE,
                warning_key='warning', closure_key='closure',
                warning_accepted_at=(NOW-timedelta(minutes=5)).isoformat(), now=NOW)
    data.update(updates)
    return close_inactive_cycle(state, **data)


class InactivityTransitionTests(unittest.TestCase):
    def test_closure_keeps_identity_facts_form_history_and_inbound_clocks(self):
        state = waiting('form')
        state['cycle'].update(form_url='https://form.invalid/private', form_effect_id='old-form')
        state['effects']['sent'] = {'type': 'tiktok_operation', 'operation': 'invite', 'creator': '@teste',
            'cycle_id': state['cycle']['id'], 'status': 'done', 'result_receipt': {'status': 'sent'}}
        result = close(state)
        self.assertTrue(result['inactivity_closed'])
        changed = result['state']
        self.assertEqual(changed['cycle']['status'], 'closed')
        self.assertEqual(changed['cycle']['reason'], 'inactivity_timeout')
        self.assertEqual(changed['revision'], 8)
        for key in ('creator_id', 'session_id', 'effects', 'history', 'processed_inbound'):
            self.assertEqual(changed[key], state[key])
        for key in ('phase', 'facts', 'form_url', 'form_effect_id', 'last_inbound_at', 'expires_at'):
            self.assertEqual(changed['cycle'][key], state['cycle'][key])
        self.assertEqual(result['reply'], '')
        self.assertEqual(result['effects'], [])

    def test_five_minutes_after_warning_is_a_strict_boundary(self):
        self.assertTrue(close(waiting(), now=NOW-timedelta(microseconds=1))['ignored'])
        self.assertTrue(close(waiting())['inactivity_closed'])

    def test_changed_cycle_new_inbound_human_and_uncertain_provider_block(self):
        cases = []
        state = waiting(); cases.append((state, {'expected_cycle_id': 'wrong'}))
        state = waiting(); state['cycle']['last_inbound_at'] = NOW.isoformat(); cases.append((state, {}))
        state = waiting(); state['human_control'] = True; cases.append((state, {}))
        state = waiting(); state['effects']['job'] = {'cycle_id': state['cycle']['id'], 'status': 'outcome_unknown'}
        cases.append((state, {}))
        state = waiting(); state['cycle']['pending_profile_changes'] = {'tiktok_declarado': '@other'}
        cases.append((state, {}))
        state = waiting(); state['cadastro_situacao'] = 'confirmado'; cases.append((state, {}))
        state = waiting('checking'); cases.append((state, {}))
        for state, updates in cases:
            with self.subTest(updates=updates, state=state):
                self.assertTrue(close(state, **updates)['ignored'])
                self.assertEqual(state['cycle']['status'], 'open')

    def test_first_return_is_new_standard_intro_without_planner_or_old_question(self):
        for phase in ('origin', 'consent_real', 'await_acceptance', 'form'):
            with self.subTest(phase=phase):
                state = close(waiting(phase))['state']
                previous = deepcopy(state['cycle'])
                result = conversation.handle(state, 'Já aceitei',
                    lambda *_: self.fail('First return must not invoke AI'),
                    now=NOW+timedelta(minutes=1), real_mode=True)
                self.assertNotEqual(result['state']['cycle']['id'], previous['id'])
                self.assertEqual(result['state']['creator_id'], CREATOR)
                self.assertEqual(result['state']['cycle']['facts'], {})
                self.assertEqual(result['state']['cycle']['phase'], 'intro')
                self.assertEqual(result['state']['closed_cycles'][-1], previous)
                self.assertEqual(result['reply'], conversation._RESET_GREETING)
                self.assertEqual(result['buttons'], ['Conhecer a Amplify', 'Quero me agenciar'])
                self.assertEqual(result['effects'], [])

    def test_old_provider_result_is_stale_after_new_cycle(self):
        state = waiting('await_acceptance')
        state['effects']['old'] = {'id': 'old', 'type': 'tiktok_operation', 'operation': 'relationship',
            'cycle_id': state['cycle']['id'], 'creator': '@teste', 'status': 'done'}
        closed = close(state)['state']
        returned = conversation.handle(closed, 'oi', now=NOW, real_mode=True)['state']
        before = deepcopy(returned)
        result = conversation.resolve_tiktok_result(returned, 'old', {'status': 'linked'}, now=NOW)
        self.assertTrue(result['ignored'])
        self.assertEqual(result['state'], before)

    def test_explicit_close_button_preserves_uncertain_invite_fence(self):
        state = waiting('inviting')
        state['effects']['invite'] = {'id': 'invite', 'type': 'tiktok_operation', 'operation': 'invite',
            'cycle_id': state['cycle']['id'], 'creator': '@teste', 'status': 'running'}
        result = conversation.handle(state, 'Encerrar agora', lambda *_: self.fail('No AI'), now=NOW, real_mode=True)
        self.assertEqual(result['state']['cycle']['reason'], 'inactivity_user_close')
        self.assertEqual(result['state']['effects']['invite']['status'], 'outcome_unknown')
        returned = conversation.handle(result['state'], 'quero me agenciar', lambda *_: self.fail('No AI'),
                                       now=NOW+timedelta(seconds=1), real_mode=True)
        self.assertEqual(returned['reply'], conversation._RESET_GREETING)
        self.assertEqual(returned['state']['effects']['invite']['status'], 'outcome_unknown')

    def test_continue_button_keeps_phase_without_granting_invite_consent(self):
        state = waiting('origin')
        result = conversation.handle(state, 'Seguir atendimento', lambda *_: self.fail('No AI'), now=NOW, real_mode=True)
        self.assertEqual(result['state']['cycle']['id'], state['cycle']['id'])
        # Release 40: a origem não é mais perguntada; seguir leva ao pedido do @.
        self.assertEqual(result['state']['cycle']['phase'], 'tiktok')
        self.assertNotIn('consentimento_convite', result['state']['cycle']['facts'])
        self.assertEqual(result['effects'], [])
        self.assertIn('@ do TikTok', result['reply'])
        state['cycle']['facts']['origem_declarada'] = 'indicacao'
        result = conversation.handle(state, 'Seguir atendimento', lambda *_: self.fail('No AI'), now=NOW, real_mode=True)
        self.assertEqual(result['state']['cycle']['phase'], 'tiktok')
        self.assertIn('Qual é o seu @', result['reply'])


class InactivityProjectionTests(unittest.TestCase):
    def setUp(self):
        from followup import sequence_keys
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name)/'state.sqlite3')
        self.state = waiting()
        self.event = dict(provider='chatwoot', event='message_created', account_id='1', inbox_id='3',
            conversation_id='26097', message_id='777', contact_id='3', sender_phone='+5547991154859',
            sender_type='contact', message_type='incoming', private=False, text='Quero me agenciar',
            created_at=self.state['cycle']['last_inbound_at'], source_ref=SOURCE)
        self.repo.reserve_event(SOURCE, CONVERSATION, 'offline')
        self.repo.finish_event(SOURCE, 'completed')
        self.repo.save_session(CONVERSATION, self.state)
        self.repo.remember_followup_source(CONVERSATION, self.event, self.state)
        source = self.repo.followup_source(CONVERSATION)
        self.warning_key, self.closure_key = sequence_keys(self.state['cycle']['id'], SOURCE)
        self.warning = dict(status='accepted', message_id='900', cycle_id=self.state['cycle']['id'],
            source_key=SOURCE, accepted_at=(NOW-timedelta(minutes=5)).isoformat())
        self.closure = dict(status='accepted', message_id='901', cycle_id=self.state['cycle']['id'],
            source_key=SOURCE, accepted_at=NOW.isoformat(), warning_key=self.warning_key,
            warning_accepted_at=self.warning['accepted_at'])
        for key, receipt in ((self.warning_key, self.warning), (self.closure_key, self.closure)):
            self.assertTrue(self.repo.reserve_followup(CONVERSATION, source, self.state, key, {'text': 'offline', 'buttons': []}))
            self.repo.finish_outbox(key, 'accepted', receipt)
            self.repo.complete_operation(key, receipt)
        self.entries = []
        entries = self.entries
        class Gateway:
            def register_contact(inner, entry):
                entries.append(deepcopy(entry))
                return dict(creator_id=CREATOR, atendimento_id=entry['atendimento_id'],
                    event_id=entry['event_id'], revision=entry['revision'], cadastro_situacao='pendente')
        class Transport:
            def ready(inner): return True
            def send_reply(inner, *_args, **_kwargs): raise AssertionError('Closure callback must not send')
        class Client:
            def configuration(inner, *_args): return {'configured': True}
        self.settings = dict(gate=dict(enabled=True, provider='chatwoot', account_id='1', inbox_id='3', phone='+5547991154859'),
            webhook_token='offline-token-long-enough', instance_id='test', readiness_issues=[], ai_enabled=True,
            conversation_enabled=True, contact_sync_enabled=True, tiktok_mode='real', real_worker_enabled=True,
            followup_enabled=True, followup_delay_seconds='300', followup_start_at=(NOW-timedelta(days=1)).isoformat(),
            inactivity_close_enabled=True, inactivity_close_delay_seconds='300', chatwoot_stages_enabled=True)
        with patch('server.ChatwootProgress') as progress:
            self.progress = progress.return_value
            self.app = create_app(self.settings, self.repo, Transport(), real_client=Client(),
                                  real_guard=lambda *_: {'allowed': True})
        self.app.extensions['v5_data_gateway'] = Gateway()
        self.callback = self.app.extensions['v5_close_for_inactivity']

    def call(self, **updates):
        data = dict(event=self.event, expected_cycle_id=self.state['cycle']['id'], expected_source_key=SOURCE,
                    warning_key=self.warning_key, closure_key=self.closure_key, now=NOW)
        data.update(updates)
        return self.callback(**data)

    def test_accepted_pair_closes_and_projects_exact_sql_snapshot_once(self):
        self.assertEqual(self.call()['status'], 'closed')
        saved = self.repo.load_session(CONVERSATION)
        self.assertEqual(saved['cycle']['reason'], 'inactivity_timeout')
        self.assertEqual(self.entries[0]['situacao'], 'encerrado')
        self.assertEqual(self.entries[0]['revision'], 8)
        self.assertEqual(self.entries[0]['event_id'], SOURCE)
        self.assertEqual(self.entries[0]['ultima_mensagem_em'], self.state['cycle']['last_inbound_at'])
        proof = self.progress.sync.call_args.args[2]
        self.assertEqual(proof['snapshot'], dict(cycle_id=self.state['cycle']['id'], phase='origin', status='closed', revision=8))
        self.assertEqual(self.call()['status'], 'closed')
        self.assertEqual(len(self.entries), 1)
        self.assertEqual(self.repo.load_session(CONVERSATION)['revision'], 8)

    def test_changed_source_or_unknown_closure_never_closes(self):
        self.repo.finish_outbox(self.closure_key, 'outcome_unknown', {'status': 'outcome_unknown'})
        self.assertEqual(self.call()['status'], 'stale')
        self.assertEqual(self.repo.load_session(CONVERSATION)['cycle']['status'], 'open')
        self.assertEqual(self.entries, [])

    def test_timer_binding_flag_and_latest_inbound_are_required(self):
        self.assertEqual(self.call(now=NOW-timedelta(microseconds=1))['status'], 'stale')
        self.assertEqual(self.call(expected_source_key='chatwoot:1:999')['status'], 'stale')
        self.settings['inactivity_close_enabled'] = False
        self.assertEqual(self.call()['status'], 'stale')
        self.assertEqual(self.entries, [])

    def test_uncertain_sql_ack_closes_local_state_but_never_repeats_rpc(self):
        class Unknown:
            calls = 0
            def register_contact(inner, _entry):
                inner.calls += 1
                raise TimeoutError('offline-lost-ack')
        gateway = Unknown()
        self.app.extensions['v5_data_gateway'] = gateway
        self.assertEqual(self.call()['status'], 'outcome_unknown')
        self.assertEqual(self.repo.load_session(CONVERSATION)['cycle']['status'], 'closed')
        self.assertEqual(self.call()['status'], 'outcome_unknown')
        self.assertEqual(gateway.calls, 1)
        self.progress.sync.assert_not_called()
