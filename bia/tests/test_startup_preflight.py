"""Source startup gate: offline tests only, no live providers."""
import os
import json
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import bootstrap
from config import load_settings
from ops import stage_preflight
from startup_preflight import StartupPreflightFailed, verify_stage_readiness

ROOT = Path(__file__).resolve().parents[1]
ENV = {
    'CHATWOOT_BASE_URL': 'https://chatwoot.t2ffoz.easypanel.host',
    'CHATWOOT_API_TOKEN': 'offline-test-token', 'V5_ENABLED': 'true',
    'CHATWOOT_ACCOUNT_ID': '1', 'CHATWOOT_INBOX_ID': '3',
    'V5_TEST_PHONE': '+5547991154859', 'V5_CHATWOOT_STAGES_ENABLED': 'true',
}
PASS = {'passed': True, 'mode': 'readonly', 'post_attempts': 0}


class StartupPreflightTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.settings = load_settings(ENV)

    def test_exact_approved_scope_and_readonly_required_labels(self):
        with patch.object(stage_preflight, 'run_preflight', return_value=PASS) as run:
            self.assertEqual(verify_stage_readiness(self.settings)['status'], 'passed')
        args, kwargs = run.call_args
        self.assertEqual(kwargs, {
            'expected_host': 'chatwoot.t2ffoz.easypanel.host',
            'expected_account_id': '1', 'expected_inbox_id': '3',
            'expected_conversation_id': '26097', 'expected_contact_id': '3',
            'require_labels': True, 'setup': False,
        })
        self.assertEqual(args[0]['CHATWOOT_BASE_URL'], ENV['CHATWOOT_BASE_URL'])
        self.assertEqual(args[0]['V5_INACTIVITY_CLOSE_ENABLED'], 'false')

    def test_settings_not_unrelated_process_environment_are_checked(self):
        with patch.dict(os.environ, {'CHATWOOT_BASE_URL': 'https://other.invalid'}), \
                patch.object(stage_preflight, 'run_preflight', return_value=PASS) as run:
            verify_stage_readiness(self.settings)
        self.assertEqual(run.call_args.args[0]['CHATWOOT_BASE_URL'], ENV['CHATWOOT_BASE_URL'])

    def test_inactivity_label_requirement_is_preserved(self):
        with patch.object(stage_preflight, 'run_preflight', return_value=PASS) as run:
            verify_stage_readiness({**self.settings, 'inactivity_close_enabled': True})
        self.assertEqual(run.call_args.args[0]['V5_INACTIVITY_CLOSE_ENABLED'], 'true')

    def test_offline_and_stages_disabled_do_not_construct_provider(self):
        with patch.object(stage_preflight, 'run_preflight', side_effect=AssertionError('network')) as run:
            for environment in ('staging', '', 'development', 'unknown'):
                with patch.dict(os.environ, {'APP_ENV': environment}):
                    self.assertEqual(verify_stage_readiness(self.settings)['status'], 'disabled')
            self.assertEqual(verify_stage_readiness({**self.settings, 'bridge_environment': 'nonproduction'})['status'], 'disabled')
            self.assertEqual(verify_stage_readiness({**self.settings, 'chatwoot_stages_enabled': False})['status'], 'disabled')
        run.assert_not_called()

    def test_failed_or_ambiguous_results_close_gate(self):
        for result in (None, {}, {'passed': 'true'}, {**PASS, 'passed': False},
                       {**PASS, 'mode': 'setup'}, {**PASS, 'post_attempts': 1},
                       {**PASS, 'post_attempts': False}):
            with self.subTest(result=result), patch.object(stage_preflight, 'run_preflight', return_value=result):
                with self.assertRaisesRegex(StartupPreflightFailed, '^stage_preflight_failed$'):
                    verify_stage_readiness(self.settings)

    def test_provider_exception_is_sanitized(self):
        with patch.object(stage_preflight, 'run_preflight', side_effect=RuntimeError('SECRET')):
            with self.assertRaises(StartupPreflightFailed) as caught:
                verify_stage_readiness(self.settings)
        self.assertEqual(str(caught.exception), 'stage_preflight_failed')
        self.assertTrue(caught.exception.__suppress_context__)

    def test_invalid_origin_rejected_before_http_factory(self):
        for origin in ('https://other.invalid', 'https://chatwoot-web-production-c799.up.railway.app',
                       ENV['CHATWOOT_BASE_URL'] + '/path'):
            with self.subTest(origin=origin), patch.object(stage_preflight, '_client') as client:
                with self.assertRaises(StartupPreflightFailed):
                    verify_stage_readiness({**self.settings, 'chatwoot_base_url': origin})
                client.assert_not_called()

    def test_failure_precedes_server_database_and_workers(self):
        with patch.object(stage_preflight, 'run_preflight', return_value={**PASS, 'passed': False}), \
                patch.object(bootstrap, 'create_server') as server, \
                patch.object(bootstrap, 'Gateway') as gateway, \
                patch.object(bootstrap, 'SmtpSender') as smtp, \
                patch.object(bootstrap, 'register_forms') as forms:
            with self.assertRaises(StartupPreflightFailed):
                bootstrap.create_app(self.settings)
        for component in (server, gateway, smtp, forms):
            component.assert_not_called()

    def test_pass_preserves_normal_app_construction(self):
        executor = SimpleNamespace()
        app = SimpleNamespace(extensions={'v5_real_executor': executor, 'v5_repository': object()})
        order = []
        def preflight(*args, **kwargs):
            order.append('preflight')
            return PASS
        def server(**kwargs):
            order.append('server')
            return app
        with patch.object(stage_preflight, 'run_preflight', side_effect=preflight), \
                patch.object(bootstrap, 'create_server', side_effect=server), \
                patch.object(bootstrap, 'Gateway', return_value=SimpleNamespace(cleanup_retention=Mock())), \
                patch.object(bootstrap, 'SmtpSender'), patch.object(bootstrap, 'register_forms'):
            self.assertIs(bootstrap.create_app(self.settings), app)
        self.assertEqual(order, ['preflight', 'server'])
        self.assertEqual(app.extensions['v5_stage_preflight']['status'], 'passed')

    def test_real_preflight_performs_only_four_gets_and_no_setup(self):
        responses = [
            {'id': 3, 'account_id': 1, 'name': stage_preflight.INBOX_NAME},
            {'id': 26097, 'account_id': 1, 'inbox_id': 3,
             'meta': {'sender': {'id': 3, 'type': 'contact', 'phone_number': ENV['V5_TEST_PHONE']}}},
            {'payload': [dict(item, id=i + 1) for i, item in enumerate(stage_preflight.APPROVED_LABELS)]},
            {'payload': []},
        ]
        requests = []
        class Response(io.BytesIO):
            status = 200
            headers = {}
        class Client:
            def open(self, request, timeout):
                requests.append(request)
                return Response(json.dumps(responses.pop(0)).encode())
        with patch.object(stage_preflight, '_client', return_value=Client()):
            self.assertEqual(verify_stage_readiness(self.settings)['status'], 'passed')
        self.assertEqual(len(requests), 4)
        self.assertTrue(all(request.get_method() == 'GET' and request.data is None for request in requests))
        self.assertEqual([request.full_url.rsplit('/', 1)[-1] for request in requests],
                         ['3', '26097', 'labels', 'automation_rules'])

    def test_docker_packages_gate_and_uses_real_bootstrap(self):
        docker = (ROOT / 'Dockerfile').read_text()
        self.assertIn('COPY bridge_config.py offline_policy.py startup_preflight.py ./', docker)
        self.assertIn('COPY ops/stage_preflight.py ./ops/stage_preflight.py', docker)
        self.assertIn("bootstrap:create_app()", docker)
        self.assertNotIn('connectionfix_launcher', docker)


if __name__ == '__main__':
    unittest.main()
