"""Offline native title round trip; no provider call or invitation is executed."""
from copy import deepcopy
from datetime import timedelta
import unittest

import conversation
from server import normalize_chatwoot
from transport import ChatwootTransport
from test_real_journey import NOW, POLICY, GATE, eligible_state


class NativeConsentTitle31Tests(unittest.TestCase):
    def render(self):
        calls = []
        def http(**kwargs):
            calls.append(kwargs)
            if kwargs['method'] == 'GET':
                return {'id': 26097, 'account_id': 1, 'inbox_id': 3, 'can_reply': True,
                        'meta': {'sender': {'id': 3, 'phone_number': GATE['phone']}}}
            return {'id': 9000}
        transport = ChatwootTransport('https://chatwoot.t2ffoz.easypanel.host',
                                      'offline-fake-token', GATE, http=http)
        event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': '1', 'inbox_id': '3',
                 'conversation_id': '26097', 'message_id': '8000', 'contact_id': '3',
                 'sender_phone': GATE['phone'], 'sender_type': 'contact', 'message_type': 'incoming',
                 'private': False, 'text': 'Quero me agenciar'}
        offer = 'Taxa de 10% sobre suas comissões, por 2 meses. Você autoriza o convite?'
        receipt = transport.send_reply(event, offer, ['Autorizo o convite real', 'Não autorizo'], 'offline:native-title')
        self.assertEqual(receipt['status'], 'accepted')
        self.assertEqual([call['method'] for call in calls], ['GET', 'POST'])
        return calls[-1]['json_body'], offer

    def test_native_outgoing_has_short_recognized_title_and_full_unchanged_value(self):
        payload, offer = self.render()
        self.assertEqual(payload['content'], offer)
        self.assertEqual(payload['content_type'], 'input_select')
        self.assertEqual(payload['content_attributes']['items'], [
            {'title': 'Pode enviar', 'value': 'Autorizo o convite real'},
            {'title': 'Não autorizo', 'value': 'Não autorizo'}])
        self.assertLessEqual(len(payload['content_attributes']['items'][0]['title']), 20)

    def test_incoming_title_authorizes_only_the_current_valid_offer_and_precheck(self):
        payload, _ = self.render()
        title = payload['content_attributes']['items'][0]['title']
        original = eligible_state()['state']
        for number, invalid in enumerate((None, 'missing_offer', 'unconfirmed_precheck', 'stale_precheck', 'invalid_policy')):
            with self.subTest(invalid=invalid):
                state, policy = deepcopy(original), dict(POLICY)
                if invalid == 'missing_offer':
                    state['cycle'].pop('invite_offer', None)
                elif invalid == 'unconfirmed_precheck':
                    state['cycle']['real_operations']['precheck']['confirmed'] = False
                elif invalid == 'stale_precheck':
                    state['cycle']['real_operations']['precheck']['observed_at'] = (NOW-timedelta(minutes=16)).isoformat()
                elif invalid == 'invalid_policy':
                    policy['approved'] = False
                event = normalize_chatwoot({'event': 'message_created', 'id': 8100+number, 'content': title,
                    'message_type': 'incoming', 'private': False, 'created_at': NOW.isoformat(),
                    'account': {'id': 1}, 'inbox': {'id': 3},
                    'conversation': {'id': 26097, 'account_id': 1, 'inbox_id': 3},
                    'sender': {'id': 3, 'type': 'contact', 'phone_number': GATE['phone']}})
                self.assertEqual(event['text'], 'Pode enviar')
                result = conversation.handle_event(state, event, GATE, now=NOW, real_mode=True,
                    operation_policy=policy, relationship_check_in_form=True)
                invites = [effect for effect in result['effects'] if effect.get('operation') == 'invite']
                if invalid is None:
                    self.assertEqual(len(invites), 1)
                    self.assertTrue(invites[0]['confirmed'])
                    self.assertEqual(invites[0]['creator'], '@teste')
                    self.assertEqual(invites[0]['consent'], result['state']['cycle']['invite_consent'])
                else:
                    self.assertEqual(invites, [])


if __name__ == '__main__':
    unittest.main()
