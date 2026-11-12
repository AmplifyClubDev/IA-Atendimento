"""Production opt-in applies only to new cycles, no network."""
import unittest
import config
import real_journey
from lead_validation import stage
NOW='2026-11-12T18:00:00Z'
class Rollout(unittest.TestCase):
    def send(self,state,text,enabled=True,at=NOW):
        return real_journey.handle_real(state,text,now=at,qualification_enabled=enabled,qualification_new_cycles_only=True)
    def test_default_disabled_and_explicit_enabled(self):
        self.assertFalse(config.load_settings({})['qualification_enabled'])
        self.assertTrue(config.load_settings({'V5_QUALIFICATION_ENABLED':'true'})['qualification_enabled'])
        self.assertTrue(config.load_settings({})['qualification_new_cycles_only'])
    def test_new_cycle_qualifies(self):
        r=self.send({},'Quero fazer parte')
        self.assertEqual(stage(r['state']['cycle']),'agency')
        self.assertFalse(r['effects'])
    def test_existing_open_cycle_is_not_requalified(self):
        old=self.send({},'Oi',enabled=False)['state']
        r=self.send(old,'Quero me agenciar')
        self.assertIsNone(stage(r['state']['cycle']))
        self.assertFalse(r['state']['cycle']['qualification_rollout'])
    def test_legacy_unmarked_cycle_is_not_requalified(self):
        old=self.send({},'Oi',enabled=False)['state']
        old['cycle'].pop('qualification_rollout')
        r=self.send(old,'Quero me agenciar')
        self.assertIsNone(stage(r['state']['cycle']))
    def test_reset_admits_new_cycle(self):
        old=self.send({},'Oi',enabled=False)['state']
        r=self.send(old,'resetar')
        r=self.send(r['state'],'Quero fazer parte')
        self.assertEqual(stage(r['state']['cycle']),'agency')
    def test_flag_off_does_not_abandon_in_progress_validation(self):
        r=self.send({},'Quero fazer parte')
        r=self.send(r['state'],'Não',enabled=False)
        self.assertEqual(stage(r['state']['cycle']),'shop')
        self.assertFalse(r['effects'])
    def test_admitted_cycle_keeps_qualification_across_turns(self):
        r=self.send({},'Oi')
        r=self.send(r['state'],'Quero me agenciar')
        self.assertEqual(stage(r['state']['cycle']),'agency')
