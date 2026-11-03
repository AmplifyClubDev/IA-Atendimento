"""Finite origin choices use the existing scoped Chatwoot transport unchanged."""
import unittest

from transport import ChatwootTransport


class OperationalMenu28Tests(unittest.TestCase):
    def test_three_origin_choices_keep_full_values_and_input_select_contract(self):
        gate = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3', 'phone': '+5547991154859'}
        event = {'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3', 'conversation_id': '26097',
                 'contact_id': '3', 'message_id': '313154', 'sender_phone': gate['phone'],
                 'message_type': 'incoming', 'private': False, 'text': 'Quero me agenciar'}
        calls = []
        def http(**kwargs):
            calls.append(kwargs)
            if kwargs['method'] == 'GET':
                return {'id': 26097, 'account_id': 1, 'inbox_id': 3, 'can_reply': True,
                        'meta': {'sender': {'id': 3, 'phone_number': gate['phone']}}}
            return {'id': 999}
        adapter = ChatwootTransport('https://chatwoot.t2ffoz.easypanel.host', 'fixture-token', gate, http=http)
        result = adapter.send_reply(event, 'Como você conheceu a Amplify?', ['Anúncio', 'Indicação', 'Outro'], 'fixture-origin28')
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual([call['method'] for call in calls], ['GET', 'POST'])
        body = calls[1]['json_body']
        self.assertEqual(body['content_type'], 'input_select')
        self.assertEqual(body['content_attributes']['items'], [
            {'title': 'Anúncio', 'value': 'Anúncio'}, {'title': 'Indicação', 'value': 'Indicação'}, {'title': 'Outro', 'value': 'Outro'}])
        self.assertEqual(body['content_attributes']['amplify_idempotency_key'], 'fixture-origin28')
        self.assertIn('/accounts/1/conversations/26097/messages', calls[1]['url'])
        self.assertFalse(body['private'])


if __name__ == '__main__':
    unittest.main()
