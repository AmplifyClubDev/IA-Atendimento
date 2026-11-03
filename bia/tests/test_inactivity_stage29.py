"""Closed-stage and opt-in configuration contracts, without any remote calls."""
from copy import deepcopy
import unittest
from uuid import uuid4

from config import load_settings
from ops.stage_preflight import APPROVED_LABELS, INACTIVITY_CLOSED_LABEL, inspect_labels
from transport import ChatwootProgress, ChatwootTransport, _PROGRESS_WITH_CLOSED


class Repo:
    def __init__(self, state):
        self.state, self.keys = deepcopy(state), set()
    def load_session(self, key):
        return deepcopy(self.state)
    def save_session(self, key, state):
        self.state = deepcopy(state)
    def event(self, key):
        return {'conversation_key': 'chatwoot:1:26097'}
    def reserve_operation(self, key, *args):
        if key in self.keys:
            return False
        self.keys.add(key)
        return True
    def complete_operation(self, *args):
        return True


class Adapter:
    progress_owned_merge = True
    def __init__(self):
        self.labels, self.writes = ['qualificação', 'outra-equipe'], []
    def read_progress(self, event):
        return list(self.labels)
    def write_progress(self, event, labels, key):
        self.writes.append(list(labels))
        self.labels = [item for item in self.labels if item not in _PROGRESS_WITH_CLOSED] + labels
        return {'status': 'outcome_unknown'}


class InactivityStage29Tests(unittest.TestCase):
    def setUp(self):
        self.gate = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
                     'phone': '+5547991154859', 'conversation_id': '26097', 'contact_id': '3',
                     'inactivity_close_enabled': True}
        self.event = {'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
                      'conversation_id': '26097', 'contact_id': '3', 'message_id': '777',
                      'message_type': 'incoming', 'private': False, 'sender_type': 'contact',
                      'sender_phone': '+554791154859', 'text': 'Quero me agenciar'}
        self.state = {'session_id': str(uuid4()), 'creator_id': str(uuid4()), 'revision': 7,
                      'cycle': {'id': str(uuid4()), 'phase': 'origin', 'status': 'closed',
                                'reason': 'inactivity_timeout'}}
        self.repo, self.adapter = Repo(self.state), Adapter()
        self.progress = ChatwootProgress(self.repo, self.gate, self.adapter)
    def proof(self):
        cycle = self.state['cycle']
        return {'kind': 'contact', 'receipt': {'creator_id': self.state['creator_id'],
                'atendimento_id': cycle['id'], 'event_id': 'chatwoot:1:777', 'revision': self.state['revision']},
                'snapshot': {'cycle_id': cycle['id'], 'phase': cycle['phase'],
                             'status': cycle['status'], 'revision': self.state['revision']}}
    def save(self):
        self.repo.state = deepcopy(self.state)
    def test_timeout_projects_closed_and_preserves_other_team_label(self):
        result = self.progress.sync(self.event, self.state, self.proof())
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(set(self.adapter.labels), {'encerrado', 'outra-equipe'})
        self.assertEqual(self.adapter.writes, [['encerrado']])
    def test_explicit_close_projects_same_closed_label(self):
        self.state['cycle']['reason'] = 'inactivity_user_close'; self.save()
        self.assertEqual(self.progress.sync(self.event, self.state, self.proof())['status'], 'confirmed')
        self.assertIn('encerrado', self.adapter.labels)
    def test_new_cycle_replaces_closed_with_intro_label(self):
        self.progress.sync(self.event, self.state, self.proof())
        self.state['cycle'] = {'id': str(uuid4()), 'phase': 'intro', 'status': 'open'}
        self.state['revision'] += 1; self.save()
        self.assertEqual(self.progress.sync(self.event, self.state, self.proof())['status'], 'confirmed')
        self.assertEqual(set(self.adapter.labels), {'conhecer', 'outra-equipe'})
    def test_completed_form_keeps_registration_label(self):
        self.state['cycle'].update(phase='form', reason='validated_form'); self.save()
        self.progress.sync(self.event, self.state, self.proof())
        self.assertEqual(set(self.adapter.labels), {'cadastro', 'outra-equipe'})
    def test_wrong_channel_never_changes_labels(self):
        self.event['inbox_id'] = '4'
        self.assertEqual(self.progress.sync(self.event, self.state, self.proof())['status'], 'ignored')
        self.assertEqual(self.adapter.writes, [])
    def test_missing_sql_receipt_never_marks_closed(self):
        self.assertEqual(self.progress.sync(self.event, self.state, {})['status'], 'ignored')
        self.assertEqual(self.adapter.writes, [])
    def test_stale_sql_snapshot_never_marks_closed(self):
        self.repo.state['revision'] += 1
        self.assertEqual(self.progress.sync(self.event, self.state, self.proof())['status'], 'ignored')
        self.assertEqual(self.adapter.writes, [])
    def test_legacy_preflight_does_not_require_sixth_label(self):
        rows = [{'id': index, **item} for index, item in enumerate(APPROVED_LABELS, 1)]
        self.assertEqual(inspect_labels(rows)['missing'], [])
        self.assertEqual(inspect_labels(rows, include_closed=True)['missing'], ['encerrado'])
    def test_new_preflight_requires_exact_closed_definition(self):
        rows = [{'id': index, **item} for index, item in enumerate(APPROVED_LABELS, 1)]
        rows.append({'id': 6, **INACTIVITY_CLOSED_LABEL})
        self.assertEqual(inspect_labels(rows, include_closed=True)['missing'], [])
        rows[-1]['show_on_sidebar'] = False
        self.assertEqual(inspect_labels(rows, include_closed=True)['collisions'], ['encerrado'])
    def test_closure_opt_in_requires_followup_and_exact_test_delay(self):
        self.assertFalse(load_settings({})['inactivity_close_enabled'])
        self.assertIn('inactivity_close_configuration_invalid',
                      load_settings({'V5_INACTIVITY_CLOSE_ENABLED': 'true'})['readiness_issues'])
        env = {'V5_INACTIVITY_CLOSE_ENABLED': 'true', 'V5_FOLLOWUP_ENABLED': 'true',
               'V5_INACTIVITY_CLOSE_DELAY_SECONDS': '301'}
        self.assertIn('inactivity_close_configuration_invalid', load_settings(env)['readiness_issues'])
        env['V5_INACTIVITY_CLOSE_DELAY_SECONDS'] = '300'
        self.assertNotIn('inactivity_close_configuration_invalid', load_settings(env)['readiness_issues'])
    def test_legacy_adapter_never_removes_closed_label_without_opt_in(self):
        requests = []
        adapter = ChatwootTransport('https://chatwoot.t2ffoz.easypanel.host', 'offline-token',
            {key: value for key, value in self.gate.items() if key != 'inactivity_close_enabled'},
            http=lambda **request: requests.append(request) or {})
        adapter._read_target = lambda *args, **kwargs: True
        adapter.write_progress(self.event, ['qualificação'], 'stage-test:1')
        self.assertEqual(len(requests), 1)
        self.assertEqual(set(requests[0]['json_body']['labels']['remove']),
                         {'conhecer', 'validação', 'convite', 'cadastro'})
        self.assertNotIn('encerrado', requests[0]['json_body']['labels']['remove'])


if __name__ == '__main__':
    unittest.main()
