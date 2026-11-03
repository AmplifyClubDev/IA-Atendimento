"""Form checks run once per explicit request; old chat checks cannot resume."""
from datetime import timedelta
import unittest

from tests import test_real_executor as fixtures
from real_operations import build_jobs


class FormWorker30Tests(unittest.TestCase):
    def fixture(self):
        fixture = fixtures.ExecutorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def enqueue_form(self, fixture):
        state, effect = fixture.state('relationship')
        effect['payload'].update(source='form', form_operation_key='form-agency:fixed')
        fixture.repository.reserve_event('chatwoot:1:777', fixtures.CONV, 'fixture')
        fixture.certify_projection(state)
        jobs = build_jobs(fixtures.EVENT, state, [effect])
        fixture.repository.prepare_reply('chatwoot:1:777', fixtures.CONV, state,
                                         'inbound:reply', None, real_jobs=jobs)
        return jobs[0]

    def result(self):
        return {'operation': 'relationship', 'creator': '@alice', 'status': 'not_found',
                'confirmed': True, 'observed_at': fixtures.NOW.isoformat(), 'evidence': {'exact': True}}

    def test_form_mode_cancels_legacy_chat_check_before_provider(self):
        fixture = self.fixture()
        fixture.settings['relationship_check_in_form'] = True
        fixture.enqueue('relationship')
        client = fixtures.FakeClient(result=self.result())
        self.assertEqual(fixture.executor(client).tick()['status'], 'cancelled')
        self.assertEqual(client.calls, [])
        self.assertEqual(fixture.applied, [])

    def test_explicit_form_check_does_not_start_automatic_provider_polling(self):
        fixture = self.fixture()
        fixture.settings['relationship_check_in_form'] = True
        job = self.enqueue_form(fixture)
        client = fixtures.FakeClient(result=self.result())
        worker = fixture.executor(client)
        self.assertEqual(worker.tick()['status'], 'completed')
        self.assertEqual(fixture.repository.real_job(job['job_key'])['status'], 'completed')
        fixture.now += timedelta(minutes=5)
        self.assertEqual(worker.tick()['status'], 'idle')
        self.assertEqual(len(client.calls), 1)

    def test_legacy_mode_keeps_its_existing_polling_contract(self):
        fixture = self.fixture()
        fixture.enqueue('relationship')
        client = fixtures.FakeClient(result=self.result())
        self.assertEqual(fixture.executor(client).tick()['status'], 'polling')
        self.assertEqual(len(client.calls), 1)


if __name__ == '__main__':
    unittest.main()
