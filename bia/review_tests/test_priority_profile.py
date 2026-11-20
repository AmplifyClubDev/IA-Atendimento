"""Priority gate contracts: no external I/O, real inbound orchestration."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from lead_validation import profile_handle, release_priority_choice
from server import create_app
from repository import Repository
from test_real_executor import EVENT, GATE, CONV, FakeClient, FakeGateway
from test_worker_form_context import Transport


class PriorityFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.order=[]; self.entries=[]; self.posts=[]; self.http_fail=False
        self.transport=Transport(); self.repo=Repository(Path(self.tmp.name)/'state.db')
        settings={'tiktok_mode':'real','real_worker_enabled':True,'gate':dict(GATE),
            'state_dir':self.tmp.name,'webhook_token':'w'*40,'conversation_enabled':True,
            'ai_enabled':True,'contact_sync_enabled':True,'instance_id':'offline-test',
            'readiness_issues':[],'qualification_enabled':True,
            'slack_bot_token':'synthetic','slack_gmv_channel_id':'C1234567890',
            'chatwoot_base_url':'https://chat.example'}
        self.app=create_app(settings,self.repo,self.transport,
            planner=lambda *_:{'provider_status':'unknown','claims':[]},
            real_client=FakeClient(),real_guard=lambda e:{'allowed':True})
        owner=self
        class Recorder(FakeGateway):
            def register_contact(self, entry):
                owner.entries.append(copy.deepcopy(entry)); owner.order.append('db')
                return {**super().register_contact(entry),'cadastro_situacao':'pendente'}
        self.app.extensions['v5_data_gateway']=Recorder()
        self.mock=patch('lead_alerts._http',side_effect=self.http); self.mock.start(); self.addCleanup(self.mock.stop)
        self.number=900

    def http(self, **kw):
        if kw['method']=='GET':
            return {'ok':True,'channel':{'id':'C1234567890','name':'alertas-bia','is_member':True,'is_archived':False}}
        self.posts.append(kw); self.order.append('slack')
        if self.http_fail: raise TimeoutError('synthetic')
        return {'ok':True,'channel':'C1234567890','ts':'123.456'}

    def send(self,text,number=None):
        self.number+=1
        event={**EVENT,'message_id':str(number or self.number),'text':text,
            'created_at':datetime.now(timezone.utc).isoformat()}
        event['source_ref']='chatwoot:1:'+event['message_id']
        with self.app.app_context(): result,code=self.app.extensions['v5_process_inbound'](event)
        self.assertEqual(code,200,result)
        return self.repo.load_session(CONV)

    def qualify(self):
        for text in ('Quero me agenciar','Não','Sim','50 mil'): state=self.send(text)
        self.assertEqual(state['cycle']['bia_validation']['stage'],'priority_profile')
        self.assertFalse(self.posts)
        self.assertEqual(self.entries[-1]['declaracoes_chat'][0]['valor'],5_000_000)
        return state

    def test_exact_profile_urls_and_rejections(self):
        for text in ('@alice','https://www.tiktok.com/@Alice?lang=pt','tiktok.com/@alice/'):
            self.assertEqual(profile_handle(text),'@alice')
        for text in ('https://evil.test/@alice','https://tiktok.com.evil.test/@alice','@alice @bob','https://vm.tiktok.com/abc','@alice.','Especialista'):
            self.assertIsNone(profile_handle(text))

    def test_full_sequence_persists_before_single_slack_and_handoff(self):
        self.qualify()
        self.send('Especialista'); self.assertFalse(self.posts)
        self.order=[]
        state=self.send('https://www.tiktok.com/@alice')
        self.assertEqual(state['cycle']['bia_validation']['stage'],'choice')
        self.assertEqual(self.order[:2],['db','db'])
        self.assertLess(self.order.index('db'),self.order.index('slack'))
        profile=self.entries[-1]['qualificacao']['perfil_tiktok']
        self.assertEqual(profile['handle'],'@alice'); self.assertFalse(profile['verificado'])
        self.assertEqual(profile['mensagem_id'],str(self.number))
        self.assertIn('Especialista',self.transport.calls[-1][2])
        self.assertEqual(len(self.posts),1)
        state=self.send('Especialista')
        self.assertEqual(state['cycle']['bia_validation']['stage'],'specialist')
        # Auditoria 20/11: o pedido de especialista avisa o time (1 alerta a mais, sem repetir).
        self.assertEqual(len(self.posts),2)
        self.assertIn('Especialista solicitado',self.posts[-1]['payload']['text'])
        self.send('Oi'); self.assertEqual(len(self.posts),2)

    def test_unknown_slack_receipt_preserves_pending_after_reload(self):
        self.qualify(); self.http_fail=True
        state=self.send('@alice')
        self.assertEqual(state['cycle']['bia_validation']['stage'],'priority_alert')
        self.assertFalse(self.transport.calls[-1][2])
        self.http_fail=False; state=self.send('Oi')
        self.assertEqual(state['cycle']['bia_validation']['stage'],'priority_alert')
        self.assertEqual(len(self.posts),1)
        self.assertIsNone(release_priority_choice(state))

    def test_followers_saved_while_waiting_and_displayed_with_source(self):
        self.qualify(); self.send('Tenho 25 mil seguidores')
        state=self.send('@alice')
        self.assertEqual(state['cycle']['facts']['seguidores_declarados'],25000)
        self.assertIn('25.000 — declarado pelo criador',self.posts[0]['payload']['text'])

    def test_machine_choice_does_not_duplicate_alert(self):
        self.qualify(); self.send('@alice'); state=self.send('Seguir com a Bia')
        self.assertEqual(state['cycle']['bia_validation']['stage'],'complete')
        self.assertEqual(len(self.posts),1)

    def test_known_profile_skips_question_and_duplicate_delivery_does_not_resend(self):
        for text in ('Quero me agenciar','Não','Sim','@alice','50 mil'): state=self.send(text)
        self.assertEqual(state['cycle']['bia_validation']['stage'],'choice')
        self.assertEqual(len(self.posts),1)
        self.send('50 mil',number=self.number)
        self.assertEqual(len(self.posts),1)
