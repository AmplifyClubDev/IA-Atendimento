"""UI opt-in, one-attempt sending and bounded upstream diagnostics; scripted HTTP only."""
from copy import deepcopy
import unittest

from config import load_settings
from playwright_client import PlaywrightClient
from tests.test_playwright_client import SETTINGS, Script, invitation_prefix, accepted_invite, ready, relation


GATE = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3', 'phone': '+5547991154859'}
UI_SETTINGS = {**SETTINGS, 'tiktok_invite_method': 'ui', 'gate': GATE, 'test_phone': GATE['phone'],
               'tiktok_mode': 'real', 'real_worker_enabled': True,
               'public_url': 'https://atendimento-v5-ensaio-production.up.railway.app'}
ENV = {'V5_TIKTOK_INVITE_METHOD': 'ui', 'V5_ENABLED': 'true', 'V5_TIKTOK_MODE': 'real',
       'V5_REAL_WORKER_ENABLED': 'true', 'V5_TEST_PHONE': GATE['phone'], 'CHATWOOT_ACCOUNT_ID': '1',
       'CHATWOOT_INBOX_ID': '3', 'V5_PUBLIC_URL': UI_SETTINGS['public_url']}


def receipt(status='create_rejected', **updates):
    value = {'version': 1, 'method': 'ui', 'status': status, 'stage': 'provider_response',
             'operation_id': '22222222-2222-4222-8222-222222222222', 'observed_at': '2026-10-30T01:00:00Z',
             'target_verified': True, 'ui_submit_attempted': True, 'provider_request_observed': True,
             'provider_post_attempted': True, 'provider_http_status': 200, 'provider_code': 20044017,
             'provider_message': 'The creator cannot be invited under these conditions.'}
    value.update(updates)
    return value


def response(status='invite_failed', *, rec=None, create=None, creator='teste'):
    value = {'ok': False, 'status': status, 'creator': creator, 'receipt': rec or receipt()}
    if create is not None:
        value['create'] = create
    return 422, value


def run(response_value, settings=None, *, authority=lambda: True):
    script = Script(invitation_prefix() + [response_value])
    result = PlaywrightClient(settings or UI_SETTINGS, script).execute(
        'invite', 'teste', confirmed=True, commission='10', before_write=authority)
    return result, script


