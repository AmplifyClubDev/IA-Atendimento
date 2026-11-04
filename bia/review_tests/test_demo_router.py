"""Synthetic offline cases for exclusive routing and production fences."""
from contextlib import nullcontext
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from demo_router import (DemoScope, DemoStore, DemoRouter, RecordingGateway, DemoWhatsAppGateway,
                         ProductionTransportFence, build_demo_router, opening_payload, CHOICES, OPENING, VERSION)
from repository import Repository

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
PHONE = '+55' + '11' + '9' + '0' * 8
OTHER = '+55' + '12' + '9' + '0' * 8
SCOPE = DemoScope('1', '3', '9', '7', PHONE)
TOKEN = 'synthetic-webhook-' + 'x' * 32


def event(**changes):
    value = {'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3', 'contact_id': '9',
             'conversation_id': '7', 'message_id': '101', 'message_type': 'incoming', 'private': False,
             'sender_phone': PHONE, 'sender_type': 'contact', 'text': CHOICES['know'],
             'created_at': (NOW + timedelta(seconds=1)).isoformat()}
    value.update(changes)
    return value


def settings(directory, *, enabled=True):
    return {'demo_enabled': enabled, 'demo_state_path': ':memory:',
            'demo_scope': {name: getattr(SCOPE, name) for name in SCOPE.__dataclass_fields__},
            'pilot_scope': {'phone': PHONE, 'contact_id': '9', 'conversation_id': '7'},
            'state_dir': str(directory), 'gate': {'enabled': True, 'provider': 'chatwoot', 'account_id': '1',
              'inbox_id': '3', 'phone': PHONE, 'mode': 'todos'},
            'webhook_token': TOKEN, 'readiness_issues': [], 'tiktok_mode': 'simulated',
            'real_worker_enabled': False, 'contact_sync_enabled': False, 'conversation_enabled': False,
            'retomada_enabled': False, 'pos_pausa_enabled': False, 'reconferencia_enabled': False}


