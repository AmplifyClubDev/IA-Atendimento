from datetime import timedelta
import unittest

import real_journey as j
from real_operations import build_jobs
from test_invite_receipt_guard58987 import state, proof, NOW

class PendingReads(unittest.TestCase):
    def setUp(self):
        self.at = j.engine._clock(NOW)
        self.state = state()
        proof(self.state, 'sent', NOW, 'invite')
        self.state['cycle']['invite_consent'] = {'cycle_id': self.state['cycle']['id'], 'creator': '@synthetic', 'policy_hash': 'synthetic'}
        self.state['cycle']['facts']['consentimento_convite'] = True

    def click(self, *, s=None, delta=0):
        return j.handle_real(s if s is not None else self.state,'Verificar novamente',
                             now=self.at+timedelta(seconds=delta),same_engine_enabled=True)

    def result(self, r, status, *, delta=0, reason=None):
        at=self.at+timedelta(seconds=delta)
        e=r['effects'][0]
        response={'operation':'relationship','creator':'synthetic','status':status,'confirmed':True,
                  'observed_at':j.engine._stamp(at),'evidence':{'complete':True,'fresh':True}}
        if reason:
            response['reason']=reason
        return j.resolve_tiktok_result(r['state'],e['id'],response,now=at)

    def test_read_only_does_not_add_acceptance_or_change_consent(self):
        r=self.click()
        effect=r['effects'][0]
        self.assertEqual(effect['operation'],'relationship')
        self.assertEqual(effect['payload']['source'],'pending_relationship_manual')
        c=r['state']['cycle']
        self.assertNotIn('aceite_declarado',c['facts'])
        self.assertEqual(c['invite_consent'],self.state['cycle']['invite_consent'])
        self.assertEqual(c['phase'],'await_acceptance')
        jobs=build_jobs({'account_id':1,'conversation_id':45,'message_id':123},r['state'],[effect])
        self.assertEqual(len(jobs),1)
        self.assertEqual(jobs[0]['operation'],'relationship')

    def test_absent_never_reinvites_or_registers(self):
        r=self.result(self.click(),'not_found',delta=1)
        cycle=r['state']['cycle']
        self.assertFalse(r['effects'])
        self.assertEqual(cycle['phase'],'await_acceptance')
        self.assertNotIn('invite_list_proof',cycle)
        self.assertEqual(cycle['invite_tracking']['stopped'],'manual_absence')
        self.assertNotIn(j.PUBLIC_FORM_URL,r['reply'])
        self.assertIn('Não reenviei',r['reply'])

    def test_pending_then_confirmed_link_accessible(self):
        pending=self.result(self.click(),'pending',delta=1)
        self.assertFalse(pending['effects'])
        self.assertIn('Verificar novamente',pending['buttons'])
        result=self.result(self.click(s=pending['state'],delta=40),'linked',delta=41)
        self.assertEqual(result['state']['cycle']['phase'],'form')
        self.assertIn(j.PUBLIC_FORM_URL,result['reply'])
        self.assertFalse(result['effects'])
        again=self.click(s=result['state'],delta=50)
        self.assertEqual(again['state']['cycle']['phase'],'form')
        self.assertIn(j.PUBLIC_FORM_URL,again['reply'])
        self.assertFalse(again['effects'])

    def test_temp_failure_resumes_using_existing_read_scan_without_chat_spam(self):
        self.state['cycle'].update(phase='form',form_url=j.PUBLIC_FORM_URL)
        initial=self.result(self.click(),'verification_pending',delta=1,reason='session_not_ready')
        self.assertEqual(initial['state']['cycle']['phase'],'form')
        self.assertIn('continua disponível',initial['reply'])
        self.assertIsNone(j.agency_read_due(initial['state'],self.at+timedelta(seconds=20)))
        resumed=j.agency_read_effect(initial['state'],self.at+timedelta(seconds=62))
        self.assertEqual(resumed['payload']['source'],'pending_relationship_recovery')
        auto=self.result({'effects':[resumed],'state':initial['state']},'verification_pending',delta=64,reason='session_not_ready')
        self.assertEqual(auto['reply'],'')
        self.assertEqual(auto['state']['cycle']['phase'],'form')
        self.assertFalse(auto['effects'])
        self.assertEqual(auto['state']['cycle']['pending_relationship_recheck']['attempts'],1)

    def test_pending_only_external_receipt_can_be_rechecked_after_absence(self):
        self.state['cycle']['real_operations'].pop('invite')
        self.state['effects'].pop('inviteproof')
        proof(self.state, 'pending', NOW)
        absent=self.result(self.click(),'not_found',delta=1)
        again=self.click(s=absent['state'],delta=40)
        self.assertEqual([e['operation'] for e in again['effects']],['relationship'])
        stale=absent['state']
        stale['cycle']['facts']['tiktok_declarado']='@notthesame'
        forbidden=self.click(s=stale,delta=40)
        self.assertFalse(forbidden['effects'])

    def test_missing_link_evidence_is_a_temporary_failure_and_never_a_promise(self):
        initial=self.click()
        e=initial['effects'][0]
        r=j.resolve_tiktok_result(initial['state'],e['id'],
            {'operation':'relationship','creator':'synthetic','status':'linked','confirmed':True,
             'observed_at':NOW,'evidence':{}},now=self.at+timedelta(seconds=1))
        self.assertEqual(r['state']['cycle']['phase'],'await_acceptance')
        self.assertNotIn(j.PUBLIC_FORM_URL,r['reply'])
        self.assertIn('Não consegui confirmar',r['reply'])
        self.assertIn('Verificar novamente',r['buttons'])

    def test_automatic_retry_is_bounded_and_silent(self):
        r=self.result(self.click(),'verification_pending',delta=1,reason='session_not_ready')
        for attempt,seconds in enumerate((62,124,186),1):
            job=j.agency_read_effect(r['state'],self.at+timedelta(seconds=seconds))
            self.assertEqual(job['payload']['source'],'pending_relationship_recovery')
            r=self.result({'effects':[job],'state':r['state']},'verification_pending',delta=seconds+1,
                          reason='session_not_ready')
            self.assertEqual(r['state']['cycle']['pending_relationship_recheck']['attempts'],attempt)
            self.assertEqual(r['reply'],'')
            self.assertFalse(r['effects'])
        self.assertIsNone(j.agency_read_due(r['state'],self.at+timedelta(seconds=248)))

    def test_stale_and_wrong_cycle_dont_queue(self):
        self.state['cycle']['real_operations']['invite']['cycle_id']='other'
        r=self.click()
        self.assertFalse(r['effects'])
        self.assertNotIn('aceite_declarado',r['state']['cycle']['facts'])

    def test_second_click_does_not_duplicate_read(self):
        r=self.click()
        r=self.click(s=r['state'],delta=5)
        self.assertFalse(r['effects'])
        self.assertEqual(sum(e.get('operation')=='relationship' for e in r['state']['effects'].values()),1)

if __name__ == '__main__':
    unittest.main()
