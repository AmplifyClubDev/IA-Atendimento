"""A deferred personal decision cannot control a newer consent offer."""
from copy import deepcopy
import unittest

from tests import test_audit_turn_fencing31 as fixtures
from tests import test_real_journey as journeys


class LatePersonalPause32Tests(unittest.TestCase):
    def test_old_personal_pause_preserves_current_cycle_and_consent(self):
        fixture = fixtures.TurnFencing31Tests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        state = journeys.eligible_state()['state']
        state['creator_id'] = fixtures.CREATOR
        state['processed_inbound'] = ['chatwoot:1:2002']
        fixture.repo.reserve_event('chatwoot:1:2002', fixtures.CONV, 'offline-seed')
        fixture.repo.prepare_reply('chatwoot:1:2002', fixtures.CONV, state, 'seed:no-reply', None)
        fixture.repo.finish_event('chatwoot:1:2002', 'completed')
        before = deepcopy(fixture.repo.load_session(fixtures.CONV))

        response = fixture.post(fixture.payload(2001, 'Prefiro pensar um pouco e volto depois'))

        self.assertEqual(response[0], 200)
        self.assertEqual(response[1]['status'], 'completed')
        self.assertTrue(response[1]['reply_suppressed'])
        after = fixture.repo.load_session(fixtures.CONV)
        self.assertEqual(after['cycle'], before['cycle'])
        self.assertEqual(after['effects'], before['effects'])
        self.assertEqual(after['revision'], before['revision'])
        self.assertEqual(after.get('closed_cycles'), before.get('closed_cycles'))
        self.assertEqual(after['processed_inbound'][-1], 'chatwoot:1:2002')
        self.assertTrue(after['history'][-1]['late_control'])
        self.assertEqual(fixture.calls, [])
        self.assertEqual(fixture.http.posts, [])
        self.assertEqual(fixture.repo.event('chatwoot:1:2001')['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
