"""Synthetic cases only; no production messages, identities, keys, or databases."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import unittest
from unittest.mock import Mock, patch

import config
import contracts
import conversao
import followup
import pilot_scope
import real_journey
import recovery
from transport import ChatwootTransport

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stage_preflight_review', ROOT / 'ops/stage_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
PHONE = '+55' + '11' + '9' + '0' * 8
OTHER_PHONE = '+55' + '11' + '9' + '0' * 7 + '1'
SYNTHETIC_ENV = {'V5_RESTRICTED_PILOT_PHONE': PHONE, 'V5_PILOT_CONVERSATION_ID': '7',
                 'V5_PILOT_CONTACT_ID': '9'}
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def event(**overrides):
    value = {'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
             'conversation_id': '7', 'contact_id': '9', 'message_id': '8',
             'sender_phone': PHONE, 'sender_type': 'contact', 'message_type': 'incoming',
             'private': False, 'text': 'synthetic input', 'created_at': NOW.isoformat()}
    value.update(overrides)
    value['source_ref'] = contracts.inbound_key(value)
    return value


def settings():
    return {'pilot_scope': pilot_scope.load_scope(SYNTHETIC_ENV),
            'gate': {'enabled': True, 'provider': 'chatwoot', 'account_id': '1',
                     'inbox_id': '3', 'phone': PHONE}, 'test_phone': PHONE,
            'followup_enabled': True, 'followup_delay_seconds': '300',
            'followup_start_at': NOW.isoformat(), 'tiktok_mode': 'real',
            'real_worker_enabled': True, 'contact_sync_enabled': True,
            'conversation_enabled': True, 'tiktok_invite_method': 'ui',
            'public_url': 'https://atendimento-v5-ensaio-production.up.railway.app'}


class OfflineBoundary(unittest.TestCase):
    def test_network_creation_is_denied(self):
        with self.assertRaisesRegex(RuntimeError, 'External calls'):
            socket.socket()

    def test_all_sources_compile_without_execution(self):
        for path in ROOT.rglob('*.py'):
            if 'tests' in path.parts:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                compile(path.read_bytes(), str(path), 'exec')

    def test_manifest_matches_only_the_sanitized_source_package(self):
        manifest = json.loads((ROOT / 'MANIFEST.json').read_text(encoding='utf-8'))
        self.assertTrue(manifest['provenance']['sanitized'])
        self.assertEqual(manifest['source_count'], len(manifest['files']))
        self.assertIn('pilot_scope.py', {entry['path'] for entry in manifest['files']})
        for entry in manifest['files']:
            with self.subTest(path=entry['path']):
                data = (ROOT / entry['path']).read_bytes()
                self.assertEqual(len(data), entry['bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry['sha256'])

    def test_dockerfile_includes_all_local_root_modules(self):
        copied = set()
        for line in (ROOT / 'Dockerfile').read_text(encoding='utf-8').splitlines():
            if line.startswith('COPY '):
                copied.update(line.split()[1:-1])
        self.assertTrue({path.name for path in ROOT.glob('*.py')} <= copied)


class ScopeCases(unittest.TestCase):
    def test_absent_scope_has_no_defaults(self):
        scope = pilot_scope.load_scope({})
        self.assertFalse(pilot_scope.scope_ready(scope))
        self.assertEqual(pilot_scope.conversation_key(scope), '')
        self.assertEqual(pilot_scope.contact_id(scope), '')

    def test_explicit_scope_is_supported(self):
        scope = pilot_scope.load_scope(SYNTHETIC_ENV)
        self.assertTrue(pilot_scope.scope_ready(scope))
        self.assertEqual(pilot_scope.conversation_key(scope), 'chatwoot:1:7')

    def test_bad_or_missing_fields_close_scope(self):
        for name in SYNTHETIC_ENV:
            for value in ('', 'invalid', '0', True):
                with self.subTest(name=name, value=value):
                    values = {**SYNTHETIC_ENV, name: value}
                    self.assertFalse(pilot_scope.scope_ready(pilot_scope.load_scope(values)))

    def test_missing_scope_blocks_startup_readiness(self):
        actual = config.load_settings({'V5_ENABLED': 'true', 'V5_TEST_PHONE': PHONE})
        self.assertIn('restricted_pilot_scope_missing', actual['readiness_issues'])

    def test_explicit_matching_scope_satisfies_new_guard(self):
        actual = config.load_settings({**SYNTHETIC_ENV, 'V5_ENABLED': 'true', 'V5_TEST_PHONE': PHONE})
        self.assertNotIn('restricted_pilot_scope_missing', actual['readiness_issues'])

    def test_phone_mismatch_blocks_startup(self):
        actual = config.load_settings({**SYNTHETIC_ENV, 'V5_ENABLED': 'true', 'V5_TEST_PHONE': OTHER_PHONE})
        self.assertIn('restricted_pilot_scope_missing', actual['readiness_issues'])

    def test_ui_guard_accepts_only_explicit_matching_scope(self):
        values = settings()
        self.assertIsNone(config.invite_method_issue(values))
        for update in ({'pilot_scope': {}}, {'test_phone': OTHER_PHONE}):
            self.assertEqual(config.invite_method_issue({**values, **update}), 'tiktok_ui_invite_scope_invalid')

    def test_historical_lists_are_empty_by_default_and_bounded(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(pilot_scope.historical_event_keys('V5_INITIAL_RECHECK_EVENT_KEYS'), frozenset())
        for raw in ('not-a-key', 'chatwoot:2:7', ','.join(['chatwoot:1:7'] * 101)):
            with patch.dict(os.environ, {'V5_INITIAL_RECHECK_EVENT_KEYS': raw}, clear=True):
                self.assertFalse(pilot_scope.historical_event_keys('V5_INITIAL_RECHECK_EVENT_KEYS'))
        self.assertFalse(real_journey.INITIAL_RECHECK)
        self.assertFalse(real_journey.INITIAL_INVITE_RECHECK)


class RestrictedFeatures(unittest.TestCase):
    def setUp(self):
        self.environ = patch.dict(os.environ, SYNTHETIC_ENV, clear=True)
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def test_followup_requires_complete_scope(self):
        values = settings()
        self.assertTrue(followup.configured(values))
        self.assertFalse(followup.configured({**values, 'pilot_scope': {}}))
        bad = deepcopy(values)
        bad['gate']['phone'] = OTHER_PHONE
        self.assertFalse(followup.configured(bad))

    def test_missing_followup_scope_never_reads_repository_or_provider(self):
        repository, transport = Mock(), Mock()
        worker = followup.Followup(repository, {**settings(), 'pilot_scope': {}}, transport,
                                   lambda key: nullcontext(), Mock())
        self.assertEqual(worker.tick()['status'], 'disabled')
        self.assertEqual(repository.mock_calls, [])
        self.assertEqual(transport.mock_calls, [])

    def test_followup_uses_configured_conversation(self):
        worker = followup.Followup(Mock(), settings(), Mock(), lambda key: nullcontext(), Mock())
        self.assertEqual(worker.conversation, 'chatwoot:1:7')

    def test_direct_form_accepts_explicit_identity_and_copies_event(self):
        state = {'cycle': {'id': 'synthetic-cycle', 'facts': {}}}
        source = event()
        self.assertTrue(real_journey._refresh_direct_request(state, source, NOW, reason='registration_access'))
        self.assertIsNot(state['cycle']['form_entry_request']['event'], source)

    def test_direct_form_rejects_wrong_identity_and_future_input(self):
        for override in ({'conversation_id': '6'}, {'contact_id': '6'}, {'sender_phone': OTHER_PHONE},
                         {'private': True}, {'created_at': (NOW + timedelta(seconds=1)).isoformat()}):
            with self.subTest(override=override):
                state = {'cycle': {'id': 'synthetic-cycle', 'facts': {}}}
                self.assertFalse(real_journey._refresh_direct_request(state, event(**override), NOW,
                                                                      reason='registration_access'))

    def test_direct_form_without_scope_is_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(real_journey._refresh_direct_request({'cycle': {}}, event(), NOW,
                                                                 reason='registration_access'))

    def test_recovery_reads_only_configured_contact(self):
        gate = settings()['gate']
        detail = {'id': '7', 'account_id': '1', 'inbox_id': '3',
                  'meta': {'sender': {'id': '9', 'phone_number': PHONE, 'type': 'contact'}}}
        self.assertTrue(recovery._target(detail, gate))
        message = {'id': '8', 'conversation_id': '7', 'private': False, 'message_type': 'incoming',
                   'content': 'synthetic input', 'created_at': NOW.isoformat(),
                   'sender': detail['meta']['sender']}
        self.assertEqual(recovery._source_event(message, detail, gate)['contact_id'], '9')
        detail['meta']['sender']['id'] = '6'
        self.assertFalse(recovery._target(detail, gate))

    def test_transport_checks_explicit_contact_for_metadata(self):
        detail = {'id': '7', 'account_id': '1', 'inbox_id': '3', 'can_reply': True,
                  'meta': {'sender': {'id': '9', 'phone_number': PHONE}}}
        http = Mock(return_value=detail)
        adapter = ChatwootTransport('https://chatwoot-web-production-c799.up.railway.app',
                                    'synthetic-test-token', settings()['gate'], http=http)
        self.assertTrue(adapter._progress_allowed(event()))
        self.assertTrue(adapter._read_target(event(), require_contact=True))
        self.assertFalse(adapter._progress_allowed(event(conversation_id='6')))
        self.assertFalse(adapter._progress_allowed(event(contact_id='6')))
        detail['meta']['sender']['id'] = '6'
        self.assertFalse(adapter._read_target(event(), require_contact=True))

    def test_preflight_missing_identifiers_never_constructs_http_client(self):
        factory = Mock(side_effect=AssertionError('HTTP must not be constructed'))
        result = preflight.run_preflight({}, expected_host=preflight.CHAT_HOST,
                                        expected_account_id='1', expected_inbox_id='3',
                                        expected_conversation_id='7', expected_contact_id='9', http_factory=factory)
        self.assertFalse(result['passed'])
        factory.assert_not_called()

    def test_preflight_matches_explicit_ids(self):
        values = {**SYNTHETIC_ENV, 'V5_ENABLED': 'true', 'CHATWOOT_ACCOUNT_ID': '1',
                  'CHATWOOT_INBOX_ID': '3', 'CHATWOOT_BASE_URL': 'https://' + preflight.CHAT_HOST,
                  'V5_TEST_PHONE': PHONE, 'CHATWOOT_API_TOKEN': 'synthetic-test-token'}
        target = {'host': preflight.CHAT_HOST, 'account_id': '1', 'inbox_id': '3',
                  'conversation_id': '7', 'contact_id': '9'}
        self.assertEqual(preflight._settings(values, target, False)['conversation_id'], '7')
        with self.assertRaises(preflight.GateClosed):
            preflight._settings(values, {**target, 'contact_id': '6'}, False)


class Release55Behavior(unittest.TestCase):
    def test_greeting_has_scripted_choices_without_ai(self):
        assistant = Mock(side_effect=AssertionError('AI must not be called for scripted greeting'))
        result = real_journey.handle_real({}, 'oi', assistant, now=NOW)
        self.assertEqual(result['buttons'], ['Conhecer a Amplify', 'Quero me agenciar'])
        self.assertEqual(result['effects'], [])
        self.assertNotIn('tiktok_declarado', result['state']['cycle']['facts'])
        assistant.assert_not_called()

    def test_soft_decline_pauses_qualification_without_jobs(self):
        result = real_journey.handle_real({}, 'agora não quero me agenciar', now=NOW)
        self.assertTrue(result['state']['cycle']['qualification_paused'])
        self.assertEqual(result['effects'], [])

    def test_explicit_decline_keeps_existing_closure_behavior(self):
        result = real_journey.handle_real({}, 'não quero me agenciar', now=NOW)
        self.assertEqual(result['state']['cycle']['status'], 'closed')
        self.assertEqual(result['state']['cycle']['reason'], 'lead_not_interested')
        self.assertEqual(result['effects'], [])

    def test_other_agency_declaration_does_not_prove_provider_relationship(self):
        for text in ('tenho uma agencia', 'estou em outra agencia'):
            self.assertTrue(real_journey._other_agency_declaration(text))
        for text in ('tenho uma agencia?', 'não tenho uma agencia', 'se tenho uma agencia'):
            self.assertFalse(real_journey._other_agency_declaration(text))

    def test_literal_handle_advances_without_ai_or_provider_call(self):
        assistant = Mock(side_effect=AssertionError('AI must not interpret a literal handle'))
        result = real_journey.handle_real({}, '@synthetic_review', assistant, now=NOW)
        self.assertEqual(result['state']['cycle']['facts']['tiktok_declarado'], '@synthetic_review')
        self.assertTrue(result['state']['cycle']['facts']['interesse_agenciamento'])
        assistant.assert_not_called()

    def test_profile_change_is_distinguished_from_retry_or_question(self):
        cycle = {'facts': {'tiktok_declarado': '@synthetic_old'}}
        self.assertEqual(real_journey._declared_profile_change('@synthetic_new', cycle), '@synthetic_new')
        self.assertIsNone(real_journey._declared_profile_change('pronto', cycle))
        self.assertIsNone(real_journey._declared_profile_change('@synthetic_new?', cycle))

    def test_unknown_eligibility_does_not_assert_inactive_shop(self):
        self.assertIn('não significa', conversao.SHOP_UNKNOWN)
        for index in (1, 2, 3):
            self.assertNotIn('Para ativar', conversao.shop_reminder(index))

    def test_pending_invite_status_is_treated_as_unlanded(self):
        cycle = {'id': 'synthetic-cycle', 'real_operations': {'invite': {
            'status': 'verification_pending', 'cycle_id': 'synthetic-cycle'}}}
        self.assertTrue(real_journey._invite_unlanded(cycle))
        cycle['real_operations']['invite']['cycle_id'] = 'different-cycle'
        self.assertFalse(real_journey._invite_unlanded(cycle))
