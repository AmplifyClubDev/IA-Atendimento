"""Internal, bounded invite diagnostics; synthetic SQLite and no network."""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from operational_diagnostics import invite_attempt_diagnostics
from repository import Repository
from server import create_app

TOKEN = "w" * 40

STAMP = '2026-11-14T07:27:41Z'
CREATOR = '@private_creator'

def eid(i):
    return 'tiktok:' + format(i,'064x')
def result(i, **evidence):
    return dict(operation='invite', creator=CREATOR, status='failed', confirmed=False,
                observed_at=(datetime.fromisoformat(STAMP.replace('Z','+00:00'))+
                             timedelta(seconds=i)).isoformat(), evidence=evidence)
def row(i, **evidence):
    return dict(effect_id=eid(i), cycle_id='cycle-'+str(i), creator=CREATOR,
                result=result(i, **evidence), updated_at=STAMP)
def effect(i, **evidence):
    return dict(type='tiktok_operation', id=eid(i), operation='invite',
                creator=CREATOR, cycle_id='cycle-'+str(i),
                result_receipt={**result(i, **evidence), 'cycle_id':'cycle-'+str(i),'job_id':eid(i)})

def put(repo, conversation, i, res):
    event = 'event:' + str(i)
    repo.reserve_event(event, conversation, 'fixture')
    with repo._connection() as db:
        job_at=(datetime.fromisoformat(STAMP.replace('Z','+00:00'))+
                timedelta(seconds=i)).isoformat()
        db.execute('INSERT INTO real_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(
            'job:'+str(i), conversation, event, eid(i), 'cycle-'+str(i), CREATOR,
            'invite', '{}', '{}', 'completed', 1, job_at,
            json.dumps(res) if isinstance(res, dict) else res, None, job_at))

class AttemptHistory(TestCase):
    def test_restart_and_exact_attempt_dedup(self):
        state={'cycle':{'id':'new'}, 'closed_cycles':[{'id':'cycle-1'}], 'effects':{
            eid(1):effect(1, post_attempted=True, http_status=422, upstream_code='16004004'),
            eid(2):effect(2, post_attempted=True, http_status=422),
        }}
        jobs=[row(2, post_attempted=True, http_status=422, receipt={'version':1,'method':'ui'}),
              row(3, post_attempted=False, upstream_code='16004004'), row(4)]
        before=deepcopy((state,jobs))
        rows=invite_attempt_diagnostics(state,jobs,{})
        self.assertEqual((state,jobs),before)
        self.assertEqual(len(rows),2)
        self.assertEqual([r['attempt'] for r in rows],[1,2])
        self.assertTrue(all(r['bridge_http_status']==422 for r in rows))
        self.assertFalse(rows[0]['provider_reason_available'])
        self.assertEqual(rows[0]['provider_reason'],'motivo não informado')
        self.assertEqual(rows[1]['provider_code'],'16004004')
        self.assertNotIn(CREATOR,json.dumps(rows));self.assertNotIn(eid(1),json.dumps(rows))

    def test_bridge_422_provider_200_keep_separate(self):
        record=row(1, post_attempted=True, http_status=422,
                   receipt={'version':1,'method':'ui','provider_http_status':200,
                            'provider_code':'16004004','provider_message':'the creator has no permission to bind',
                            'provider_post_attempted':True, 'operation_id':'09cd356a-108c-49e6-ae02-d4e9623f357e'})
        r=invite_attempt_diagnostics({},[record],{})[0]
        self.assertEqual((r['bridge_http_status'],r['provider_http_status']),(422,200))
        self.assertEqual(r['provider_message'],'the creator has no permission to bind')
        self.assertTrue(r['provider_reason_available']);self.assertTrue(r['provider_post_attempted'])
        self.assertNotIn('09cd356a',str(r))

    def test_bridge_attempt_can_have_no_upstream_post_or_reason(self):
        r=invite_attempt_diagnostics({},[row(1, post_attempted=False, bridge_post_attempted=True, http_status=422,
                    receipt={'version':1,'method':'ui','provider_post_attempted':False,'status':'not_attempted'})],{})[0]
        self.assertTrue(r['bridge_post_attempted']); self.assertFalse(r['provider_post_attempted'])
        self.assertFalse(r['provider_reason_available']);self.assertNotIn('provider_message',r)

    def test_reject_mismatched_results_and_withhold_private_text(self):
        bad=row(1, post_attempted=True, http_status=422)
        bad['result']['creator']='@other'
        cross=effect(2, post_attempted=True, http_status=422)
        cross['result_receipt']['cycle_id']='other'
        r=invite_attempt_diagnostics({'effects':{eid(2):cross}},[
            bad,row(3, post_attempted=True, http_status=422, upstream_code='12345678900',
                    upstream_message='Joana Exemplo @private_creator +55-47-99999-2222 /secret'),
            row(4, post_attempted=True, http_status=422, upstream_code='JOANA_EXEMPLO'),
            row(5, post_attempted=True, http_status=422, upstream_code='987654321'),
        ],{})
        self.assertEqual(len(r),3)
        for item in r:
            self.assertNotIn('provider_message',item);self.assertNotIn('provider_code',item)
            self.assertFalse(item['provider_reason_available']);self.assertTrue(item['provider_detail_withheld'])
            self.assertEqual(item['provider_reason'],'detalhe omitido por privacidade')

    def test_sql_filters_scope_and_limits_before_decode(self):
        with TemporaryDirectory() as tmp:
            repo=Repository(tmp+'/state.sqlite3')
            own='chatwoot:1:101'
            for i in range(1,21): put(repo,own,i,result(i,post_attempted=True,http_status=422))
            for i in range(21,34): put(repo,own,i,result(i,post_attempted=False,http_status=422))
            put(repo,own,34,'{malformed')
            put(repo,'chatwoot:1:102',35,result(35,post_attempted=True,http_status=422))
            with patch('repository.json.loads',wraps=json.loads) as decoder:
                rows=repo.invite_attempt_rows(own)
                self.assertEqual(decoder.call_count,12)
            self.assertEqual([r['effect_id'] for r in rows],[eid(i) for i in range(20,8,-1)])
            self.assertEqual([r['effect_id'] for r in repo.invite_attempt_rows('chatwoot:1:102')],[eid(35)])
            self.assertEqual(repo.invite_attempt_rows('chatwoot:2:101'),[])

