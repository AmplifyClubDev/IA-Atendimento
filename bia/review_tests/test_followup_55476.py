from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest import TestCase
from retomada import Retomada, STEPS, LINKED_STEPS, MIN_GAP, message, step_key, FOLLOWUP_CLOSE

class Followup55476(TestCase):
    def setUp(self):
        self.now=datetime(2026,11,13,15,tzinfo=timezone.utc)
        self.state={'cycle':{'id':'cycle','mode':'real','phase':'await_acceptance','facts':{'tiktok_declarado':'@synthetic'},'last_inbound_at':self.now.isoformat()}}
        r={'status':'pending','confirmed':True,'creator':'@synthetic','cycle_id':'cycle','job_id':'proof','evidence':{'read':True},'observed_at':self.now.isoformat()}
        self.state['cycle']['real_operations']={'relationship':r}
        self.state['effects']={'proof':{'type':'tiktok_operation','operation':'relationship','status':'done','cycle_id':'cycle','creator':'@synthetic'}}
        self.source={'event_key':'chatwoot:1:1'}
        self.rows={}
        self.worker=Retomada.__new__(Retomada)
        self.worker.repository=SimpleNamespace(get_operation=lambda k:self.rows.get(k))
    def test_two_ten_minute_steps(self):
        self.assertEqual(STEPS,((1,timedelta(minutes=10)),(2,timedelta(minutes=20))))
        self.assertEqual(LINKED_STEPS,STEPS)
        self.assertEqual(MIN_GAP,timedelta(minutes=10))
    def test_due_boundaries_and_durable_limit(self):
        self.assertIsNone(self.worker._due(self.state,self.source,self.now+timedelta(minutes=9,seconds=59)))
        self.assertEqual(self.worker._due(self.state,self.source,self.now+timedelta(minutes=10)),1)
        self.rows[step_key('cycle','chatwoot:1:1',1)]={'status':'completed'}
        self.state['cycle']['retomada']={'step':1,'source_key':'chatwoot:1:1','stage':['await_acceptance',None],
                                         'at':(self.now+timedelta(minutes=10)).isoformat()}
        self.assertIsNone(self.worker._due(self.state,self.source,self.now+timedelta(minutes=19)))
        self.assertEqual(self.worker._due(self.state,self.source,self.now+timedelta(minutes=20)),2)
        self.rows[step_key('cycle','chatwoot:1:1',2)]={'status':'completed'}
        self.assertIsNone(self.worker._due(self.state,self.source,self.now+timedelta(hours=23)))
    def test_no_repeated_greeting_closure_notice_only_second(self):
        first=message(self.state,1,{},now=self.now)[0]; second=message(self.state,2,{},now=self.now)[0]
        self.assertFalse(first.startswith('Oi'));self.assertFalse(second.startswith('Oi'))
        self.assertIn('encerrar atendimento',first);self.assertEqual(second,FOLLOWUP_CLOSE)
        self.assertNotEqual(first,second)
        self.assertIsNone(message(self.state,3,{}))
    def test_unknown_invitation_has_no_proactive_message(self):
        self.state['cycle']['phase']='blocked'
        self.assertIsNone(message(self.state,1,{},now=self.now))
    def test_qualification_follows_current_field(self):
        for stage,needle in [('agency','agenciado'),('shop','ativado'),('gmv','GMV')]:
            self.state['cycle'].update(phase='intro',bia_validation={'stage':stage})
            self.assertIn(needle,message(self.state,1,{},now=self.now)[0])
            self.assertNotIn('seu @',message(self.state,1,{},now=self.now)[0])
    def test_second_accepted_closes_and_preserves_receipts_but_unknown_does_not(self):
        from copy import deepcopy
        from threading import RLock
        from unittest.mock import patch
        for status in ['accepted','outcome_unknown']:
            state=deepcopy(self.state)
            state.update(processed_inbound=['chatwoot:1:1'])
            state['effects']['old-invite']={'result_receipt':{'status':'sent','confirmed':True}}
            state['cycle']['real_operations']['relationship']['observed_at']=(self.now+timedelta(minutes=15)).isoformat()
            state['cycle'].update(mode='real',status='open',opened_at=self.now.isoformat(),expires_at=(self.now+timedelta(days=1)).isoformat())
            state['cycle']['retomada']={'step':1,'source_key':'chatwoot:1:1','stage':['await_acceptance',None],
                                         'at':(self.now+timedelta(minutes=10)).isoformat()}
            source={**self.source,'cycle_id':'cycle','event':{'created_at':self.now.isoformat()}}
            saved=[];stopped=[]
            repo=SimpleNamespace(followup_source=lambda c:source,load_session=lambda c:deepcopy(state),
                get_operation=lambda k:None,conversation_delivery_context=lambda *a:{'latest_attempt_status':'accepted','last_accepted_reply':{'at':self.now.isoformat()}},
                followup_clear=lambda *a:True,reserve_followup=lambda *a:True,reserve_operation=lambda *a:True,
                complete_operation=lambda *a:None,finish_outbox=lambda *a:None,save_session=lambda c,s:saved.append(deepcopy(s)))
            worker=Retomada(repo,{},SimpleNamespace(send_reply=lambda *a,**k:{'status':status,'message_id':'2'}),lambda c:RLock(),lambda e:{'allowed':True},now=lambda:self.now+timedelta(minutes=20),policy=lambda:{},on_stopped=lambda *a:stopped.append(a))
            worker._source_unchanged=lambda *a:True
            with patch('retomada.production_blocked',return_value=False),patch('retomada.allow_inbound',return_value=True),patch('retomada.inbound_key',return_value='chatwoot:1:1'):
                result=worker._conversation('conv',self.now+timedelta(minutes=20))
            self.assertEqual(result['status'],status)
            if status=='accepted':
                self.assertEqual(saved[-1]['cycle']['status'],'closed')
                self.assertEqual(saved[-1]['effects'],state['effects'])
                self.assertEqual(len(stopped),1)
            else:
                self.assertFalse(saved);self.assertFalse(stopped)
