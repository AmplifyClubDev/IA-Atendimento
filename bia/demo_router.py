"""Exclusive owner demo: independent state, approved copy and simulated effects.

Disabled by default. This module never imports the production bootstrap,
repository, provider clients, AI or mail sender. Live delivery is a separate
explicit capability, limited to one verified Chatwoot conversation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid

from contracts import allow_inbound, inbound_key, normalize_phone, same_phone
import demo_flow

VERSION = 'v1'
OPENING = ('Oi! Que bom ter você por aqui 💙\n\n'
           'Eu sou a Bia, da *Amplify*, uma agência de creators do TikTok Shop.\n\n'
           'Como posso te ajudar hoje? 😊')
CHOICES = {'join': 'Quero fazer parte', 'know': 'Conhecer a Amplify', 'member': 'Já sou Amplify'}


def opening_payload(key):
    if not isinstance(key, str) or not re.fullmatch(r'bia-demo:' + VERSION + r':[a-f0-9]{32}:opening', key):
        raise ValueError('demo_message_key_invalid')
    return {'content': OPENING, 'message_type': 'outgoing', 'private': False, 'content_type': 'input_select',
            'content_attributes': {'items': [{'title': title, 'value': key + ':' + action}
                                            for action, title in CHOICES.items()]}}


def message_payload(key, *, continuation_enabled=False, answer=None):
    if isinstance(key, str) and key.startswith('bia-demo:v2:'):
        if continuation_enabled is not True:
            raise ValueError('demo_continuation_disabled')
        return demo_flow.payload(key, OPENING, CHOICES, answer=answer)
    return opening_payload(key)


def identifier(value):
    return str(value) if type(value) in (str, int) and re.fullmatch(r'[1-9][0-9]{0,19}', str(value)) else None


def clock(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('demo_timestamp_invalid')
    return value.astimezone(timezone.utc)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


@dataclass(frozen=True)
class DemoScope:
    account_id: str
    inbox_id: str
    contact_id: str
    conversation_id: str
    phone: str

    def __post_init__(self):
        if any(identifier(getattr(self, name)) != getattr(self, name)
               for name in ('account_id', 'inbox_id', 'contact_id', 'conversation_id')):
            raise ValueError('demo_scope_ids_invalid')
        if not normalize_phone(self.phone):
            raise ValueError('demo_scope_phone_invalid')

    @property
    def conversation_key(self):
        return 'chatwoot:' + self.account_id + ':' + self.conversation_id

    @property
    def slot(self):
        return digest([self.account_id, self.inbox_id, self.contact_id, self.conversation_id, normalize_phone(self.phone)])

    def claims(self, event):
        """Reserve partial owner matches too; bad identity never falls through."""
        if not isinstance(event, dict) or (str(event.get('account_id')), str(event.get('inbox_id'))) != (self.account_id, self.inbox_id):
            return False
        return (str(event.get('conversation_id')) == self.conversation_id
                or str(event.get('contact_id')) == self.contact_id
                or same_phone(self.phone, event.get('sender_phone')))

    def accepts(self, event):
        gate = {'enabled': True, 'provider': 'chatwoot', 'account_id': self.account_id,
                'inbox_id': self.inbox_id, 'phone': self.phone}
        return (allow_inbound(gate, event)
                and str(event.get('contact_id')) == self.contact_id
                and str(event.get('conversation_id')) == self.conversation_id)


def production_blocked(settings, event=None, conversation_key=None):
    scope = settings.get('_demo_scope') if isinstance(settings, dict) else None
    return bool(scope and (conversation_key == scope.conversation_key or scope.claims(event)))


def excluded_conversations(settings):
    scope = settings.get('_demo_scope') if isinstance(settings, dict) else None
    return (scope.conversation_key,) if scope else ()


class DemoStore:
    """Demo-only SQLite; never receives the production repository object."""
    def __init__(self, path, *, production_path=None):
        if path != ':memory:':
            path = str(Path(path).resolve())
            if production_path:
                production_path = Path(production_path).resolve()
                if Path(path) == production_path or (Path(path).exists() and production_path.exists()
                                                     and Path(path).samefile(production_path)):
                    raise ValueError('demo_store_must_be_separate')
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables & {'sessions', 'inbound_events', 'operations', 'outbox', 'real_jobs'}:
            self.db.close()
            raise ValueError('demo_store_contains_production_schema')
        if tables - {'demo_runs', 'demo_starts', 'demo_events', 'demo_outbox', 'demo_simulations'}:
            self.db.close()
            raise ValueError('demo_store_not_dedicated')
        if path != ':memory:':
            os.chmod(path, 0o600)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS demo_runs (
            slot TEXT PRIMARY KEY, run TEXT NOT NULL, started TEXT NOT NULL,
            watermark TEXT NOT NULL, step TEXT NOT NULL, choice TEXT,
            parent_id TEXT, parent_external TEXT, outbox_key TEXT);
          CREATE TABLE IF NOT EXISTS demo_starts (
            slot TEXT NOT NULL, request_id TEXT NOT NULL, run TEXT NOT NULL,
            result TEXT NOT NULL, PRIMARY KEY(slot,request_id));
          CREATE TABLE IF NOT EXISTS demo_events (
            slot TEXT NOT NULL, event_key TEXT NOT NULL, digest TEXT NOT NULL,
            result TEXT NOT NULL, PRIMARY KEY(slot,event_key));
          CREATE TABLE IF NOT EXISTS demo_outbox (
            key TEXT PRIMARY KEY, slot TEXT NOT NULL, run TEXT NOT NULL,
            payload TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT);
          CREATE TABLE IF NOT EXISTS demo_simulations (
            slot TEXT NOT NULL, run TEXT NOT NULL, operation TEXT NOT NULL,
            result TEXT NOT NULL);
        ''')

    def current(self, slot):
        with self.lock:
            row = self.db.execute('SELECT * FROM demo_runs WHERE slot=?', (slot,)).fetchone()
            return dict(row) if row else None

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise


class SimulatedEffects:
    """No provider, URL or credential is accepted by these adapters."""
    def run(self, operation, fixture='unknown'):
        if operation == 'tiktok' and fixture in {'eligible', 'ineligible', 'unknown', 'failure'}:
            return {'operation': operation, 'status': 'simulated', 'fixture': fixture, 'provider_called': False}
        if operation == 'invite' and fixture in {'unknown', 'accepted', 'declined', 'failure'}:
            return {'operation': operation, 'status': 'simulated', 'fixture': fixture, 'sent': False}
        if operation == 'relationship' and fixture in {'linked', 'not_linked', 'unknown', 'failure'}:
            return {'operation': operation, 'status': 'simulated', 'fixture': fixture,
                    'provider_called': False, 'production_relationship': False}
        raise ValueError('demo_simulation_invalid')


class RecordingGateway:
    """Offline default: records synthetic presentation; no network capability."""
    def __init__(self):
        self.sent = []

    def preflight(self, scope):
        return {'after_message_id': '0'}

    def send(self, scope, payload, key):
        self.sent.append({'payload': payload, 'key': key})
        return {'status': 'accepted', 'message_id': str(int(digest(key)[:15], 16) or 1), 'simulated': True}

    def lookup(self, scope, key):
        return None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class DemoWhatsAppGateway:
    """Only future real egress: exact owner conversation, with no auto retry."""
    def __init__(self, base_url, token, *, scope, live_enabled=False, opener=None, now=clock, continuation_enabled=False):
        parts = urlsplit(base_url)
        if (parts.scheme != 'https' or not parts.hostname or parts.port not in (None, 443)
                or parts.path not in ('', '/') or parts.query or parts.fragment or parts.username or parts.password):
            raise ValueError('demo_chatwoot_base_invalid')
        self.base_url, self.token = base_url.rstrip('/'), token
        self.scope = scope
        self.context_payload = None
        self.continuation_enabled = continuation_enabled is True
        self.live_enabled, self.opener, self.now = live_enabled, opener, now

    def _api(self, scope, method, suffix='', payload=None):
        if scope != self.scope:
            raise ValueError('demo_egress_scope_mismatch')
        if self.live_enabled is not True or not isinstance(self.token, str) or not self.token or re.search(r'[\r\n]', self.token):
            raise ValueError('demo_live_delivery_disabled')
        if (method, suffix) not in {('GET', ''), ('GET', '/messages'), ('POST', '/messages')}:
            raise ValueError('demo_egress_denied')
        url = self.base_url + '/api/v1/accounts/' + scope.account_id + '/conversations/' + scope.conversation_id + suffix
        raw = None if payload is None else json.dumps(payload, ensure_ascii=True).encode()
        request = Request(url, data=raw, method=method, headers={
            'api_access_token': self.token, 'Accept': 'application/json', 'Content-Type': 'application/json'})
        opener = self.opener or build_opener(_NoRedirect())
        with opener.open(request, timeout=10) as response:
            raw = response.read(2_097_153)
            if len(raw) > 2_097_152:
                raise ValueError('demo_response_too_large')
            return json.loads(raw)

    def preflight(self, scope):
        detail = self._api(scope, 'GET')
        sender = (detail.get('meta') or {}).get('sender') or {}
        if (str(detail.get('id')) != scope.conversation_id or str(detail.get('account_id')) != scope.account_id
                or str(detail.get('inbox_id')) != scope.inbox_id or str(sender.get('id')) != scope.contact_id
                or not same_phone(scope.phone, sender.get('phone_number')) or detail.get('can_reply') is not True):
            raise ValueError('demo_recipient_or_window_unverified')
        rows = self._api(scope, 'GET', '/messages').get('payload')
        if not isinstance(rows, list):
            raise ValueError('demo_messages_unverified')
        incoming = [m for m in rows if m.get('message_type') in (0, 'incoming') and m.get('private') is False
                    and type(m.get('created_at')) in (int, float)]
        now = clock(self.now()).timestamp()
        if not incoming or not 0 <= now - max(m['created_at'] for m in incoming) < 86400:
            raise ValueError('demo_reply_window_closed')
        ids = [int(str(m['id'])) for m in rows if identifier(m.get('id'))]
        return {'after_message_id': str(max(ids, default=0))}

    def send(self, scope, payload, key):
        if scope != self.scope:
            raise ValueError('demo_egress_scope_mismatch')
        if payload != self.expected_payload(key):
            raise ValueError('demo_payload_not_approved')
        self.preflight(scope)  # Identity/window rechecked directly before POST.
        result = self._api(scope, 'POST', '/messages', payload)
        if (not identifier(result.get('id')) or (result.get('conversation_id') is not None
                                               and str(result['conversation_id']) != scope.conversation_id)):
            raise ValueError('demo_delivery_unconfirmed')
        return {'status': 'accepted', 'message_id': str(result['id']), 'external_id': result.get('source_id')}

    def expected_payload(self, key):
        if key.startswith('bia-demo:v2:') and demo_flow.key_parts(key)[1] == 'faq_context':
            if self.continuation_enabled is not True or not callable(self.context_payload):
                raise ValueError('demo_context_payload_unavailable')
            return self.context_payload(key)
        return message_payload(key, continuation_enabled=self.continuation_enabled)

    def lookup(self, scope, key):
        expected = self.expected_payload(key)
        rows = self._api(scope, 'GET', '/messages').get('payload') or []
        matches = [m for m in rows if m.get('content') == expected['content']
                   and m.get('message_type') in (1, 'outgoing') and m.get('private') is False
                   and m.get('content_type') == 'input_select'
                   and (m.get('content_attributes') or {}).get('items') == expected['content_attributes']['items']
                   and all(m.get(key) is None or str(m[key]) == value for key, value in (
                       ('account_id', scope.account_id), ('inbox_id', scope.inbox_id), ('conversation_id', scope.conversation_id)))]
        if len(matches) != 1 or not identifier(matches[0].get('id')):
            return None
        return {'status': 'accepted', 'message_id': str(matches[0]['id']), 'external_id': matches[0].get('source_id')}


class ProductionTransportFence:
    """Defense at old write paths, independently of ingress/catch-up guards."""
    def __init__(self, delegate, scope):
        self.delegate, self.scope = delegate, scope

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def send_reply(self, event, *args, **kwargs):
        if self.scope.claims(event):
            return {'status': 'failed', 'reason': 'demo_contact_excluded_from_production'}
        return self.delegate.send_reply(event, *args, **kwargs)

    def read_progress(self, event, *args, **kwargs):
        if self.scope.claims(event):
            return None
        return self.delegate.read_progress(event, *args, **kwargs)

    def write_progress(self, event, *args, **kwargs):
        if self.scope.claims(event):
            return {'status': 'failed', 'reason': 'demo_contact_excluded_from_production'}
        return self.delegate.write_progress(event, *args, **kwargs)

    def http(self, *, method, url, **kwargs):
        path = urlsplit(url).path
        prefix = '/api/v1/accounts/' + self.scope.account_id + '/conversations/' + self.scope.conversation_id
        if path == prefix or path.startswith(prefix + '/'):
            raise ValueError('demo_contact_excluded_from_production')
        return self.delegate.http(method=method, url=url, **kwargs)


class DemoRouter:
    def __init__(self, scope, store, gateway=None, *, now=clock, continuation_enabled=False, question_answerer=None):
        self.scope, self.store = scope, store
        self.gateway, self.now = gateway or RecordingGateway(), now
        self.continuation_enabled = continuation_enabled is True
        self.effects = SimulatedEffects()
        self.question_answerer = question_answerer

    def claims(self, event):
        return self.scope.claims(event)

    def start(self, request_id):
        return self._start(request_id)

    def _start(self, request_id, *, reset_event=None):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_id):
            raise ValueError('demo_start_request_id_required')
        with self.store.lock:
            previous = self.store.db.execute('SELECT result FROM demo_starts WHERE slot=? AND request_id=?',
                                             (self.scope.slot, request_id)).fetchone()
            if previous:
                return json.loads(previous['result'])
            pending = self.store.db.execute("SELECT 1 FROM demo_outbox WHERE slot=? AND status='outcome_unknown' LIMIT 1",
                                            (self.scope.slot,)).fetchone()
            if pending:
                return {'status': 'demo_delivery_unconfirmed', 'repeat_allowed': False}
            preflight = self.gateway.preflight(self.scope)
            watermark = str(preflight.get('after_message_id', '0'))
            if not re.fullmatch(r'[0-9]{1,20}', watermark):
                raise ValueError('demo_watermark_invalid')
            if reset_event:
                watermark = str(max(int(watermark), int(reset_event[2])))
            run = uuid.uuid4().hex
            key = (demo_flow.new_key(run, 'opening') if self.continuation_enabled else
                   'bia-demo:' + VERSION + ':' + run + ':opening')
            payload = message_payload(key, continuation_enabled=self.continuation_enabled)
            self.store.db.execute('BEGIN IMMEDIATE')
            try:
                if self.store.db.execute("SELECT 1 FROM demo_outbox WHERE slot=? AND status='outcome_unknown' LIMIT 1", (self.scope.slot,)).fetchone():
                    self.store.db.execute('ROLLBACK')
                    return {'status': 'demo_delivery_unconfirmed', 'repeat_allowed': False}
                self.store.db.execute('INSERT OR REPLACE INTO demo_runs VALUES(?,?,?,?,?,?,?,?,?)',
                    (self.scope.slot, run, clock(self.now()).isoformat(), watermark,
                     'delivery_pending' if self.continuation_enabled else 'opening', None, None, None, key))
                metadata = {'reset_event_key': reset_event[0]} if reset_event else None
                self.store.db.execute('INSERT INTO demo_outbox VALUES(?,?,?,?,?,?)',
                    (key, self.scope.slot, run, json.dumps(payload), 'outcome_unknown',
                     json.dumps(metadata) if metadata else None))
                result = {'status': 'demo_delivery_unconfirmed', 'run': run, 'repeat_allowed': False}
                self.store.db.execute('INSERT INTO demo_starts VALUES(?,?,?,?)',
                    (self.scope.slot, request_id, run, json.dumps(result)))
                if reset_event:
                    event_result = {'accepted': False, 'status': 'demo_delivery_unconfirmed',
                                    'repeat_allowed': False, 'production_effects': False}
                    self.store.db.execute('INSERT INTO demo_events VALUES(?,?,?,?)',
                        (self.scope.slot, reset_event[0], reset_event[1], json.dumps(event_result)))
                self.store.db.execute('COMMIT')
            except Exception:
                self.store.db.execute('ROLLBACK')
                raise
            # Unknown is committed before external IO. Never automatically retry.
            try:
                receipt = self.gateway.send(self.scope, payload, key)
                result = self._accept(key, receipt)
            except Exception:
                pass
            self.store.db.execute('UPDATE demo_starts SET result=? WHERE slot=? AND request_id=?',
                                  (json.dumps(result), self.scope.slot, request_id))
            return result

    def _accept(self, key, receipt):
        if receipt.get('status') != 'accepted' or not identifier(receipt.get('message_id')):
            raise ValueError('demo_receipt_unconfirmed')
        flow = key.startswith('bia-demo:v2:')
        step = demo_flow.key_parts(key)[1] if flow else 'opening'
        kind = 'opening' if step == 'opening' else 'message'
        result = {'status': 'demo_' + kind + ('_simulated' if receipt.get('simulated') is True else '_created'),
                  'message_id': str(receipt['message_id']), 'version': demo_flow.FLOW_VERSION if flow else VERSION,
                  'whatsapp_live': receipt.get('simulated') is not True}
        if flow:result['step'] = step
        with self.store.transaction():
            pending = self.store.db.execute('SELECT receipt FROM demo_outbox WHERE key=?', (key,)).fetchone()
            metadata = json.loads(pending['receipt']) if pending and pending['receipt'] else {}
            self.store.db.execute('UPDATE demo_outbox SET status=?,receipt=? WHERE key=?',
                                  ('accepted', json.dumps({**receipt, 'grounded': metadata.get('grounded'),
                                                         'resume_step': metadata.get('resume_step'),
                                                         'last_question': metadata.get('last_question')}), key))
            if flow:
                self.store.db.execute("UPDATE demo_runs SET parent_id=?,parent_external=?,"
                                      "step=CASE WHEN step='delivery_pending' THEN ? ELSE step END WHERE slot=? AND outbox_key=?",
                                      (str(receipt['message_id']), receipt.get('external_id'), step, self.scope.slot, key))
            else:
                self.store.db.execute('UPDATE demo_runs SET parent_id=?,parent_external=? WHERE slot=? AND outbox_key=?',
                                      (str(receipt['message_id']), receipt.get('external_id'), self.scope.slot, key))
            if step == 'opening' and not metadata.get('pending_event_key'):
                self.store.db.execute('UPDATE demo_starts SET result=? WHERE slot=? AND run=(SELECT run FROM demo_outbox WHERE key=?)',
                                      (json.dumps(result), self.scope.slot, key))
            if metadata.get('pending_event_key'):
                event_result = {'accepted': True, 'status': 'demo_step_presented', 'step': step,
                                'choice': metadata['choice'], 'message_id': str(receipt['message_id']),
                                'production_effects': False}
                self.store.db.execute('UPDATE demo_events SET result=? WHERE slot=? AND event_key=?',
                                      (json.dumps(event_result), self.scope.slot, metadata['pending_event_key']))
            if metadata.get('reset_event_key'):
                event_result = {'accepted': True, 'status': 'demo_reset_presented', 'step': 'opening',
                                'message_id': str(receipt['message_id']), 'production_effects': False}
                self.store.db.execute('UPDATE demo_events SET result=? WHERE slot=? AND event_key=?',
                                      (json.dumps(event_result), self.scope.slot, metadata['reset_event_key']))
        return result

    def _handle_flow_locked(self, event, state, event_key, fingerprint, *, correlated, conflict):
        result = {'accepted': False, 'status': 'demo_choice_not_current', 'production_effects': False}
        if state['step'] == 'delivery_pending':
            result.update(status='demo_delivery_unconfirmed', repeat_allowed=False)
        elif not state['outbox_key'].startswith('bia-demo:v2:'):
            result['status'] = 'demo_flow_restart_required'
        else:
            run, step, _ = demo_flow.key_parts(state['outbox_key'])
            referenced = event.get('demo_reply_to') is not None or event.get('demo_reply_external') is not None
            if run == state['run'] and step == state['step'] and not conflict and (not referenced or correlated):
                previous = self.store.db.execute('SELECT receipt,payload FROM demo_outbox WHERE key=?', (state['outbox_key'],)).fetchone()
                metadata = json.loads(previous['receipt']) if previous and previous['receipt'] else {}
                resume_step = metadata.get('resume_step') if step in demo_flow.FAQ_STEPS else step
                if resume_step not in demo_flow.RETURN_STEPS:
                    resume_step = 'opening'
                last_question = demo_flow.safe_context_text(metadata.get('last_question'), 500)
                if not last_question and step == 'faq_unavailable' and state['choice'] == 'faq_benefits':
                    # Compatibility with an already presented failure from the old
                    # benefits button, whose exact menu question was not persisted.
                    last_question = demo_flow.TEMPLATES['about'][1]['faq_benefits']
                question_answerer = self.question_answerer
                if getattr(question_answerer, 'accepts_dialogue_context', False) is True:
                    dialogue = {'current_step': step, 'return_step': resume_step,
                                'last_question': last_question,
                                'last_answer': json.loads(previous['payload']).get('content', '') if previous else ''}
                    question_answerer = lambda question: self.question_answerer(question, conversation=dialogue)
                decision = demo_flow.decision(step, event.get('text'), correlated=correlated, opening_choices=CHOICES,
                                              question_answerer=question_answerer, resume_step=resume_step,
                                              last_question=last_question)
                if decision:
                    key = demo_flow.new_key(run, decision['step'])
                    grounded = decision.get('grounded')
                    payload = message_payload(key, continuation_enabled=True,
                                              answer=grounded['answer'] if grounded else None)
                    result = {'accepted': False, 'status': 'demo_delivery_unconfirmed', 'repeat_allowed': False,
                              'production_effects': False}
                    with self.store.transaction():
                        self.store.db.execute('INSERT INTO demo_events VALUES(?,?,?,?)',
                                              (self.scope.slot, event_key, fingerprint, json.dumps(result)))
                        self.store.db.execute('INSERT INTO demo_outbox VALUES(?,?,?,?,?,?)',
                                              (key, self.scope.slot, run, json.dumps(payload), 'outcome_unknown',
                                               json.dumps({'pending_event_key': event_key, 'choice': decision['action'],
                                                           'grounded': grounded,
                                                           'resume_step': resume_step if decision['step'] in demo_flow.FAQ_STEPS else decision['step'],
                                                           'last_question': demo_flow.safe_context_text(decision.get('question'), 500)})))
                        self.store.db.execute('UPDATE demo_runs SET step=?,choice=?,parent_id=NULL,parent_external=NULL,'
                                              'outbox_key=?,started=?,watermark=? WHERE slot=?',
                                              ('delivery_pending', decision['action'], key, clock(self.now()).isoformat(),
                                               event['message_id'], self.scope.slot))
                        for operation, fixture in decision['effects']:
                            simulation = self.effects.run(operation, fixture)
                            self.store.db.execute('INSERT INTO demo_simulations VALUES(?,?,?,?)',
                                                  (self.scope.slot, run, operation, json.dumps(simulation)))
                    try:
                        self._accept(key, self.gateway.send(self.scope, payload, key))
                    except Exception:
                        pass
                    cached = self.store.db.execute('SELECT result FROM demo_events WHERE slot=? AND event_key=?',
                                                    (self.scope.slot, event_key)).fetchone()
                    return json.loads(cached['result']), 202
        self.store.db.execute('INSERT INTO demo_events VALUES(?,?,?,?)',
                              (self.scope.slot, event_key, fingerprint, json.dumps(result)))
        return result, 202

    def reconcile(self):
        with self.store.lock:
            state = self.store.current(self.scope.slot)
            if not state:
                return {'status': 'demo_not_started'}
            row = self.store.db.execute('SELECT * FROM demo_outbox WHERE key=?', (state['outbox_key'],)).fetchone()
            if row['status'] == 'accepted':
                return {'status': 'demo_already_confirmed', 'message_id': state['parent_id']}
            receipt = self.gateway.lookup(self.scope, state['outbox_key'])
            return self._accept(state['outbox_key'], receipt) if receipt else {'status': 'demo_delivery_unconfirmed', 'repeat_allowed': False}

    @staticmethod
    def decorate(event, payload):
        """Add correlation only to demo events; legacy event digests stay intact."""
        attributes = payload.get('content_attributes') if isinstance(payload, dict) else None
        attributes = attributes if isinstance(attributes, dict) else {}
        return {**event, 'demo_reply_to': attributes.get('in_reply_to'),
                'demo_reply_external': attributes.get('in_reply_to_external_id')}

    def _input_context(self, event, state):
        try:
            if not isinstance(event.get('created_at'), str):
                raise ValueError('demo_timestamp_required')
            stamp, now = clock(event.get('created_at')), clock(self.now())
            recent = (clock(state['started']) <= stamp <= now + timedelta(seconds=30)
                      and now - clock(state['started']) <= timedelta(hours=1)
                      and int(event['message_id']) > int(state['watermark']))
        except (ValueError, TypeError, KeyError, OverflowError):
            recent = False
        parent = bool(state['parent_id'] and identifier(event.get('demo_reply_to')) == state['parent_id'])
        external = bool(state['parent_external'] and event.get('demo_reply_external') == state['parent_external'])
        conflict = ((event.get('demo_reply_to') is not None and not parent)
                    or (state['parent_external'] and event.get('demo_reply_external') is not None and not external))
        return recent, parent or external, conflict

    def _handle_reset(self, event, event_key, fingerprint):
        # Reset is a fresh inbound command, not an old button or an expiry bypass.
        # Keep the same identity checks, durable deduplication and unknown-send fence.
        with self.store.lock:
            previous = self.store.db.execute('SELECT digest,result FROM demo_events WHERE slot=? AND event_key=?',
                                             (self.scope.slot, event_key)).fetchone()
            if previous:
                return (json.loads(previous['result']) if previous['digest'] == fingerprint else
                        {'accepted': False, 'status': 'demo_conflicting_duplicate'}), 202
            state = self.store.current(self.scope.slot)
            try:
                if not isinstance(event.get('created_at'), str) or not identifier(event.get('message_id')):
                    raise ValueError('demo_timestamp_or_id_required')
                stamp, now = clock(event['created_at']), clock(self.now())
                recent = (now - timedelta(minutes=5) <= stamp <= now + timedelta(seconds=30)
                          and (not state or (stamp >= clock(state['started'])
                               and int(event['message_id']) > int(state['watermark']))))
            except (ValueError, TypeError, KeyError, OverflowError):
                recent = False
            result = {'accepted': False, 'status': 'demo_stale_event', 'production_effects': False}
            if recent:
                try:
                    result = self._start('inbound-reset-' + digest(event_key),
                                         reset_event=(event_key, fingerprint, event['message_id']))
                except Exception:
                    result = {'status': 'demo_reset_unavailable'}
                # The start transaction persisted this event before any send. If
                # receipt persistence failed, return its uncertainty, never retry.
                cached = self.store.db.execute('SELECT result FROM demo_events WHERE slot=? AND event_key=?',
                                               (self.scope.slot, event_key)).fetchone()
                if cached:
                    return json.loads(cached['result']), 202
                result = {'accepted': False, 'production_effects': False, **result}
            self.store.db.execute('INSERT INTO demo_events VALUES(?,?,?,?)',
                                  (self.scope.slot, event_key, fingerprint, json.dumps(result)))
            return result, 202

    def _handle_continuation(self, event, event_key, fingerprint):
        # Keep one contact serialized, but commit uncertainty before network IO.
        with self.store.lock:
            previous = self.store.db.execute('SELECT digest,result FROM demo_events WHERE slot=? AND event_key=?',
                                             (self.scope.slot, event_key)).fetchone()
            if previous:
                return (json.loads(previous['result']) if previous['digest'] == fingerprint else
                        {'accepted': False, 'status': 'demo_conflicting_duplicate'}), 202
            state = self.store.current(self.scope.slot)
            if state:
                recent, correlated, conflict = self._input_context(event, state)
                if recent:
                    return self._handle_flow_locked(event, state, event_key, fingerprint,
                                                    correlated=correlated, conflict=conflict)
            result = {'accepted': False, 'status': 'demo_stale_event' if state else 'demo_not_started'}
            self.store.db.execute('INSERT INTO demo_events VALUES(?,?,?,?)',
                                  (self.scope.slot, event_key, fingerprint, json.dumps(result)))
            return result, 202

    def handle(self, event):
        if not self.claims(event):
            raise ValueError('demo_event_outside_scope')
        if not self.scope.accepts(event):
            return {'accepted': False, 'status': 'demo_identity_rejected'}, 202
        event_key, fingerprint = inbound_key(event), digest(event)
        if event['text'].strip().casefold() == 'resetar':
            return self._handle_reset(event, event_key, fingerprint)
        if self.continuation_enabled:
            return self._handle_continuation(event, event_key, fingerprint)
        with self.store.transaction():
            previous = self.store.db.execute('SELECT digest,result FROM demo_events WHERE slot=? AND event_key=?',
                                             (self.scope.slot, event_key)).fetchone()
            if previous:
                return (json.loads(previous['result']) if previous['digest'] == fingerprint else
                        {'accepted': False, 'status': 'demo_conflicting_duplicate'}), 202
            state = self.store.current(self.scope.slot)
            result = {'accepted': False, 'status': 'demo_not_started'}
            if state:
                recent, correlated, conflict = self._input_context(event, state)
                action = next((key for key, title in CHOICES.items() if event.get('text') == title), None)
                if not recent:
                    result['status'] = 'demo_stale_event'
                elif state['step'] != 'opening' or not action or not correlated or conflict:
                    result['status'] = 'demo_choice_not_current'
                else:
                    self.store.db.execute('UPDATE demo_runs SET step=?,choice=? WHERE slot=?',
                                          ('awaiting_review', action, self.scope.slot))
                    result = {'accepted': True, 'status': 'demo_choice_recorded', 'choice': action,
                              'next_message': 'awaiting_user_review', 'production_effects': False}
            self.store.db.execute('INSERT INTO demo_events VALUES(?,?,?,?)',
                                  (self.scope.slot, event_key, fingerprint, json.dumps(result)))
            return result, 202

    def simulate(self, operation, fixture='unknown'):
        with self.store.lock:
            state = self.store.current(self.scope.slot)
            if not state or state['step'] != 'awaiting_review':
                raise ValueError('demo_choice_required')
            result = self.effects.run(operation, fixture)
            self.store.db.execute('INSERT INTO demo_simulations VALUES(?,?,?,?)',
                                  (self.scope.slot, state['run'], operation, json.dumps(result)))
            return result

    def stop(self):
        with self.store.lock:
            self.store.db.execute('UPDATE demo_runs SET step=? WHERE slot=?', ('closed', self.scope.slot))
        return {'status': 'demo_closed', 'production_still_excluded': True}


def build_demo_router(settings, *, gateway=None, production_path=None):
    if not isinstance(settings, dict) or settings.get('demo_enabled') is not True:
        return None
    values = settings.get('demo_scope')
    if not isinstance(values, dict):
        raise ValueError('demo_scope_required')
    scope = DemoScope(**values)
    path = settings.get('demo_state_path')
    if not isinstance(path, str) or not path:
        raise ValueError('demo_state_path_required')
    if path == ':memory:' and settings.get('demo_whatsapp_live') is True:
        raise ValueError('demo_live_delivery_requires_durable_state')
    production_path = production_path or Path(settings.get('state_dir', '/data')) / 'atendimento.sqlite3'
    if gateway is None:
        gateway = (DemoWhatsAppGateway(settings.get('chatwoot_base_url', ''), settings.get('chatwoot_api_token', ''),
                                      scope=scope, live_enabled=True,
                                      continuation_enabled=settings.get('demo_continuation_enabled') is True)
                   if settings.get('demo_whatsapp_live') is True else RecordingGateway())
    store = DemoStore(path, production_path=production_path)
    if isinstance(gateway, DemoWhatsAppGateway):
        def persisted_context_payload(key):
            row = store.db.execute('SELECT payload FROM demo_outbox WHERE key=? AND slot=?',
                                   (key, scope.slot)).fetchone()
            if row is None:
                raise ValueError('demo_context_payload_not_persisted')
            return json.loads(row['payload'])
        gateway.context_payload = persisted_context_payload
    settings['_demo_scope'] = scope
    from demo_answers import build_answerer
    return DemoRouter(scope, store, gateway, continuation_enabled=settings.get('demo_continuation_enabled') is True,
                      question_answerer=build_answerer(settings))
