"""Clock-controlled pilot reminders; no provider, AI, SMTP or socket calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from config import load_settings
from followup import Followup, CONVERSATION, configured, reminder
from repository import Repository
from transport import ChatwootTransport


class FakeTransport:
    def __init__(self, event):
        self.event = deepcopy(event)
        self.sent, self.reads = [], []
        self.receipt = {'status': 'accepted', 'message_id': '900'}
        self.before_send = None
        self.messages = [self.message(event)]
        self.token = 'fake-offline-token'
    @staticmethod
    def message(event):
        return {'id': event['message_id'], 'conversation_id': 26097, 'message_type': 0, 'private': False,
                'content': event['text'], 'created_at': datetime.fromisoformat(event['created_at']).timestamp(),
                'sender': {'id': 3, 'type': 'contact', 'phone_number': event['sender_phone']}}
    def _conversation_url(self, event):
        return 'https://chatwoot.invalid/api/v1/accounts/1/conversations/26097'
    def http(self, **kwargs):
        assert kwargs['method'] == 'GET'
        self.reads.append(kwargs['url'])
        return {'payload': deepcopy(self.messages)}
    def send_reply(self, event, text, buttons, key, *, before_write=None):
        if self.before_send:
            self.before_send()
        if before_write() is not True:
            return {'status': 'failed', 'reason': 'send_cancelled_before_post'}
        self.sent.append({'event': deepcopy(event), 'text': text, 'buttons': buttons, 'key': key})
        return deepcopy(self.receipt)


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='followup-test-')
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repository(Path(self.tmp.name) / 'state.sqlite3')
        self.now = datetime.now(timezone.utc)
        self.source_at = self.now - timedelta(seconds=300)
        self.event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': '1', 'inbox_id': '3',
            'conversation_id': '26097', 'message_id': '777', 'contact_id': '3', 'sender_phone': '+5547991154859',
            'sender_type': 'contact', 'message_type': 'incoming', 'private': False, 'text': 'Quero me agenciar',
            'created_at': self.source_at.isoformat(), 'source_ref': 'chatwoot:1:777'}
        self.settings = {'followup_enabled': True, 'followup_delay_seconds': '300',
            'followup_start_at': (self.now-timedelta(hours=1)).isoformat(), 'tiktok_mode': 'real',
            'real_worker_enabled': True, 'contact_sync_enabled': True, 'conversation_enabled': True,
            'gate': {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
                     'phone': '+5547991154859'}}
        self.state = {'session_id': 'session', 'revision': 3, 'creator_id': 'creator', 'cadastro_situacao': 'pendente',
            'processed_inbound': ['chatwoot:1:777'], 'history': [], 'effects': {},
            'cycle': {'id': 'cycle', 'mode': 'real', 'status': 'open', 'phase': 'tiktok', 'facts': {},
                'opened_at': (self.now-timedelta(minutes=10)).isoformat(),
                'last_inbound_at': self.source_at.isoformat(), 'expires_at': (self.source_at+timedelta(hours=24)).isoformat()},
            'contact_sync_proof': {'creator_id': 'creator', 'atendimento_id': 'cycle',
                                   'event_id': 'chatwoot:1:777', 'revision': 3}}
        self.repo.reserve_event('chatwoot:1:777', CONVERSATION, 'offline')
        self.repo.reserve_operation('chatwoot:1:777:contact:3', 'chatwoot:1:777', 'contact_sync')
        self.repo.complete_operation('chatwoot:1:777:contact:3', self.state['contact_sync_proof'])
        self.repo.prepare_reply('chatwoot:1:777', CONVERSATION, self.state, 'first-reply',
                                {'text': 'Qual é seu @ do TikTok?', 'buttons': []})
        self.repo.finish_outbox('first-reply', 'accepted', {'status': 'accepted', 'message_id': '778'})
        with self.repo._connection() as db:
            db.execute("UPDATE outbox SET updated_at=? WHERE outbox_key='first-reply'", (self.source_at.isoformat(),))
        self.repo.finish_event('chatwoot:1:777', 'completed')
        self.assertTrue(self.repo.remember_followup_source(CONVERSATION, self.event, self.state))
        self.transport = FakeTransport(self.event)
        self.lock = threading.RLock()
        self.guard_result = {'allowed': True}
        self.followup = Followup(self.repo, self.settings, self.transport, lambda _: self.lock,
                                  lambda _: self.guard_result, now=lambda: self.now)
        for target in ('socket.create_connection', 'socket.socket.connect', 'socket.socket.connect_ex'):
            mock = patch(target, side_effect=AssertionError('network forbidden'))
            mock.start()
            self.addCleanup(mock.stop)
    def save(self):
        self.repo.save_session(CONVERSATION, self.state)
    def assert_no_send(self):
        self.followup.next_probe_at = None
        self.followup.tick()
        self.assertEqual(self.transport.sent, [])
    def test_exact_five_minutes_sends_one_contextual_question_without_state_change(self):
        before = self.repo.load_session(CONVERSATION)
        self.assertEqual(self.followup.tick()['status'], 'accepted')
        self.assertEqual(len(self.transport.sent), 1)
        self.assertIn('@ do TikTok', self.transport.sent[0]['text'])
        self.assertEqual(self.transport.sent[0]['buttons'], [])
        self.assertEqual(self.repo.load_session(CONVERSATION), before)
        self.assertEqual(len(self.repo.outbox('chatwoot:1:777')), 2)
        self.assertEqual(self.repo.event('chatwoot:1:777')['status'], 'completed')
    def test_before_five_minutes_is_idle_without_provider_read(self):
        self.now -= timedelta(microseconds=1)
        self.assert_no_send()
        self.assertEqual(self.transport.reads, [])
    def test_duplicate_ticks_and_new_worker_instance_do_not_repeat(self):
        self.followup.tick()
        self.followup.tick()
        another = Followup(self.repo, self.settings, self.transport, lambda _: self.lock,
                           lambda _: {'allowed': True}, now=lambda: self.now)
        another.tick()
        self.assertEqual(len(self.transport.sent), 1)
    def test_unknown_transport_result_is_durable_and_never_retried(self):
        self.transport.receipt = {'status': 'outcome_unknown', 'reason': 'lost_ack'}
        self.assertEqual(self.followup.tick()['status'], 'outcome_unknown')
        self.followup.tick()
        self.assertEqual(len(self.transport.sent), 1)
    def test_exception_after_send_remains_unknown_and_never_retries(self):
        original = self.transport.send_reply
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError('not logged')
        self.transport.send_reply = lost
        self.followup.tick()
        self.followup.tick()
        self.assertEqual(len(self.transport.sent), 1)
    def test_new_inbound_in_chatwoot_blocks_even_before_webhook_arrives(self):
        newer = deepcopy(self.transport.messages[0]); newer['id'] = 780
        self.transport.messages.append(newer)
        self.assert_no_send()
    def test_new_inbound_between_reservation_and_post_cancels_permanently(self):
        def incoming():
            newer = deepcopy(self.transport.messages[0]); newer['id'] = 780
            self.transport.messages.append(newer)
        self.transport.before_send = incoming
        self.assertEqual(self.followup.tick()['status'], 'failed')
        self.assertEqual(self.transport.sent, [])
        self.transport.messages = [FakeTransport.message(self.event)]
        self.transport.before_send = None
        self.assert_no_send()
    def test_new_state_revision_before_post_cancels(self):
        def incoming():
            state = self.repo.load_session(CONVERSATION); state['revision'] += 1
            self.repo.save_session(CONVERSATION, state)
        self.transport.before_send = incoming
        self.assert_no_send()
    def test_baseline_prevents_old_backlog_and_exact_baseline_is_excluded(self):
        self.settings['followup_start_at'] = self.source_at.isoformat()
        self.assert_no_send()
        self.assertEqual(self.transport.reads, [])
    def test_no_baseline_or_enable_or_real_worker_means_no_reads(self):
        for key, value in [('followup_start_at', ''), ('followup_enabled', False), ('real_worker_enabled', False),
                           ('conversation_enabled', False), ('contact_sync_enabled', False), ('tiktok_mode', 'simulated')]:
            old = self.settings.get(key); self.settings[key] = value
            self.assert_no_send(); self.settings[key] = old
        self.assertEqual(self.transport.reads, [])
    def test_no_other_phone_inbox_account_or_conversation(self):
        for key, value in [('phone', '+5547999999999'), ('account_id', '2'), ('inbox_id', '4')]:
            original = self.settings['gate'][key]; self.settings['gate'][key] = value
            self.assert_no_send(); self.settings['gate'][key] = original
        self.state['processed_inbound'] = ['chatwoot:1:999']; self.save(); self.assert_no_send()
    def test_closed_completed_blocked_and_provider_phases_are_excluded(self):
        original = deepcopy(self.state)
        for status in ['closed', 'expired', 'completed']:
            self.state = deepcopy(original); self.state['cycle']['status'] = status; self.save(); self.assert_no_send()
        for phase in ['checking', 'inviting', 'checking_acceptance', 'blocked']:
            self.state = deepcopy(original); self.state['cycle']['phase'] = phase; self.save(); self.assert_no_send()
    def test_expired_and_source_24hours_old_are_excluded(self):
        self.now = self.source_at + timedelta(hours=24)
        self.assert_no_send()
    def test_registered_human_pause_optout_pending_profile_blocks(self):
        original = deepcopy(self.state)
        for path, key, value in [('root', 'cadastro_situacao', 'confirmado'), ('root', 'human_control', True),
            ('root', 'opt_out', True), ('cycle', 'qualification_paused', True),
            ('cycle', 'pending_profile_changes', {'tiktok': 'other'}), ('cycle', 'opt_out', True)]:
            self.state = deepcopy(original)
            (self.state if path == 'root' else self.state['cycle'])[key] = value
            self.save(); self.assert_no_send()
    def test_live_human_takeover_blocks_and_no_reservation_is_created(self):
        self.guard_result = {'allowed': False, 'reason': 'human_control_blocked'}
        self.assert_no_send()
        self.assertEqual(len(self.repo.outbox('chatwoot:1:777')), 1)
    def test_provider_pending_unknown_effect_and_job_block(self):
        self.state['effects'] = {'x': {'cycle_id': 'cycle', 'status': 'outcome_unknown'}}
        self.save(); self.assert_no_send()
        self.state['effects'] = {}; self.save()
        with self.repo._connection() as db:
            db.execute("INSERT INTO real_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ('job', CONVERSATION,
                'chatwoot:1:777', 'effect', 'cycle', 'alice', 'relationship', '{}', '{}', 'polling', 1,
                self.now.isoformat(), None, None, self.now.isoformat()))
        self.assert_no_send()
    def test_uncertain_outbox_or_operation_blocks(self):
        self.repo.finish_outbox('first-reply', 'outcome_unknown', {})
        self.assert_no_send()
        self.repo.finish_outbox('first-reply', 'accepted', {'status': 'accepted'})
        self.repo.reserve_operation('uncertain', 'chatwoot:1:777', 'conversation_turn')
        self.assert_no_send()
    def test_failed_latest_reply_cannot_use_planned_history_as_delivery(self):
        self.repo.finish_outbox('first-reply', 'failed', {'status': 'failed'})
        self.assert_no_send()
    def test_source_text_private_sender_or_timestamp_mismatch_blocks(self):
        original = deepcopy(self.transport.messages[0])
        for key, value in [('content', 'different'), ('private', True), ('message_type', 1), ('created_at', 1)]:
            self.transport.messages = [{**deepcopy(original), key: value}]
            self.assert_no_send()
        wrong = deepcopy(original); wrong['sender']['phone_number'] = '+5547999999999'
        self.transport.messages = [wrong]; self.assert_no_send()
    def test_contact_proof_missing_or_revision_drift_blocks(self):
        self.state['contact_sync_proof']['revision'] = 2
        self.save(); self.assert_no_send()
    def test_source_is_replaced_and_cascades_with_session_retention(self):
        self.assertEqual(self.repo.followup_source(CONVERSATION)['event_key'], 'chatwoot:1:777')
        with self.repo._connection() as db:
            db.execute('DELETE FROM sessions WHERE conversation_key=?', (CONVERSATION,))
            self.assertEqual(db.execute('SELECT count(*) FROM followup_sources').fetchone()[0], 0)
    def test_uncompleted_event_cannot_become_followup_source(self):
        self.repo.finish_event('chatwoot:1:777', 'outcome_unknown')
        self.assertFalse(self.repo.remember_followup_source(CONVERSATION, self.event, self.state))
        self.assert_no_send()
    def test_origin_nudge_is_optional_and_acceptance_nudge_does_not_claim_link(self):
        self.state['cycle']['phase'] = 'origin'
        self.assertIn('pode não informar', reminder(self.state, self.settings)[0])
        self.state['cycle']['phase'] = 'await_acceptance'
        text, buttons = reminder(self.state, self.settings)
        self.assertIn('Parcerias', text); self.assertEqual(buttons, [])
        self.assertNotIn('confirmado', text)
    def test_consent_requires_exact_approved_offer_and_never_mutates_state(self):
        from real_journey import _consent_prompt
        from real_operations import policy_for
        self.settings.update(tiktok_policy_approved=True, tiktok_invite_commission='10',
            tiktok_commission_unit='percent', tiktok_duration_fixed_months='2', tiktok_duration_label='2 meses',
            tiktok_policy_version='approved-v1')
        self.state['cycle']['phase'] = 'consent_real'; self.state['cycle']['facts']['tiktok_declarado'] = '@alice'
        self.assertIsNone(reminder(self.state, self.settings))
        _consent_prompt(self.state['cycle'], policy_for(self.settings))
        old = deepcopy(self.state)
        text, buttons = reminder(self.state, self.settings)
        # Release 40: o bloco das condições sai uma vez; o lembrete só pergunta de novo.
        self.assertIn('Posso te mandar o convite', text)
        self.assertEqual(buttons, ['Autorizo enviar o convite']); self.assertEqual(self.state, old)
    def test_form_only_repeats_the_existing_original_form_link(self):
        self.state['cycle']['phase'] = 'form'
        self.assertIsNone(reminder(self.state, self.settings))
        self.state['cycle']['form_url'] = 'https://evil.invalid/cadastro'
        self.assertIsNone(reminder(self.state, self.settings))
        url = 'https://amplify-cadastro.up.railway.app/cadastro/ensaio#s=' + 'x'*43
        self.state['cycle']['form_url'] = url
        self.assertIn(url, reminder(self.state, self.settings)[0])
    def test_delay_is_fixed_300_and_start_must_be_timezone_aware(self):
        self.settings['followup_delay_seconds'] = '1'; self.assertFalse(configured(self.settings))
        self.settings['followup_delay_seconds'] = '300'; self.settings['followup_start_at'] = '2026-10-29'
        self.assertFalse(configured(self.settings))
    def test_transport_callback_denied_or_exception_never_posts(self):
        calls = []
        def http(**kwargs):
            calls.append(kwargs['method'])
            return {'id': 999}
        transport = ChatwootTransport('https://chatwoot.invalid', 'offline', self.settings['gate'], http=http)
        with patch.object(transport, '_read_target', return_value=True):
            self.assertEqual(transport.send_reply(self.event, 'Olá', [], 'test', before_write=lambda: False)['status'], 'failed')
            def fail(): raise RuntimeError('not logged')
            self.assertEqual(transport.send_reply(self.event, 'Olá', [], 'test2', before_write=fail)['status'], 'failed')
            self.assertEqual(calls, [])
            self.assertEqual(transport.send_reply(self.event, 'Olá', [], 'legacy')['status'], 'accepted')
            self.assertEqual(calls, ['POST'])
    def test_prolonged_remote_pause_has_thirty_second_read_cooldown(self):
        calls = []
        def guard(event):
            calls.append(event['message_id'])
            return {'allowed': False}
        self.followup.guard = guard
        self.assertEqual(self.followup.tick()['status'], 'blocked')
        self.assertEqual(self.followup.tick()['status'], 'cooldown')
        self.now += timedelta(seconds=30)
        self.assertEqual(self.followup.tick()['status'], 'blocked')
        self.assertEqual(calls, ['777', '777'])
    def test_config_loader_requires_exact_pilot_delay_and_utc_baseline(self):
        env = {'V5_FOLLOWUP_ENABLED': 'true', 'V5_FOLLOWUP_START_AT': '2026-10-29T12:00:00Z',
            'V5_FOLLOWUP_DELAY_SECONDS': '300', 'V5_TIKTOK_MODE': 'real',
            'V5_TEST_PHONE': '+5547991154859', 'CHATWOOT_ACCOUNT_ID': '1', 'CHATWOOT_INBOX_ID': '3'}
        self.assertNotIn('followup_configuration_invalid', load_settings(env)['readiness_issues'])
        for key, value in [('V5_FOLLOWUP_START_AT', ''), ('V5_FOLLOWUP_START_AT', '2026-10-29T09:00:00-03:00'),
                           ('V5_FOLLOWUP_DELAY_SECONDS', '60'), ('CHATWOOT_INBOX_ID', '4')]:
            self.assertIn('followup_configuration_invalid', load_settings({**env, key: value})['readiness_issues'])
        self.assertFalse(load_settings({})['followup_enabled'])
    def test_one_replaced_source_row_per_conversation(self):
        newer = {**self.event, 'message_id': '779', 'source_ref': 'chatwoot:1:779'}
        self.repo.reserve_event('chatwoot:1:779', CONVERSATION, 'new')
        self.repo.finish_event('chatwoot:1:779', 'completed')
        self.state['processed_inbound'].append('chatwoot:1:779'); self.save()
        self.assertTrue(self.repo.remember_followup_source(CONVERSATION, newer, self.state))
        with self.repo._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM followup_sources').fetchone()[0], 1)
        self.assertEqual(self.repo.followup_source(CONVERSATION)['event_key'], 'chatwoot:1:779')
    def test_server_installs_callback_on_same_executor_without_new_thread(self):
        from server import create_app
        app = create_app({**self.settings, 'state_dir': self.tmp.name, 'readiness_issues': []},
            repository=self.repo, transport=self.transport, real_guard=lambda _: {'allowed': True})
        worker = app.extensions['v5_real_executor']
        self.assertIs(worker.followup_tick.__self__, app.extensions['v5_followup'])
        self.assertTrue(callable(app.extensions['v5_followup_tick']))
        self.assertIsNone(worker.thread)
    def test_existing_worker_loop_calls_followup_only_when_idle(self):
        from server import create_app
        app = create_app({**self.settings, 'state_dir': self.tmp.name, 'readiness_issues': []},
            repository=self.repo, transport=self.transport, real_guard=lambda _: {'allowed': True})
        worker = app.extensions['v5_real_executor']
        for job_status, expected in [('completed', []), ('idle', ['retention', 'followup'])]:
            calls = []
            worker.stop_event.clear()
            worker.sessions_checked_at = datetime.now(timezone.utc).isoformat()
            worker.tick = lambda: {'status': job_status}
            worker.maintain_retention = lambda: calls.append('retention')
            worker.followup_tick = lambda: calls.append('followup')
            worker.wake_event.wait = lambda _: worker.stop_event.set()
            worker._run()
            self.assertEqual(calls, expected)
    def test_intro_nudge_after_oi_is_inviting_without_presuming_interest_or_buttons(self):
        self.state['cycle']['phase'] = 'intro'; self.save()
        self.assertEqual(self.followup.tick()['status'], 'accepted')
        sent = self.transport.sent[0]
        self.assertEqual(sent['text'], 'Sigo por aqui se precisar 💙 O que você gostaria de conhecer sobre a Amplify?')
        self.assertEqual(sent['buttons'], [])
        self.assertNotIn('agenciamento', sent['text'])
    def test_uncertain_provider_receipt_and_nonterminal_outbox_block_even_if_job_finished(self):
        self.state['cycle']['real_operations'] = {'lookup': {'status': 'outcome_unknown'}}
        self.save(); self.assert_no_send()
        self.state['cycle']['real_operations'] = {}; self.save()
        with self.repo._connection() as db:
            db.execute('INSERT INTO outbox VALUES(?,?,?,?,?,?,?)', ('queued', 'chatwoot:1:777', CONVERSATION,
                '{}', 'queued', None, self.now.isoformat()))
        self.assert_no_send()
    def test_slow_provider_just_replied_waits_five_minutes_before_nudge(self):
        with self.repo._connection() as db:
            db.execute("UPDATE outbox SET updated_at=? WHERE outbox_key='first-reply'", (self.now.isoformat(),))
        self.assertEqual(self.followup.tick()['status'], 'idle')
        self.assertEqual(self.transport.reads, [])
        self.now += timedelta(seconds=300)
        self.assertEqual(self.followup.tick()['status'], 'accepted')
    def test_unmarked_human_public_reply_blocks_even_if_assignment_is_unchanged(self):
        self.transport.messages.append({'id': 780, 'message_type': 1, 'private': False,
            'conversation_id': 26097, 'content': 'Human reply', 'sender': {'id': 7, 'type': 'user'}})
        self.assert_no_send()
    def test_bia_public_reply_is_allowed_only_with_accepted_provider_receipt(self):
        outgoing = {'id': 778, 'message_type': 'outgoing', 'private': False, 'conversation_id': 26097,
            'content': 'Qual é seu @?', 'sender': {'id': 7, 'type': 'user'}}
        self.transport.messages.append(outgoing)
        self.assertEqual(self.followup.tick()['status'], 'accepted')
    def test_actor_attribute_alone_does_not_authorize_an_outgoing(self):
        self.transport.messages.append({'id': 781, 'message_type': 1, 'private': False, 'conversation_id': 26097,
            'content': 'Unknown', 'content_attributes': {'amplify_actor': 'v5_rehearsal'}})
        self.assert_no_send()
    def test_phone_omitted_in_message_requires_fresh_exact_contact_guard(self):
        del self.transport.messages[0]['sender']['phone_number']
        self.assertFalse(self.followup._source_unchanged(self.event, self.state))
        self.assertEqual(self.followup.tick()['status'], 'accepted')
    def test_unconfirmed_invite_post_and_parked_reads_cannot_prompt_to_accept(self):
        self.state['cycle']['phase'] = 'await_acceptance'
        for status in ('pending_verification', 'verification_pending', 'failed'):
            self.state['cycle']['real_operations'] = {'invite': {'status': status,
                'confirmed': False, 'evidence': {'create_accepted': True, 'post_attempted': True}}}
            self.save(); self.assert_no_send()
        # A complete, exact-scope provider observation can guide acceptance.
        self.state['cycle']['facts']['tiktok_declarado'] = '@alice'
        self.state['effects']['real-pending'] = {'type': 'tiktok_operation', 'operation': 'relationship',
            'status': 'done', 'cycle_id': 'cycle', 'creator': '@alice'}
        self.state['cycle']['real_operations']['relationship'] = {'status': 'pending', 'confirmed': True,
            'creator': '@alice', 'cycle_id': 'cycle', 'job_id': 'real-pending',
            'observed_at': self.source_at.isoformat(), 'evidence': {'complete': True}}
        self.save()
        self.assertEqual(self.followup.tick()['status'], 'accepted')
    def test_operational_status_exposes_only_configuration_and_fixed_tick_state(self):
        before = self.followup.status()
        self.assertTrue(before['enabled']); self.assertTrue(before['configured'])
        self.assertEqual(before['delay_seconds'], 300); self.assertIsNone(before['last_tick_at'])
        self.assertEqual(before['status'], 'not_run')
        self.now -= timedelta(seconds=1)
        self.followup.tick()
        after = self.followup.status()
        self.assertEqual(after['status'], 'idle')
        self.assertEqual(after['last_tick_at'], self.now.isoformat())
        self.assertNotIn('phone', str(after)); self.assertNotIn('text', after)
        self.assertEqual(self.transport.sent, [])
    def test_first_inbound_reserved_before_cycle_opening_still_blocks_uncertain_operation(self):
        self.state['cycle']['opened_at'] = (self.source_at+timedelta(microseconds=2)).isoformat()
        self.save()
        self.repo.remember_followup_source(CONVERSATION,self.event,self.state)
        with self.repo._connection() as db:
            db.execute('UPDATE inbound_events SET created_at=? WHERE event_key=?',
                ((self.source_at+timedelta(microseconds=1)).isoformat(),'chatwoot:1:777'))
            db.execute("UPDATE outbox SET updated_at=? WHERE outbox_key='first-reply'",
                ((self.source_at+timedelta(microseconds=3)).isoformat(),))
        self.now += timedelta(seconds=1)
        self.repo.reserve_operation('uncertain-first-turn','chatwoot:1:777','conversation_turn')
        self.assert_no_send()
        self.assertEqual(self.transport.reads,[])
        self.repo.complete_operation('uncertain-first-turn',{'reconciled':True})
        self.assertEqual(self.followup.tick()['status'],'accepted')
    def test_real_reset_invalidates_old_reminder_without_ai_read_or_send(self):
        import real_journey
        previous_creator=self.state['creator_id']
        previous_cycle=self.state['cycle']['id']
        planner_calls=[]
        def forbidden_planner(*args):
            planner_calls.append(True)
            raise AssertionError('reset must not call AI')
        reset=real_journey.handle_real(self.state,'Resetar',forbidden_planner,now=self.now)
        self.assertEqual(planner_calls,[])
        self.assertNotEqual(reset['state']['cycle']['id'],previous_cycle)
        self.assertEqual(reset['state']['cycle']['phase'],'intro')
        self.assertEqual(reset['state']['creator_id'],previous_creator)
        self.assertIn('Bia',reset['reply'])
        self.repo.save_session(CONVERSATION,reset['state'])
        self.assertEqual(self.followup.tick()['status'],'idle')
        self.assertEqual(self.transport.reads,[])
        self.assertEqual(self.transport.sent,[])


if __name__ == '__main__':
    unittest.main()
