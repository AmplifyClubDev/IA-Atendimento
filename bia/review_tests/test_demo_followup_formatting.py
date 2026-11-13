"""Readable follow-ups preserve words, timing, exact receipts and send boundaries."""
import json
import unittest

import demo_followup
import test_demo_followup as reminder_fixtures
import test_demo_inactivity_close as closure_fixtures
import test_demo_resolution_receipt as receipt_fixtures


class FollowupFormatting(unittest.TestCase):
    def test_warning_has_three_short_paragraphs_and_preserves_original_words(self):
        original = ('Ainda estou por aqui 😊 Quer continuar de onde paramos? '
                    'Se não houver resposta em mais 10 minutos, encerro este atendimento por agora.')
        paragraphs = demo_followup.PAYLOAD['content'].split('\n\n')
        self.assertEqual(paragraphs, [
            'Ainda estou por aqui 😊',
            'Quer continuar de onde paramos?',
            'Se não houver resposta em mais 10 minutos, encerro este atendimento por agora.'])
        self.assertEqual(' '.join(paragraphs), original)

    def test_closure_separates_thanks_and_preserves_original_words(self):
        paragraphs = demo_followup.CLOSE_PAYLOAD['content'].split('\n\n')
        self.assertEqual(paragraphs, [
            'Como não tivemos resposta, encerrei este atendimento por agora.',
            'Obrigada pela conversa! 💙'])
        self.assertEqual(' '.join(paragraphs), demo_followup.PRE_FORMAT_CLOSE_PAYLOAD['content'])

    def test_both_payloads_are_plain_whatsapp_text_with_real_line_breaks(self):
        for payload in (demo_followup.PAYLOAD, demo_followup.CLOSE_PAYLOAD):
            with self.subTest(payload=payload):
                self.assertEqual(set(payload), {'content', 'message_type', 'private', 'content_type'})
                self.assertEqual(payload['message_type'], 'outgoing')
                self.assertIs(payload['private'], False)
                self.assertEqual(payload['content_type'], 'text')
                content = json.loads(json.dumps(payload))['content']
                self.assertIn('\n\n', content)
                self.assertNotIn('\\n', content)
                self.assertNotRegex(content, r'[*_`<>\r]')
                self.assertNotIn('\n\n\n', content)
                self.assertEqual(content, content.strip())
                self.assertTrue(all(line == line.strip() for line in content.splitlines()))


class FollowupWireFormatting(unittest.TestCase):
    setup_live = reminder_fixtures.LiveGatewayReminders.setup_live

    def test_provider_warning_preserves_paragraphs_in_one_message(self):
        provider, router = self.setup_live()
        self.assertEqual(demo_followup.tick(router)['status'], 'accepted')
        posts = [call for call in provider.calls if call[0] == 'POST']
        self.assertEqual(len(posts), 2)  # One opening, then one warning.
        self.assertEqual(posts[-1][2], demo_followup.PAYLOAD)
        self.assertEqual(posts[-1][2]['content'].count('\n\n'), 2)
        self.assertEqual(demo_followup.tick(router)['status'], 'idle')


class ClosureWireFormatting(unittest.TestCase):
    setUp = closure_fixtures.ProviderClose.setUp

    def test_provider_closure_preserves_paragraphs_and_resolves_once(self):
        self.assertEqual(demo_followup.tick(self.router)['status'], 'closed')
        notices = [call for call in self.provider.calls
                   if call[0] == 'POST' and call[1].endswith('/messages')]
        self.assertEqual(len(notices), 3)  # Opening, warning, closing notice.
        self.assertEqual(notices[-1][2], demo_followup.CLOSE_PAYLOAD)
        self.assertEqual(notices[-1][2]['content'].count('\n\n'), 1)
        self.assertEqual(demo_followup.tick(self.router)['status'], 'idle')
        self.assertEqual(len([call for call in self.provider.calls
                              if call[1].endswith('/toggle_status')]), 1)


class PreFormatClosureReceipt(unittest.TestCase):
    setUp = receipt_fixtures.HistoricalReadback.setUp
    status = receipt_fixtures.HistoricalReadback.status

    def set_historical_payload(self, payload):
        self.store.db.execute('UPDATE demo_closures SET payload=?', (json.dumps(payload),))
        self.provider.messages[0]['content'] = payload['content']

    def test_pre_format_receipt_can_be_verified_by_reads_only_without_rewriting(self):
        payload = demo_followup.PRE_FORMAT_CLOSE_PAYLOAD
        self.set_historical_payload(payload)
        self.assertEqual(demo_followup.reconcile_resolutions(self.router), 1)
        self.assertEqual(self.status(), 'resolved')
        persisted = json.loads(self.store.db.execute('SELECT payload FROM demo_closures').fetchone()[0])
        self.assertEqual(persisted, payload)
        self.assertEqual([method for method, _ in self.provider.calls], ['GET', 'GET', 'GET'])
        self.assertEqual(self.provider.posts, 0)

    def test_pre_format_receipt_does_not_accept_reformatted_remote_message(self):
        self.set_historical_payload(demo_followup.PRE_FORMAT_CLOSE_PAYLOAD)
        self.provider.messages[0]['content'] = demo_followup.CLOSE_PAYLOAD['content']
        self.assertEqual(demo_followup.reconcile_resolutions(self.router), 0)
        self.assertEqual(self.status(), 'resolve_unknown')
        self.assertEqual(self.provider.posts, 0)

    def test_pre_format_allowlist_stays_exact_and_rejects_arbitrary_whitespace(self):
        payload = demo_followup.PRE_FORMAT_CLOSE_PAYLOAD
        for changes in ({'content': payload['content'] + ' '},
                        {'content': payload['content'].replace('. ', '.\n')},
                        {'private': 0}, {'private': True}, {'extra': 'field'}):
            with self.subTest(changes=changes):
                self.set_historical_payload({**payload, **changes})
                self.assertEqual(demo_followup.reconcile_resolutions(self.router), 0)
        self.assertEqual(self.status(), 'resolve_unknown')
        self.assertEqual(self.provider.calls, [])
