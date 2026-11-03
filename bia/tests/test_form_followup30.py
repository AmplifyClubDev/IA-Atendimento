"""Form handoff does not become chat inactivity or renew the 24-hour deadline."""
import unittest

from followup import CONVERSATION
from tests import test_inactivity_followup29 as fixtures


class FormFollowup30Tests(unittest.TestCase):
    def fixture(self, *, form, enabled):
        fixture = fixtures.InactivityFollowup29Tests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.f.settings['relationship_check_in_form'] = enabled
        state = fixture.f.repo.load_session(CONVERSATION)
        state['cycle']['phase'] = 'form' if form else 'origin'
        fixture.f.repo.save_session(CONVERSATION, state)
        return fixture

    def test_form_handoff_does_not_warn_close_or_change_deadline(self):
        fixture = self.fixture(form=True, enabled=True)
        before = fixture.f.repo.load_session(CONVERSATION)
        self.assertEqual(fixture.f.followup.tick()['status'], 'idle')
        self.assertEqual(fixture.f.transport.sent, [])
        self.assertEqual(fixture.closed, [])
        self.assertEqual(fixture.f.repo.load_session(CONVERSATION), before)

    def test_sdr_keeps_five_minute_warning(self):
        fixture = self.fixture(form=False, enabled=True)
        self.assertEqual(fixture.f.followup.tick()['status'], 'accepted')
        self.assertEqual(len(fixture.f.transport.sent), 1)

    def test_legacy_form_flow_keeps_its_existing_warning(self):
        fixture = self.fixture(form=True, enabled=False)
        self.assertEqual(fixture.f.followup.tick()['status'], 'accepted')
        self.assertEqual(len(fixture.f.transport.sent), 1)


if __name__ == '__main__':
    unittest.main()
