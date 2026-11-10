"""Synthetic offline coverage for reply-only image handling. No live messages."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import contracts
import server
from repository import Repository
from transport import ChatwootTransport
from test_demo_router import settings, PHONE, OTHER, TOKEN

class ImageGuidance(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.config = settings(self.directory.name, enabled=False)
        self.repo = Repository(Path(self.directory.name) / 'state.sqlite3')
        self.calls = []
        self.detail = {'id': '7', 'account_id': '1', 'inbox_id': '3', 'can_reply': True, 'status': 'open',
                       'labels': [], 'custom_attributes': {},
                       'meta': {'sender': {'id': '9', 'phone_number': PHONE}, 'assignee': None}}
        self.fail_post = False; self.pause_on_target = False; self.gets = 0
        def http(**call):
            self.calls.append(call)
            if call['method'] == 'GET':
                self.gets += 1
                if self.pause_on_target and self.gets >= 3:
                    self.detail['custom_attributes']['human_control'] = True
                return deepcopy(self.detail)
            if self.fail_post:
                raise TimeoutError('synthetic uncertainty')
            return {'id': '202'}
        self.transport = ChatwootTransport('https://chat.example.invalid', 'synthetic-token', self.config['gate'], http=http)
        self.planner = Mock(side_effect=AssertionError('No image may reach LLM'))
        self.app = server.create_app(self.config, repository=self.repo, transport=self.transport,
                                     planner=self.planner, answerer=self.planner, real_client=Mock())
        self.app.testing = True
        self.client = self.app.test_client()
        self.state = {'revision': 4, 'processed_inbound': ['chatwoot:1:100'],
                      'cycle': {'id': 'synthetic-cycle', 'phase': 'await_acceptance', 'status': 'open',
                                'facts': {'tiktok_declarado': '@synthetic'}, 'invite_consent': {'status': 'confirmed'}},
                      'effects': {'existing': {'operation': 'relationship', 'status': 'pending'}},
                      'history': []}
        self.repo.save_session('chatwoot:1:7', deepcopy(self.state))
    def payload(self, **changes):
        p = {'event': 'message_created', 'id': '101', 'message_type': 'incoming', 'private': False,
             'content': None, 'created_at': datetime.now(timezone.utc).isoformat(),
             'account': {'id': '1'}, 'inbox': {'id': '3'},
             'sender': {'id': '9', 'phone_number': PHONE, 'type': 'contact'},
             'conversation': {'id': '7', 'account_id': '1', 'inbox_id': '3', 'meta': {'sender': {'id': '9', 'phone_number': PHONE}}},
             'attachments': [{'id': 42, 'file_type': 'image', 'data_url': 'https://media.example.invalid/private'}]}
        p.update(changes); return p
    def send(self, payload=None):
        return self.client.post('/webhook/chatwoot', json=payload or self.payload(), headers={'X-Amplify-Webhook-Token': TOKEN})
    def posts(self):return [r for r in self.calls if r['method'] == 'POST']
    def test_captionless_image_has_one_fixed_reply_and_no_business_effects(self):
        result = self.send()
        self.assertEqual(result.status_code, 200); self.assertEqual(result.json['status'], 'completed')
        self.assertEqual(len(self.posts()), 1)
        body = self.posts()[0]['json_body']; self.assertEqual(body['content'], contracts.IMAGE_ONLY_REPLY)
        self.assertEqual(body['content_type'], 'text'); self.assertFalse(body['private'])
        self.planner.assert_not_called()
        state = self.repo.load_session('chatwoot:1:7')
        self.assertEqual(state['cycle'], self.state['cycle']); self.assertEqual(state['effects'], self.state['effects'])
        self.assertEqual(state['history'], []); self.assertEqual(state['processed_inbound'][-1], 'chatwoot:1:101')
        self.assertIsNone(self.repo.followup_source('chatwoot:1:7'))
        with self.repo._connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM real_jobs').fetchone()[0], 0)
    def test_duplicate_does_not_send_twice(self):
        p=self.payload(); self.send(p); result=self.send(p)
        self.assertTrue(result.json['duplicate']); self.assertEqual(len(self.posts()), 1)
    def test_uncertain_send_is_not_retried(self):
        self.fail_post=True; p=self.payload(); first=self.send(p); second=self.send(p)
        self.assertEqual(first.json['status'], 'outcome_unknown'); self.assertTrue(second.json['duplicate'])
        self.assertEqual(len(self.posts()), 1)
    def test_image_data_is_not_copied_or_downloaded(self):
        event=server.normalize_chatwoot(self.payload())
        self.assertEqual(event['image_attachment_ids'], ['42']); self.assertIsNone(event['text'])
        self.assertNotIn('private', str(event.get('image_attachment_ids')))
        self.send(); self.assertTrue(all('media.example.invalid' not in c['url'] for c in self.calls))
    def test_original_text_contract_stays_closed_for_image(self):
        event=server.normalize_chatwoot(self.payload())
        self.assertFalse(contracts.allow_inbound(self.config['gate'],event))
        self.assertTrue(contracts.allow_image_inbound(self.config['gate'],event))
    def test_private_outgoing_foreign_and_conflicting_identity_ignored(self):
        cases=[{'private':True},{'message_type':'outgoing'},{'account':{'id':'2'}},
               {'sender':{'id':'10','phone_number':OTHER,'type':'contact'}},
               {'sender':{'id':'9','phone_number':PHONE,'type':'user'}}]
        for case in cases:
            with self.subTest(case=case):self.assertEqual(self.send(self.payload(**case)).status_code,202)
        self.assertEqual(self.posts(),[])
    def test_unknown_audio_mixed_and_invalid_attachments_ignored(self):
        for attachments in ([],None,[{'id':42,'file_type':'audio'}],[{'id':True,'file_type':'image'}],
                            [{'id':42,'file_type':'image'},{'id':43,'file_type':'audio'}]):
            with self.subTest(attachments=attachments):
                self.assertEqual(self.send(self.payload(attachments=attachments)).status_code,202)
        self.assertEqual(self.posts(),[])
    def test_human_assignment_control_or_closed_window_blocks(self):
        for change in ('assignee','human_control','can_reply','status'):
            with self.subTest(change=change):
                detail=deepcopy(self.detail)
                if change=='assignee': self.detail['meta']['assignee']={'id':'999','type':'user'}
                elif change=='human_control':self.detail['custom_attributes']['human_control']=True
                elif change=='can_reply':self.detail['can_reply']=False
                else:self.detail['status']='resolved'
                self.assertEqual(self.send().status_code,202);self.detail=detail
        self.assertEqual(self.posts(),[])
    def test_control_is_rechecked_immediately_before_send(self):
        self.pause_on_target=True;result=self.send()
        self.assertEqual(result.json['status'],'failed');self.assertEqual(self.posts(),[])
    def test_local_human_control_blocks(self):
        state=deepcopy(self.state);state['human_control']=True;self.repo.save_session('chatwoot:1:7',state)
        self.assertEqual(self.send().status_code,202);self.assertEqual(self.posts(),[])
    def test_stale_image_records_without_reply_or_cursor_regression(self):
        result=self.send(self.payload(id='99'));self.assertEqual(result.json['status'],'completed')
        self.assertEqual(self.posts(),[]);self.assertEqual(self.repo.load_session('chatwoot:1:7')['processed_inbound'][-1],'chatwoot:1:100')
    def test_transport_refuses_other_copy_or_buttons_for_image(self):
        event=server.normalize_chatwoot(self.payload())
        for copy,buttons in [('Seu convite foi enviado',[]),(contracts.IMAGE_ONLY_REPLY,['Aceitei'])]:
            result=self.transport.send_reply(event,copy,buttons,'synthetic-key',image_only=True)
            self.assertEqual(result['status'],'failed')
        self.assertEqual(self.posts(),[])
    def test_unknown_attachment_shapes_fail_closed(self):
        event=server.normalize_chatwoot(self.payload())
        for images in ([{}],[True],['42','42'],['0'],['42']*5):
            with self.subTest(images=images):
                event['image_attachment_ids']=images
                self.assertFalse(contracts.allow_image_inbound(self.config['gate'],event))
    def test_missing_timestamp_or_contact_rejected(self):
        for case in ({'created_at':None},{'sender':{'phone_number':PHONE,'type':'contact'},'conversation':{'id':'7','account_id':'1','inbox_id':'3'}}):
            self.assertEqual(self.send(self.payload(**case)).status_code,202)
        self.assertEqual(self.posts(),[])
    def test_unauthenticated_webhook_never_reads_or_sends(self):
        result=self.client.post('/webhook/chatwoot',json=self.payload())
        self.assertEqual(result.status_code,401);self.assertEqual(self.calls,[])

if __name__=='__main__':unittest.main(verbosity=2)
