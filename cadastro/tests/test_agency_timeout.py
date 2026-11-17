"""Offline proofs for the Cadastro relationship lookup timeout."""
import ast
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

from agency import AgencyChecker, proof

ROOT = Path(__file__).resolve().parents[1]
HANDLE = 'qa.creator'


class FakeBridge:
    def __init__(self, scenario, latency=0):
        self.scenario = scenario
        self.latency = latency
        self.calls = []

    def __call__(self, *, method, url, headers, json_body, timeout):
        request = urlsplit(url)
        query = parse_qs(request.query)
        self.calls.append((method, request.path, query.get('status', [None])[0], timeout))
        if method != 'GET':
            raise AssertionError('relationship check must be read only')
        if request.path.endswith('/ready'):
            return 200, {'ok': True, 'status': 'ready', 'contexto': {'aberto': True, 'pronto': True},
                         'probe': {'status': 'ok', 'ageMs': 0}, 'readiness': {'fresh': True},
                         'riskGuard': {'status': 'clear'}}
        if not request.path.endswith('/relations'):
            raise AssertionError('unexpected operation')
        if self.latency > timeout:
            raise TimeoutError('synthetic bridge response exceeded per-call timeout')
        if self.scenario == 'upstream_unavailable':
            return 503, {'ok': False}
        status = int(query['status'][0])
        matching = self.scenario == 'linked' and status == 1 or self.scenario == 'pending' and status == 2
        item = {'arroba': HANDLE, 'status': 'vinculado' if status == 1 else 'solicitada',
                'tiktok_status': status, 'tiktok_data_status': status, 'relation_id': 'qa-123'}
        return 200, {'ok': True, 'status': 'relations_listed', 'completo': self.scenario != 'incomplete',
                     'pages': [{'ok': True, 'hasMore': False}],
                     'items': [item] if matching else [], 'query': {'status': status, 'creators': [HANDLE]}}


class AgencyTimeout(unittest.TestCase):
    def checker(self, scenario, latency=0):
        transport = FakeBridge(scenario, latency)
        checker = AgencyChecker('x' * 40, transport=transport)
        self.addCleanup(checker.pool.shutdown)
        return checker, transport

    def assert_routes(self, result, expected_status):
        # Exercise the exact pure Flask route helper with a synthetic result,
        # without importing Flask, calling providers, or touching app storage.
        tree = ast.parse((ROOT / 'app' / 'publico.py').read_text(encoding='utf8'))
        route = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'approve_agency')
        class CadastroError(Exception):
            def __init__(self, message, status):
                self.status = status
        ns = {'run_agency': lambda _: result, 'proof': proof, 'PENDING_GUIDE': 'synthetic',
              'CadastroError': CadastroError}
        exec(compile(ast.Module(body=[route], type_ignores=[]), 'publico.py', 'exec'), ns)
        with self.assertRaises(CadastroError) as denied:
            ns['approve_agency']('synthetic-record', HANDLE)
        self.assertEqual(denied.exception.status, expected_status)

    def test_complete_response_after_30_seconds_remains_a_proof_and_reuses_cache(self):
        checker, bridge = self.checker('linked', latency=31)
        result = checker.check(HANDLE)
        self.assertIsNotNone(proof(result))
        self.assertEqual(proof(result)['creator'], '@' + HANDLE)
        self.assertEqual(proof(result)['evidence']['source'], 'partner_relations')
        self.assertEqual(checker.check(HANDLE)['job_id'], result['job_id'])
        self.assertEqual([row[-1] for row in bridge.calls], [5, 35])
        self.assertEqual(checker.wait_seconds, 38)
        html = (ROOT / 'app' / 'static' / 'cadastro.html').read_text(encoding='utf8')
        self.assertIn('AbortSignal.timeout(45000)', html)
        self.assertLess(35, checker.wait_seconds)
        self.assertLess(checker.wait_seconds, 45)

    def test_possibly_pending_and_absent_both_run_second_scope_and_never_cache(self):
        for scenario, expected in [('pending', 'pending'), ('absent', 'not_found')]:
            with self.subTest(scenario=scenario):
                checker, bridge = self.checker(scenario)
                result = checker.check(HANDLE)
                self.assertEqual(result['status'], expected)
                self.assertIsNone(proof(result))
                self.assert_routes(result, 409)
                self.assertEqual([entry[2] for entry in bridge.calls], [None, '1', '2'])
                self.assertEqual(checker.check(HANDLE)['status'], expected)
                self.assertEqual(len(bridge.calls), 6)

    def test_total_provider_failure_after_35_seconds_no_retry_or_proof(self):
        checker, bridge = self.checker('linked', latency=36)
        result = checker.check(HANDLE)
        self.assertEqual(result['status'], 'verification_pending')
        self.assertIsNone(proof(result))
        self.assert_routes(result, 503)
        self.assertEqual([entry[2] for entry in bridge.calls], [None, '1'])

    def test_fast_503_and_incomplete_are_not_upgraded_to_linked(self):
        for scenario in ('upstream_unavailable', 'incomplete'):
            with self.subTest(scenario=scenario):
                checker, bridge = self.checker(scenario)
                result = checker.check(HANDLE)
                self.assertEqual(result['status'], 'verification_pending')
                self.assertIsNone(proof(result))
                self.assert_routes(result, 503)
                self.assertEqual([entry[2] for entry in bridge.calls], [None, '1'])


if __name__ == '__main__':
    unittest.main()
