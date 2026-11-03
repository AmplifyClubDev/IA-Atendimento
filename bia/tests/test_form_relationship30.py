"""The form owns an explicit durable relationship read; GET never starts one."""
from datetime import timedelta
import unittest
from unittest.mock import patch

from forms import FormStore, _sha
from tests import test_original_form_compat as fixtures

NOW = fixtures.NOW


class FormRelationship30Tests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.OriginalFormCompatTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.repo, self.client = fixture.repo, fixture.client
        fixture.settings['relationship_check_in_form'] = True
        self.state = fixture.state
        self.state['revision'] = 1
        self.state['cycle']['relationship_check_in_form'] = True
        self.state['cycle']['real_operations'].pop('relationship')
        self.state['effects'].clear()
        self.repo.save_session(fixture.conv, self.state)
        self.repo.reserve_event('chatwoot:1:101', fixture.conv, 'fixture-source')
        self.calls, self.status = [], 'queued'
        fixture.app.extensions['v5_verify_form_relationship'] = self.callback
        for target in ['socket.create_connection', 'socket.socket.connect', 'socket.socket.connect_ex']:
            guard = patch(target, side_effect=AssertionError('network forbidden'))
            guard.start()
            self.addCleanup(guard.stop)

    def callback(self, state, event, *, creator, operation_key, now, start):
        self.calls.append(dict(creator=creator, operation_key=operation_key, start=start))
        return {'status': self.status}

    def post(self, handle='contato_exemplo_v5'):
        return self.fixture.post('agenciamento', {'tiktok': handle})

    def get(self):
        return self.client.get('/cadastro/compat/agenciamento', headers=self.fixture.headers)

    def database(self):
        with FormStore(self.repo.path).db() as db:
            return '\n'.join(db.iterdump())

    def prove(self, *, source='form', operation_key=None, sql=True):
        key = operation_key or self.calls[-1]['operation_key']
        state = self.repo.load_session(self.fixture.conv)
        cycle, job = state['cycle'], 'form-relationship-effect'
        state['revision'] += 1
        state['effects'][job] = dict(id=job, type='tiktok_operation', operation='relationship', status='done',
            cycle_id=cycle['id'], creator='@contato_exemplo_v5',
            payload={'source': source, 'form_operation_key': _sha(cycle['id'] + ':@contato_exemplo_v5:' + key)})
        cycle['real_operations']['relationship'] = dict(operation='relationship', job_id=job,
            creator='@contato_exemplo_v5', cycle_id=cycle['id'], status='linked', confirmed=True,
            observed_at=NOW.isoformat(), evidence={'source': 'partner_relations'})
        proof = dict(creator_id=state['creator_id'], atendimento_id=cycle['id'],
                     event_id='chatwoot:1:101', revision=state['revision'])
        state['contact_sync_proof'] = proof
        if sql:
            operation = proof['event_id'] + ':contact:' + str(state['revision'])
            self.repo.reserve_operation(operation, proof['event_id'], 'contact_sync')
            self.repo.complete_operation(operation, proof)
        self.repo.save_session(self.fixture.conv, state)
        self.status = 'linked'

    def test_link_context_opens_before_relationship_but_gate_and_submit_stay_closed(self):
        self.assertEqual(self.fixture.context().status_code, 200)
        result = self.client.put('/cadastro/compat/respostas', json=self.fixture.payload(), headers=self.fixture.headers)
        self.assertEqual(result.status_code, 409)
        submitted = self.client.post('/cadastro/' + self.fixture.token,
            json=self.fixture.payload(5, final=True), headers=self.fixture.headers)
        self.assertEqual(submitted.status_code, 409)
        self.assertEqual(self.fixture.gateway.calls, [])

    def test_post_generates_server_key_and_duplicate_active_post_reuses_read(self):
        first = self.post()
        self.assertEqual(first.json['reason'], 'verificacao_em_andamento')
        self.assertEqual(first.json['retry_after_seconds'], 3)
        key = self.calls[-1]['operation_key']
        self.assertRegex(key, r'^form:[0-9a-f-]{36}:relationship:[0-9a-f]{32}$')
        self.assertEqual(self.calls[-1]['creator'], '@contato_exemplo_v5')
        self.post()
        self.assertEqual([x['start'] for x in self.calls], [True, False])
        self.assertEqual({x['operation_key'] for x in self.calls}, {key})

    def test_get_is_strictly_read_only_and_does_not_start_or_create_a_draft(self):
        self.assertEqual(self.get().json['reason'], 'verificacao_nao_iniciada')
        self.assertEqual(self.calls, [])
        self.post()
        before = self.database()
        self.assertEqual(self.get().json['reason'], 'verificacao_em_andamento')
        self.assertEqual(self.database(), before)
        self.assertFalse(self.calls[-1]['start'])

    def test_linked_get_requires_durable_form_proof_and_sql_projection(self):
        self.post()
        self.status = 'linked'
        self.assertEqual(self.get().status_code, 409)
        self.prove(sql=False)
        self.assertEqual(self.get().status_code, 409)
        self.prove()
        before = self.database()
        self.assertEqual(self.get().json, {'status': 'aprovada'})
        self.assertEqual(self.database(), before)
        self.assertEqual(self.fixture.gateway.calls, [])

    def test_linked_from_chat_or_other_form_key_never_opens_gate(self):
        self.post()
        self.prove(source='chat')
        self.assertEqual(self.get().status_code, 409)
        self.prove(operation_key='form:another:relationship:unrelated')
        self.assertEqual(self.get().status_code, 409)

    def test_pending_and_not_found_need_new_explicit_post_for_fresh_read(self):
        for status in ['pending', 'not_found']:
            self.status = status
            self.assertEqual(self.post().json['status'], 'aguardando_vinculo')
            key = self.calls[-1]['operation_key']
            self.get()
            self.assertFalse(self.calls[-1]['start'])
            self.post()
            self.assertNotEqual(self.calls[-1]['operation_key'], key)

    def test_unknown_failed_or_invalid_response_never_approves(self):
        for status in ['failed', 'outcome_unknown', 'verification_pending', 'approved', None]:
            self.status = status
            with self.subTest(status=status):
                self.assertEqual(self.post().json['status'], 'conferencia')
        self.fixture.app.extensions['v5_verify_form_relationship'] = lambda *a, **k: (_ for _ in ()).throw(TimeoutError())
        self.assertEqual(self.post().json['status'], 'conferencia')

    def test_identity_token_query_and_cycle_guards_precede_callback(self):
        self.assertEqual(self.post('different_creator').status_code, 409)
        self.assertEqual(self.client.get('/cadastro/compat/agenciamento').status_code, 401)
        self.assertEqual(self.client.get('/cadastro/compat/agenciamento?operation_key=forged',
            headers=self.fixture.headers).status_code, 400)
        self.state['cycle']['id'] = '11111111-1111-4111-8111-111111111111'
        self.repo.save_session(self.fixture.conv, self.state)
        self.assertEqual(self.get().status_code, 410)
        self.assertEqual(self.calls, [])

    def test_linked_get_allows_original_put_and_email_sequence_without_sql_submission(self):
        self.post()
        self.prove()
        self.assertEqual(self.get().json['status'], 'aprovada')
        payload = self.fixture.payload()
        payload['answers'] = {key: self.fixture.answers[key] for key in ('nome', 'email', 'whatsapp', 'tiktok')}
        first = self.client.put('/cadastro/compat/respostas', json=payload, headers=self.fixture.headers)
        self.assertEqual(first.status_code, 200, first.json)
        self.fixture.revision = first.json['revision']
        self.fixture.verify()
        initial = self.fixture.post('validacao-inicial', {key: self.fixture.answers[key]
            for key in ('nome', 'email', 'whatsapp', 'tiktok')})
        self.assertEqual(initial.json['status'], 'aprovada')
        self.assertEqual(self.fixture.gateway.calls, [])

    def test_form_factory_requires_real_invitation_and_never_promotes_it_to_linked(self):
        state = self.repo.load_session(self.fixture.conv)
        cycle, job = state['cycle'], 'invitation-effect'
        consent = {'source': 'explicit_inbound'}
        cycle['invite_consent'] = consent
        state['effects'][job] = dict(id=job, type='tiktok_operation', operation='invite', status='done',
            cycle_id=cycle['id'], creator='@contato_exemplo_v5', confirmed=True, consent=consent)
        cycle['real_operations']['invite'] = dict(job_id=job, creator='@contato_exemplo_v5', cycle_id=cycle['id'],
            status='sent', confirmed=True, observed_at=NOW.isoformat(), evidence={'sent': True})
        effect = dict(id='new-form-effect', type='generate_form_link', cycle_id=cycle['id'],
            payload={'verification_mode': 'real', 'relationship_check_in_form': True, 'invite_job_id': job,
                     'facts': cycle['facts']})
        with self.fixture.app.app_context():
            url = self.fixture.app.extensions['v5_form_link_factory'](state, effect, self.fixture.event)
        self.assertEqual(url, self.fixture.url)
        self.assertNotIn('relationship', cycle['real_operations'])
        cycle['real_operations']['invite']['status'] = 'outcome_unknown'
        with self.fixture.app.app_context(), self.assertRaises(ValueError):
            self.fixture.app.extensions['v5_form_link_factory'](state, effect, self.fixture.event)

    def test_original_final_maps_all_fields_once_after_form_proof(self):
        self.post()
        self.prove()
        self.fixture.ready()
        result = self.fixture.post('respostas', self.fixture.payload(5, final=True))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertTrue(result.json['submitted'])
        self.assertEqual(len(self.fixture.gateway.calls), 1)
        self.assertEqual(len(self.fixture.mail.receipts), 1)
        replay = self.fixture.post('respostas', self.fixture.payload(5, final=True))
        self.assertTrue(replay.json['submitted'])
        self.assertEqual(len(self.fixture.gateway.calls), 1)

    def test_proof_expiry_and_revision_drift_block_advancement(self):
        self.post()
        self.prove()
        state = self.repo.load_session(self.fixture.conv)
        state['revision'] += 1
        self.repo.save_session(self.fixture.conv, state)
        self.assertEqual(self.get().status_code, 409)
        self.fixture.now = NOW + timedelta(hours=25)
        self.assertEqual(self.get().status_code, 410)

    def test_explicit_reads_keep_one_row_per_form_and_delete_cascades(self):
        self.status = 'not_found'
        self.post()
        self.post()
        with FormStore(self.repo.path).db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM v5_form_relationship_checks').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            foreign = db.execute('PRAGMA foreign_key_list(v5_form_relationship_checks)').fetchone()
            self.assertEqual((foreign['table'], foreign['on_delete']), ('v5_forms', 'CASCADE'))
            db.execute('DELETE FROM v5_forms')
            self.assertEqual(db.execute('SELECT count(*) FROM v5_form_relationship_checks').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
