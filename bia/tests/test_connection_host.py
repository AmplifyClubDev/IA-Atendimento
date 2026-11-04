"""Exact approved-host migration; never use wildcard/fallback/redirect or I/O."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from transport import ChatwootTransport

ROOT = Path(__file__).resolve().parents[1]
OLD = 'chatwoot-web-production-c799.up.railway.app'
HOST = 'chatwoot.t2ffoz.easypanel.host'


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class ConnectionHostTests(unittest.TestCase):
    def setUp(self):
        self.stage=load('connectionfix_stage',ROOT/'ops/stage_preflight.py')
        self.env={'CHATWOOT_BASE_URL':'https://'+HOST,'CHATWOOT_API_TOKEN':'offline-test-token',
            'V5_ENABLED':'true','CHATWOOT_ACCOUNT_ID':'1','CHATWOOT_INBOX_ID':'3','V5_TEST_PHONE':'+5547991154859'}
        self.target={'host':HOST,'account_id':'1','inbox_id':'3','conversation_id':'26097','contact_id':'3'}
        self.gate={'enabled':True,'provider':'chatwoot','account_id':'1','inbox_id':'3','phone':'+5547991154859'}
        self.event={'provider':'chatwoot','account_id':'1','inbox_id':'3','conversation_id':'26097',
            'contact_id':'3','message_id':'777','message_type':'incoming','private':False,
            'sender_type':'contact','sender_phone':'+5547991154859','text':'Oi'}
    def test_stage_accepts_only_exact_easypanel_scope(self):
        self.assertEqual(self.stage._settings(self.env,self.target,False)['base'],'https://'+HOST)
        for key in ('account_id','inbox_id','conversation_id','contact_id'):
            with self.assertRaises(self.stage.GateClosed):
                self.stage._settings(self.env,{**self.target,key:'999'},False)
    def test_old_or_arbitrary_host_is_rejected_before_http_factory(self):
        for host in (OLD,'other.invalid'):
            calls=[]
            result=self.stage.run_preflight({**self.env,'CHATWOOT_BASE_URL':'https://'+host},
                expected_host=host,expected_account_id='1',expected_inbox_id='3',expected_conversation_id='26097',
                expected_contact_id='3',require_labels=True,http_factory=lambda:calls.append('HTTP'))
            self.assertFalse(result['passed']);self.assertEqual(result['post_attempts'],0);self.assertEqual(calls,[])
    def test_stage_does_not_accept_redirect_path_query_credentials_or_alternate_port(self):
        for url in ('https://'+HOST+'/x','https://'+HOST+'?x=1','https://u:p@'+HOST,'https://'+HOST+':443'):
            with self.assertRaises(self.stage.GateClosed):self.stage._settings({**self.env,'CHATWOOT_BASE_URL':url},self.target,False)
    def test_visual_progress_accepts_easypanel_but_no_old_or_other_host(self):
        for host,expected in ((HOST,True),(OLD,False),('other.invalid',False)):
            transport=ChatwootTransport('https://'+host,'offline-test-token',self.gate)
            self.assertIs(transport._progress_allowed(self.event),expected)
    def test_visual_progress_preserves_account_inbox_contact_and_conversation_fences(self):
        transport=ChatwootTransport('https://'+HOST,'offline-test-token',self.gate)
        for key in ('account_id','inbox_id','contact_id','conversation_id'):
            self.assertFalse(transport._progress_allowed({**self.event,key:'999'}))


if __name__=='__main__':unittest.main()
