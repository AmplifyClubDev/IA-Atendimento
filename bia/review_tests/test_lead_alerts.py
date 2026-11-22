import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import lead_alerts
from contracts import inbound_key
from repository import Repository

CHANNEL = 'C1234567890'


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.repo = Repository(Path(self.temp.name)/'state.db')
        self.event = {'provider':'chatwoot','account_id':'1','conversation_id':'7','message_id':'101',
                      'inbox_id':'3','contact_id':'9','sender_phone':'+5511999999999'}
        self.repo.reserve_event(inbound_key(self.event),'chatwoot:1:7','digest')
        self.settings = {'slack_bot_token':'synthetic-token','slack_gmv_channel_id':CHANNEL,
                         'gate':{'account_id':'1','inbox_id':'3'},'chatwoot_base_url':'https://chat.example'}
        self.state = {'cycle': {'id':'cycle-a','facts':{'nome_declarado':'Ana','tiktok_declarado':'@ana',
                 'gmv_30d_declarado_centavos':5_000_000,'gmv_30d_moeda':'BRL'},
                 'bia_validation':{'high_gmv':True,'alert_requested':True,'priority_flow_version':2}}}
        self.calls=[]
        self.info = {'ok':True,'channel':{'id':CHANNEL,'name':'alerta-bia','is_member':True,'is_archived':False}}
        self.reply = {'ok':True,'channel':CHANNEL,'ts':'123.456'}

    def http(self,**kw):
        self.calls.append(kw)
        if kw['method']=='GET': return copy.deepcopy(self.info)
        if isinstance(self.reply,Exception): raise self.reply
        return self.reply

    def run_alert(self):
        return lead_alerts.dispatch(self.settings,self.repo,self.event,self.state,http=self.http)

    def posts(self): return [x for x in self.calls if x['method']=='POST']

    def test_threshold_exact_and_replay_no_second_post(self):
        result=self.run_alert(); self.assertEqual(result['events']['threshold']['status'],'accepted')
        self.assertEqual(self.run_alert(),result); self.assertEqual(len(self.posts()),1)
        text=self.posts()[0]['payload']['text']
        self.assertIn('R$ 50.000,00',text); self.assertIn('últimos 30 dias',text)
        self.assertIn('/app/accounts/1/conversations/7',text)
        self.assertIn(self.event['sender_phone'],text)
        self.assertIn('<@U0AF0DWMD1U>', text); self.assertIn('<@U0CA10SDPDJ>', text)

    def test_below_threshold_and_invalid_amounts_never_send(self):
        for amount in (4_999_999,None,True,'5000000',float('nan'),-100,100_000_000_001):
            self.state['cycle']['facts']['gmv_30d_declarado_centavos']=amount
            self.assertEqual(self.run_alert()['status'],'not_requested')
        self.assertFalse(self.calls)

    def test_wrong_currency_never_send(self):
        self.state['cycle']['facts']['gmv_30d_moeda']='USD'
        self.assertEqual(self.run_alert()['status'],'not_requested'); self.assertFalse(self.calls)

    def test_channel_identity_name_archive_membership_must_match(self):
        for change in ({'name':'general'},{'id':'C9876543210'},{'is_archived':True},{'is_member':False},{'is_im':True}):
            original=copy.deepcopy(self.info)
            self.info['channel'].update(change)
            self.assertEqual(self.run_alert()['events']['threshold']['reason'],'slack_channel_unverified')
            self.info=original
        self.assertFalse(self.posts())
        self.info['channel']['name']='alertas-bia'
        self.assertEqual(self.run_alert()['events']['threshold']['status'],'accepted')

    def test_channel_read_timeout_can_retry_without_send_reservation(self):
        def read_fail(**kw): raise TimeoutError('read')
        result=lead_alerts.dispatch(self.settings,self.repo,self.event,self.state,http=read_fail)
        self.assertEqual(result['events']['threshold']['status'],'blocked')
        self.assertEqual(self.run_alert()['events']['threshold']['status'],'accepted')

    def test_send_timeout_never_retries(self):
        self.reply=TimeoutError('secret should not leak')
        self.assertEqual(self.run_alert()['events']['threshold']['status'],'outcome_unknown')
        self.reply={'ok':True,'channel':CHANNEL,'ts':'123.456'}
        self.assertEqual(self.run_alert()['events']['threshold']['status'],'outcome_unknown')
        self.assertEqual(len(self.posts()),1)

    def test_slack_rejection_or_malformed_receipt_not_accepted_or_retried(self):
        for reply, expected in (({'ok':False,'error':'not_in_channel'},'failed'),
                                 ({'ok':True,'channel':'C9876543210','ts':'123.4'},'outcome_unknown'),
                                 ({'ok':True,'channel':CHANNEL},'outcome_unknown')):
            self.state['cycle']['id']+= 'x'; self.reply=reply
            self.assertEqual(self.run_alert()['events']['threshold']['status'],expected)
            count=len(self.posts()); self.run_alert(); self.assertEqual(len(self.posts()),count)

    def test_machine_preference_does_not_send_another_alert(self):
        self.run_alert()
        rec=self.state['cycle']['bia_validation']
        rec['preference']='machine'
        self.run_alert(); self.run_alert()
        self.assertEqual(len(self.posts()),1)

    def test_specialist_request_sends_no_extra_alert(self):
        # 22/11: ficam só os alertas de GMV; o pedido de especialista não gera alerta.
        self.run_alert()
        rec=self.state['cycle']['bia_validation']
        rec['preference']='specialist'; rec['handoff_requested']=True
        result=self.run_alert()
        self.assertNotIn('specialist',result['events'])
        self.assertEqual(len(self.posts()),1)

    def test_specialist_without_handoff_flag_does_not_alert(self):
        self.run_alert()
        self.state['cycle']['bia_validation']['preference']='specialist'
        self.run_alert()
        self.assertEqual(len(self.posts()),1)

    def test_invalid_profile_and_legacy_never_send(self):
        self.state['cycle']['facts']['tiktok_declarado']='<!everyone>'
        self.assertEqual(self.run_alert()['status'],'pending_profile'); self.assertFalse(self.posts())
        self.state['cycle']['facts']['tiktok_declarado']='@ana'
        self.state['cycle']['bia_validation'].pop('priority_flow_version')
        self.assertEqual(self.run_alert()['status'],'legacy_cycle'); self.assertFalse(self.posts())

    def test_name_injection_and_phone_link_safety(self):
        self.state['cycle']['facts']['nome_declarado']='<!channel> +5511999999999'
        self.run_alert(); payload=self.posts()[0]['payload']
        self.assertNotIn('<!',payload['text'])
        self.assertIn('https://wa.me/5511999999999',payload['text'])
        self.assertIn('https://www.tiktok.com/@ana',payload['text'])
        self.assertFalse(payload['link_names']); self.assertFalse(payload['unfurl_links'])

    def test_scope_and_chatwoot_base_validation(self):
        for url in ('http://chat.example','https://user:pass@chat.example','https://chat.example?q=x','https://chat.example/path'):
            self.settings['chatwoot_base_url']=url
            self.assertEqual(self.run_alert()['reason'],'invalid_scope')
        self.settings['chatwoot_base_url']='https://chat.example'; self.event['account_id']='2'
        self.assertEqual(self.run_alert()['reason'],'invalid_scope'); self.assertFalse(self.calls)

    def test_no_settings_no_network(self):
        self.settings.pop('slack_bot_token')
        self.assertEqual(self.run_alert()['events']['threshold']['reason'],'slack_not_configured')
        self.assertFalse(self.calls)

    def test_opt_out_blocks_alert(self):
        self.state['opt_out']=True
        self.assertEqual(self.run_alert()['reason'],'opt_out'); self.assertFalse(self.calls)

    def test_crashed_reserved_post_remains_unknown(self):
        original=self.repo.complete_operation
        def crash(*args,**kwargs): raise RuntimeError('storage after post')
        self.repo.complete_operation=crash
        with self.assertRaises(RuntimeError): self.run_alert()
        self.repo.complete_operation=original
        self.assertEqual(self.run_alert()['events']['threshold']['status'],'outcome_unknown')
        self.assertEqual(len(self.posts()),1)

    def test_probe_is_read_only_and_redacts_identifiers(self):
        result=lead_alerts.probe(self.settings,http=self.http)
        self.assertEqual(result,{'configured':True,'verified':True,'reason':'verified','channel_name':'alerta-bia'})
        self.assertNotIn(CHANNEL,str(result)); self.assertNotIn('synthetic-token',str(result))
        self.assertFalse(self.posts())

    def test_racing_dispatch_has_one_post(self):
        import threading
        barrier=threading.Barrier(2)
        def racing_http(**kw):
            if kw['method']=='GET': barrier.wait(timeout=2)
            return self.http(**kw)
        errors=[]
        def run():
            try: lead_alerts.dispatch(self.settings,self.repo,self.event,copy.deepcopy(self.state),http=racing_http)
            except Exception as exc: errors.append(exc)
        threads=[threading.Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=4)
        self.assertFalse(errors); self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(len(self.posts()),1)


if __name__=='__main__': unittest.main()
