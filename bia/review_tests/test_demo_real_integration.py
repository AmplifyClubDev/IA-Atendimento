"""Actual isolated app/worker/form integration, all providers synthetic."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
from review_tests.test_demo_real_bridge import settings, SCOPE, event
from demo_real_bridge import install
from demo_router import DemoRouter, DemoStore, RecordingGateway
from server import create_app
from forms import register_forms
from tests.test_real_executor import FakeClient, FakeGateway
from tests.test_worker_form_context import Transport

class Integration(unittest.TestCase):
    def test_real_join_profile_consent_one_invite_and_scoped_form(self):
        with tempfile.TemporaryDirectory() as directory, patch('real_journey.AUTO_INVITE', True):
            root=Path(directory); config=settings(root)
            config.update(conversation_enabled=True, ai_enabled=False, webhook_token='w'*40,
                form_secret='s'*40, tiktok_policy_approved=True, tiktok_invite_commission='10',
                tiktok_policy_version='synthetic', tiktok_commission_unit='percent',
                tiktok_duration_fixed_months='2', tiktok_duration_label='2 meses',
                form_public_url='https://amplify-cadastro.up.railway.app/cadastro/ensaio')
            posted=[]
            def provider(operation,creator,kwargs):
                if operation=='invite':
                    self.assertTrue(kwargs['before_write']())
                    posted.append(creator)
                status={'lookup':'verification_pending','precheck':'eligible','invite':'sent',
                        'relationship':'linked' if posted else 'not_found'}[operation]
                return {'operation':operation,'creator':creator,'status':status,'confirmed':True,
                    'observed_at':datetime.now(timezone.utc).isoformat(),
                    'evidence':{'source':'partner_relations','complete':True,'exact':True,'fresh':True,
                                'active':bool(posted),'relation_id':'synthetic-relation','tiktok_status':1 if posted else 0}}
            client=FakeClient(hook=provider); transport=Transport()
            def factory(child):
                app=create_app(child,transport=transport,real_client=client,real_guard=lambda e:{'allowed':True})
                app.extensions['v5_data_gateway']=FakeGateway()
                register_forms(app,child,app.extensions['v5_repository'])
                return app
            store=DemoStore(str(root/'demo.sqlite'));self.addCleanup(store.close)
            router=DemoRouter(SCOPE,store,RecordingGateway(),now=lambda:datetime.now(timezone.utc),continuation_enabled=True)
            main=Flask('real-integration');main.extensions['v5_demo_router']=router
            bridge=install(main,config,runtime_factory=factory,start=False);self.addCleanup(bridge.db.close)
            executor=bridge.runtime.extensions['v5_real_executor'];repo=bridge.runtime.extensions['v5_repository']
            router.start('synthetic-real-integration')
            def send(identifier,text,**extra):
                ev=event(message_id=str(identifier),text=text,created_at=datetime.now(timezone.utc).isoformat(),**extra)
                response=router.handle(ev)
                self.assertEqual(response[0]['status'],'demo_real_active')
                return ev
            send(101,'Quero fazer parte',demo_reply_to=store.current(SCOPE.slot)['parent_id'])
            send(102,'Indicação')
            send(103,'@alice')
            for _ in range(4): executor.tick()
            state=repo.load_session('chatwoot:1:7')
            self.assertEqual(state['cycle']['facts']['tiktok_declarado'],'@alice')
            self.assertEqual(state['cycle']['phase'],'consent_real')
            self.assertEqual(posted,[]) # global AUTO_INVITE=True cannot bypass consent
            consent=send(104,'Pode mandar')
            for _ in range(4): executor.tick()
            self.assertEqual(posted,['alice'])
            state=repo.load_session('chatwoot:1:7')
            self.assertEqual(state['cycle']['phase'],'form')
            url=state['cycle']['form_url'];self.assertIn('/cadastro/ensaio#s=',url)
            token=url.split('#s=')[1]
            self.assertTrue(bridge.owns_form(token))
            with main.test_client() as http:
                for path in ('/cadastro/'+token,'/cadastro/api/contexto','/cadastro/compat/contexto'):
                    response=http.get(path,headers={'Authorization':'Bearer '+token})
                    self.assertEqual(response.status_code,303 if path=='/cadastro/'+token else 200,(path,response.get_data(as_text=True)))
                self.assertEqual(http.get('/cadastro/api/contexto',headers={'Authorization':'Bearer '+'z'*43}).status_code,404)
            router.handle(consent)
            send(105,'E agora?')
            for _ in range(3):executor.tick()
            self.assertEqual(posted,['alice'])
            with bridge.runtime.extensions['v5_forms_store'].db() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM v5_forms').fetchone()[0],1)
            # Disabling after enrollment must not silently resume simulated mode.
            with self.assertRaisesRegex(ValueError,'disabled_with_active_history'):
                install(Flask('rollback'),{**config,'demo_real_enabled':False})

if __name__=='__main__': unittest.main()
