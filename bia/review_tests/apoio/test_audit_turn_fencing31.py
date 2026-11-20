"""Offline ingress races: a newer lead turn cancels an older unsent reply."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import time
import unittest

import conversation
from contracts import inbound_key
from repository import Repository
from server import create_app, normalize_chatwoot
from transport import ChatwootTransport

PHONE = '+5547991154859'
CONV = 'chatwoot:1:26097'
CREATOR = '22222222-2222-4222-8222-222222222222'
GATE = dict(enabled=True, provider='chatwoot', account_id='1', inbox_id='3', phone=PHONE)


class Client:
    def configuration(self, *args):
        return {'configured': True}


class Gateway:
    def register_contact(self, entry):
        return dict(creator_id=CREATOR, atendimento_id=entry['atendimento_id'],
                    event_id=entry['event_id'], revision=entry['revision'])


class HTTP:
    def __init__(self):
        self.posts, self.reads, self.before_get = [], [], None
    def __call__(self, *, method, url, **kwargs):
        if method == 'GET':
            self.reads.append(url)
            callback, self.before_get = self.before_get, None
            if callback:
                callback()
            return {'id': 26097, 'account_id': 1, 'inbox_id': 3, 'can_reply': True,
                    'meta': {'sender': {'id': 3, 'phone_number': PHONE}}}
        assert method == 'POST' and url.endswith('/messages')
        self.posts.append(deepcopy(kwargs))
        return {'id': 900000 + len(self.posts)}


class TurnFencing31Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='turn-fence31-')
        self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name) / 'state.sqlite3')
        self.now = datetime.now(timezone.utc) - timedelta(seconds=30)
        self.http = HTTP()
        self.transport = ChatwootTransport('https://chatwoot.t2ffoz.easypanel.host',
                                          'offline-fake-token', GATE, http=self.http)
        self.entered, self.release = threading.Event(), threading.Event()
        self.addCleanup(self.release.set)
        self.calls, self.responses, self.threads = [], {}, []
        self.slow = False
        def planner(text, context, settings):
            self.calls.append(text)
            if self.slow and text == 'Resetae':
                self.entered.set()
                if not self.release.wait(5):
                    raise AssertionError('offline planner was not released')
            return {'provider_status': 'completed', 'claims': [], 'intent': 'converse',
                    'reply': 'A Amplify orienta creators na parceria.',
                    'next_phase': context['phase'], 'topic_ids': ['amplify']}
        self.settings = dict(gate=GATE, webhook_token='offline-test-token-long-enough',
            state_dir=self.temp.name, readiness_issues=[], instance_id='test',
            conversation_enabled=True, ai_enabled=True, contact_sync_enabled=True,
            tiktok_mode='real', real_worker_enabled=True)
        self.app = create_app(self.settings, self.repo, self.transport, planner=planner,
                              real_client=Client(), real_guard=lambda event: {'allowed': True})
        self.app.extensions['v5_data_gateway'] = Gateway()

    def payload(self, identifier, text='Resetae', *, seconds=0, inbox=3):
        return dict(event='message_created', id=identifier, content=text,
            message_type='incoming', private=False, created_at=(self.now+timedelta(seconds=seconds)).isoformat(),
            account={'id': 1}, inbox={'id': inbox},
            conversation={'id': 26097, 'account_id': 1, 'inbox_id': inbox,
                'meta': {'sender': {'id': 3, 'type': 'contact', 'phone_number': PHONE}}},
            sender={'id': 3, 'type': 'contact', 'phone_number': PHONE})

    def post(self, body):
        with self.app.test_client() as client:
            result = client.post('/webhook/chatwoot', json=body,
                headers={'X-Amplify-Webhook-Token': self.settings['webhook_token']})
            return result.status_code, result.get_json()

    def start(self, label, body):
        thread = threading.Thread(target=lambda: self.responses.__setitem__(label, self.post(body)), daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def join(self):
        self.release.set()
        for thread in self.threads:
            thread.join(5)
            self.assertFalse(thread.is_alive(), 'offline request did not complete')

    def wait_new_source(self, old):
        event = normalize_chatwoot(old)
        fence = self.app.extensions['v5_reply_fence']
        until = time.monotonic()+3
        while fence.current(event) and time.monotonic() < until:
            threading.Event().wait(.005)
        self.assertFalse(fence.current(event), 'new reservation was not exposed before lock')

    def source_posts(self, identifier):
        key = f'chatwoot:1:{identifier}:reply'
        return [row for row in self.http.posts if row['headers']['Idempotency-Key'] == key]

    def test_reset_reserved_while_ai_waits_suppresses_old_reply_and_greets_once(self):
        self.slow = True
        old, reset = self.payload(313803), self.payload(313804, 'Resetar', seconds=6)
        self.start('old', old)
        self.assertTrue(self.entered.wait(3))
        self.start('reset', reset)
        self.wait_new_source(old)
        guard = self.app.extensions['v5_real_executor'].guard(normalize_chatwoot(old))
        self.assertFalse(guard['allowed'])
        self.assertEqual(guard['reason'], 'new_reset_pending')
        self.join()
        self.assertEqual(self.source_posts(313803), [])
        self.assertEqual(len(self.source_posts(313804)), 1)
        self.assertEqual(self.source_posts(313804)[0]['json_body']['content'], conversation._RESET_GREETING)
        state = self.repo.load_session(CONV)
        self.assertEqual(state['creator_id'], CREATOR)
        self.assertEqual(state['cycle']['phase'], 'intro')
        last = datetime.fromisoformat(state['cycle']['last_inbound_at'].replace('Z','+00:00'))
        expires = datetime.fromisoformat(state['cycle']['expires_at'].replace('Z','+00:00'))
        self.assertEqual(expires-last, timedelta(hours=24))
        self.assertTrue(self.app.extensions['v5_real_executor'].guard(normalize_chatwoot(reset))['allowed'])
        self.assertTrue(self.post(reset)[1]['duplicate'])
        self.assertEqual(len(self.source_posts(313804)), 1)

    def test_reset_barrier_survives_a_later_ordinary_message_waiting_for_lock(self):
        self.slow = True
        old = self.payload(1000)
        reset = self.payload(1001, 'Resetar', seconds=1)
        newer = self.payload(1002, 'oi', seconds=2)
        self.start('old', old)
        self.assertTrue(self.entered.wait(3))
        self.start('reset', reset)
        self.wait_new_source(old)
        self.start('newer', newer)
        self.wait_new_source(reset)
        self.assertFalse(self.app.extensions['v5_real_executor'].guard(normalize_chatwoot(old))['allowed'])
        self.join()
        state = self.repo.load_session(CONV)
        self.assertIn('chatwoot:1:1001', state['processed_inbound'])
        self.assertIn('chatwoot:1:1002', state['processed_inbound'])
        self.assertEqual(len(state['closed_cycles']), 1)
        self.assertEqual(self.source_posts(1000), [])
        self.assertEqual(len(self.source_posts(1002)), 1)
        self.assertTrue(self.app.extensions['v5_real_executor'].guard(normalize_chatwoot(newer))['allowed'])

    def test_larger_ordinary_processed_id_is_not_proof_that_reset_ran(self):
        reset = normalize_chatwoot(self.payload(1100, 'Resetar'))
        newer = normalize_chatwoot(self.payload(1101, 'oi', seconds=1))
        fence = self.app.extensions['v5_reply_fence']
        fence.observe(reset, reset=True)
        fence.observe(newer)
        self.assertTrue(fence.reset_waiting({'processed_inbound': ['chatwoot:1:1101']}, newer))
        self.assertFalse(fence.reset_waiting({'processed_inbound': ['chatwoot:1:1100', 'chatwoot:1:1101']}, newer))

    def test_new_question_cancels_stale_reply_without_canceling_authorized_jobs(self):
        self.slow = True
        old, newer = self.payload(100), self.payload(101, 'Quais os benefícios?', seconds=1)
        self.start('old', old)
        self.assertTrue(self.entered.wait(3))
        self.start('newer', newer)
        self.wait_new_source(old)
        self.assertTrue(self.app.extensions['v5_real_executor'].guard(normalize_chatwoot(old))['allowed'])
        self.join()
        self.assertEqual(self.source_posts(100), [])
        self.assertEqual(len(self.source_posts(101)), 1)
        self.assertIn('chatwoot:1:100', self.repo.load_session(CONV)['processed_inbound'])
        self.assertIn('chatwoot:1:101', self.repo.load_session(CONV)['processed_inbound'])

    def test_duplicate_during_ai_wait_does_not_cancel_or_regenerate_reply(self):
        self.slow = True
        body = self.payload(200)
        self.start('old', body)
        self.assertTrue(self.entered.wait(3))
        duplicate = self.post(body)
        self.assertTrue(duplicate[1]['duplicate'])
        self.join()
        self.assertEqual(self.calls, ['Resetae'])
        self.assertEqual(len(self.source_posts(200)), 1)

    def test_conflicting_duplicate_does_not_cancel_current_reply(self):
        self.slow = True
        body = self.payload(300)
        self.start('old', body)
        self.assertTrue(self.entered.wait(3))
        conflict = self.post({**body, 'content': 'Resetar'})
        self.assertEqual(conflict[1]['status'], 'event_conflict')
        self.join()
        self.assertEqual(len(self.source_posts(300)), 1)

    def test_other_channel_cannot_invalidate_the_pilot_reply(self):
        self.slow = True
        body = self.payload(400)
        self.start('old', body)
        self.assertTrue(self.entered.wait(3))
        self.assertEqual(self.post(self.payload(999, 'Resetar', inbox=4))[1]['status'], 'ignored')
        self.join()
        self.assertEqual(len(self.source_posts(400)), 1)
        self.assertIsNone(self.repo.event('chatwoot:1:999'))

    def test_reset_during_recipient_get_is_checked_again_immediately_before_post(self):
        old, reset = self.payload(500, 'oi'), self.payload(501, 'Resetar', seconds=1)
        def during_get():
            self.start('reset', reset)
            self.wait_new_source(old)
        self.http.before_get = during_get
        status, result = self.post(old)
        self.join()
        self.assertEqual(status, 200)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.source_posts(500), [])
        self.assertEqual(len(self.source_posts(501)), 1)
        outbox = self.repo.outbox('chatwoot:1:500')
        self.assertEqual(outbox[0]['status'], 'failed')
        self.assertEqual(outbox[0]['receipt']['reason'], 'reply_superseded_by_new_inbound')

    def test_data_before_a_proven_reset_is_historical_without_touching_new_cycle(self):
        self.assertEqual(self.post(self.payload(102, 'Resetar', seconds=5))[1]['status'], 'completed')
        before = self.repo.load_session(CONV)
        calls = len(self.calls)
        late = self.post(self.payload(101, 'Me chamo Antigo, vim por indicação, meu @ é @antigo'))
        self.assertEqual(late[1]['status'], 'completed')
        self.assertTrue(late[1]['reply_suppressed'])
        after = self.repo.load_session(CONV)
        self.assertEqual(after['cycle'], before['cycle'])
        self.assertEqual(after['revision'], before['revision'])
        self.assertEqual(after['creator_id'], before['creator_id'])
        self.assertEqual(after['cycle']['facts'], {})
        self.assertEqual(after['processed_inbound'][-1], 'chatwoot:1:102')
        self.assertEqual(len(self.calls), calls)
        self.assertIn('chatwoot:1:101', after['processed_inbound'])
        self.assertEqual(after['history'][-1]['source_ref'], 'chatwoot:1:101')
        self.assertNotEqual(after['history'][-1]['cycle_id'], after['cycle']['id'])
        self.assertEqual(self.source_posts(101), [])
        self.assertEqual(self.repo.event('chatwoot:1:101')['status'], 'completed')

    def test_late_ordinary_data_without_reset_preserves_both_updates(self):
        self.settings.update(followup_enabled=True, followup_delay_seconds='300',
                             followup_start_at=(self.now-timedelta(hours=1)).isoformat())
        self.assertEqual(self.post(self.payload(1202, 'Quero me agenciar', seconds=2))[1]['status'], 'completed')
        before = self.repo.load_session(CONV)
        self.assertEqual(self.post(self.payload(1201, 'Vim por indicação'))[1]['status'], 'completed')
        after = self.repo.load_session(CONV)
        self.assertEqual(after['cycle']['id'], before['cycle']['id'])
        self.assertEqual(after['revision'], before['revision']+1)
        self.assertEqual(after['cycle']['facts']['origem_declarada'], 'indicacao')
        self.assertIn('chatwoot:1:1201', after['processed_inbound'])
        self.assertIn('chatwoot:1:1202', after['processed_inbound'])
        self.assertEqual(after['processed_inbound'][-1], 'chatwoot:1:1202')
        self.assertEqual(self.repo.followup_source(CONV)['event_key'], 'chatwoot:1:1202')
        self.assertTrue(self.app.extensions['v5_followup']._eligible(
            self.repo.followup_source(CONV), after, self.now+timedelta(seconds=302)))
        self.assertEqual(self.source_posts(1201), [])

    def test_late_reset_cannot_clear_newer_already_processed_lead(self):
        self.assertEqual(self.post(self.payload(1302, 'Quero me agenciar', seconds=2))[1]['status'], 'completed')
        before = self.repo.load_session(CONV)
        late = self.post(self.payload(1301, 'Resetar'))
        self.assertEqual(late[1]['status'], 'completed')
        self.assertTrue(late[1]['reply_suppressed'])
        after = self.repo.load_session(CONV)
        self.assertEqual(after['cycle'], before['cycle'])
        self.assertEqual(after['revision'], before['revision'])
        self.assertEqual(after['cycle']['facts']['interesse_agenciamento'], True)
        self.assertEqual(after['processed_inbound'][-1], 'chatwoot:1:1302')
        self.assertEqual(self.source_posts(1301), [])
        self.assertTrue(self.app.extensions['v5_real_executor'].guard(normalize_chatwoot(self.payload(1302)))['allowed'])

    def test_old_controls_cannot_answer_or_authorize_a_newer_consent_offer(self):
        from test_real_journey import eligible_state
        state = eligible_state()['state']
        state['creator_id'] = CREATOR
        state['processed_inbound'] = ['chatwoot:1:1402']
        self.repo.reserve_event('chatwoot:1:1402', CONV, 'offline-seed')
        self.repo.prepare_reply('chatwoot:1:1402', CONV, state, 'seed:no-reply', None)
        self.repo.finish_event('chatwoot:1:1402', 'completed')
        for identifier, text in zip((1401, 1400, 1399, 1398),
                                     ('Sim', 'Não', 'Autorizo o convite real', 'Encerrar agora')):
            with self.subTest(text=text):
                before = self.repo.load_session(CONV)
                response = self.post(self.payload(identifier, text))
                self.assertEqual(response[1]['status'], 'completed')
                self.assertTrue(response[1]['reply_suppressed'])
                after = self.repo.load_session(CONV)
                self.assertEqual(after['cycle'], before['cycle'])
                self.assertEqual(after['effects'], before['effects'])
                self.assertEqual(after['revision'], before['revision'])
                self.assertEqual(after['processed_inbound'][-1], 'chatwoot:1:1402')
                self.assertTrue(after['history'][-1]['late_control'])
                self.assertNotEqual(after['history'][-1]['cycle_id'], after['cycle']['id'])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.http.posts, [])

    def test_transport_canceled_authority_never_posts(self):
        event = normalize_chatwoot(self.payload(700, 'oi'))
        result = self.transport.send_reply(event, 'Resposta válida.', [], 'offline:700', before_write=lambda: False)
        self.assertEqual(result['reason'], 'send_cancelled_before_post')
        self.assertEqual(self.http.posts, [])

    def test_transport_authority_error_never_posts(self):
        event = normalize_chatwoot(self.payload(701, 'oi'))
        def unavailable():
            raise RuntimeError('offline source unavailable')
        result = self.transport.send_reply(event, 'Resposta válida.', [], 'offline:701', before_write=unavailable)
        self.assertEqual(result['reason'], 'send_cancelled_before_post')
        self.assertEqual(self.http.posts, [])

    def test_single_current_turn_still_posts_once_with_normal_receipt(self):
        body = self.payload(800, 'Resetar')
        self.assertEqual(self.post(body)[1]['status'], 'completed')
        self.assertEqual(len(self.source_posts(800)), 1)
        self.assertEqual(self.repo.outbox('chatwoot:1:800')[0]['status'], 'accepted')


if __name__ == '__main__':
    unittest.main()
