"""Binding-permission rejection must be exact, terminal, and non-speculative."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import socket
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from playwright_client import PlaywrightClient
from tests.test_playwright_client import SETTINGS,Script,invitation_prefix
from test_regressao41 import eligible,say,settle
import receipt_grounding

CODE='16004004'
REASON='creator_binding_not_permitted'

def rejected(creator='teste',code=CODE,accepted=False):
    return 422,{'ok':False,'creator':creator,'status':'invite_failed',
                'create':{'ok':accepted,'data':{'code':code,'message':'the creator has no permission to bind'}}}

def execute(response):
    script=Script(invitation_prefix()+[response])
    result=PlaywrightClient(SETTINGS,script).execute('invite','teste',confirmed=True,
                  commission='10',before_write=lambda:True)
    return result,script

class BindingPermissionTests(unittest.TestCase):
    def setUp(self):
        for guard in [patch.object(socket.socket,'connect',side_effect=AssertionError('network forbidden')),
                      patch.object(socket,'create_connection',side_effect=AssertionError('network forbidden'))]:
            guard.start();self.addCleanup(guard.stop)
    def test_exact_rejected_code_is_terminal_reason(self):
        result,script=execute(rejected())
        self.assertEqual((result['status'],result['reason']),('failed',REASON))
        self.assertFalse(result['confirmed']);self.assertEqual(len(script.writes()),1)
    def test_wrong_creator_never_classifies_current_profile(self):
        result,_=execute(rejected(creator='other'))
        self.assertNotEqual(result['reason'],REASON)
    def test_wrong_code_never_classifies_permission(self):
        for code in ['16004005','16004004x',None]:
            with self.subTest(code=code):self.assertNotEqual(execute(rejected(code=code))[0]['reason'],REASON)
    def test_create_accepted_takes_precedence(self):
        result,_=execute(rejected(accepted=True))
        self.assertEqual(result['status'],'pending_verification');self.assertNotEqual(result['reason'],REASON)
    def test_wrong_http_or_no_rejection_does_not_classify(self):
        for response in [(200,rejected()[1]),(422,{**rejected()[1],'create':{}})]:
            with self.subTest(response=response):self.assertNotEqual(execute(response)[0]['reason'],REASON)
    def failed_journey(self):
        asked=say('Pode mandar',eligible('@synthetic')['state'])
        effect=next(e for e in asked['effects'] if e['operation']=='invite')
        return settle(asked['state'],effect,'failed',confirmed=False,reason=REASON,
                      evidence={'post_attempted':True,'create_accepted':False,'upstream_code':CODE,'http_status':422})
    def test_permission_failure_blocks_without_retry(self):
        result=self.failed_journey();cycle=result['state']['cycle']
        self.assertEqual(cycle['phase'],'blocked');self.assertEqual(cycle['block_reason'],REASON)
        self.assertEqual(cycle['team_alert']['reason'],REASON)
        self.assertFalse(result['effects']);self.assertNotIn('invite_retry',cycle)
        self.assertNotIn('invite_failed_retry',cycle)
        self.assertIn('não tem permissão',result['reply']);self.assertNotIn('seguidores',result['reply'])
    def test_repeat_result_does_not_send_or_retry(self):
        result=self.failed_journey();state=result['state']
        effect=next(e for e in state['effects'].values() if e['operation']=='invite')
        repeated=settle(state,effect,'failed',confirmed=False,reason=REASON,evidence={'upstream_code':CODE})
        self.assertFalse(repeated['effects']);self.assertFalse(repeated['reply'])
    def test_unbound_code_alone_does_not_claim_permission_block(self):
        state={'cycle':{'facts':{},'real_operations':{'invite':{'status':'failed','reason':'invitation_rejected',
               'evidence':{'create_accepted':False,'upstream_code':CODE}}}}}
        reply=receipt_grounding._relationship_status(state,None)
        self.assertNotIn('não tem permissão',reply)
    def test_known_reason_has_no_fabricated_cause_or_acceptance(self):
        result=self.failed_journey()
        reply=receipt_grounding._relationship_status(result['state'],None)
        self.assertIn('não tem permissão',reply)
        for forbidden in ['seguidores','idade','vendas','Para aceitar','Parcerias']:
            self.assertNotIn(forbidden,reply)

if __name__=='__main__':unittest.main()