class AuthenticatedInviteHistory(TestCase):
    def test_same_auth_gate_and_no_writes(self):
        with TemporaryDirectory() as tmp:
            repo=Repository(tmp+'/state.sqlite3')
            own='chatwoot:1:101'
            put(repo,own,1,result(1,post_attempted=True,http_status=422))
            put(repo,'chatwoot:1:102',2,result(2,post_attempted=True,http_status=200))
            transport=Mock(token='fixture')
            transport._conversation_url.return_value='https://example.invalid/conversations/101'
            transport.http.side_effect=[{'meta':{},'status':'open'},{'payload':[]}]
            app=create_app({'webhook_token':TOKEN,'gate':{'account_id':1}},repository=repo,transport=transport)
            client=app.test_client()
            path='/diagnostico/conversa/101'
            with patch.object(repo,'invite_attempt_rows',wraps=repo.invite_attempt_rows) as lookup:
                self.assertEqual(client.get(path).status_code,401)
                self.assertEqual(client.get(path,headers={'Authorization':'Bearer '+'x'*40}).status_code,401)
                self.assertEqual(client.get(path+'?token='+TOKEN).status_code,401)
                lookup.assert_not_called()
                transport.http.assert_not_called()
                with repo._connection() as db:
                    before=[tuple(z) for z in db.execute('SELECT * FROM real_jobs')]
                response=client.get(path,headers={'Authorization':'Bearer '+TOKEN})
                with repo._connection() as db:
                    after=[tuple(z) for z in db.execute('SELECT * FROM real_jobs')]
            self.assertEqual(response.status_code,200);self.assertEqual(before,after)
            self.assertEqual(lookup.call_args.args,(own,))
            self.assertEqual([call.kwargs['method'] for call in transport.http.call_args_list],['GET','GET'])
            project=response.get_json()['atendimento']
            self.assertEqual([r['bridge_http_status'] for r in project['tentativas_convite']],[422])
            self.assertIn('operacoes_tiktok',project)
