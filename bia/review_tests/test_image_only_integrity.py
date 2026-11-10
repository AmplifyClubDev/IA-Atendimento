"""Adversarial offline media regressions: preserve existing business authority."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import followup
import real_journey
import server
from real_operations import build_jobs
import test_image_only_guidance as media_fixture


CONVERSATION = 'chatwoot:1:7'
SOURCE = 'chatwoot:1:100'
CYCLE = '11111111-1111-4111-8111-111111111111'
CREATOR = '22222222-2222-4222-8222-222222222222'


class ImageIntegrity(unittest.TestCase):
    def setUp(self):
        self.fixture = media_fixture.ImageGuidance()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.now = datetime.now(timezone.utc)
        self.source_time = self.now - timedelta(minutes=10)
        self.event = server.normalize_chatwoot(self.fixture.payload(
            id='100', content='@synthetic', attachments=[], created_at=self.source_time.isoformat()))
        self.state = deepcopy(self.fixture.state)
        self.state.update(creator_id=CREATOR, effects={})
        self.state['cycle'].update(id=CYCLE, mode='real', phase='tiktok',
            opened_at=(self.now-timedelta(minutes=20)).isoformat(),
            last_inbound_at=self.source_time.isoformat(), expires_at=(self.now+timedelta(hours=23)).isoformat())
        self.proof = {'creator_id': CREATOR, 'atendimento_id': CYCLE,
                      'event_id': SOURCE, 'revision': self.state['revision']}
        self.state['contact_sync_proof'] = self.proof
        self.repo = self.fixture.repo
        self.repo.reserve_event(SOURCE, CONVERSATION, 'synthetic-original-text')
        self.repo.finish_event(SOURCE, 'completed')
        self.repo.reserve_operation(SOURCE+':contact:4', SOURCE, 'sync_contact')
        self.repo.complete_operation(SOURCE+':contact:4', self.proof)
        self.repo.save_session(CONVERSATION, self.state)
        self.assertTrue(self.repo.remember_followup_source(CONVERSATION, self.event, self.state))
        self.original_source = self.repo.followup_source(CONVERSATION)

    def send_image(self, message_id):
        timestamp = self.source_time - timedelta(minutes=1) if message_id == '99' else self.now
        response = self.fixture.send(self.fixture.payload(id=message_id, created_at=timestamp.isoformat()))
        self.assertEqual(response.json['status'], 'completed')
        return self.repo.load_session(CONVERSATION)

    def job(self):
        effect = {'id': 'synthetic-precheck', 'type': 'tiktok_operation', 'operation': 'precheck',
                  'creator': '@synthetic', 'cycle_id': CYCLE, 'status': 'pending',
                  'payload': {'operation': 'precheck', 'creator': '@synthetic', 'cycle_id': CYCLE}}
        self.state['effects'] = {effect['id']: effect}
        job = build_jobs(self.event, self.state, [effect])[0]
        self.repo.prepare_reply(SOURCE, CONVERSATION, self.state, SOURCE+':unused', None, real_jobs=[job])
        executor = self.fixture.app.extensions['v5_real_executor']
        # Separate copy prevents changing webhook readiness or starting a real worker.
        executor.settings = {**executor.settings, 'tiktok_mode': 'real',
                             'real_worker_enabled': True, 'contact_sync_enabled': True}
        self.assertTrue(executor._valid(job, self.state, self.now))
        return executor, job

    def assert_business_preserved(self, state):
        for key in ('revision', 'creator_id', 'contact_sync_proof', 'cycle', 'effects', 'history'):
            self.assertEqual(state[key], self.state[key], key)
        self.assertEqual(self.repo.followup_source(CONVERSATION), self.original_source)

    def test_new_image_preserves_already_authorized_job_and_sql_proof(self):
        executor, job = self.job()
        after = self.send_image('101')
        self.assertTrue(executor._valid(job, after, self.now))
        self.assert_business_preserved(after)
        self.assertEqual(after['processed_inbound'][-1], 'chatwoot:1:101')
        self.assertEqual(len(self.fixture.posts()), 1)

    def test_late_image_preserves_already_authorized_job_without_reply(self):
        executor, job = self.job()
        after = self.send_image('99')
        self.assertTrue(executor._valid(job, after, self.now))
        self.assert_business_preserved(after)
        self.assertEqual(after['processed_inbound'][-1], SOURCE)
        self.assertEqual(self.fixture.posts(), [])

    def followup_worker(self):
        config = {**self.fixture.config, 'tiktok_mode': 'real', 'real_worker_enabled': True,
            'contact_sync_enabled': True, 'conversation_enabled': True, 'followup_enabled': True,
            'followup_delay_seconds': '300', 'followup_start_at':
            (self.now-timedelta(hours=1)).isoformat()}
        self.assertTrue(followup.configured(config))
        worker = followup.Followup(self.repo, config, self.fixture.transport,
            self.fixture.app.extensions['v5_conversation_lock_for'], lambda event: {'allowed': True})
        self.assertTrue(worker._eligible(self.original_source, self.state, self.now))
        return worker

    def test_late_image_does_not_invalidate_current_text_followup(self):
        worker = self.followup_worker()
        after = self.send_image('99')
        self.assertTrue(worker._eligible(self.original_source, after, self.now))
        self.assert_business_preserved(after)

    def test_new_image_blocks_old_followup_without_replacing_its_source(self):
        worker = self.followup_worker()
        after = self.send_image('101')
        self.assertFalse(worker._eligible(self.original_source, after, self.now))
        self.assert_business_preserved(after)

    def test_image_preserves_existing_direct_registration_authority(self):
        self.state['cycle'].update(relationship_check_in_form=True,
            form_entry_request={'reason': 'registration_access', 'event': deepcopy(self.event),
                                'source_key': SOURCE, 'cycle_id': CYCLE, 'creator': '@synthetic'})
        self.repo.save_session(CONVERSATION, self.state)
        self.assertTrue(real_journey.form_entry_allowed(self.state, now=self.now))
        after = self.send_image('101')
        self.assertTrue(real_journey.form_entry_allowed(after, now=self.now))
        self.assert_business_preserved(after)

    def test_first_image_does_not_fabricate_business_revision_or_cycle(self):
        self.repo.save_session(CONVERSATION, {})
        after = self.send_image('101')
        self.assertNotIn('revision', after)
        self.assertNotIn('cycle', after)
        self.assertNotIn('contact_sync_proof', after)
        self.assertEqual(after['processed_inbound'], ['chatwoot:1:101'])
        self.assertEqual(len(self.fixture.posts()), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
