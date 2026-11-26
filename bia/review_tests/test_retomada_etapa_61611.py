from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import retomada as f

AT = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)
KEY = 'chatwoot:1:100'
CONV = 'chatwoot:1:1:999'


class Store:
    def __init__(self):
        self.state = {'processed_inbound': [KEY], 'cycle': {
            'id': 'c', 'status': 'open', 'mode': 'real', 'phase': 'intro', 'facts': {},
            'opened_at': AT.isoformat(), 'last_inbound_at': AT.isoformat(),
            'expires_at': (AT + timedelta(hours=24)).isoformat(),
        }}
        self.source = {'cycle_id': 'c', 'event_key': KEY, 'event': {
            'provider': 'chatwoot', 'account_id': '1', 'message_id': '100',
            'created_at': AT.isoformat(),
        }}
        self.ops = {}
        self.last = AT

    def followup_source(self, conv): return deepcopy(self.source)
    def load_session(self, conv): return deepcopy(self.state)
    def save_session(self, conv, state): self.state = deepcopy(state)
    def get_operation(self, key): return self.ops.get(key)
    def followup_clear(self, conv, state): return True
    def conversation_delivery_context(self, conv, at):
        return {'latest_attempt_status':'accepted', 'last_accepted_reply':{'at':self.last.isoformat()}}
    def reserve_followup(self, conv, source, state, key, payload):
        if key in self.ops: return False
        self.ops[key] = 'reserved'
        return True
    def complete_operation(self, key, receipt, status): self.ops[key] = status
    def finish_outbox(self, *args): pass


class FollowupPerStage(unittest.TestCase):
    def setUp(self):
        self.repo = Store()
        self.out = []
        self.closed = []
        self.ack = 'accepted'
        self.current = AT
        self.worker = f.Retomada(
            self.repo, {}, SimpleNamespace(send_reply=self.send), lambda _:nullcontext(),
            lambda event:{'allowed':True}, now=lambda:self.current,
            on_stopped=lambda *args:self.closed.append(args),
        )
        self.worker._source_unchanged = lambda *args: True

    def send(self, event, text, buttons, key, before_write):
        assert before_write()
        self.out.append((text, buttons))
        if self.ack == 'accepted': self.repo.last = self.current
        return {'status':self.ack}

    def tick(self, minutes):
        self.current = AT + timedelta(minutes=minutes)
        with patch.object(f, 'allow_inbound', return_value=True), patch.object(f, 'production_blocked', return_value=False):
            return self.worker._conversation(CONV, self.current)

    def test_no_handle_before_interest_followed_by_separate_close(self):
        self.assertEqual(self.tick(9)['status'], 'idle')
        self.assertEqual(self.tick(10)['step'], 1)
        self.assertIn('conhecer melhor', self.out[0][0])
        self.assertIn('encerrar atendimento', self.out[0][0])
        self.assertNotIn('@', self.out[0][0])
        self.assertNotIn('arroba_pedido', self.repo.state['cycle'])
        self.assertEqual(self.repo.state['cycle']['status'], 'open')
        self.assertEqual(self.tick(19)['status'], 'idle')
        self.assertEqual(self.tick(20)['step'], 2)
        self.assertEqual(self.out[-1], (f.FOLLOWUP_CLOSE, []))
        self.assertEqual(self.repo.state['cycle']['status'], 'closed')
        self.assertEqual(len(self.closed), 1)
        self.tick(60)
        self.assertEqual(len(self.out), 2)
        self.assertEqual(len(self.closed), 1)

    def test_late_scan_still_warns_first_and_gives_ten_minutes(self):
        self.assertEqual(self.tick(29)['step'], 1)
        self.assertEqual(self.tick(38)['status'], 'idle')
        self.assertEqual(self.tick(39)['step'], 2)

    def test_human_control_advance_reply_and_optout_never_close_the_old_step(self):
        for case in ['human_control', 'phase', 'inbound', 'opt_out']:
            with self.subTest(case=case):
                self.setUp()
                self.tick(10)
                if case == 'phase': self.repo.state['cycle']['phase'] = 'tiktok'
                elif case == 'inbound': self.repo.state['processed_inbound'].append('chatwoot:1:101')
                else: self.repo.state[case] = True
                self.tick(20)
                self.assertEqual(len(self.out), 1)
                self.assertFalse(self.closed)

    def test_unknown_receipt_does_not_close_or_retry(self):
        self.ack = 'outcome_unknown'
        self.tick(10)
        self.tick(30)
        self.assertEqual(len(self.out), 1)
        self.assertFalse(self.closed)

    def test_stage_specific_copy_and_exclusions(self):
        for stage, keyword in [('agency','agenciado'),('shop','ativado'),('activate','ative'),('gmv','GMV')]:
            with self.subTest(stage=stage):
                cycle = {'phase':'intro','bia_validation':{'stage':stage},'facts':{}}
                self.assertIn(keyword, f.message({'cycle':cycle}, 1, {})[0])
        for stage in ['specialist','priority_alert']:
            self.assertIsNone(f.message({'cycle':{'phase':'intro','bia_validation':{'stage':stage}}}, 1, {}))
        self.assertIsNone(f.message({'cycle':{'phase':'blocked'}}, 1, {}))
        self.assertIsNone(f.message({'cycle':{'phase':'await_acceptance'}},1,{}))
        self.assertIsNone(f.message({'cycle':{'valid':True,'phase':'form','acesso_liberado':True}},1,{}))
        with patch('real_journey.invite_acceptance_proven',return_value=True):
            msg, buttons = f.message({'cycle':{'phase':'await_acceptance'}},1,{})
            self.assertIn('Parcerias', msg)
            self.assertEqual(buttons,['Já aceitei'])

    def test_legacy_warning_not_replayed_or_used_for_new_closure(self):
        self.repo.ops[f.step_key('c',KEY,1)]='completed'
        self.repo.state['cycle']['retomada']={'step':1,'at':AT.isoformat()}
        self.tick(30)
        self.assertFalse(self.out)
        self.assertFalse(self.closed)
