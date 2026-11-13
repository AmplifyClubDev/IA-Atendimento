"""Lead-facing copy, including queued but never attempted messages."""
import json
import unittest
from datetime import timedelta
import demo_flow
import demo_followup
import test_demo_followup as reminder_cases
import test_demo_inactivity_close as close_cases

class LeadCopy(unittest.TestCase):
    setUp = reminder_cases.Reminders.setUp
    due = reminder_cases.Reminders.due
    warning = close_cases.CloseCases.warning

    def test_reminder_and_closure_have_no_test_or_reset_language(self):
        texts=[demo_followup.PAYLOAD['content'],demo_followup.CLOSE_PAYLOAD['content'],demo_flow.TEMPLATES['closed'][0]]
        for text in texts:
            self.assertNotRegex(text.casefold(),r'test|reset|simula|ensaio')
        self.assertIn('mais 10 minutos',texts[0])
        self.assertEqual(texts[1], 'Como não tivemos resposta, encerrei este atendimento por agora.\n\nObrigada pela conversa! 💙')
        self.assertEqual(demo_flow.TEMPLATES['closed'][1], {})
        for _, menu in demo_flow.TEMPLATES.values():
            if 'close' in menu:self.assertEqual(menu['close'],'Encerrar atendimento')

    def test_pending_reminder_uses_new_copy_without_changing_due(self):
        old=dict(demo_followup.PAYLOAD,content='Mensagem de teste antiga')
        self.store.db.execute('UPDATE demo_followups SET payload=?',(json.dumps(old),))
        due=self.store.db.execute('SELECT due FROM demo_followups').fetchone()[0]
        self.due()
        self.assertEqual(demo_followup.tick(self.router)['status'],'accepted')
        self.assertEqual(self.gateway.sent[-1]['payload'],demo_followup.PAYLOAD)
        row=self.store.db.execute('SELECT payload,due FROM demo_followups').fetchone()
        self.assertEqual(json.loads(row['payload']),demo_followup.PAYLOAD)
        self.assertEqual(row['due'],due)

    def test_pending_closure_uses_new_copy_and_still_resolves(self):
        self.warning()
        old=dict(demo_followup.CLOSE_PAYLOAD,content='Para iniciar um novo teste, escreva Resetar.')
        self.store.db.execute('UPDATE demo_closures SET payload=?',(json.dumps(old),))
        due=self.store.db.execute('SELECT due FROM demo_closures').fetchone()[0]
        self.due()
        self.assertEqual(demo_followup.tick(self.router)['status'],'closed')
        self.assertEqual(self.gateway.sent[-1]['payload'],demo_followup.CLOSE_PAYLOAD)
        row=self.store.db.execute('SELECT payload,due FROM demo_closures').fetchone()
        self.assertEqual(json.loads(row['payload']),demo_followup.CLOSE_PAYLOAD)
        self.assertEqual(row['due'],due)
        self.assertEqual(len(self.gateway.resolved),1)

    def test_uncertain_reminder_payload_is_preserved_and_not_retried(self):
        old=json.dumps(dict(demo_followup.PAYLOAD,content='antigo'))
        self.store.db.execute("UPDATE demo_followups SET status='outcome_unknown',payload=?",(old,))
        self.due()
        self.assertEqual(demo_followup.tick(self.router)['status'],'idle')
        self.assertEqual(self.store.db.execute('SELECT payload FROM demo_followups').fetchone()[0],old)
        self.assertEqual(len(self.gateway.sent),1)

    def test_uncertain_closure_payload_is_preserved_and_not_retried(self):
        self.warning()
        old=json.dumps(dict(demo_followup.CLOSE_PAYLOAD,content='antigo'))
        self.store.db.execute("UPDATE demo_closures SET status='notice_unknown',payload=?",(old,))
        self.due()
        self.assertEqual(demo_followup.tick(self.router)['status'],'idle')
        self.assertEqual(self.store.db.execute('SELECT payload FROM demo_closures').fetchone()[0],old)
        self.assertEqual(len(self.gateway.sent),2)
        self.assertEqual(self.gateway.resolved,[])
