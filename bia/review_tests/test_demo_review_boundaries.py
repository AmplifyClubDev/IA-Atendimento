"""Second-pass adversarial review; fake IO only, independently built fixtures."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock

from demo_router import DemoScope, DemoStore, DemoWhatsAppGateway, RecordingGateway, OPENING, opening_payload
from repository import Repository

STAMP = datetime(2026, 2, 1, tzinfo=timezone.utc)
REVIEW_SCOPE = DemoScope('2', '4', '11', '13', '+55' + '21' + '99' + '0' * 7)
KEY = 'bia-demo:v1:' + 'b' * 32 + ':opening'


class FakeChatwoot:
    def __init__(self):
        self.calls = []
        self.detail = {'id': '13', 'account_id': '2', 'inbox_id': '4', 'can_reply': True,
                       'meta': {'sender': {'id': '11', 'phone_number': REVIEW_SCOPE.phone}}}
        self.messages = [{'id': '100', 'message_type': 'incoming', 'private': False,
                          'created_at': (STAMP - timedelta(seconds=10)).timestamp()}]
        self.post_result = {'id': '201', 'conversation_id': '13', 'source_id': 'synthetic-provider-id'}

    def open(self, request, timeout):
        self.calls.append((request.method, request.full_url, json.loads(request.data) if request.data else None))
        if request.method == 'POST':value = self.post_result
        elif request.full_url.endswith('/messages'):value = {'payload': self.messages}
        else:value = self.detail
        return io.BytesIO(json.dumps(value).encode())

    def gateway(self):
        return DemoWhatsAppGateway('https://chat.review.invalid', 'synthetic-review-token', scope=REVIEW_SCOPE,
                                   live_enabled=True, opener=self, now=lambda: STAMP)


class EgressReview(unittest.TestCase):
    def test_future_live_gateway_is_bound_to_one_scope(self):
        fake = FakeChatwoot(); gateway = fake.gateway()
        other = DemoScope('2', '4', '12', '14', '+55' + '31' + '99' + '0' * 7)
        with self.assertRaisesRegex(ValueError, 'scope'):
            gateway.send(other, opening_payload(KEY), KEY)
        with self.assertRaisesRegex(ValueError, 'scope'):gateway.preflight(other)
        self.assertEqual(fake.calls, [])

    def test_only_approved_envelope_can_reach_network(self):
        fake = FakeChatwoot(); gateway = fake.gateway()
        for change in ({'content': 'unapproved copy'}, {'private': True}, {'campaign_id': 1},
                       {'content_type': 'cards'}, {'conversation_id': '14'}, {'template_params': {}}):
            with self.subTest(change=list(change)):
                payload = {**opening_payload(KEY), **change}
                with self.assertRaisesRegex(ValueError, 'approved'):gateway.send(REVIEW_SCOPE, payload, KEY)
        self.assertEqual(fake.calls, [])

    def test_valid_approved_send_has_only_exact_chatwoot_endpoints(self):
        fake = FakeChatwoot(); result = fake.gateway().send(REVIEW_SCOPE, opening_payload(KEY), KEY)
        self.assertEqual(result['message_id'], '201')
        base = 'https://chat.review.invalid/api/v1/accounts/2/conversations/13'
        self.assertEqual([(method, url) for method, url, body in fake.calls],
                         [('GET', base), ('GET', base + '/messages'), ('POST', base + '/messages')])
        self.assertEqual(fake.calls[-1][2], opening_payload(KEY))

    def test_wrong_identity_or_closed_window_never_posts(self):
        for field, value in (('id', '14'), ('account_id', '3'), ('inbox_id', '5'), ('can_reply', False)):
            fake = FakeChatwoot(); fake.detail[field] = value
            with self.assertRaises(ValueError):fake.gateway().send(REVIEW_SCOPE, opening_payload(KEY), KEY)
            self.assertNotIn('POST', [call[0] for call in fake.calls])
        for field, value in (('id', '12'), ('phone_number', '+55' + '31' + '99' + '0' * 7)):
            fake = FakeChatwoot(); fake.detail['meta']['sender'][field] = value
            with self.assertRaises(ValueError):fake.gateway().send(REVIEW_SCOPE, opening_payload(KEY), KEY)
            self.assertNotIn('POST', [call[0] for call in fake.calls])

    def test_missing_or_expired_inbound_never_posts(self):
        for messages in ([], [{'id': '100', 'message_type': 'incoming', 'private': False,
                               'created_at': (STAMP - timedelta(days=1)).timestamp()}]):
            fake = FakeChatwoot(); fake.messages = messages
            with self.assertRaisesRegex(ValueError, 'window'):fake.gateway().send(REVIEW_SCOPE, opening_payload(KEY), KEY)
            self.assertNotIn('POST', [call[0] for call in fake.calls])

    def test_receipt_for_wrong_conversation_is_unconfirmed(self):
        fake = FakeChatwoot(); fake.post_result['conversation_id'] = '14'
        with self.assertRaisesRegex(ValueError, 'unconfirmed'):
            fake.gateway().send(REVIEW_SCOPE, opening_payload(KEY), KEY)
        self.assertEqual([call[0] for call in fake.calls].count('POST'), 1)

    def receipt(self):
        return {**opening_payload(KEY), 'id': '201', 'message_type': 1, 'conversation_id': '13',
                'account_id': '2', 'inbox_id': '4', 'source_id': 'synthetic-provider-id'}

    def test_reconciliation_requires_exact_body_items_and_scope(self):
        for change in ({'content': 'different'}, {'private': True}, {'conversation_id': '14'},
                       {'content_attributes': {'items': [{'title': 'different', 'value': KEY + ':join'}]}}):
            fake = FakeChatwoot(); fake.messages = [{**self.receipt(), **change}]
            self.assertIsNone(fake.gateway().lookup(REVIEW_SCOPE, KEY))
        fake = FakeChatwoot(); fake.messages = [self.receipt()]
        self.assertEqual(fake.gateway().lookup(REVIEW_SCOPE, KEY)['message_id'], '201')
        self.assertEqual([call[0] for call in fake.calls], ['GET'])

    def test_ambiguous_receipt_never_becomes_authority(self):
        fake = FakeChatwoot(); fake.messages = [self.receipt(), {**self.receipt(), 'id': '202'}]
        self.assertIsNone(fake.gateway().lookup(REVIEW_SCOPE, KEY))
        self.assertEqual([call[0] for call in fake.calls], ['GET'])

    def test_preflight_does_not_send_outgoing_business_effects(self):
        fake = FakeChatwoot(); fake.gateway().preflight(REVIEW_SCOPE)
        self.assertTrue(all(method == 'GET' for method, url, body in fake.calls))
        self.assertTrue(all(body is None for method, url, body in fake.calls))


class StorageReview(unittest.TestCase):
    def test_demo_rejects_an_unrelated_database_without_modification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'unrelated.sqlite3'
            db = sqlite3.connect(path); db.execute('CREATE TABLE unrelated(value TEXT)'); db.commit(); db.close()
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'dedicated'):DemoStore(str(path))
            self.assertEqual(path.read_bytes(), before)

    def test_server_checks_actual_supplied_production_repository_path(self):
        from server import create_app
        from test_demo_router import settings
        with tempfile.TemporaryDirectory() as directory:
            repository = Repository(Path(directory) / 'custom-production.sqlite3')
            values = settings(directory); values['demo_state_path'] = str(repository.path)
            with self.assertRaisesRegex(ValueError, 'separate'):
                create_app(values, repository=repository, transport=Mock(), real_client=Mock(), demo_gateway=RecordingGateway())
            with repository._connection() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'demo_%'").fetchone()[0], 0)

    def test_invalid_future_gateway_configuration_creates_no_demo_state(self):
        from demo_router import build_demo_router
        from test_demo_router import settings
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'new-demo.sqlite3'
            values = {**settings(directory), 'demo_state_path': str(path),
                      'demo_whatsapp_live': True, 'chatwoot_base_url': 'http://invalid.example'}
            with self.assertRaises(ValueError):build_demo_router(values)
            self.assertFalse(path.exists())
