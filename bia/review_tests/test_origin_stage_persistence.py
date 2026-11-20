"""Readback-only snapshots and source-preserving origin recording. Offline."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'apoio'))
from copy import deepcopy
from unittest.mock import patch
import unittest
import conversation
import engine
import test_etiquetas48
from test_real_journey import NOW, POLICY, GATE
from test_real_executor import EVENT
from transport import ChatwootProgress
from gateway import Gateway, SubmissionUnknown


class SnapshotPersistence(unittest.TestCase):
    parado = test_etiquetas48.Etiquetas48Tests.parado
    contact_proof = test_etiquetas48.Etiquetas48Tests.contact_proof
    def setUp(self):
        test_etiquetas48.Etiquetas48Tests.setUp(self)
        self.records = []
        self.progress.confirmed_sink = lambda event, state, labels: self.records.append(deepcopy(labels)) or {'status':'recorded'}

    def test_only_readback_confirmed_owned_labels_are_persisted(self):
        result = self.parado()
        self.assertEqual(result['persistence'], 'recorded')
        self.assertEqual(self.records, [['convite', 'encerrado']])
        self.assertNotIn('outra-equipe', self.records[0])

    def test_failed_write_readback_never_persists_desired(self):
        self.adapter.write_progress = lambda *args: {'status':'outcome_unknown'}
        self.assertEqual(self.parado()['status'], 'outcome_unknown')
        self.assertEqual(self.records, [])

    def test_sink_failure_does_not_interrupt_chatwoot_or_send_messages(self):
        def fail(*args): raise TimeoutError()
        self.progress.confirmed_sink = fail
        result = self.parado()
        self.assertEqual(result['status'], 'confirmed')
        self.assertEqual(result['persistence'], 'unconfirmed')

    def test_unchanged_labels_still_require_fresh_readback(self):
        self.parado()
        self.state = self.repo.load_session('x')
        self.adapter.labels = ['cadastro']
        result = self.parado()
        self.assertEqual(result['persistence'], 'unconfirmed')
        self.assertEqual(len(self.records), 1)

    def test_stale_state_or_missing_sql_proof_not_sent_to_sink(self):
        self.state['revision'] += 1
        result = self.parado()
        self.assertEqual(result['status'], 'ignored')
        self.assertEqual(self.records, [])


class OriginRecording(unittest.TestCase):
    def run_event(self, text, source=True, future=False):
        event={**EVENT,'text':text,'created_at':NOW.isoformat(),'source_ref':'chatwoot:1:777'}
        if not source: event.pop('source_ref')
        if future: event['created_at']='2099-01-01T00:00:00Z'
        return conversation.handle_event(engine._state({}),event,GATE,now=NOW,real_mode=True,operation_policy=POLICY)

    def test_prefilled_ad_greeting_preserves_timestamp_and_origin_kind(self):
        result=self.run_event('Quero saber mais sobre o agenciamento')
        self.assertEqual(result['state']['observations']['origin'],
            {'at':engine._stamp(NOW),'reference':'chatwoot:1:777','source':'ad_prefilled_message','value':'anuncio'})

    def test_missing_or_future_provider_source_cannot_create_origin_observation(self):
        for opts in ({'source':False},{'future':True}):
            result=self.run_event('Quero saber mais sobre o agenciamento',**opts)
            self.assertNotIn('origin',result['state']['observations'])

    def test_ordinary_hello_does_not_infer_an_ad(self):
        result=self.run_event('Oi')
        self.assertNotIn('origin',result['state']['observations'])



class GatewayReceiptTests(unittest.TestCase):
    def test_gateway_checks_complete_receipt(self):
        gateway=Gateway({})
        entry={'atendimento_id':'a','revision':2,'labels':['convite'],'signature':'s'}
        gateway._rpc=lambda *a: {'status':'recorded',**entry}
        self.assertEqual(gateway.register_chatwoot_labels(entry)['status'],'recorded')
        gateway._rpc=lambda *a: {'status':'recorded',**entry,'labels':['cadastro']}
        with self.assertRaises(SubmissionUnknown): gateway.register_chatwoot_labels(entry)

class ContactPayloadTests(unittest.TestCase):
    def test_origin_channel_and_prefill_observation_reach_gateway_without_changing_phase(self):
        import tempfile
        from datetime import datetime, timezone
        from server import create_app
        from repository import Repository
        from test_worker_form_context import Transport
        from test_real_executor import FakeClient, FakeGateway, CREATOR_ID
        with tempfile.TemporaryDirectory() as d:
            entries=[]
            class Recorder(FakeGateway):
                def register_contact(self, entry):
                    entries.append(deepcopy(entry))
                    return {**super().register_contact(entry),'cadastro_situacao':'pendente'}
            config={'tiktok_mode':'real','real_worker_enabled':True,'gate':dict(GATE),
                'state_dir':d,'webhook_token':'w'*40,'conversation_enabled':True,'ai_enabled':True,
                'contact_sync_enabled':True,'instance_id':'offline-test','readiness_issues':[],
                'tiktok_policy_approved':True,'tiktok_invite_commission':'10',
                'tiktok_policy_version':'offline','tiktok_commission_unit':'percent',
                'tiktok_duration_fixed_months':'2','tiktok_duration_label':'2 meses'}
            repo=Repository(Path(d)/'test.sqlite')
            app=create_app(config,repo,Transport(),planner=lambda *_:{'provider_status':'unknown','claims':[]},
                real_client=FakeClient(),real_guard=lambda e:{'allowed':True})
            app.extensions['v5_data_gateway']=Recorder()
            def send(n,text):
                event={**EVENT,'message_id':str(n),'text':text,'created_at':datetime.now(timezone.utc).isoformat(),
                       'source_ref':f'chatwoot:1:{n}'}
                with app.app_context(): result,code=app.extensions['v5_process_inbound'](event)
                self.assertEqual(code,200,result)
            send(778,'Quero saber mais sobre o agenciamento')
            self.assertEqual(entries[-1]['origem']['source'],'ad_prefilled_message')
            state=repo.load_session('chatwoot:1:26097')
            state['cycle']['facts']['origem_canal_declarado']='instagram'
            repo.save_session('chatwoot:1:26097',state)
            send(779,'Oi')
            self.assertEqual(entries[-1]['qualificacao']['origem_canal_declarado'],'instagram')
            self.assertEqual(entries[-1]['etapa'],'intro')

if __name__ == '__main__':
    unittest.main()