class RouterCases(unittest.TestCase):
    def setUp(self):
        self.store = DemoStore(':memory:')
        self.addCleanup(self.store.close)
        self.gateway = RecordingGateway()
        self.router = DemoRouter(SCOPE, self.store, self.gateway, now=lambda: NOW)

    def start(self, key='synthetic-start-1'):
        result = self.router.start(key)
        self.assertEqual(result['status'], 'demo_opening_simulated')
        return result

    def click(self, **changes):
        return event(**{'demo_reply_to': self.store.current(SCOPE.slot)['parent_id'], **changes})

    def test_start_uses_only_approved_copy_and_three_versioned_buttons(self):
        self.start()
        payload = self.gateway.sent[0]['payload']
        self.assertEqual(payload['content'], OPENING)
        self.assertEqual([row['title'] for row in payload['content_attributes']['items']], list(CHOICES.values()))
        self.assertTrue(all(row['value'].startswith('bia-demo:' + VERSION + ':') for row in payload['content_attributes']['items']))

    def test_all_three_choices_are_recorded_without_automatic_continuation(self):
        for index, (choice, title) in enumerate(CHOICES.items()):
            self.start('synthetic-start-' + str(index))
            count = len(self.gateway.sent)
            result, code = self.router.handle(self.click(text=title, message_id=str(101 + index)))
            self.assertEqual((code, result['choice']), (202, choice))
            self.assertEqual(result['next_message'], 'awaiting_user_review')
            self.assertEqual(len(self.gateway.sent), count)

    def test_duplicate_click_is_durable_and_does_not_send_again(self):
        self.start()
        source = self.click()
        self.assertEqual(self.router.handle(source), self.router.handle(source))
        self.assertEqual(len(self.gateway.sent), 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_events').fetchone()[0], 1)

    def test_conflicting_duplicate_is_closed(self):
        self.start(); source = self.click()
        self.router.handle(source)
        result, _ = self.router.handle({**source, 'text': CHOICES['join']})
        self.assertEqual(result['status'], 'demo_conflicting_duplicate')

    def test_start_request_is_idempotent(self):
        result = self.start()
        self.assertEqual(self.router.start('synthetic-start-1'), result)
        self.assertEqual(len(self.gateway.sent), 1)

    def test_restart_changes_parent_and_preserves_demo_history(self):
        self.start(); old = self.click()
        self.router.handle(old)
        self.start('synthetic-restart-2')
        self.assertNotEqual(old['demo_reply_to'], self.store.current(SCOPE.slot)['parent_id'])
        result, _ = self.router.handle({**old, 'message_id': '102'})
        self.assertEqual(result['status'], 'demo_choice_not_current')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_outbox').fetchone()[0], 2)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_events').fetchone()[0], 2)

    def test_old_timestamp_and_missing_timestamp_are_rejected(self):
        self.start()
        for index, stamp in enumerate((None, (NOW - timedelta(seconds=1)).isoformat(),
                                       (NOW + timedelta(hours=1)).isoformat(), 'invalid')):
            result, _ = self.router.handle(self.click(message_id=str(110 + index), created_at=stamp))
            self.assertEqual(result['status'], 'demo_stale_event')

    def test_old_message_id_is_rejected_despite_recent_timestamp(self):
        self.gateway.preflight = lambda scope: {'after_message_id': '200'}
        self.start()
        self.assertEqual(self.router.handle(self.click())[0]['status'], 'demo_stale_event')

    def test_free_text_old_title_and_missing_parent_do_not_advance(self):
        self.start()
        for index, change in enumerate(({'text': 'old scripted title'}, {'demo_reply_to': None},
                                         {'text': 'resetar'}, {'demo_reply_to': '8'})):
            result, _ = self.router.handle(self.click(message_id=str(110 + index), **change))
            self.assertEqual(result['status'], 'demo_choice_not_current')
        self.assertEqual(len(self.gateway.sent), 1)

    def test_current_internal_parent_is_enough_before_external_receipt_arrives(self):
        self.start()
        result, _ = self.router.handle(self.click(demo_reply_external='synthetic-provider-reference'))
        self.assertEqual(result['status'], 'demo_choice_recorded')

    def test_conflicting_known_external_reference_is_rejected(self):
        self.start()
        self.store.db.execute('UPDATE demo_runs SET parent_external=?', ('synthetic-current-reference',))
        result, _ = self.router.handle(self.click(demo_reply_external='synthetic-old-reference'))
        self.assertEqual(result['status'], 'demo_choice_not_current')

    def test_expired_session_stays_reserved_without_sending(self):
        self.start(); self.router.now = lambda: NOW + timedelta(hours=2)
        self.assertEqual(self.router.handle(self.click())[0]['status'], 'demo_stale_event')
        self.assertTrue(self.router.claims(event()))

    def test_stop_does_not_return_contact_to_production(self):
        self.start(); self.router.stop()
        self.assertTrue(self.router.claims(event()))
        self.assertEqual(self.router.handle(self.click())[0]['status'], 'demo_choice_not_current')

    def test_identity_uses_full_number_and_all_scope_ids(self):
        self.start()
        for change in ({'contact_id': '8'}, {'conversation_id': '8'}, {'sender_phone': OTHER}, {'private': True}):
            source = self.click(**change)
            self.assertTrue(self.router.claims(source))
            self.assertEqual(self.router.handle(source)[0]['status'], 'demo_identity_rejected')
        self.assertFalse(self.router.claims(event(contact_id='8', conversation_id='8', sender_phone=OTHER)))
        self.assertFalse(self.router.claims(event(account_id='2')))
        self.assertFalse(self.router.claims(event(inbox_id='2')))

    def test_verified_brazilian_mobile_alias_matches(self):
        mobile = '+55' + '11' + '99' + '0' * 7
        scope = DemoScope('1', '3', '9', '7', mobile)
        alias = mobile[:5] + mobile[6:]
        self.assertTrue(scope.claims(event(sender_phone=alias)))
        self.assertTrue(scope.accepts(event(sender_phone=alias)))

    def test_ninth_digit_alias_is_not_inferred_for_non_mobile_fixture(self):
        # The old fixture starts its local part with zero, outside the existing
        # mobile contract (6-9). Preserve its rejection as a negative case.
        alias = PHONE[:5] + PHONE[6:]
        self.assertFalse(SCOPE.accepts(event(sender_phone=alias)))

    def test_simulated_providers_have_no_real_invite_and_form_is_removed(self):
        self.start(); self.router.handle(self.click())
        for operation in ('tiktok', 'invite'):
            result = self.router.simulate(operation)
            self.assertEqual(result['status'], 'simulated')
            self.assertFalse(result.get('sent', False))
            self.assertFalse(result.get('production_submission', False))
            self.assertIsNone(result.get('url'))
        with self.assertRaises(ValueError): self.router.simulate('smtp')
        with self.assertRaises(ValueError): self.router.simulate('form')
        self.assertEqual(len(self.gateway.sent), 1)

    def test_simulation_requires_a_current_choice(self):
        with self.assertRaises(ValueError): self.router.simulate('invite')

    def test_timeout_never_retries_until_receipt_is_reconciled(self):
        class Uncertain(RecordingGateway):
            def send(inner, scope, payload, key):
                inner.receipt = super(Uncertain, inner).send(scope, payload, key)
                raise TimeoutError()
            def lookup(inner, scope, key):return inner.receipt
        gateway = Uncertain()
        router = DemoRouter(SCOPE, self.store, gateway, now=lambda: NOW)
        result = router.start('synthetic-unknown-1')
        self.assertEqual(result['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(router.start('synthetic-unknown-1'), result)
        self.assertEqual(router.start('synthetic-unknown-2')['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(len(gateway.sent), 1)
        self.assertEqual(router.reconcile()['status'], 'demo_opening_simulated')
        self.assertEqual(router.start('synthetic-unknown-1')['status'], 'demo_opening_simulated')
        self.assertEqual(len(gateway.sent), 1)

    def test_unconfirmed_lookup_keeps_resend_forbidden(self):
        self.gateway.send = Mock(side_effect=TimeoutError())
        self.router.start('synthetic-unknown-1')
        self.assertFalse(self.router.reconcile()['repeat_allowed'])
        self.router.start('synthetic-unknown-2')
        self.gateway.send.assert_called_once()

    def test_receipt_confirmation_is_atomic_when_storage_update_fails(self):
        self.store.db.executescript("""CREATE TRIGGER synthetic_receipt_failure
            BEFORE UPDATE OF parent_id ON demo_runs
            BEGIN SELECT RAISE(ABORT, 'synthetic receipt failure'); END;""")
        result = self.router.start('synthetic-receipt-failure')
        self.assertEqual(result['status'], 'demo_delivery_unconfirmed')
        row = self.store.db.execute('SELECT status FROM demo_outbox').fetchone()
        self.assertEqual(row['status'], 'outcome_unknown')
        self.assertIsNone(self.store.current(SCOPE.slot)['parent_id'])
        self.assertEqual(self.router.start('synthetic-no-retry')['status'], 'demo_delivery_unconfirmed')
        self.assertEqual(len(self.gateway.sent), 1)

    def test_concurrent_duplicate_click_has_one_transition(self):
        self.start(); source = self.click(); results = []
        threads = [threading.Thread(target=lambda: results.append(self.router.handle(source))) for _ in range(4)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(len(results), 4)
        self.assertEqual(len(self.gateway.sent), 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM demo_events').fetchone()[0], 1)

    def test_durable_duplicate_survives_router_recreation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'demo.sqlite')
            store = DemoStore(path); router = DemoRouter(SCOPE, store, self.gateway, now=lambda: NOW)
            router.start('synthetic-durable-start')
            source = event(demo_reply_to=store.current(SCOPE.slot)['parent_id'])
            result = router.handle(source); store.close()
            store = DemoStore(path)
            try:
                again = DemoRouter(SCOPE, store, self.gateway, now=lambda: NOW)
                self.assertEqual(again.handle(source), result)
                self.assertEqual(len(self.gateway.sent), 1)
            finally:store.close()


class GatewayAndConfiguration(unittest.TestCase):
    def test_live_egress_is_disabled_without_explicit_capability(self):
        gateway = DemoWhatsAppGateway('https://chat.example.invalid', 'synthetic-token', scope=SCOPE)
        with self.assertRaisesRegex(ValueError, 'disabled'):gateway.preflight(SCOPE)

    def test_disabled_config_does_not_create_state(self):
        self.assertIsNone(build_demo_router({'demo_enabled': False}))

    def test_live_mode_rejects_memory_state(self):
        with tempfile.TemporaryDirectory() as directory:
            values = {**settings(directory), 'demo_whatsapp_live': True}
            with self.assertRaisesRegex(ValueError, 'durable'):build_demo_router(values)

    def test_demo_cannot_use_production_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'atendimento.sqlite3'; path.write_text('untouched')
            with self.assertRaisesRegex(ValueError, 'separate'):
                DemoStore(str(path), production_path=path)
            self.assertEqual(path.read_text(), 'untouched')

    def test_existing_production_schema_is_rejected_under_another_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'custom-production.sqlite3'
            repository = Repository(path)
            opened = None
            try:
                with self.assertRaisesRegex(ValueError, 'production'):
                    opened = DemoStore(str(path), production_path=Path(directory) / 'different.sqlite3')
            finally:
                if opened is not None:opened.close()
            with repository._connection() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'demo_%'").fetchone()[0], 0)

    def test_invalid_enabled_scope_does_not_silently_disable_routing(self):
        with self.assertRaises(ValueError):build_demo_router({'demo_enabled': True})

    def test_production_transport_blocks_owner_and_preserves_other_contact(self):
        delegate = Mock(); fence = ProductionTransportFence(delegate, SCOPE)
        self.assertEqual(fence.send_reply(event(), 'x', [], 'k')['status'], 'failed')
        self.assertIsNone(fence.read_progress(event()))
        self.assertEqual(fence.write_progress(event())['status'], 'failed')
        self.assertEqual(delegate.mock_calls, [])
        other = event(contact_id='8', conversation_id='8', sender_phone=OTHER)
        fence.send_reply(other, 'x', [], 'k'); delegate.send_reply.assert_called_once()
        with self.assertRaises(ValueError):fence.http(method='POST', url='https://chat.example.invalid/api/v1/accounts/1/conversations/7/messages')

    def test_live_preflight_rejects_wrong_recipient_without_post(self):
        calls = []
        class Opener:
            def open(self, request, timeout):
                calls.append(request.method)
                return io.BytesIO(json.dumps({'id': '7', 'account_id': '1', 'inbox_id': '3', 'can_reply': True,
                    'meta': {'sender': {'id': '8', 'phone_number': OTHER}}}).encode())
        gateway = DemoWhatsAppGateway('https://chat.example.invalid', 'synthetic-token', scope=SCOPE, live_enabled=True, opener=Opener(), now=lambda: NOW)
        key = 'bia-demo:v1:' + 'a' * 32 + ':opening'
        with self.assertRaisesRegex(ValueError, 'recipient'):gateway.send(SCOPE, opening_payload(key), key)
        self.assertEqual(calls, ['GET'])


class ProductionJobFences(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.repo = Repository(Path(self.directory.name) / 'production.sqlite3')
        self.config = settings(self.directory.name)
        self.config['_demo_scope'] = SCOPE
        self.repo.set_demo_scope(SCOPE)
        self.seed_counter = 100

    def seed(self, name, conversation, status='queued', operation='invite', owner=None):
        key = 'synthetic-' + name
        self.seed_counter += 1
        owner = conversation == SCOPE.conversation_key if owner is None else owner
        source = 'chatwoot:1:' + str(self.seed_counter)
        source_event = event(conversation_id=conversation.rsplit(':', 1)[1],
                             contact_id='9' if owner else '8', sender_phone=PHONE if owner else OTHER,
                             message_id=str(self.seed_counter))
        with self.repo._connection() as db:
            db.execute('INSERT OR IGNORE INTO inbound_events VALUES(?,?,?,?,?,?)', (source, conversation, 'synthetic', 'completed', NOW.isoformat(), NOW.isoformat()))
            db.execute('INSERT INTO real_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (key, conversation, source, 'synthetic-effect', 'synthetic-cycle', '@synthetic', operation,
                 json.dumps(source_event), '{}', status, 0, NOW.isoformat(), None, None, NOW.isoformat()))
        return key

    def test_pending_owner_jobs_are_held_and_other_jobs_not_starved(self):
        own = self.seed('owner', SCOPE.conversation_key)
        ready = self.seed('ready-owner', SCOPE.conversation_key, 'result_ready')
        other = self.seed('other', 'chatwoot:1:8', operation='precheck')
        self.assertEqual(self.repo.claim_real_job(NOW.isoformat())['job_key'], other)
        self.assertEqual(self.repo.real_job(own)['status'], 'queued')
        self.assertEqual(self.repo.real_job(own)['attempts'], 0)
        self.assertEqual(self.repo.real_job(ready)['status'], 'result_ready')

    def test_restart_recovery_does_not_requeue_or_change_owner_job(self):
        own = self.seed('running-owner', SCOPE.conversation_key, 'running')
        before = self.repo.real_job(own)
        self.repo.recover_real_jobs(NOW.isoformat())
        self.assertEqual(self.repo.real_job(own), before)

    def test_owner_jobs_in_another_conversation_are_held_by_identity(self):
        own = self.seed('owner-another-chat', 'chatwoot:1:18', owner=True)
        other = self.seed('other-real-contact', 'chatwoot:1:8', operation='precheck')
        self.assertEqual(self.repo.claim_real_job(NOW.isoformat())['job_key'], other)
        self.assertEqual(self.repo.real_job(own)['status'], 'queued')
        self.assertEqual(self.repo.real_job(own)['attempts'], 0)

    def test_recovery_holds_owner_job_in_another_conversation(self):
        own = self.seed('owner-another-running-chat', 'chatwoot:1:18', 'running', owner=True)
        before = self.repo.real_job(own)
        self.repo.recover_real_jobs(NOW.isoformat())
        self.assertEqual(self.repo.real_job(own), before)

    def test_reminder_and_recheck_scans_do_not_list_owner(self):
        self.seed('owner-read', SCOPE.conversation_key, operation='precheck')
        self.seed('other-read', 'chatwoot:1:8', operation='precheck')
        self.assertEqual(self.repo.precheck_conversations(), ['chatwoot:1:8'])

    def test_uncertain_read_recovery_holds_owner_and_recovers_other_contact(self):
        for owner, conversation in ((True, 'chatwoot:1:18'), (False, 'chatwoot:1:8')):
            with self.subTest(owner=owner):
                key = self.seed('uncertain-' + str(owner), conversation,
                                'outcome_unknown', operation='lookup', owner=owner)
                state = {'cycle': {'id': 'synthetic-cycle', 'mode': 'real', 'status': 'open',
                                  'expires_at': (NOW + timedelta(hours=1)).isoformat(),
                                  'facts': {'tiktok_declarado': '@synthetic'}},
                         'effects': {'synthetic-effect': {'id': 'synthetic-effect', 'status': 'pending',
                                     'type': 'tiktok_operation', 'operation': 'lookup',
                                     'cycle_id': 'synthetic-cycle', 'creator': '@synthetic', 'payload': {}}}}
                result = {'operation': 'lookup', 'creator': '@synthetic'}
                with self.repo._connection() as db:
                    db.execute('INSERT INTO sessions VALUES(?,?,?)',
                               (conversation, json.dumps(state), NOW.isoformat()))
                    db.execute('UPDATE real_jobs SET attempts=1,result_json=? WHERE job_key=?',
                               (json.dumps(result), key))
                    db.execute('INSERT INTO inbound_events VALUES(?,?,?,?,?,?)',
                               (key + ':result:synthetic-effect:1', conversation, 'synthetic',
                                'outcome_unknown', NOW.isoformat(), NOW.isoformat()))
                before = self.repo.real_job(key)
                self.repo.recover_real_jobs(NOW.isoformat())
                if owner:
                    self.assertEqual(self.repo.real_job(key), before)
                else:
                    self.assertEqual(self.repo.real_job(key)['status'], 'queued')

    def test_old_retomada_is_stopped_before_repository_or_provider(self):
        from retomada import Retomada
        worker = Retomada.__new__(Retomada); worker.settings = self.config
        worker.repository, worker.registration, worker.lock_for = Mock(), Mock(), Mock()
        result = worker._conversation(SCOPE.conversation_key, NOW)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(worker.repository.mock_calls, [])
        worker.registration.assert_not_called(); worker.lock_for.assert_not_called()

    def test_old_followup_is_stopped_before_repository(self):
        from followup import Followup
        worker = Followup.__new__(Followup); worker.settings = self.config
        worker.conversation = SCOPE.conversation_key; worker.repository = Mock()
        self.assertEqual(worker._tick()['status'], 'blocked')
        self.assertEqual(worker._tick_inactivity()['status'], 'blocked')
        self.assertEqual(worker.repository.mock_calls, [])

    def test_catchup_skips_owner_before_reading_messages(self):
        from retomada import PosPausa
        worker = PosPausa.__new__(PosPausa); worker.settings = self.config; worker._get = Mock()
        result = worker._candidate({'id': '7'}, NOW, 'https://chat.example.invalid')
        self.assertEqual(result[1], 'demo_contact_excluded_from_production')
        worker._get.assert_not_called()

    def test_real_executor_authority_and_result_application_are_fenced(self):
        from real_operations import RealExecutor
        worker = RealExecutor.__new__(RealExecutor); worker.settings = self.config
        worker.repository, worker.lock_for = Mock(), Mock()
        job = {'conversation_key': SCOPE.conversation_key, 'event': event()}
        self.assertFalse(worker._authorized(job))
        self.assertEqual(worker._apply(job)['status'], 'blocked')
        self.assertEqual(worker.repository.mock_calls, [])
        worker.lock_for.assert_not_called()


class FlaskRouting(unittest.TestCase):
    def make_app(self, enabled=True):
        from server import create_app
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        repository = Repository(Path(directory.name) / 'atendimento.sqlite3')
        transport = Mock(); transport.ready.return_value = True
        transport.supports_reply_fencing = False
        transport.send_reply.return_value = {'status': 'accepted', 'message_id': 'synthetic-reply'}
        gateway = RecordingGateway()
        app = create_app(settings(directory.name, enabled=enabled), repository=repository,
                         transport=transport, demo_gateway=gateway, real_guard=Mock(return_value={'allowed': True}), real_client=Mock())
        app.testing = True
        if enabled:
            app.extensions['v5_demo_router'].now = lambda: NOW
            self.addCleanup(app.extensions['v5_demo_router'].store.close)
        return app, repository, transport, gateway

    def raw(self, title=CHOICES['know'], *, owner=True, parent=None, identifier='101'):
        sender = {'id': '9' if owner else '8', 'phone_number': PHONE if owner else OTHER, 'type': 'contact'}
        return {'event': 'message_created', 'id': identifier, 'message_type': 'incoming', 'private': False,
                'content': title, 'created_at': (NOW + timedelta(seconds=1)).isoformat(),
                'account': {'id': '1'}, 'inbox': {'id': '3'}, 'sender': sender,
                'conversation': {'id': '7' if owner else '8', 'account_id': '1', 'inbox_id': '3', 'meta': {'sender': sender}},
                'content_attributes': {'in_reply_to': parent}}

    def test_three_choices_never_touch_production_tables_or_transport(self):
        app, repo, transport, gateway = self.make_app()
        client = app.test_client()
        for index, title in enumerate(CHOICES.values()):
            start = client.post('/demo/start?token=' + TOKEN, json={'request_id': 'synthetic-start-' + str(index)})
            self.assertEqual(start.status_code, 200, start.json)
            response = client.post('/webhook/chatwoot?token=' + TOKEN,
                                   json=self.raw(title, parent=start.json['message_id'], identifier=str(101 + index)))
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json['status'], 'demo_choice_recorded')
        transport.send_reply.assert_not_called()
        with repo._connection() as db:
            for table in ('sessions', 'inbound_events', 'operations', 'outbox', 'real_jobs'):
                self.assertEqual(db.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0, table)

    def test_owner_remains_excluded_when_demo_storage_fails(self):
        app, repo, transport, gateway = self.make_app()
        app.extensions['v5_demo_router'].handle = Mock(side_effect=RuntimeError('synthetic failure'))
        response = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=self.raw())
        self.assertEqual(response.status_code, 503)
        transport.send_reply.assert_not_called()
        with repo._connection() as db:self.assertEqual(db.execute('SELECT count(*) FROM inbound_events').fetchone()[0], 0)

    def test_other_contact_keeps_existing_flow(self):
        outcomes = []
        for enabled in (False, True):
            app, repo, transport, gateway = self.make_app(enabled)
            response = app.test_client().post('/webhook/chatwoot?token=' + TOKEN, json=self.raw('oi', owner=False))
            outcomes.append((response.status_code, response.json, transport.send_reply.call_count))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0][2], 1)

    def test_demo_admin_cannot_change_recipient_or_send_arbitrary_copy(self):
        app, repo, transport, gateway = self.make_app()
        client = app.test_client()
        self.assertEqual(client.post('/demo/start', json={'request_id': 'synthetic-start'}).status_code, 401)
        self.assertEqual(client.post('/demo/start?token=' + TOKEN, json={'request_id': 'synthetic-start', 'contact_id': '8'}).status_code, 400)
        self.assertEqual(client.post('/demo/send?token=' + TOKEN, json={'text': 'unreviewed copy'}).status_code, 400)
        self.assertEqual(gateway.sent, [])