class InviteUIClient34Tests(unittest.TestCase):
    def test_api_default_is_unchanged_in_configuration_and_request_body(self):
        self.assertEqual(load_settings({})['tiktok_invite_method'], 'api')
        result, script = run(accepted_invite(False), SETTINGS)
        self.assertEqual(result['status'], 'pending_verification')
        self.assertEqual(script.writes()[0]['json_body'], {'creator': 'teste', 'confirm': True,
                         'commission': '10', 'skip_precheck': True, 'force_reinvite': False})

    def test_ui_is_explicit_and_only_the_exact_real_pilot_scope_is_ready(self):
        self.assertNotIn('tiktok_ui_invite_scope_invalid', load_settings(ENV)['readiness_issues'])
        for key, value in [('V5_ENABLED', 'false'), ('V5_TIKTOK_MODE', 'simulated'),
                           ('V5_REAL_WORKER_ENABLED', 'false'), ('V5_TEST_PHONE', '+5511999999999'),
                           ('CHATWOOT_ACCOUNT_ID', '2'), ('CHATWOOT_INBOX_ID', '4'),
                           ('V5_PUBLIC_URL', 'https://other-production.up.railway.app')]:
            with self.subTest(key=key):
                self.assertIn('tiktok_ui_invite_scope_invalid', load_settings({**ENV, key: value})['readiness_issues'])
        self.assertIn('tiktok_invite_method_invalid', load_settings({'V5_TIKTOK_INVITE_METHOD': 'other'})['readiness_issues'])

    def test_direct_client_also_rejects_ui_outside_pilot_before_any_http(self):
        for change in ({'tiktok_mode': 'simulated'}, {'test_phone': '+5511999999999'},
                       {'public_url': 'https://example.invalid'}, {'gate': {**GATE, 'inbox_id': '4'}},
                       {'tiktok_invite_method': 'other'}, {'tiktok_invite_method': []}):
            with self.subTest(change=change):
                script = Script([])
                client = PlaywrightClient({**UI_SETTINGS, **change}, script)
                result = client.execute('invite', 'teste', confirmed=True, commission='10', before_write=lambda: True)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['reason'], 'invitation_method_not_authorized')
                self.assertFalse(script.calls)
                self.assertFalse(client.configuration('invite')['configured'])

    def test_ui_request_has_only_the_explicit_method_extension(self):
        result, script = run(accepted_invite(False))
        self.assertEqual(result['status'], 'pending_verification')
        self.assertEqual(len(script.writes()), 1)
        self.assertEqual(script.writes()[0]['json_body'], {'creator': 'teste', 'confirm': True,
            'commission': '10', 'skip_precheck': True, 'force_reinvite': False, 'invite_method': 'ui'})

    def test_ui_success_still_requires_independent_same_creator_relation(self):
        accepted = accepted_invite()
        accepted[1]['receipt'] = receipt('create_accepted', provider_code=0)
        script = Script(invitation_prefix() + [accepted, ready(), relation(1), relation(2, True)])
        result = PlaywrightClient(UI_SETTINGS, script).execute('invite', 'teste', confirmed=True,
            commission='10', before_write=lambda: True)
        self.assertEqual(result['status'], 'sent')
        self.assertTrue(result['confirmed'])
        self.assertTrue(result['evidence']['create_accepted'])
        self.assertEqual(result['evidence']['receipt']['method'], 'ui')
        self.assertEqual(len(script.writes()), 1)

    def test_definite_rejection_preserves_sanitized_provider_details(self):
        result, script = run(response(create={'ok': False}))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'invitation_rejected')
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['evidence']['create_accepted'])
        self.assertEqual(result['evidence']['http_status'], 422)
        self.assertEqual(result['evidence']['provider_http_status'], 200)
        self.assertEqual(result['evidence']['upstream_code'], '20044017')
        self.assertIn('creator cannot be invited', result['evidence']['upstream_message'])
        self.assertEqual(len(script.writes()), 1)

    def test_existing_api_nested_code_and_message_are_preserved(self):
        result, _ = run((422, {'ok': False, 'status': 'invite_failed', 'creator': 'teste',
                    'create': {'ok': False, 'data': {'code': 20044017, 'message': 'Creator is not eligible.'}}}), SETTINGS)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['evidence']['upstream_code'], '20044017')
        self.assertEqual(result['evidence']['upstream_message'], 'Creator is not eligible.')

    def test_credentials_links_and_controls_are_not_preserved_in_diagnostics(self):
        message = 'Bearer private-short; cookie=session-short; token="private-key" ' + SETTINGS['tiktok_invites_token']
        message += '\nhttps://example.invalid/?token=private-url user@example.invalid\x00 ' + 'x' * 50
        result, _ = run(response(create={'ok': False}, rec=receipt(provider_message=message,
            provider_code='token:private-key', raw={'cookie': 'private-value'})))
        rendered = repr(result['evidence'])
        for secret in ('private-short', 'session-short', 'private-key', 'private-url', 'private-value',
                       SETTINGS['tiktok_invites_token'], 'user@example.invalid', 'x' * 50):
            self.assertNotIn(secret, rendered)
        self.assertLessEqual(len(result['evidence']['upstream_message']), 200)
        self.assertNotIn('\x00', result['evidence']['upstream_message'])
        self.assertNotIn('raw', result['evidence']['receipt'])

    def test_accepted_creation_is_never_reclassified_as_rejected(self):
        result, _ = run(response('invite_sent_unverified', create={'ok': True},
                                rec=receipt('create_accepted', provider_code=0)))
        self.assertEqual(result['status'], 'pending_verification')
        self.assertEqual(result['reason'], 'invitation_reconciliation_required')
        self.assertTrue(result['evidence']['create_accepted'])
        self.assertFalse(result['confirmed'])

    def test_transport_timeout_after_the_single_bridge_post_remains_unknown(self):
        result, script = run(TimeoutError('private cookie or token'))
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertTrue(result['evidence']['post_attempted'])
        self.assertEqual(len(script.writes()), 1)
        self.assertNotIn('private', repr(result))
        self.assertNotIn('receipt', result['evidence'])

    def test_proven_not_attempted_before_click_has_separate_bridge_receipt(self):
        rec = receipt('not_attempted', stage='target_selection', ui_submit_attempted=False,
                      provider_request_observed=False, provider_post_attempted=False)
        result, script = run(response('invite_not_attempted', rec=rec))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['reason'], 'invitation_not_attempted')
        self.assertFalse(result['evidence']['post_attempted'])
        self.assertTrue(result['evidence']['bridge_post_attempted'])
        self.assertEqual(len(script.writes()), 1)

    def test_proven_interception_block_after_click_is_still_not_a_provider_post(self):
        rec = receipt('not_attempted', stage='request_blocked', provider_post_attempted=False,
                      create_post_blocked=True)
        result, _ = run(response('invite_not_attempted', rec=rec))
        self.assertEqual(result['reason'], 'invitation_not_attempted')
        self.assertFalse(result['evidence']['post_attempted'])
        self.assertTrue(result['evidence']['receipt']['ui_submit_attempted'])

    def test_missing_or_ambiguous_no_write_receipt_cannot_release_unknown_fence(self):
        original = receipt('not_attempted', provider_post_attempted=False)
        variants = [original, {**original, 'provider_post_attempted': 'false'},
                    {**original, 'version': True}, {**original, 'method': 'api'},
                    {**original, 'status': 'outcome_unknown'}]
        for rec in variants:
            with self.subTest(rec=rec):
                result, script = run(response('invite_not_attempted', rec=rec))
                self.assertEqual(result['status'], 'outcome_unknown')
                self.assertTrue(result['evidence']['post_attempted'])
                self.assertEqual(len(script.writes()), 1)

    def test_click_timeout_without_observed_request_is_not_proof_of_no_effect(self):
        rec = receipt('outcome_unknown', provider_post_attempted=False, provider_request_observed=False)
        result, _ = run((500, {'ok': False, 'creator': 'teste',
                    'status': 'operation_uncertain_reconcile_same_target', 'receipt': rec}))
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertTrue(result['evidence']['post_attempted'])
        self.assertFalse(result['confirmed'])

    def test_not_attempted_proof_for_another_target_cannot_release_this_target(self):
        rec = receipt('not_attempted', ui_submit_attempted=False,
                      provider_post_attempted=False, provider_request_observed=False)
        result, _ = run(response('invite_not_attempted', rec=rec, creator='another'))
        self.assertEqual(result['status'], 'outcome_unknown')
        self.assertTrue(result['evidence']['post_attempted'])

    def test_existing_pending_invitation_prevents_ui_submission(self):
        script = Script([ready(), ready(), relation(1), relation(2, True)])
        result = PlaywrightClient(UI_SETTINGS, script).execute('invite', 'teste', confirmed=True,
            commission='10', before_write=lambda: True)
        self.assertEqual(result['status'], 'pending')
        self.assertFalse(result['evidence']['post_attempted'])
        self.assertFalse(script.writes())

    def test_no_confirmation_or_last_moment_authority_never_submits_ui(self):
        script = Script([])
        result = PlaywrightClient(UI_SETTINGS, script).execute('invite', 'teste', confirmed=False,
            commission='10', before_write=lambda: True)
        self.assertEqual(result['reason'], 'explicit_confirmation_required')
        self.assertFalse(script.calls)
        result, script = run(accepted_invite(), authority=lambda: False)
        self.assertEqual(result['reason'], 'write_authority_unconfirmed')
        self.assertFalse(script.writes())

    def test_receipt_shape_is_allowlisted_and_bounded(self):
        rec = receipt(provider_message='A' * 500, provider_code='bad\ncode', operation_id='not-a-uuid',
                      observed_at='private-date', unknown='private-field', screenshot='private-image')
        result, _ = run(response(create={'ok': False}, rec=rec))
        kept = result['evidence']['receipt']
        for key in ('unknown', 'screenshot', 'operation_id', 'observed_at', 'provider_code'):
            self.assertNotIn(key, kept)
        self.assertLessEqual(len(kept['provider_message']), 200)


if __name__ == '__main__':
    unittest.main()
