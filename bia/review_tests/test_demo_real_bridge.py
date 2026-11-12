"""No network, provider sends or database writes outside temporary rehearsal files."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from flask import Flask, jsonify

from demo_router import DemoScope, DemoStore, DemoRouter, RecordingGateway, production_blocked
from demo_real_bridge import DemoRealBridge, isolated_settings, install
from demo_followup import tick

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
PHONE = '+5511900000000'
SCOPE = DemoScope('1', '3', '9', '7', PHONE)
OTHER = DemoScope('1', '3', '10', '8', '+5512900000000')


def event(**kw):
    return {'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3', 'contact_id': '9',
            'conversation_id': '7', 'message_id': '101', 'sender_phone': PHONE,
            'message_type': 'incoming', 'private': False, 'sender_type': 'contact',
            'text': 'Quero fazer parte', 'created_at': NOW.isoformat(), **kw}


def settings(root):
    return {'state_dir': str(root), 'demo_enabled': True, 'demo_real_enabled': True,
        'demo_real_test_phone': PHONE, 'demo_continuation_enabled': True,
        'demo_scope': SCOPE.__dict__, 'demo_scopes': [SCOPE.__dict__, OTHER.__dict__],
        'demo_pending_scope': None, 'demo_state_path': str(root/'demo.sqlite'),
        'demo_whatsapp_live': False, 'demo_followup_enabled': True,
        'tiktok_mode': 'real', 'real_worker_enabled': True, 'contact_sync_enabled': True,
        'gate': {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
                 'phone': PHONE, 'mode': 'todos', 'phones': [PHONE, OTHER.phone]},
        'public_url': 'https://test.example', 'webhook_token': 'x'*32}


class Cases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.settings = settings(self.root)
        self.store = DemoStore(str(self.root/'demo.sqlite')); self.addCleanup(self.store.close)
        self.router = DemoRouter(SCOPE, self.store, RecordingGateway(), now=lambda: NOW,
                                 continuation_enabled=True, followup_enabled=True)
        self.runtime = Flask('synthetic-real-runtime')
        self.runtime.extensions['v5_real_executor'] = Mock(guard=lambda ev: {'allowed': True})
        self.processed = []
        def process(ev):
            self.processed.append(ev); return {'accepted': True, 'status': 'completed'}, 200
        self.runtime.extensions['v5_process_inbound'] = process
        self.runtime.extensions['v5_forms_store'] = Mock(row=lambda token: token == 'a'*43)
        @self.runtime.get('/cadastro/api/contexto')
        def context(): return jsonify(source='isolated')
        self.bridge = DemoRealBridge(self.settings, [SCOPE], self.root/'real', runtime_factory=lambda s: self.runtime)
        self.addCleanup(self.bridge.db.close)
        self.store.real_bridge = self.bridge

    def test_default_disabled_does_not_construct_runtime(self):
        app=Flask('disabled'); factory=Mock()
        self.assertIsNone(install(app, {'demo_real_enabled': False}, runtime_factory=factory))
        factory.assert_not_called()

    def test_runtime_gate_is_never_all_and_state_separate(self):
        child=isolated_settings(self.settings, [SCOPE])
        self.assertEqual(child['gate']['mode'],'lista'); self.assertEqual(child['gate']['phones'], [PHONE])
        self.assertFalse(child['demo_enabled']); self.assertNotIn('demo_scopes',child)
        self.assertNotEqual(child['state_dir'], self.settings['state_dir'])
        self.assertFalse(child['followup_enabled']); self.assertFalse(child['retention_enabled'])
        self.assertFalse(child['gate']['inactivity_close_enabled'])

    def test_unselected_and_not_enrolled_never_dispatch(self):
        self.assertIsNone(self.bridge.dispatch(self.router, event()))
        other=DemoRouter(OTHER,self.store,RecordingGateway(),now=lambda:NOW)
        self.assertIsNone(self.bridge.dispatch(other,event(),begin=True)); self.assertFalse(self.processed)

    def test_exact_scope_required_before_handoff(self):
        for change in ({'sender_phone':OTHER.phone},{'contact_id':'10'},{'inbox_id':'4'},{'conversation_id':'8'}):
            self.assertFalse(self.bridge.dispatch(self.router,event(**change),begin=True)[0]['accepted'])
        self.assertFalse(self.processed); self.assertIsNone(self.bridge.enrolled(SCOPE))

    def test_stale_event_rejected(self):
        ev=event(created_at=(NOW-timedelta(minutes=6)).isoformat())
        self.assertEqual(self.bridge.dispatch(self.router,ev,begin=True)[0]['status'],'demo_real_stale_event')
        self.assertFalse(self.processed)

    def test_handoff_persists_without_simulated_proofs_or_facts(self):
        self.assertTrue(self.bridge.dispatch(self.router,event(),begin=True)[0]['accepted'])
        self.assertEqual(self.processed,[event()])
        self.assertTrue(self.bridge.authorized_event(event()))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_simulations').fetchone()[0],0)
        self.assertEqual(tick(self.router)['status'],'real_handoff_active')
        self.assertEqual(self.router.start('synthetic-start-key')['status'],'demo_real_already_active')

    def test_old_or_conflicting_event_does_not_enter_real_flow(self):
        self.bridge.dispatch(self.router,event(),begin=True)
        self.assertFalse(self.bridge.dispatch(self.router,event(message_id='100'))[0]['accepted'])
        self.assertFalse(self.bridge.dispatch(self.router,event(text='changed'))[0]['accepted'])
        self.assertEqual(len(self.processed),1)

    def test_provider_outcome_unknown_never_returns_to_simulation(self):
        def failed(ev): raise TimeoutError('synthetic')
        self.runtime.extensions['v5_process_inbound']=failed
        with self.assertRaises(TimeoutError): self.bridge.dispatch(self.router,event(),begin=True)
        self.assertIsNotNone(self.bridge.enrolled(SCOPE))
        self.assertEqual(tick(self.router)['status'],'real_handoff_active')

    def test_new_conversation_cannot_repeat_existing_invite(self):
        self.bridge.dispatch(self.router,event(),begin=True)
        newer=DemoScope('1','3','9','99',PHONE)
        router=DemoRouter(newer,self.store,RecordingGateway(),now=lambda:NOW)
        result=self.bridge.dispatch(router,event(conversation_id='99',message_id='102'))
        self.assertEqual(result[0]['status'],'demo_real_previous_conversation_active')
        self.assertEqual(len(self.processed),1)

    def test_unknown_demo_outcome_blocks_new_handoff(self):
        self.store.db.execute('INSERT INTO demo_outbox VALUES(?,?,?,?,?,?)',('x',SCOPE.slot,'r','{}','outcome_unknown','{}'))
        result=self.bridge.dispatch(self.router,event(),begin=True)
        self.assertEqual(result[0]['status'],'demo_real_delivery_unconfirmed'); self.assertFalse(self.processed)

    def test_durable_scope_removal_fails_closed(self):
        self.bridge.dispatch(self.router,event(),begin=True)
        with self.assertRaisesRegex(ValueError,'active_history'):
            DemoRealBridge(self.settings,[OTHER],self.root/'real',runtime_factory=lambda s:self.runtime)

    def test_executor_guard_rejects_spoofed_identity(self):
        self.bridge.dispatch(self.router,event(),begin=True)
        guard=self.runtime.extensions['v5_real_executor'].guard
        self.assertTrue(guard(event())['allowed'])
        self.assertFalse(guard(event(contact_id='10'))['allowed'])

    def test_form_tokens_remain_store_scoped(self):
        self.assertTrue(self.bridge.owns_form('a'*43))
        self.assertFalse(self.bridge.owns_form('b'*43)); self.assertFalse(self.bridge.owns_form('a'))

    def test_selected_phone_requires_unique_existing_scope(self):
        app=Flask('install'); app.extensions['v5_demo_router']=self.router
        with self.assertRaisesRegex(ValueError,'not_in_verified_demo'):
            install(app,{**self.settings,'demo_real_test_phone':'+5513900000000'},start=False)

    def test_stop_and_reset_stay_in_real_runtime(self):
        self.bridge.dispatch(self.router,event(),begin=True)
        for i,text in enumerate(('parar','resetar'),102):
            result=self.router.handle(event(message_id=str(i),text=text))
            self.assertEqual(result[0]['status'],'demo_real_active')
        self.assertEqual([ev['text'] for ev in self.processed],['Quero fazer parte','parar','resetar'])

    def test_valid_join_hooks_real_runtime_without_simulation(self):
        self.router.start('synthetic-hook-test')
        ev=event(demo_reply_to=self.store.current(SCOPE.slot)['parent_id'])
        result=self.router.handle(ev)
        self.assertEqual(result[0]['status'],'demo_real_active')
        self.assertEqual(self.processed,[ev])
        self.assertEqual(len(self.router.gateway.sent),1)

    def test_worker_guard_can_run_while_inbound_runtime_is_processing(self):
        import threading
        seen=[]
        def process(ev):
            thread=threading.Thread(target=lambda:seen.append(self.bridge.authorized_event(ev)),daemon=True)
            thread.start();thread.join(timeout=2)
            self.assertFalse(thread.is_alive(), 'registry lock must not span provider/runtime calls')
            return {'accepted':True,'status':'completed'},200
        self.runtime.extensions['v5_process_inbound']=process
        self.bridge.dispatch(self.router,event(),begin=True)
        self.assertEqual(seen,[True])

    def test_form_dispatch_only_existing_isolated_token(self):
        main=Flask('main-form-dispatch')
        main.extensions['v5_demo_router']=self.router
        @main.get('/cadastro/api/contexto')
        def main_context():return jsonify(source='main')
        bridge=install(main,self.settings,runtime_factory=lambda s:self.runtime,start=False)
        self.addCleanup(bridge.db.close)
        with main.test_client() as client:
            self.assertEqual(client.get('/cadastro/api/contexto',headers={'Authorization':'Bearer '+'a'*43}).json['source'],'isolated')
            self.assertEqual(client.get('/cadastro/api/contexto',headers={'Authorization':'Bearer '+'b'*43}).json['source'],'main')

    def test_actual_runtime_constructs_with_separate_repository_and_forms(self):
        real_settings={**self.settings,'webhook_token':'synthetic-'+'x'*32,'form_secret':'y'*32,
                       'conversation_enabled':True,'ai_enabled':True,'instance_id':'synthetic-real-test'}
        bridge=DemoRealBridge(real_settings,[SCOPE],self.root/'construction')
        self.addCleanup(bridge.db.close)
        self.assertIsNone(bridge.runtime.extensions['v5_demo_router'])
        self.assertIsNotNone(bridge.runtime.extensions['v5_forms_store'])
        self.assertTrue(str(bridge.runtime.extensions['v5_repository'].path).endswith('demo-real-test/runtime/atendimento.sqlite3'))
        self.assertFalse(bridge.status()['ready'])

if __name__ == '__main__': unittest.main()
