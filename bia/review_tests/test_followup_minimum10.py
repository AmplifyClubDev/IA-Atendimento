import unittest
from datetime import datetime,timedelta,timezone
from followup import Followup
from demo_followup import effective_due,PAYLOAD

class MinimumTen(unittest.TestCase):
    def test_single_real_owner(self):
        worker=Followup.__new__(Followup)
        worker.settings={'retomada_enabled':True,'followup_enabled':True,'inactivity_close_enabled':True}
        self.assertEqual(worker._tick(),{'status':'disabled','reason':'retomada_owner'})
    def test_old_and_new_demo_deadline_extended_without_new_key(self):
        at=datetime(2026,11,13,15,tzinfo=timezone.utc)
        row={'key':'bia-demo-followup:v2:old-key','due':(at+timedelta(minutes=5)).isoformat()}
        self.assertEqual(effective_due(row),at+timedelta(minutes=10))
        closure={'key':'bia-demo-close:old-key','due':(at+timedelta(minutes=15)).isoformat()}
        self.assertEqual(effective_due(closure),at+timedelta(minutes=20))
        self.assertIn('10 minutos',PAYLOAD['content'])
