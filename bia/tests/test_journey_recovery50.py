"""Conclusão exige identidade compatível, inclusive nas fichas antigas duplicadas."""
from datetime import timedelta
from uuid import uuid4
import unittest
from gateway import Gateway, SubmissionRejected, SubmissionUnknown
from config import PROJECT_REF
from test_release39 import RetomadaTests


class RegistrationIdentityTests(unittest.TestCase):
    def check_rows(self, rows):
        self.calls = []
        def read(**kw):
            self.calls.append(kw)
            return rows
        return Gateway({'v5_url': 'https://' + PROJECT_REF + '.supabase.co', 'v5_service_key': 'server'},
                       transport=read).registration_status('+5575991040908', '@gabiosantana1')

    def row(self, phone='5575991040908', handle='gabiosantana1', status='Confirmado'):
        return dict(id=str(uuid4()), whatsapp=phone, tiktok=handle, cadastro=status)

    def test_compatible_phone_and_profile_confirm_old_reference_without_reassignment(self):
        rows = [self.row('557591040908', None, 'Pendente'), self.row()]
        self.assertEqual(self.check_rows(rows), 'confirmado')
        self.assertEqual(self.calls[0]['method'], 'GET')
        self.assertNotIn('email', self.calls[0]['url'])

    def test_same_handle_other_person_is_not_completion(self):
        self.assertEqual(self.check_rows([self.row('5533984551406')]), 'conferencia')

    def test_same_phone_other_profile_and_duplicate_confirmed_are_ambiguous(self):
        self.assertEqual(self.check_rows([self.row(handle='other'), self.row()]), 'conferencia')
        self.assertEqual(self.check_rows([self.row(), self.row()]), 'conferencia')

    def test_incomplete_or_malformed_read_is_not_absence(self):
        for rows in ([self.row()] * 10, {}, [{'id': 'bad'}]):
            with self.assertRaises(SubmissionUnknown):
                self.check_rows(rows)

    def test_unfinished_registration_stays_pending(self):
        self.assertEqual(self.check_rows([self.row(status='Pendente')]), 'pendente')


class CompletionRefreshTests(RetomadaTests):
    def form(self):
        state = self.repo.load_session(self.CONV)
        state['cycle']['phase'] = 'form'
        self.repo.save_session(self.CONV, state)

    def test_completion_before_reminder_due_updates_state_without_message(self):
        self.form()
        self.subject.registration = lambda _: 'confirmado'
        self.tick_at(timedelta(minutes=1))
        self.assertEqual(self.repo.load_session(self.CONV)['cadastro_situacao'], 'confirmado')
        self.assertEqual(self.chatwoot.sent, [])

    def test_expired_form_still_recognizes_completion_without_reopening(self):
        self.form()
        self.subject.registration = lambda _: 'confirmado'
        self.tick_at(timedelta(hours=25))
        self.assertEqual(self.repo.load_session(self.CONV)['cadastro_situacao'], 'confirmado')
        self.assertEqual(self.chatwoot.sent, [])

    def test_identity_conflict_blocks_generic_form_reminder(self):
        self.form()
        self.subject.registration = lambda _: 'conferencia'
        self.tick_at(timedelta(hours=3))
        self.assertEqual(self.chatwoot.sent, [])
