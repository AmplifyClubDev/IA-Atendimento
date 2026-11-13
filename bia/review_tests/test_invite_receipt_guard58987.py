import unittest
from unittest.mock import patch
import real_journey as j
import retomada
NOW='2026-11-13T18:30:00+00:00'
def state():
 s=j.handle_real({},'Oi',now=NOW)['state'];s['cycle'].update(phase='await_acceptance',facts={'tiktok_declarado':'@synthetic'},relationship_check_in_form=True)
 return s
def proof(s,status='pending',observed=NOW,operation='relationship'):
 c=s['cycle'];i=operation+'proof'
 c.setdefault('real_operations',{})[operation]={'status':status,'confirmed':True,'creator':'@synthetic','cycle_id':c['id'],'job_id':i,'evidence':{'read':True},'observed_at':observed}
 s['effects'][i]={'id':i,'type':'tiktok_operation','operation':operation,'status':'done','creator':'@synthetic','cycle_id':c['id']}
class ReceiptGuards(unittest.TestCase):
 def test_phase_or_record_is_not_proof(self):
  s=state();self.assertIsNone(retomada.message(s,1,{},now=NOW))
  s['cycle']['real_operations']={'invite':{'status':'sent','cycle_id':s['cycle']['id']}}
  self.assertIsNone(retomada.message(s,2,{},now=NOW))
 def test_fresh_pending_allowed_stale_wrong_cycle_denied(self):
  s=state();proof(s);self.assertIsNotNone(retomada.message(s,1,{},now=NOW))
  s['cycle']['real_operations']['relationship']['cycle_id']='old'
  self.assertIsNone(retomada.message(s,1,{},now=NOW))
  proof(s,observed='2026-11-13T17:00:00+00:00');self.assertIsNone(retomada.message(s,1,{},now=NOW))
 def test_later_absence_overrides_send(self):
  s=state();proof(s,'sent','2026-11-13T18:25:00+00:00','invite');proof(s,'not_found')
  self.assertFalse(j.invite_acceptance_proven(s,NOW))
 def test_not_found_without_new_write_never_awaits_acceptance(self):
  s=state();c=s['cycle'];e={'id':'read','creator':'@synthetic','payload':{}}
  c['prior_invite_check']={'effect_id':'read'}
  with patch.object(j,'_effect',return_value=None),patch.object(j,'precheck_proven',return_value=True):r=j._settle_acceptance_check(s,j.engine._clock(NOW),e,'not_found',{})
  self.assertEqual(r['state']['cycle']['phase'],'blocked');self.assertFalse(r['effects']);self.assertNotIn('aceite o convite',r['reply'])
 def test_current_linked_proof_preserves_form(self):
  s=state();proof(s,'linked');r=j._settle_acceptance_check(s,j.engine._clock(NOW),{'id':'old','payload':{}},'not_found')
  self.assertEqual(r['state']['cycle']['phase'],'form');self.assertIn(j.PUBLIC_FORM_URL,r['reply'])
 def test_cancellation_does_not_send_or_infer_platform_status(self):
  s=state();r=j.handle_real(s,'Cancelei o convite',now=NOW,same_engine_enabled=True)
  self.assertFalse(r['effects']);self.assertFalse(r['state']['cycle']['facts']['consentimento_convite'])
  self.assertIsNone(retomada.message(r['state'],1,{},now=NOW))
 def test_cancel_report_does_not_override_current_link(self):
  s=state();proof(s,'linked');r=j.handle_real(s,'Cancelei o convite',now=NOW,same_engine_enabled=True)
  self.assertEqual(r['state']['cycle']['phase'],'form');self.assertFalse(r['effects'])
 def test_older_absence_cannot_overwrite_new_link(self):
  s=state();proof(s,'linked');c=s['cycle'];s['effects']['oldread']={'id':'oldread','type':'tiktok_operation','operation':'relationship','creator':'@synthetic','cycle_id':c['id'],'status':'running','payload':{'source':'chat_acceptance'}}
  result={'operation':'relationship','creator':'@synthetic','status':'not_found','confirmed':True,'observed_at':'2026-11-13T18:29:00+00:00','evidence':{'read':True}}
  r=j.resolve_tiktok_result(s,'oldread',result,now=NOW)
  self.assertEqual(r['state']['cycle']['real_operations']['relationship']['status'],'linked')

 def test_registration_reminder_also_needs_bound_link(self):
  s=state();proof(s,'linked');self.assertIsNotNone(retomada.message(s,1,{},now=NOW))
  s['effects']={};self.assertIsNone(retomada.message(s,1,{},now=NOW))

 def test_missing_or_invalid_observation_cannot_prove(self):
  for stamp in [None,'','invalid']:
   s=state();proof(s,observed=stamp);self.assertFalse(j.invite_acceptance_proven(s,NOW))
 def test_ambiguous_cancellation_does_not_revoke_consent(self):
  for text in ['Não cancelei o convite','Eu cancelei o convite?','Se eu cancelei o convite','Como cancelei o convite?']:
   s=state();s['cycle']['facts']['consentimento_convite']=True
   r=j.handle_real(s,text,now=NOW,same_engine_enabled=True)
   self.assertNotIn('invite_cancellation_reported',r['state']['cycle'])
   self.assertTrue(r['state']['cycle']['facts']['consentimento_convite'])

 def test_latest_relation_supersedes_old_cross_operation_link(self):
  s=state();proof(s,'linked','2026-11-13T18:20:00+00:00','invite');proof(s,'not_found','2026-11-13T18:29:00+00:00')
  self.assertFalse(j._linked_in_cycle(s,j.engine._clock(NOW)))
  r=j._settle_acceptance_check(s,j.engine._clock(NOW),{'id':'read','payload':{}},'not_found')
  self.assertNotEqual(r['state']['cycle']['phase'],'form')
  proof(s,'linked',NOW,'invite');self.assertTrue(j._linked_in_cycle(s,j.engine._clock(NOW)))

 def test_cancel_resume_reads_offer_then_requires_new_consent(self):
  from test_real_journey import eligible_state, inbound, settle
  initial=eligible_state()
  cancelled=inbound('Cancelei o convite',initial['state'])
  self.assertEqual(cancelled['state']['cycle']['phase'],'blocked')
  resumed=inbound('Quero me agenciar',cancelled['state'])
  self.assertEqual([e['operation'] for e in resumed['effects']],['relationship'])
  self.assertTrue(resumed['state']['cycle']['invite_cancellation_reported'])
  offered=settle(resumed['state'],resumed['effects'][0],'not_found')
  self.assertEqual(offered['state']['cycle']['phase'],'consent_real')
  self.assertFalse(offered['effects'])
  self.assertFalse(offered['state']['cycle']['facts']['consentimento_convite'])
  self.assertTrue(offered['state']['cycle']['invite_cancellation_reported'])
  accepted=inbound('Sim',offered['state'])
  self.assertNotIn('invite_cancellation_reported',accepted['state']['cycle'])
  self.assertEqual([e['operation'] for e in accepted['effects']],['invite'])
 def test_resume_after_real_attempt_preserves_prior_write_fence(self):
  from test_real_journey import eligible_state, inbound, settle
  sent=inbound('Sim',eligible_state()['state'])
  sent=settle(sent['state'],sent['effects'][0],'sent')
  cancelled=inbound('Cancelei o convite',sent['state'])
  pending=next(e for e in cancelled['state']['effects'].values() if e.get('operation')=='relationship' and e['status']=='pending')
  cancelled=settle(cancelled['state'],pending,'not_found')
  resumed=inbound('Quero me agenciar',cancelled['state'])
  offered=settle(resumed['state'],resumed['effects'][0],'not_found')
  accepted=inbound('Sim',offered['state'])
  self.assertFalse(any(e['operation']=='invite' for e in accepted['effects']))
  self.assertEqual(sum(e.get('operation')=='invite' for e in accepted['state']['effects'].values()),1)
 def test_form_mode_cancel_resume_uses_authorized_read_source(self):
  from test_real_journey import inbound, settle
  r=None
  for text in ['Oi','Quero me agenciar','Indicação','@synthetic']:
   r=inbound(text,r['state'] if r else None,relationship_check_in_form=True)
  job=next(e for e in r['effects'] if e['operation']=='precheck')
  r=settle(r['state'],job,'eligible')
  r=inbound('Cancelei o convite',r['state'])
  r=inbound('Quero me agenciar',r['state'])
  self.assertEqual([e['operation'] for e in r['effects']],['relationship'])
  r=settle(r['state'],r['effects'][0],'not_found')
  self.assertEqual(r['state']['cycle']['phase'],'consent_real')
  self.assertFalse(r['effects'])
  self.assertTrue(r['state']['cycle']['invite_cancellation_reported'])
 def test_resume_worker_allows_bound_read_and_deduplicates_by_effect(self):
  from test_real_executor import ExecutorTests, FakeClient, EVENT, CONV, NOW as EXEC_NOW
  from real_operations import build_jobs
  from copy import deepcopy
  fixture=ExecutorTests();fixture.setUp()
  try:
   fixture.settings['relationship_check_in_form']=True
   fixture.repository.reserve_event('chatwoot:1:777',CONV,'fixture')
   for operation in ['relationship','precheck']:
    s,e=fixture.state(operation);e['payload']['source']='cancellation_resume'
    fixture.certify_projection(s)
    job=build_jobs(EVENT,s,[e])[0]
    self.assertTrue(fixture.executor(FakeClient())._valid(job,s,EXEC_NOW))
    other=deepcopy(e);other['id']+=':next';s['effects'][other['id']]=other
    self.assertNotEqual(job['job_key'],build_jobs(EVENT,s,[other])[0]['job_key'])
  finally: fixture.doCleanups()
