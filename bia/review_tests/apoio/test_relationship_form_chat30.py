"""Chat sends the invite; only a form-owned read confirms the relationship."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

import conversao
import conversation
import engine
import real_journey as journey
from real_operations import build_jobs, business_key
from repository import Repository
from server import create_app
from test_real_journey import POLICY, GATE

AT = datetime.now(timezone.utc)
CONV = 'chatwoot:1:26097'
SOURCE = 'chatwoot:1:777'
CREATOR = '22222222-2222-4222-8222-222222222222'


def inbound(text, state=None, *, enabled=True):
    return conversation.handle(state or {}, text, now=AT, real_mode=True,
        operation_policy=POLICY, relationship_check_in_form=enabled)


def settle(state, effect, status, **updates):
    result = dict(operation=effect['operation'], creator=effect['creator'].lstrip('@'), status=status,
        confirmed=True, observed_at=AT.isoformat(), evidence={'source': 'offline', 'complete': True})
    result.update(updates)
    return conversation.resolve_tiktok_result(state, effect['id'], result, now=AT, operation_policy=POLICY)


def qualified():
    result = inbound('oi')
    for text in ('Quero me agenciar', 'Indicação', '@teste'):
        result = inbound(text, result['state'])
    return result


def eligible():
    result = qualified()
    effect = next(item for item in result['effects'] if item['operation'] == 'precheck')
    return settle(result['state'], effect, 'eligible')


def invited(status='sent', **updates):
    result = inbound('Autorizo o convite real', eligible()['state'])
    effect = result['effects'][0]
    return settle(result['state'], effect, status, **updates)


def direct_entry(text='Já sou agenciado pela Amplify'):
    state = {}
    first = None
    for identifier, message in (('9001', text), ('9002', '@teste')):
        event = dict(provider='chatwoot', account_id='1', inbox_id='3', conversation_id='26097',
            contact_id='3', message_id=identifier, sender_phone=GATE['phone'], sender_type='contact',
            message_type='incoming', private=False, text=message, created_at=AT.isoformat(),
            source_ref='chatwoot:1:'+identifier)
        result = conversation.handle_event(state, event, GATE, now=AT, real_mode=True,
            operation_policy=POLICY, relationship_check_in_form=True)
        first = first or result
        state = result['state']
    return first, result, event


class FormHandoffJourneyTests(unittest.TestCase):
    def test_explicit_amplify_creator_or_registration_request_opens_form_without_invite(self):
        for text in ('Já sou agenciado pela Amplify', 'Quero meu cadastro', 'Quero meus acessos'):
            with self.subTest(text=text):
                first, result, event = direct_entry(text)
                self.assertIn('@ do TikTok', first['reply'])
                self.assertEqual(result['state']['cycle']['phase'], 'form')
                # Release 37: the single public form link, no per-contact link effect.
                self.assertEqual(result['effects'], [])
                self.assertEqual(result['state']['cycle']['form_url'], journey.PUBLIC_FORM_URL)
                self.assertIn(journey.PUBLIC_FORM_URL, result['reply'])
                self.assertFalse(any(effect.get('type') == 'tiktok_operation' for effect in result['state']['effects'].values()))
                self.assertNotIn('invite_consent', result['state']['cycle'])
                self.assertFalse(journey.relationship_proven(result['state'], now=AT))

    def test_other_agency_or_forged_source_never_opens_direct_amplify_form(self):
        _, result, _ = direct_entry('Já tenho agência')
        self.assertNotIn('form_entry_request', result['state']['cycle'])
        # Release 40: o @ pedido na primeira resposta leva só às leituras do perfil (que conferem a agência atual).
        self.assertEqual({effect['operation'] for effect in result['effects']}, {'lookup', 'precheck'})
        _, result, event = direct_entry()
        event['source_ref'] = 'chatwoot:1:forged'
        event['text'] = 'Já sou agenciado pela Amplify @teste'
        fresh = conversation.handle_event({}, event, GATE, now=AT, real_mode=True,
            operation_policy=POLICY, relationship_check_in_form=True)
        self.assertNotIn('form_entry_request', fresh['state']['cycle'])
        self.assertEqual(fresh['effects'], [])
    def test_initial_reads_check_profile_without_chat_relationship_job(self):
        result = qualified()
        self.assertEqual({item['operation'] for item in result['effects']}, {'lookup', 'precheck'})
        self.assertNotIn('relationship', result['state']['cycle'].get('real_operations', {}))

    def test_eligible_profile_offers_terms_without_relationship_not_found(self):
        result = eligible()
        self.assertEqual(result['state']['cycle']['phase'], 'consent_real')
        self.assertEqual(result['effects'], [])
        self.assertIn('Posso te mandar o convite no TikTok', result['reply'])
        self.assertIn('10%', result['reply'])
        self.assertNotIn('relationship', result['state']['cycle'].get('real_operations', {}))

    def test_no_consent_never_creates_invite(self):
        result = inbound('Não', eligible()['state'])
        self.assertEqual(result['effects'], [])
        self.assertFalse(result['state']['cycle']['facts']['consentimento_convite'])

    def test_accepted_invite_goes_directly_to_form_without_acceptance_declaration(self):
        for status in ('sent', 'pending', 'linked'):
            with self.subTest(status=status):
                result = invited(status)
                self.assertEqual(result['state']['cycle']['phase'], 'form')
                self.assertEqual(result['effects'], [])
                self.assertIn(journey.PUBLIC_FORM_URL, result['reply'])
                self.assertNotIn('aceite_declarado', result['state']['cycle']['facts'])
                self.assertFalse(journey.relationship_proven(result['state'], now=AT))
                self.assertNotIn('me avise', result['reply'].lower())
                self.assertNotIn('vínculo foi confirmado', result['reply'].lower())
                self.assertTrue(journey.form_entry_allowed(result['state'], now=AT))

    def test_unconfirmed_invite_never_claims_sent_and_reads_the_list_in_5_minutes(self):
        # Release 43 (tabela 5b): pending_verification e outcome_unknown não abrem o formulário nem dizem "enviado";
        # a Bia diz que está confirmando e lê a lista de vínculos 5 min depois.
        for status, evidence in (('outcome_unknown', {'post_attempted': True}), ('pending_verification', {}),
                                 ('pending_verification', {'create_accepted': True, 'post_attempted': True})):
            with self.subTest(status=status, evidence=evidence):
                result = invited(status, confirmed=False, evidence=evidence)
                self.assertEqual(result['reply'], conversao.INVITE_CONFIRMING)
                self.assertEqual(result['state']['cycle']['phase'], 'await_acceptance')
                self.assertEqual([item['operation'] for item in result['effects']], ['relationship'])
                self.assertEqual(result['effects'][0]['payload']['not_before'], (AT + timedelta(minutes=5)).isoformat())
                # O formulário confere o vínculo sozinho; com o pedido aceito pela ponte, o link só sai se o lead pedir.
                self.assertEqual(journey.form_entry_allowed(result['state'], now=AT), evidence.get('create_accepted') is True)
                self.assertNotIn(journey.PUBLIC_FORM_URL, result['reply'])

    def test_form_entry_fences_cycle_handle_marker_and_real_invitation(self):
        # The public form checks the agency link itself; the chat only needs a
        # real, consented invite of this cycle/handle before sending the link.
        result = invited()
        for mutate in ('handle', 'invite_id', 'consent'):
            with self.subTest(mutate=mutate):
                state = deepcopy(result['state'])
                if mutate == 'handle': state['cycle']['facts']['tiktok_declarado'] = '@other'
                elif mutate == 'invite_id': state['cycle']['real_operations']['invite']['job_id'] = 'wrong'
                else: state['cycle']['invite_consent'] = {}
                self.assertFalse(journey.form_entry_allowed(state, now=AT))

    def test_form_relationship_result_changes_proof_without_chat_message_or_new_work(self):
        for status in ('linked', 'pending', 'not_found'):
            with self.subTest(status=status):
                state = invited()['state']
                effect = dict(id='form-read', type='tiktok_operation', operation='relationship', creator='@teste',
                    cycle_id=state['cycle']['id'], status='pending', payload={'source': 'form', 'form_operation_key': 'test'})
                state['effects'][effect['id']] = effect
                result = settle(state, effect, status)
                self.assertEqual(result['reply'], '')
                self.assertEqual(result['effects'], [])
                self.assertEqual(result['state']['cycle']['phase'], 'form')
                self.assertEqual(result['state']['effects']['form-read']['status'], 'done')
                self.assertEqual(journey.form_relationship_proven(result['state'], now=AT), status == 'linked')

    def test_old_chat_relationship_result_cannot_confirm_mode30(self):
        state = invited()['state']
        effect = dict(id='chat-read', type='tiktok_operation', operation='relationship', creator='@teste',
            cycle_id=state['cycle']['id'], status='pending', payload={})
        state['effects']['chat-read'] = effect
        result = settle(state, effect, 'linked')
        self.assertTrue(result['ignored'])
        self.assertFalse(journey.form_relationship_proven(result['state'], now=AT))

    def test_legacy_false_still_waits_for_relationship_before_consent(self):
        result = inbound('oi', enabled=False)
        for text in ('Quero me agenciar', 'Indicação', '@teste'):
            result = inbound(text, result['state'], enabled=False)
        self.assertIn('relationship', {item['operation'] for item in result['effects']})
        effect = next(item for item in result['effects'] if item['operation'] == 'precheck')
        result = settle(result['state'], effect, 'eligible')
        self.assertEqual(result['state']['cycle']['phase'], 'checking')


class FormRelationshipCallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.repo = Repository(Path(self.tmp.name)/'state.sqlite3')
        self.state = invited()['state']
        self.state.update(creator_id=CREATOR, processed_inbound=[SOURCE])
        self.event = dict(provider='chatwoot', account_id='1', inbox_id='3', conversation_id='26097',
            contact_id='3', message_id='777', sender_phone=GATE['phone'], sender_type='contact',
            message_type='incoming', private=False, text='Autorizo o convite real',
            created_at=AT.isoformat(), source_ref=SOURCE)
        self.repo.reserve_event(SOURCE, CONV, 'offline')
        self.repo.finish_event(SOURCE, 'completed')
        proof = dict(creator_id=CREATOR, atendimento_id=self.state['cycle']['id'], event_id=SOURCE, revision=self.state['revision'])
        self.state['contact_sync_proof'] = proof
        self.repo.reserve_operation(SOURCE+':contact:'+str(self.state['revision']), SOURCE, 'contact_sync')
        self.repo.complete_operation(SOURCE+':contact:'+str(self.state['revision']), proof)
        invite = next(item for item in self.state['effects'].values() if item.get('operation') == 'invite')
        jobs = build_jobs(self.event, self.state, [invite])
        self.repo.prepare_reply(SOURCE, CONV, self.state, 'unused', None, real_jobs=jobs)
        with self.repo._connection() as db:
            db.execute("UPDATE real_jobs SET status='completed'")
        self.entries, self.calls = [], []
        self.next_status = 'linked'
        outer = self
        class Client:
            def configuration(inner, *_args): return {'configured': True}
            def execute(inner, operation, creator, **kwargs):
                outer.calls.append((operation, creator, kwargs))
                return dict(operation=operation, creator=creator, status=outer.next_status, confirmed=True,
                    observed_at=datetime.now(timezone.utc).isoformat(), evidence={'source': 'offline', 'complete': True})
        class Transport:
            def ready(inner): return True
            def send_reply(inner, *_args, **_kwargs): raise AssertionError('Form read must never send chat')
        class Gateway:
            def register_contact(inner, entry):
                outer.entries.append(deepcopy(entry))
                return dict(creator_id=CREATOR, atendimento_id=entry['atendimento_id'], event_id=entry['event_id'],
                    revision=entry['revision'], cadastro_situacao='pendente')
        self.settings = dict(gate=GATE, webhook_token='offline-token-long-enough', instance_id='test',
            conversation_enabled=True, ai_enabled=True, contact_sync_enabled=True, tiktok_mode='real',
            real_worker_enabled=True, relationship_check_in_form=True)
        self.app = create_app(self.settings, self.repo, Transport(), real_client=Client(), real_guard=lambda *_: {'allowed': True})
        self.app.extensions['v5_data_gateway'] = Gateway()
        self.callback = self.app.extensions['v5_verify_form_relationship']

    def call(self, *, start=True, creator='teste', operation_key=None):
        operation_key = operation_key or getattr(self, 'current_operation', 'form:fixture:relationship:nonce_0001')
        if start:
            self.current_operation = operation_key
        return self.callback(self.repo.load_session(CONV), creator=creator, operation_key=operation_key,
                             now=datetime.now(timezone.utc), start=start)

    def test_post_only_enqueues_and_get_does_not_execute_provider_or_write(self):
        self.assertEqual(self.call()['status'], 'queued')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.call()['status'], 'queued')
        before, entries = deepcopy(self.repo.load_session(CONV)), len(self.entries)
        self.assertEqual(self.call(start=False)['status'], 'queued')
        self.assertEqual(self.repo.load_session(CONV), before)
        self.assertEqual(len(self.entries), entries)
        self.assertEqual(self.repo.outbox(SOURCE), [])

    def test_worker_confirms_only_form_proof_and_sql_without_chat(self):
        self.call()
        self.assertEqual(self.app.extensions['v5_real_executor'].tick()['status'], 'completed')
        self.assertEqual(self.calls[0][0], 'relationship')
        self.assertEqual(self.call(start=False)['status'], 'linked')
        self.assertEqual(self.call(start=False, operation_key='form:fixture:relationship:wrong_nonce')['status'], 'failed')
        state = self.repo.load_session(CONV)
        self.assertTrue(journey.form_relationship_proven(state, now=datetime.now(timezone.utc)))
        self.assertEqual(state['cycle']['phase'], 'form')
        with self.repo._connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)

    def test_pending_is_terminal_for_one_get_and_new_post_reads_fresh_same_job_row(self):
        self.next_status = 'pending'
        self.call()
        self.assertEqual(self.app.extensions['v5_real_executor'].tick()['status'], 'completed')
        self.assertEqual(self.call(start=False)['status'], 'pending')
        self.next_status = 'linked'
        self.assertEqual(self.call(operation_key='form:fixture:relationship:nonce_0002')['status'], 'queued')
        self.app.extensions['v5_real_executor'].tick()
        self.assertEqual(self.call(start=False)['status'], 'linked')
        self.assertEqual([operation for operation, _, _ in self.calls], ['relationship', 'relationship'])
        with self.repo._connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM real_jobs WHERE operation='relationship'").fetchone()[0], 1)

    def test_wrong_profile_or_session_cannot_enqueue(self):
        self.assertEqual(self.call(creator='other')['status'], 'failed')
        wrong = deepcopy(self.state); wrong['session_id'] = 'wrong'
        self.assertEqual(self.callback(wrong, creator='teste', operation_key='form:fixture:relationship:nonce', now=AT)['status'], 'failed')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.entries, [])

    def test_linked_memory_without_completed_sql_is_never_approved(self):
        self.call()
        self.app.extensions['v5_real_executor'].tick()
        state = self.repo.load_session(CONV)
        proof = state['contact_sync_proof']
        self.repo.complete_operation(proof['event_id']+':contact:'+str(proof['revision']), {}, 'outcome_unknown')
        self.assertEqual(self.call(start=False)['status'], 'outcome_unknown')

    def install_direct_entry(self):
        _, result, event = direct_entry()
        self.state, self.event = result['state'], event
        self.state['creator_id'] = CREATOR
        source = event['source_ref']
        self.repo.reserve_event(source, CONV, 'actual-direct-entry-fixture')
        self.repo.finish_event(source, 'completed')
        proof = dict(creator_id=CREATOR, atendimento_id=self.state['cycle']['id'], event_id=source, revision=self.state['revision'])
        self.state['contact_sync_proof'] = proof
        self.repo.reserve_operation(source+':contact:'+str(self.state['revision']), source, 'contact_sync')
        self.repo.complete_operation(source+':contact:'+str(self.state['revision']), proof)
        self.repo.save_session(CONV, self.state)

    def test_direct_creator_path_verifies_in_form_without_any_invite_job(self):
        self.install_direct_entry()
        self.assertEqual(self.call()['status'], 'queued')
        self.assertEqual(self.calls, [])
        self.app.extensions['v5_real_executor'].tick()
        self.assertEqual(self.call(start=False)['status'], 'linked')
        self.assertEqual([operation for operation, _, _ in self.calls], ['relationship'])
        with self.repo._connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM real_jobs WHERE cycle_id=? AND operation='invite'",
                                        (self.state['cycle']['id'],)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)

    def test_direct_creator_forged_source_or_missing_sql_proof_cannot_start_read(self):
        self.install_direct_entry()
        changed = self.repo.load_session(CONV)
        changed['cycle']['form_entry_request']['source_key'] = 'chatwoot:1:forged'
        self.repo.save_session(CONV, changed)
        self.assertEqual(self.call()['status'], 'failed')
        self.assertEqual(self.calls, [])
        self.install_direct_entry()
        changed = self.repo.load_session(CONV)
        proof = changed['contact_sync_proof']
        self.repo.complete_operation(proof['event_id']+':contact:'+str(proof['revision']), {}, 'outcome_unknown')
        self.assertEqual(self.call()['status'], 'outcome_unknown')
        self.assertEqual(self.calls, [])
