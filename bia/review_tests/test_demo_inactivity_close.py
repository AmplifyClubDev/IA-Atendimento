"""5+5 closure: mocked time/provider, no real messages or status writes."""
import io
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from demo_followup import tick, tick_all
from demo_router import DemoStore, DemoRouter, DemoWhatsAppGateway, DemoMultiplexer, configure_context_payload
from test_demo_followup import Reminders
from test_demo_router import event, SCOPE, OTHER
from test_demo_review_boundaries import FakeChatwoot, REVIEW_SCOPE, STAMP

class CloseCases(unittest.TestCase):
    setUp = Reminders.setUp
    due = Reminders.due

    def warning(self):
        self.due()
        self.assertEqual(tick(self.router)['status'], 'accepted')
        row = self.store.db.execute('SELECT * FROM demo_closures').fetchone()
        self.gateway.preflight.return_value = {'after_message_id': row['warning_message_id']}
        return row

    def test_five_plus_five_closes_once_preserving_history(self):
        self.warning()
        before = [self.store.db.execute('SELECT count(*) FROM '+t).fetchone()[0]
                  for t in ('demo_outbox','demo_events','demo_starts')]
        self.at += timedelta(seconds=299)
        self.assertEqual(tick(self.router)['status'], 'idle')
        self.at += timedelta(seconds=1)
        self.assertEqual(tick(self.router), {'status':'closed','stage':'closure'})
        state = self.store.current(SCOPE.slot)
        self.assertEqual((state['step'], state['choice']), ('closed','inactivity_timeout'))
        self.assertEqual(state['run'], self.state['run'])
        self.assertEqual(len(self.gateway.sent), 3)
        self.assertEqual(len(self.gateway.resolved), 1)
        self.assertEqual(tick(self.router)['status'], 'idle')
        self.assertEqual(before, [self.store.db.execute('SELECT count(*) FROM '+t).fetchone()[0]
                  for t in ('demo_outbox','demo_events','demo_starts')])

    def test_interaction_cancels_without_restart(self):
        self.warning()
        before=self.store.current(SCOPE.slot)
        self.router.handle(event(message_id='102',text='Voltar ao início',created_at=self.at.isoformat()))
        self.due()
        self.assertEqual(tick(self.router)['status'],'idle')
        self.assertEqual(self.store.current(SCOPE.slot), before)
        self.assertEqual(self.gateway.resolved, [])

    def test_provider_new_message_cancels_closure(self):
        self.warning(); self.due()
        self.gateway.preflight.return_value={'after_message_id':'999999'}
        self.assertEqual(tick(self.router)['status'],'source_changed')
        self.assertEqual(len(self.gateway.sent),2)
        self.assertEqual(self.gateway.resolved, [])

    def test_unknown_notice_never_resolves_or_resends(self):
        self.warning(); self.due()
        self.gateway.send=Mock(side_effect=TimeoutError)
        self.assertEqual(tick(self.router)['status'],'unconfirmed')
        self.assertEqual(tick(self.router)['status'],'idle')
        self.gateway.send.assert_called_once()
        self.assertEqual(self.gateway.resolved, [])
        self.assertNotEqual(self.store.current(SCOPE.slot)['step'],'closed')

    def test_unknown_resolution_never_retries(self):
        self.warning(); self.due()
        self.gateway.resolve_inactivity=Mock(side_effect=TimeoutError)
        self.assertEqual(tick(self.router)['status'],'unconfirmed')
        self.assertEqual(self.store.current(SCOPE.slot)['step'],'closed')
        self.assertEqual(tick(self.router)['status'],'idle')
        self.gateway.resolve_inactivity.assert_called_once()

    def test_old_accepted_warning_not_backfilled(self):
        self.store.db.execute("UPDATE demo_followups SET status='accepted'")
        self.at += timedelta(minutes=30)
        self.assertEqual(tick(self.router)['status'],'idle')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_closures').fetchone()[0],0)

    def test_old_pending_warning_cannot_create_closure(self):
        self.store.db.execute("UPDATE demo_followups SET key=replace(key,':v2:',':')")
        self.due()
        self.assertEqual(tick(self.router)['status'],'accepted')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_closures').fetchone()[0],0)

    def test_disabled_feature_blocks_existing_pending_close(self):
        self.warning(); self.due(); self.router.followup_enabled=False
        self.assertEqual(tick(self.router)['status'],'disabled')
        self.assertEqual(self.gateway.resolved, [])

    def test_reset_cancels_old_episode(self):
        self.warning()
        self.router.handle(event(message_id='102',text='Resetar',created_at=self.at.isoformat()))
        self.due()
        tick(self.router)
        self.assertEqual(self.gateway.resolved, [])
        self.assertNotEqual(self.store.current(SCOPE.slot)['run'],self.state['run'])

    def test_expired_close_does_not_replay_after_downtime(self):
        self.warning();self.at+=timedelta(hours=1)
        self.assertEqual(tick(self.router)['status'],'expired')
        self.assertEqual(self.gateway.resolved, [])

    def test_restart_preserves_due_and_deduplication(self):
        self.warning()
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'demo.sqlite')
            import sqlite3
            db=sqlite3.connect(path);self.store.db.backup(db);db.close()
            other=DemoStore(path);self.addCleanup(other.close)
            router=DemoRouter(SCOPE,other,self.gateway,now=lambda:self.at,continuation_enabled=True,followup_enabled=True)
            self.due()
            self.assertEqual(tick(router)['status'],'closed')
            self.assertEqual(tick(router)['status'],'idle')
            self.assertEqual(len(self.gateway.resolved),1)

