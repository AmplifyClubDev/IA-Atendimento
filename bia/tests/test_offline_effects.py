"""Synthetic-only offline policy regression tests. Never contact a provider."""
import importlib
import os
from pathlib import Path
import sys
import types
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offline_policy import ExternalEffectsDisabled, REASON
from gateway import Gateway, PROJECT_REF, SubmissionRejected
from smtp import SmtpSender
from transport import ChatwootTransport, _http
from playwright_client import PlaywrightClient, _transport
from answers import answer_question, _http_transport
from guided_ai import plan_turn
from real_operations import RealExecutor
from followup import Followup
from retomada import Retomada, PosPausa
from recovery import recover_stalled

SETTINGS = {'bridge_environment': 'nonproduction', 'bridge_nonproduction_enabled': True,
            'tiktok_mode': 'real', 'real_worker_enabled': True, 'retention_enabled': True,
            'followup_enabled': True, 'retomada_enabled': True, 'pos_pausa_enabled': True,
            'ai_enabled': True, 'context_db_enabled': True, 'form_public_url': 'https://example.invalid'}

class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bomb = Mock(side_effect=AssertionError('external adapter invoked'))

    def disabled(self, result):
        self.assertEqual(result['status'], 'disabled')
        self.assertEqual(result['reason'], REASON)

    def test_gateway_settings_block_and_production_pin_preserved(self):
        with self.assertRaisesRegex(ExternalEffectsDisabled, REASON):
            Gateway(SETTINGS, self.bomb)._rpc('synthetic', {})
        self.bomb.assert_not_called()
        with self.assertRaisesRegex(SubmissionRejected, 'v5_target_mismatch'):
            Gateway({'v5_url': 'https://example.invalid', 'v5_service_key': 'fake'}, self.bomb)._rpc('synthetic', {})
        adapter = Mock(return_value={'synthetic': True})
        self.assertEqual(Gateway({'v5_url': 'https://' + PROJECT_REF + '.supabase.co', 'v5_service_key': 'fake'}, adapter)._rpc('synthetic', {}), {'synthetic': True})
        adapter.assert_called_once()

    def test_smtp_direct_and_public_methods_are_disabled(self):
        sender = SmtpSender(SETTINGS, self.bomb)
        self.disabled(sender._send('x', 'x', 'x', 'x'))
        self.disabled(sender.send_otp('x', 'x', 'x'))
        self.disabled(sender.send_receipt('x', {}, 'x'))
        self.bomb.assert_not_called()

    def test_chatwoot_reads_writes_cloud_and_exposed_http(self):
        t = ChatwootTransport('https://example.invalid', 'fake', {}, http=self.bomb,
                              cloud={'token': 'fake', 'phone_number_id': '123456'}, settings=SETTINGS)
        for method, args in [(t.http, ()), (t._read_target, ({},)),
                             (t.read_progress, ({},)), (t._send_url_button, ({}, {}))]:
            with self.subTest(method=method.__name__), self.assertRaisesRegex(ExternalEffectsDisabled, REASON):
                method(*args)
        self.disabled(t.send_reply({}, 'test', [], 'synthetic'))
        self.disabled(t.write_progress({}, [], 'synthetic'))
        self.disabled(t.reconcile_reply({}, 'synthetic'))
        self.bomb.assert_not_called()

    def test_production_chatwoot_wrapper_passes_arguments_unchanged(self):
        adapter = Mock(return_value={'synthetic': True})
        t = ChatwootTransport('', '', {}, http=adapter)
        args = {'method': 'GET', 'url': 'https://example.invalid', 'headers': {}, 'timeout': 3}
        self.assertEqual(t.http(**args), {'synthetic': True})
        adapter.assert_called_once_with(**args)

    def test_low_level_network_helpers_block_process_staging_even_with_legacy_flags(self):
        with patch.dict(os.environ, {'APP_ENV': 'staging', 'V5_TIKTOK_NONPRODUCTION_ENABLED': 'true', 'PONTES_NONPRODUCTION_ACTIVATION_ENABLED': 'true'}):
            with patch('urllib.request.OpenerDirector.open', self.bomb):
                for method, args in [(_http, {'method':'GET','url':'https://example.invalid','headers':{}}),
                                     (_transport, {'method':'GET','url':'https://example.invalid','headers':{}}),
                                     (_http_transport, {'method':'POST','url':'https://example.invalid','headers':{},'json':{},'timeout':1})]:
                    with self.subTest(method=method.__name__), self.assertRaisesRegex(ExternalEffectsDisabled, REASON):
                        method(**args)
            with self.assertRaises(ExternalEffectsDisabled):
                Gateway({'bridge_environment':'production'}, self.bomb)._rpc('synthetic', {})
        self.bomb.assert_not_called()

    def test_ai_disabled_before_context_fetch_or_injected_provider(self):
        for result in [answer_question('hello', [], SETTINGS, self.bomb), plan_turn('hello', {}, SETTINGS, self.bomb)]:
            self.assertEqual(result['provider_status'], 'disabled')
            self.assertEqual(result['reason'], REASON)
        self.bomb.assert_not_called()

    def test_bridge_direct_and_executor_methods(self):
        client = PlaywrightClient(SETTINGS, self.bomb)
        self.disabled(client.configuration())
        self.assertFalse(client.configuration()['configured'])
        self.disabled(client.execute('invite', 'synthetic'))
        with self.assertRaises(ExternalEffectsDisabled):
            client._call('invites', 'POST', '/synthetic')
        worker = RealExecutor(self.bomb, self.bomb, SETTINGS, self.bomb, self.bomb, self.bomb)
        self.disabled(worker.tick())
        self.disabled(worker.probe_sessions())
        self.disabled(worker.maintain_retention())
        self.assertFalse(worker.start())
        self.assertEqual(worker.last_error, REASON)
        with self.assertRaises(ExternalEffectsDisabled):
            worker._run()
        self.bomb.assert_not_called()

    def test_secondary_worker_direct_ticks(self):
        for cls in [Followup, Retomada, PosPausa]:
            worker = object.__new__(cls)
            worker.settings = SETTINGS
            self.disabled(worker.tick())
        self.disabled(recover_stalled(types.SimpleNamespace(extensions={'v5_settings': SETTINGS})))

    def test_bootstrap_never_relinks_probes_or_starts_in_nonproduction(self):
        executor = types.SimpleNamespace(retention_cleanup=None, probe_sessions=self.bomb, start=self.bomb)
        app = types.SimpleNamespace(extensions={'v5_real_executor': executor, 'v5_repository': object(), 'v5_form_relink_existing': self.bomb})
        server = types.ModuleType('server');server.create_app = Mock(return_value=app)
        forms = types.ModuleType('forms');forms.register_forms = Mock()
        with patch.dict(sys.modules, {'server':server, 'forms':forms}):
            sys.modules.pop('bootstrap', None)
            bootstrap = importlib.import_module('bootstrap')
            self.assertIs(bootstrap.create_app(SETTINGS), app)
        sys.modules.pop('bootstrap', None)
        self.disabled(app.extensions['v5_external_effects'])
        self.bomb.assert_not_called()

    def test_actual_flask_bootstrap_is_offline(self):
        try:
            import flask
        except ImportError:
            self.skipTest('Flask runtime dependencies not installed')
        from config import load_settings
        sys.modules.pop('bootstrap', None)
        bootstrap = importlib.import_module('bootstrap')
        with tempfile.TemporaryDirectory() as directory:
            settings = load_settings({'APP_ENV': 'staging'})
            settings.update(SETTINGS, state_dir=directory)
            with patch('urllib.request.OpenerDirector.open', self.bomb), patch('smtplib.SMTP_SSL', self.bomb):
                app = bootstrap.create_app(settings)
                self.disabled(app.extensions['v5_external_effects'])
                self.assertIsNone(app.extensions['v5_real_executor'].thread)
                self.assertEqual(app.test_client().get('/healthz').status_code, 200)
        self.bomb.assert_not_called()

    def test_actual_flask_readiness_refuses_simulated_and_real_offline(self):
        try:
            from server import create_app
        except ImportError:
            self.skipTest('Flask runtime dependencies not installed')
        gate = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
                'phone': '+15555550123'}
        for mode in ('simulated', 'real'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                settings = dict(SETTINGS, state_dir=directory, tiktok_mode=mode, gate=gate,
                                context_db_enabled=False, conversation_enabled=False,
                                webhook_token='synthetic-token-12345678',
                                chatwoot_base_url='https://example.invalid', chatwoot_api_token='fake')
                with patch('urllib.request.OpenerDirector.open', self.bomb):
                    app = create_app(settings)
                    self.assertFalse(app.extensions['v5_transport'].ready())
                    result = app.test_client().get('/ready')
                    self.assertEqual(result.status_code, 503)
                    self.assertFalse(result.json['ready'])
                    self.disabled(result.json)
                    self.assertIn(REASON, result.json['issues'])
                    self.assertEqual(app.test_client().get('/healthz').status_code, 200)
        self.bomb.assert_not_called()

    def test_standalone_preflight_and_readonly_helpers_are_offline(self):
        from ops.stage_preflight import run_preflight, _request
        from tools.listar_entrada_todos import ReadOnlyChatwoot
        from verify_private import local_request
        result = run_preflight({'APP_ENV': 'staging'}, setup=True, http_factory=self.bomb)
        self.disabled(result)
        self.assertFalse(result['passed'])
        self.assertEqual(result['post_attempts'], 0)
        with patch.dict(os.environ, {'APP_ENV': 'staging'}):
            for callback in [lambda: _request(self.bomb, 'GET', 'https://example.invalid', 'fake'),
                             lambda: ReadOnlyChatwoot('https://example.invalid', 'fake').http(method='GET', url='https://example.invalid', headers={}, timeout=1),
                             lambda: local_request('/healthz')]:
                with self.assertRaises(ExternalEffectsDisabled):
                    callback()
        self.bomb.assert_not_called()

    def test_process_marker_wins_over_production_settings(self):
        with patch.dict(os.environ, {'RAILWAY_ENVIRONMENT_NAME':'staging', 'APP_ENV':'production'}):
            self.disabled(SmtpSender({'bridge_environment':'production'}, self.bomb).send_otp('x','x','x'))
            with self.assertRaises(ExternalEffectsDisabled):
                ChatwootTransport('', '', {}, http=self.bomb, settings={'bridge_environment':'production'}).http()
        self.bomb.assert_not_called()

if __name__ == '__main__':
    unittest.main()