class LifecycleProvider(FakeChatwoot):
    def __init__(self):
        super().__init__();self.detail['status']='open';self.next_id=201
    def open(self,request,timeout):
        if request.method=='POST' and request.full_url.endswith('/toggle_status'):
            self.calls.append((request.method,request.full_url,json.loads(request.data)))
            self.detail['status']='resolved'
            return io.BytesIO(json.dumps({'status':'resolved'}).encode())
        if request.method=='POST':
            self.post_result={'id':str(self.next_id),'conversation_id':REVIEW_SCOPE.conversation_id}
            self.next_id+=1
            self.messages.append({'id':self.post_result['id'],'message_type':'outgoing','private':False})
        return super().open(request,timeout)

class ProviderClose(unittest.TestCase):
    def setUp(self):
        self.at=STAMP;self.provider=LifecycleProvider();self.store=DemoStore(':memory:');self.addCleanup(self.store.close)
        self.gateway=DemoWhatsAppGateway('https://chat.review.invalid','synthetic-token',scope=REVIEW_SCOPE,
            live_enabled=True,opener=self.provider,now=lambda:self.at,continuation_enabled=True)
        configure_context_payload(self.gateway,self.store,REVIEW_SCOPE)
        self.router=DemoRouter(REVIEW_SCOPE,self.store,self.gateway,now=lambda:self.at,continuation_enabled=True,followup_enabled=True)
        self.router.start('synthetic-close-start')
        self.at+=timedelta(minutes=5)
        self.assertEqual(tick(self.router)['status'],'accepted')
        self.at+=timedelta(minutes=5)

    def test_resolves_exact_conversation_with_explicit_status(self):
        self.assertEqual(tick(self.router)['status'],'closed')
        status_calls=[c for c in self.provider.calls if c[1].endswith('/toggle_status')]
        self.assertEqual(status_calls,[('POST','https://chat.review.invalid/api/v1/accounts/2/conversations/13/toggle_status',{'status':'resolved'})])
        self.assertEqual(self.provider.detail['status'],'resolved')

    def test_human_takeover_cancels_notice_and_resolution(self):
        self.provider.detail['meta']['assignee']={'id':'9'}
        self.assertEqual(tick(self.router)['status'],'human_or_closed')
        self.assertEqual(len([c for c in self.provider.calls if c[0]=='POST']),2)

    def test_last_moment_reply_prevents_notice_and_resolution(self):
        original=self.gateway.preflight;count=[0]
        def racing(scope):
            count[0]+=1
            if count[0]==2:self.provider.messages.append({'id':'333','message_type':'incoming','private':False,'created_at':self.at.timestamp()})
            return original(scope)
        self.gateway.preflight=racing
        self.assertEqual(tick(self.router)['status'],'unconfirmed')
        self.assertEqual(len([c for c in self.provider.calls if c[0]=='POST']),2)
        self.assertEqual(tick(self.router)['status'],'idle')

    def test_reply_after_notice_prevents_provider_resolution(self):
        original=self.gateway.resolve_inactivity
        def racing(scope,key):
            self.provider.messages.append({'id':'333','message_type':'incoming','private':False,'created_at':self.at.timestamp()})
            return original(scope,key)
        self.gateway.resolve_inactivity=racing
        self.assertEqual(tick(self.router)['status'],'unconfirmed')
        self.assertFalse(any(c[1].endswith('/toggle_status') for c in self.provider.calls))

    def test_unreserved_or_other_scope_cannot_resolve(self):
        with self.assertRaises(ValueError):self.gateway.resolve_inactivity(REVIEW_SCOPE,'bia-demo-close:unreserved')
        with self.assertRaises(ValueError):self.gateway.resolve_inactivity(SCOPE,'bia-demo-close:unreserved')
        self.assertFalse(any(c[1].endswith('/toggle_status') for c in self.provider.calls))
