"""Exclusive owner demo: independent state, approved copy and simulated effects.

Disabled by default. This module never imports the production bootstrap,
repository, provider clients, AI or mail sender. Live delivery is a separate
explicit capability, limited to at most five approved contacts. Conversation
renewal is separately opt-in and requires a direct Chatwoot identity proof.
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
MAX_DEMO_SCOPES = 5
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
    def conversation_keys(self):
        return (self.conversation_key,)

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


class DemoPhoneReservation:
    """Reserve a preapproved phone before its Chatwoot IDs are known."""
    def __init__(self, account_id, inbox_id, phone):
        if any(identifier(value) != value for value in (account_id, inbox_id)):
            raise ValueError('demo_pending_scope_ids_invalid')
        if not normalize_phone(phone):
            raise ValueError('demo_pending_scope_phone_invalid')
        self.account_id, self.inbox_id, self.phone = account_id, inbox_id, phone
        self.bound_scope = None

    @property
    def slot(self):
        return digest(['pending-phone-v1', self.account_id, self.inbox_id, normalize_phone(self.phone)])

    @property
    def conversation_keys(self):
        return self.bound_scope.conversation_keys if self.bound_scope else ()

    def claims(self, event):
        if self.bound_scope and self.bound_scope.claims(event):
            return True
        return (isinstance(event, dict)
                and (str(event.get('account_id')), str(event.get('inbox_id'))) == (self.account_id, self.inbox_id)
                and same_phone(self.phone, event.get('sender_phone')))

    def accepts(self, event):
        return bool(self.bound_scope and self.bound_scope.accepts(event))


class DemoContactReservation:
    """Reserve a configured person and every independently verified conversation.

    This is only an exclusion/dispatch identity, never an egress capability.
    Each immutable DemoScope still owns its own gateway, state and history.
    """
    def __init__(self, scope, store):
        self.original = scope
        self.store = store
        self.scopes = (scope,)
        for name in DemoScope.__dataclass_fields__:
            setattr(self, name, getattr(scope, name))

    @property
    def slot(self):
        return self.original.slot

    @property
    def conversation_keys(self):
        # Exclusions must be visible even to old workers which only know a
        # conversation ID and have not handled another inbound since startup.
        # This grants no egress authority or state: admission still needs guard().
        with self.store.lock:
            keys = [scope.conversation_key for scope in self.scopes]
            for row in self.store.db.execute(
                    'SELECT conversation_id,conversation_key FROM demo_conversation_bindings WHERE owner_slot=?',
                    (self.slot,)):
                conversation = identifier(row['conversation_id'])
                if not conversation or row['conversation_key'] != 'chatwoot:' + self.account_id + ':' + conversation:
                    raise ValueError('demo_conversation_binding_invalid')
                if row['conversation_key'] not in keys:
                    keys.append(row['conversation_key'])
            return tuple(keys)

    def reserve(self, scope):
        if scope not in self.scopes:
            self.scopes += (scope,)

    def claims(self, event):
        if any(scope.claims(event) for scope in self.scopes):
            return True
        return (isinstance(event, dict)
                and (str(event.get('account_id')), str(event.get('inbox_id'))) == (self.account_id, self.inbox_id)
                and 'chatwoot:' + self.account_id + ':' + str(event.get('conversation_id')) in self.conversation_keys)

    def accepts(self, event):
        return any(scope.accepts(event) for scope in self.scopes)


@dataclass(frozen=True)
class DemoScopes:
    """A bounded reservation, never an egress identity or a production gate."""
    scopes: tuple

    def __post_init__(self):
        if (type(self.scopes) is not tuple or not 1 <= len(self.scopes) <= MAX_DEMO_SCOPES
                or any(not isinstance(scope, (DemoScope, DemoPhoneReservation, DemoContactReservation)) for scope in self.scopes)):
            raise ValueError('demo_scopes_invalid')
        primary = self.scopes[0]
        for index, scope in enumerate(self.scopes):
            if (scope.account_id, scope.inbox_id) != (primary.account_id, primary.inbox_id):
                raise ValueError('demo_scopes_account_or_inbox_mismatch')
            for other in self.scopes[:index]:
                left = scope.bound_scope if isinstance(scope, DemoPhoneReservation) else scope
                right = other.bound_scope if isinstance(other, DemoPhoneReservation) else other
                if (same_phone(scope.phone, other.phone)
                        or set(scope.conversation_keys) & set(other.conversation_keys)
                        or (left and right and (left.conversation_id == right.conversation_id
                                               or left.contact_id == right.contact_id))):
                    raise ValueError('demo_scopes_identity_overlap')

    @property
    def conversation_keys(self):
        return tuple(key for scope in self.scopes for key in scope.conversation_keys)

    def claims(self, event):
        return any(scope.claims(event) for scope in self.scopes)


def verified_scopes(settings):
    scope = settings.get('_demo_scope') if isinstance(settings, dict) else None
    if isinstance(scope, (DemoScope, DemoContactReservation)):
        return (scope,)
    return scope.scopes if isinstance(scope, DemoScopes) else ()


def configured_scopes(settings):
    def parse(value):
        if not isinstance(value, dict) or set(value) != set(DemoScope.__dataclass_fields__):
            raise ValueError('demo_scope_required')
        return DemoScope(**value)
    primary = parse(settings.get('demo_scope'))
    if 'demo_scopes' not in settings:
        return (primary,)
    values = settings['demo_scopes']
    if type(values) is not list or not 1 <= len(values) <= MAX_DEMO_SCOPES:
        raise ValueError('demo_scopes_invalid')
    scopes = DemoScopes(tuple(parse(value) for value in values)).scopes
    if (any(getattr(scopes[0], name) != getattr(primary, name)
            for name in ('account_id', 'inbox_id', 'contact_id', 'conversation_id'))
            or not same_phone(scopes[0].phone, primary.phone)):
        raise ValueError('demo_scopes_primary_mismatch')
    # Preserve the established slot and exact egress identity even if the
    # explicit list uses the provider's equivalent Brazilian mobile notation.
    scopes = (primary,) + scopes[1:]
    gate = settings.get('gate') or {}
    if (gate.get('provider'), gate.get('account_id'), gate.get('inbox_id')) != (
            'chatwoot', primary.account_id, primary.inbox_id):
        raise ValueError('demo_scopes_gate_mismatch')
    return scopes


def configured_pending_scope(settings, scopes):
    if 'demo_pending_scope' not in settings:
        return None
    value = settings['demo_pending_scope']
    if (not 1 <= len(scopes) < MAX_DEMO_SCOPES or not isinstance(value, dict)
            or set(value) != {'account_id', 'inbox_id', 'phone'}):
        raise ValueError('demo_pending_scope_invalid')
    pending = DemoPhoneReservation(**value)
    DemoScopes(tuple(scopes) + (pending,))
    gate = settings.get('gate') or {}
    if (gate.get('provider'), gate.get('account_id'), gate.get('inbox_id')) != (
            'chatwoot', pending.account_id, pending.inbox_id):
        raise ValueError('demo_scopes_gate_mismatch')
    return pending


def production_blocked(settings, event=None, conversation_key=None):
    return any(conversation_key in scope.conversation_keys or scope.claims(event)
               for scope in verified_scopes(settings))


def excluded_conversations(settings):
    return tuple(key for scope in verified_scopes(settings) for key in scope.conversation_keys)


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
        self.path = path
        self.owner_locks = threading.local()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables & {'sessions', 'inbound_events', 'operations', 'outbox', 'real_jobs'}:
            self.db.close()
            raise ValueError('demo_store_contains_production_schema')
        if tables - {'demo_runs', 'demo_starts', 'demo_events', 'demo_outbox', 'demo_simulations', 'demo_followups', 'demo_closures', 'demo_conversation_bindings'}:
            self.db.close()
            raise ValueError('demo_store_not_dedicated')
        if path != ':memory:':
            os.chmod(path, 0o600)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS demo_conversation_bindings (
            owner_slot TEXT NOT NULL, conversation_id TEXT NOT NULL,
            conversation_key TEXT NOT NULL UNIQUE, first_event_key TEXT NOT NULL,
            first_event_digest TEXT NOT NULL, verified_at TEXT NOT NULL,
            PRIMARY KEY(owner_slot,conversation_id), UNIQUE(owner_slot,first_event_key));
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
          CREATE TABLE IF NOT EXISTS demo_closures (
            key TEXT PRIMARY KEY, slot TEXT NOT NULL, source_key TEXT NOT NULL,
            due TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
            warning_message_id TEXT NOT NULL, closure_message_id TEXT);
          CREATE TABLE IF NOT EXISTS demo_followups (
            key TEXT PRIMARY KEY, slot TEXT NOT NULL, source_key TEXT NOT NULL,
            due TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
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
    def owner_lock(self, slot):
        """Serialize one person's effects across threads and overlapping workers.

        SQLite still owns each durable transaction. The separate advisory lock
        spans verification and send, without holding a SQL transaction over IO.
        """
        with self.lock:
            active = getattr(self.owner_locks, 'active', set())
            if self.path == ':memory:' or slot in active:
                yield
                return
            if not isinstance(slot, str) or not re.fullmatch(r'[a-f0-9]{64}', slot):
                raise ValueError('demo_owner_lock_invalid')
            import fcntl
            fd = os.open(self.path + '.owner-' + slot + '.lock',
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                self.owner_locks.active = active | {slot}
                try:
                    yield
                finally:
                    self.owner_locks.active = active
            finally:
                os.close(fd)

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
        self.resolved = []

    def preflight(self, scope):
        return {'after_message_id': '0'}

    def send(self, scope, payload, key):
        self.sent.append({'payload': payload, 'key': key})
        return {'status': 'accepted', 'message_id': str(int(digest(key)[:15], 16) or 1), 'simulated': True}

    def resolve_inactivity(self, scope, key):
        self.resolved.append({'scope': scope, 'key': key})
        return {'status': 'resolved', 'simulated': True}

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
        if (method, suffix) not in {('GET', ''), ('GET', '/messages'), ('POST', '/messages'), ('POST', '/toggle_status')}:
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

    def verify_inbound(self, scope, event):
        """Read-only proof of the complete recipient and this exact inbound."""
        self.preflight(scope)
        rows = self._api(scope, 'GET', '/messages').get('payload')
        if not isinstance(rows, list):
            raise ValueError('demo_binding_message_unverified')
        matches = [row for row in rows if isinstance(row, dict)
                   and identifier(row.get('id')) == identifier(event.get('message_id'))]
        if len(matches) != 1:
            raise ValueError('demo_binding_message_unverified')
        row = matches[0]
        sender = row.get('sender') if isinstance(row.get('sender'), dict) else {}
        if (row.get('message_type') not in (0, 'incoming') or row.get('private') is not False
                or str(row.get('conversation_id')) != scope.conversation_id
                or identifier(sender.get('id')) != scope.contact_id
                or not same_phone(sender.get('phone_number'), scope.phone)
                or row.get('content') != event.get('text')
                or type(row.get('created_at')) not in (int, float)
                or not abs(row['created_at'] - clock(event.get('created_at')).timestamp()) <= 1):
            raise ValueError('demo_binding_message_unverified')
        return True

    def send(self, scope, payload, key):
        if scope != self.scope:
            raise ValueError('demo_egress_scope_mismatch')
        if payload != self.expected_payload(key):
            raise ValueError('demo_payload_not_approved')
        preflight = self.preflight(scope)  # Identity/window rechecked directly before POST.
        if key.startswith(('bia-demo-followup:', 'bia-demo-close:')):
            if not callable(getattr(self, 'followup_current', None)) or not self.followup_current(key, preflight):
                raise ValueError('demo_followup_source_changed')
            self.inactivity_human_guard(scope)
        result = self._api(scope, 'POST', '/messages', payload)
        if (not identifier(result.get('id')) or (result.get('conversation_id') is not None
                                               and str(result['conversation_id']) != scope.conversation_id)):
            raise ValueError('demo_delivery_unconfirmed')
        return {'status': 'accepted', 'message_id': str(result['id']), 'external_id': result.get('source_id')}

    def inactivity_human_guard(self, scope):
        detail = self._api(scope, 'GET')
        if (detail.get('status') != 'open' or (detail.get('meta') or {}).get('assignee')
                or (detail.get('custom_attributes') or {}).get('human_control')):
            raise ValueError('demo_human_or_closed')

    def resolve_inactivity(self, scope, key):
        if not key.startswith('bia-demo-close:'):
            raise ValueError('demo_closure_key_required')
        preflight = self.preflight(scope)
        if not callable(getattr(self, 'followup_current', None)) or not self.followup_current(key, preflight):
            raise ValueError('demo_closure_source_changed')
        self.inactivity_human_guard(scope)
        result = self._api(scope, 'POST', '/toggle_status', {'status': 'resolved'})
        # Chatwoot's accounts API wraps its receipt and uses current_status,
        # not the conversation detail's top-level status field.
        if isinstance(result, dict) and 'payload' in result:
            receipt = result['payload']
            confirmed = (isinstance(receipt, dict) and receipt.get('success') is True
                         and identifier(receipt.get('conversation_id')) == scope.conversation_id
                         and receipt.get('current_status') == 'resolved')
        else:
            # Retain compatibility with the previously supported flat adapter.
            confirmed = (isinstance(result, dict) and result.get('status') == 'resolved'
                         and (result.get('conversation_id') is None
                              or identifier(result['conversation_id']) == scope.conversation_id))
        if not confirmed:
            raise ValueError('demo_resolution_unconfirmed')
        return {'status': 'resolved'}

    def verify_resolution(self, scope, message_id, payload):
        """Read-only evidence for an already attempted close; never retry it.

        A closed conversation is not sufficient on its own: prove the complete
        recipient and the previously acknowledged closing message as well.
        An expired reply window does not prevent reading a historical receipt.
        """
        from demo_followup import approved_closure_receipt
        if not identifier(message_id) or not approved_closure_receipt(payload):
            raise ValueError('demo_resolution_proof_invalid')

        def resolved_identity(detail):
            sender = (detail.get('meta') or {}).get('sender') or {}
            return (str(detail.get('id')) == scope.conversation_id
                    and str(detail.get('account_id')) == scope.account_id
                    and str(detail.get('inbox_id')) == scope.inbox_id
                    and str(sender.get('id')) == scope.contact_id
                    and same_phone(scope.phone, sender.get('phone_number'))
                    and detail.get('status') == 'resolved')

        if not resolved_identity(self._api(scope, 'GET')):
            return False
        rows = self._api(scope, 'GET', '/messages').get('payload')
        if not isinstance(rows, list):
            return False
        matches = [row for row in rows if isinstance(row, dict) and identifier(row.get('id')) == message_id]
        if len(matches) != 1:
            return False
        row = matches[0]
        if (row.get('message_type') not in (1, 'outgoing') or row.get('private') is not False
                or str(row.get('conversation_id')) != scope.conversation_id
                or row.get('content') != payload['content'] or row.get('content_type') != payload['content_type']
                or any(row.get(name) is not None and str(row[name]) != getattr(scope, name)
                       for name in ('account_id', 'inbox_id'))):
            return False
        # Do not release the fence if it reopened or changed owner during reads.
        return resolved_identity(self._api(scope, 'GET'))

    def expected_payload(self, key):
        if key.startswith(('bia-demo-followup:', 'bia-demo-close:')) and callable(getattr(self, 'followup_payload', None)):
            return self.followup_payload(key)
        if key.startswith('bia-demo:v2:') and demo_flow.key_parts(key)[1] == 'faq_context':
            if self.continuation_enabled is not True or not callable(self.context_payload):
                raise ValueError('demo_context_payload_unavailable')
            return self.context_payload(key)
        return message_payload(key, continuation_enabled=self.continuation_enabled)

    def lookup(self, scope, key):
        # Reconcile exactly what was already attempted, even if menu copy changed
        # in a later deploy. This is read-only and never authorizes a new send.
        expected = (self.context_payload(key) if key.startswith('bia-demo:v2:')
                    and self.continuation_enabled is True and callable(self.context_payload)
                    else self.expected_payload(key))
        rows = self._api(scope, 'GET', '/messages').get('payload') or []
        matches = [m for m in rows if m.get('content') == expected['content']
                   and m.get('message_type') in (1, 'outgoing') and m.get('private') is False
                   and m.get('content_type') == expected['content_type']
                   and (m.get('content_attributes') or {}).get('items') == (expected.get('content_attributes') or {}).get('items')
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
        scopes = self.scope.scopes if isinstance(self.scope, DemoScopes) else (self.scope,)
        for scope in scopes:
            for key in scope.conversation_keys:
                _, account, conversation = key.split(':')
                prefix = '/api/v1/accounts/' + account + '/conversations/' + conversation
                if path == prefix or path.startswith(prefix + '/'):
                    raise ValueError('demo_contact_excluded_from_production')
        return self.delegate.http(method=method, url=url, **kwargs)


class DemoRouter:
    def __init__(self, scope, store, gateway=None, *, now=clock, continuation_enabled=False, question_answerer=None, followup_enabled=False):
        self.followup_enabled = followup_enabled is True
        self.scope, self.store = scope, store
        self.gateway, self.now = gateway or RecordingGateway(), now
        self.continuation_enabled = continuation_enabled is True
        self.effects = SimulatedEffects()
        self.question_answerer = question_answerer

    def claims(self, event):
        return self.scope.claims(event)

    def select(self, scope=None):
        if scope is None:
            return self
        if not isinstance(scope, dict) or scope != self.scope.__dict__:
            raise ValueError('demo_control_scope_invalid')
        return self

    def start(self, request_id):
        return self._start(request_id)

    def _start(self, request_id, *, reset_event=None):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_id):
            raise ValueError('demo_start_request_id_required')
        owner = getattr(self, 'contact_owner', None)
        with owner.guard() if owner is not None else self.store.lock:
            previous = self.store.db.execute('SELECT result FROM demo_starts WHERE slot=? AND request_id=?',
                                             (self.scope.slot, request_id)).fetchone()
            if previous:
                return json.loads(previous['result'])
            if owner is not None and owner.effects_blocked(self.scope):
                return {'status': 'demo_delivery_unconfirmed', 'repeat_allowed': False}
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
            pending = self.store.db.execute('SELECT receipt FROM demo_outbox WHERE key=? AND slot=?', (key, self.scope.slot)).fetchone()
            if pending is None:
                raise ValueError('demo_outbox_scope_mismatch')
            metadata = json.loads(pending['receipt']) if pending and pending['receipt'] else {}
            self.store.db.execute('UPDATE demo_outbox SET status=?,receipt=? WHERE key=? AND slot=?',
                                  ('accepted', json.dumps({**receipt, 'grounded': metadata.get('grounded'),
                                                         'resume_step': metadata.get('resume_step'),
                                                         'last_question': metadata.get('last_question')}), key, self.scope.slot))
            if flow:
                self.store.db.execute("UPDATE demo_runs SET parent_id=?,parent_external=?,"
                                      "step=CASE WHEN step='delivery_pending' THEN ? ELSE step END WHERE slot=? AND outbox_key=?",
                                      (str(receipt['message_id']), receipt.get('external_id'), step, self.scope.slot, key))
            else:
                self.store.db.execute('UPDATE demo_runs SET parent_id=?,parent_external=? WHERE slot=? AND outbox_key=?',
                                      (str(receipt['message_id']), receipt.get('external_id'), self.scope.slot, key))
            if step == 'opening' and not metadata.get('pending_event_key'):
                self.store.db.execute('UPDATE demo_starts SET result=? WHERE slot=? AND run=(SELECT run FROM demo_outbox WHERE key=? AND slot=?)',
                                      (json.dumps(result), self.scope.slot, key, self.scope.slot))
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
        if self.followup_enabled and self.continuation_enabled:
            from demo_followup import arm
            arm(self, key)
        return result

    def _dialogue_context(self, state, step, resume_step):
        """Rebuild bounded dialogue from confirmed outbox rows in this run only.

        No model-produced summary, profile input, pending output, or simulated
        effect is promoted into a business fact or consent.
        """
        rows = self.store.db.execute(
            "SELECT key,payload,receipt FROM demo_outbox WHERE slot=? AND run=? "
            "AND status='accepted' AND rowid <= "
            "(SELECT rowid FROM demo_outbox WHERE key=? AND slot=? AND run=?) "
            "ORDER BY rowid DESC LIMIT 24",
            (self.scope.slot, state['run'], state['outbox_key'], self.scope.slot, state['run'])).fetchall()
        recent = []
        pending, last_question, last_answer = '', '', ''
        for row in rows:
            metadata = json.loads(row['receipt']) if row['receipt'] else {}
            question = demo_flow.safe_context_text(metadata.get('last_question'), 500)
            answer = demo_flow.safe_context_text(json.loads(row['payload']).get('content'), 900)
            if row['key'] == state['outbox_key']:
                last_question, last_answer = question, answer
                grounded = metadata.get('grounded')
                if isinstance(grounded, dict) and grounded.get('evidence') and grounded.get('knowledge_version'):
                    clarification = grounded.get('clarification_question')
                    original = grounded.get('answer')
                    from demo_support import clarification_question
                    if (isinstance(clarification, str) and clarification.strip().endswith('?')
                            and isinstance(original, str) and clarification_question(original) == clarification.strip()):
                        pending = demo_flow.safe_context_text(clarification.strip(), 500)
            if question and len(recent) < 6:
                recent.append({'question': question, 'answer': answer})
        recent.reverse()
        return {'current_step': step, 'return_step': resume_step,
                'last_question': last_question, 'last_answer': last_answer,
                'recent_dialogue': recent,
                'prior_questions': list(dict.fromkeys(item['question'] for item in recent)),
                'pending_clarification': pending,
                'operational_facts': {'real_profile_checked': False, 'real_invite_sent': False,
                                      'real_relationship_created': False, 'commercial_consent': False}}

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
                previous = self.store.db.execute('SELECT receipt,payload FROM demo_outbox WHERE key=? AND slot=?',
                                                 (state['outbox_key'], self.scope.slot)).fetchone()
                if previous is None:
                    raise ValueError('demo_outbox_scope_mismatch')
                metadata = json.loads(previous['receipt']) if previous and previous['receipt'] else {}
                resume_step = metadata.get('resume_step') if step in demo_flow.KNOWLEDGE_STEPS else step
                if resume_step not in demo_flow.RETURN_STEPS:
                    resume_step = 'opening'
                last_question = demo_flow.safe_context_text(metadata.get('last_question'), 500)
                if not last_question and step == 'faq_unavailable' and state['choice'] == 'faq_benefits':
                    # Compatibility with an already presented failure from the old
                    # benefits button, whose exact menu question was not persisted.
                    last_question = demo_flow.TEMPLATES['about'][1]['faq_benefits']
                dialogue = self._dialogue_context(state, step, resume_step)
                question_answerer = self.question_answerer
                if getattr(question_answerer, 'accepts_dialogue_context', False) is True:
                    question_answerer = lambda question: self.question_answerer(question, conversation=dialogue)
                previous_payload = json.loads(previous['payload'])
                decision = demo_flow.decision(step, event.get('text'), correlated=correlated, opening_choices=CHOICES,
                                              question_answerer=question_answerer, resume_step=resume_step,
                                              last_question=last_question, pending_clarification=dialogue['pending_clarification'],
                                              current_choices=demo_flow.presented_choices(state['outbox_key'], previous_payload))
                if decision and decision.get('no_op') is True:
                    result = {'accepted': True, 'status': 'demo_acknowledged', 'step': step,
                              'production_effects': False}
                    self.store.db.execute('INSERT INTO demo_events VALUES(?,?,?,?)',
                                          (self.scope.slot, event_key, fingerprint, json.dumps(result)))
                    return result, 202
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
                                                           'resume_step': resume_step if decision['step'] in demo_flow.KNOWLEDGE_STEPS else decision['step'],
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
            row = self.store.db.execute('SELECT * FROM demo_outbox WHERE key=? AND slot=?',
                                        (state['outbox_key'], self.scope.slot)).fetchone()
            if row is None:
                raise ValueError('demo_outbox_scope_mismatch')
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
        if self.followup_enabled:
            from demo_followup import cancel_for_inbound
            cancel_for_inbound(self, event)
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

    def handle_verified_webhook(self, event):
        # The authenticated webhook alone may start a never-started static demo.
        # Existing sessions (including closed/expired/pending) keep their state.
        # Reset owns freshness, idempotency and durable unknown-send fencing.
        if not self.claims(event):
            raise ValueError('demo_event_outside_scope')
        if not self.scope.accepts(event):
            return {'accepted': False, 'status': 'demo_identity_rejected'}, 202
        with self.store.lock:
            if self.store.current(self.scope.slot) is None:
                return self._handle_reset(event, inbound_key(event), digest(event))
            return self.handle(event)

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


def configure_context_payload(gateway, store, scope):
    if isinstance(gateway, DemoWhatsAppGateway):
        def persisted_context_payload(key):
            with store.lock:
                row = store.db.execute('SELECT payload FROM demo_outbox WHERE key=? AND slot=?',
                                       (key, scope.slot)).fetchone()
            if row is None:
                raise ValueError('demo_context_payload_not_persisted')
            return json.loads(row['payload'])
        gateway.context_payload = persisted_context_payload
        def persisted_followup_payload(key):
            from demo_followup import persisted_payload
            return persisted_payload(store, scope, key)
        gateway.followup_payload = persisted_followup_payload
        def followup_current(key, preflight):
            from demo_followup import source_current
            return source_current(store, scope, key, preflight)
        gateway.followup_current = followup_current



class DemoPendingRouter:
    """Only an authenticated, provider-verified fresh webhook can bind once."""
    def __init__(self, reservation, store, existing_scopes, gateway_factory, *,
                 continuation_enabled=False, question_answerer=None, now=clock, followup_enabled=False,
                 conversation_rollover_enabled=False):
        self.followup_enabled = followup_enabled is True
        self.scope, self.store, self.existing_scopes = reservation, store, tuple(existing_scopes)
        self.gateway_factory = gateway_factory
        self.continuation_enabled, self.question_answerer = continuation_enabled, question_answerer
        self.now, self.router, self.binding = now, None, None
        self.binding_failed = False
        self.conversation_rollover_enabled = conversation_rollover_enabled is True
        self._load_binding()

    def _load_binding(self):
        marker = self.store.db.execute('SELECT result FROM demo_starts WHERE slot=? AND request_id=?',
                                      ('binding:' + self.scope.slot, 'verified-scope-v1')).fetchone()
        if marker is not None:
            row = json.loads(marker['result'])
            if (not isinstance(row, dict) or set(row) != {'reservation', 'scope_json', 'first_event_key', 'first_event_digest'}
                    or row['reservation'] != self.scope.slot):
                raise ValueError('demo_binding_state_invalid')
            scope = DemoScope(**json.loads(row['scope_json']))
            self._check_candidate(scope)
            if (not re.fullmatch(r'chatwoot:' + scope.account_id + r':[1-9][0-9]{0,19}', row['first_event_key'])
                    or not re.fullmatch(r'[a-f0-9]{64}', row['first_event_digest'])):
                raise ValueError('demo_binding_state_invalid')
            self.scope.bound_scope = scope
            self.binding = dict(row)
            self.router = self._router(scope)
            self.scope.bound_scope = self.router.scope
            return True
        return False

    def _check_candidate(self, scope):
        if ((scope.account_id, scope.inbox_id) != (self.scope.account_id, self.scope.inbox_id)
                or normalize_phone(scope.phone) != normalize_phone(self.scope.phone)):
            raise ValueError('demo_binding_identity_invalid')
        DemoScopes(self.existing_scopes + (scope,))

    def _router(self, scope, gateway=None):
        gateway = self.gateway_factory(scope) if gateway is None else gateway
        configure_context_payload(gateway, self.store, scope)
        router = DemoRouter(scope, self.store, gateway, now=lambda: self.now(),
                          continuation_enabled=self.continuation_enabled, question_answerer=self.question_answerer,
                          followup_enabled=self.followup_enabled)
        has_bindings = self.store.db.execute('SELECT 1 FROM demo_conversation_bindings WHERE owner_slot=? LIMIT 1',
                                             (scope.slot,)).fetchone()
        if self.conversation_rollover_enabled or has_bindings:
            router = DemoConversationRouter(router, self.gateway_factory, enabled=self.conversation_rollover_enabled)
            router.other_scopes = self.existing_scopes
        return router

    def claims(self, event):
        return self.scope.claims(event)

    def select(self, scope=None):
        if self.router is None or self.binding_failed:
            raise ValueError('demo_binding_required')
        return self.router.select(scope)

    def handle(self, event):
        if not self.claims(event):
            raise ValueError('demo_event_outside_scope')
        if self.binding_failed or self.router is None:
            return {'accepted': False, 'status': 'demo_identity_pending', 'production_effects': False}, 202
        return self.router.handle(event)

    def handle_verified_webhook(self, event):
        with self.store.lock:
            if not self.claims(event):
                raise ValueError('demo_event_outside_scope')
            if self.binding_failed:
                return {'accepted': False, 'status': 'demo_binding_unavailable', 'production_effects': False}, 202
            if self.router is None:
                try:
                    scope = DemoScope(self.scope.account_id, self.scope.inbox_id,
                                      identifier(event.get('contact_id')), identifier(event.get('conversation_id')),
                                      self.scope.phone)
                    self._check_candidate(scope)
                    if not scope.accepts(event):
                        raise ValueError('demo_binding_identity_invalid')
                    if not isinstance(event.get('created_at'), str):
                        raise ValueError('demo_binding_timestamp_invalid')
                    if not clock(self.now()) - timedelta(minutes=5) <= clock(event['created_at']) <= clock(self.now()) + timedelta(seconds=30):
                        raise ValueError('demo_binding_timestamp_invalid')
                    gateway = self.gateway_factory(scope)
                    # An offline recording gateway has no authority to establish identity.
                    if not isinstance(gateway, DemoWhatsAppGateway) or gateway.verify_inbound(scope, event) is not True:
                        raise ValueError('demo_binding_verifier_required')
                except Exception:
                    return {'accepted': False, 'status': 'demo_binding_unverified', 'production_effects': False}, 202
                binding = {'reservation': self.scope.slot, 'scope_json': json.dumps(scope.__dict__, sort_keys=True),
                           'first_event_key': inbound_key(event), 'first_event_digest': digest(event)}
                # Publish the verified reservation first. If persistence fails, keep
                # all discovered identities reserved, but never acquire send authority.
                self.scope.bound_scope = scope
                try:
                    with self.store.transaction():
                        self.store.db.execute('INSERT INTO demo_starts VALUES(?,?,?,?)',
                            ('binding:' + self.scope.slot, 'verified-scope-v1', 'binding-v1', json.dumps(binding)))
                    self.binding = binding
                    self.router = self._router(scope, gateway)
                    self.scope.bound_scope = self.router.scope
                except sqlite3.IntegrityError:
                    # An overlapping process may have already committed the only
                    # binding. Read that authority; never overwrite or rebind it.
                    try:
                        if not self._load_binding():
                            raise ValueError('demo_binding_not_persisted')
                    except Exception:
                        self.binding_failed = True
                        return {'accepted': False, 'status': 'demo_binding_unavailable', 'production_effects': False}, 202
                except Exception:
                    self.binding_failed = True
                    return {'accepted': False, 'status': 'demo_binding_unavailable', 'production_effects': False}, 202
            if isinstance(self.router, DemoConversationRouter):
                # The initial phone binding remains immutable. Only its now
                # proven contact may acquire independently verified conversations.
                if inbound_key(event) == self.binding['first_event_key'] and digest(event) != self.binding['first_event_digest']:
                    return {'accepted': False, 'status': 'demo_conflicting_duplicate'}, 202
                return self.router.handle_verified_webhook(event)
            if not self.router.scope.accepts(event):
                return {'accepted': False, 'status': 'demo_identity_rejected'}, 202
            if inbound_key(event) == self.binding['first_event_key']:
                if digest(event) != self.binding['first_event_digest']:
                    return {'accepted': False, 'status': 'demo_conflicting_duplicate'}, 202
                # Freshness, durable dedup and unknown-send fences are identical to
                # Resetar. This is only a response to the first verified inbound.
                return self.router._handle_reset(event, inbound_key(event), digest(event))
            return self.router.handle(event)


class DemoConversationRouter:
    """Opt-in, durable admission of fresh conversations for one approved person.

    The webhook cannot change the person's identity. It supplies only a candidate
    conversation ID, which a scoped read-only Chatwoot proof must corroborate.
    Controls and catch-up cannot establish a binding. Old slots are never moved
    or deleted, and an uncertain send is not bypassed by changing conversations.
    """
    MAX_CONVERSATIONS = 100

    def __init__(self, original, gateway_factory, *, enabled=False):
        self.original, self.store = original, original.store
        self.scope = DemoContactReservation(original.scope, original.store)
        self.gateway_factory, self.enabled = gateway_factory, enabled is True
        self.now = original.now
        original.now = lambda: self.now()
        self.question_answerer = original.question_answerer
        self.routers = {original.scope.conversation_id: original}
        self.bindings = {}
        self.other_scopes = ()
        self.binding_failed = False
        original.contact_owner = self
        self._load_bindings()

    def _candidate(self, conversation_id):
        original = self.scope.original
        return DemoScope(original.account_id, original.inbox_id, original.contact_id,
                         identifier(conversation_id), original.phone)

    def _router(self, scope, gateway=None):
        gateway = self.gateway_factory(scope) if gateway is None else gateway
        if not isinstance(gateway, DemoWhatsAppGateway) or gateway.scope != scope:
            raise ValueError('demo_binding_verifier_required')
        configure_context_payload(gateway, self.store, scope)
        router = DemoRouter(scope, self.store, gateway, now=lambda: self.now(),
            continuation_enabled=self.original.continuation_enabled,
            question_answerer=self.question_answerer, followup_enabled=self.original.followup_enabled)
        router.contact_owner = self
        return router

    def _load_bindings(self):
        rows = self.store.db.execute(
            'SELECT * FROM demo_conversation_bindings WHERE owner_slot=? ORDER BY rowid LIMIT ?',
            (self.scope.slot, self.MAX_CONVERSATIONS + 1)).fetchall()
        if len(rows) >= self.MAX_CONVERSATIONS:
            raise ValueError('demo_conversation_bindings_limit')
        for row in rows:
            scope = self._candidate(row['conversation_id'])
            if (scope == self.scope.original or row['conversation_key'] != scope.conversation_key
                    or not re.fullmatch(r'chatwoot:' + scope.account_id + r':[1-9][0-9]{0,19}', row['first_event_key'])
                    or not re.fullmatch(r'[a-f0-9]{64}', row['first_event_digest'])):
                raise ValueError('demo_conversation_binding_invalid')
            clock(row['verified_at'])
            self.bindings[scope.conversation_id] = dict(row)
            self.scope.reserve(scope)
            if scope.conversation_id not in self.routers:
                self.routers[scope.conversation_id] = self._router(scope)

    @contextmanager
    def guard(self):
        with self.store.owner_lock(self.scope.slot):
            # Another process may have verified a conversation since startup.
            self._load_bindings()
            yield

    def effects_blocked(self, target):
        for scope in self.scope.scopes:
            if scope == target:
                continue
            for table, statuses in (
                    ('demo_outbox', ('outcome_unknown',)),
                    ('demo_followups', ('outcome_unknown',)),
                    ('demo_closures', ('notice_unknown', 'resolve_unknown'))):
                query = 'SELECT 1 FROM ' + table + ' WHERE slot=? AND status IN (' + ','.join('?' for _ in statuses) + ') LIMIT 1'
                if self.store.db.execute(query, (scope.slot, *statuses)).fetchone():
                    return True
        return False

    def reconcile_resolution_blockers(self, target):
        from demo_followup import reconcile_resolutions
        for router in tuple(self.routers.values()):
            if router.scope != target and self.store.db.execute(
                    "SELECT 1 FROM demo_closures WHERE slot=? AND status='resolve_unknown' LIMIT 1",
                    (router.scope.slot,)).fetchone():
                reconcile_resolutions(router)
                break  # At most one historical receipt/readback per fresh inbound.

    def claims(self, event):
        return self.scope.claims(event)

    decorate = staticmethod(DemoRouter.decorate)

    def select(self, scope=None):
        if self.binding_failed:
            raise ValueError('demo_binding_unavailable')
        if scope is None:
            return self.original  # Preserve the established control destination.
        for router in self.routers.values():
            if scope == router.scope.__dict__:
                return router
        raise ValueError('demo_control_scope_invalid')

    def start(self, request_id):
        return self.select().start(request_id)

    def reconcile(self):
        return self.select().reconcile()

    def stop(self):
        return self.select().stop()

    def simulate(self, operation, fixture='unknown'):
        return self.select().simulate(operation, fixture)

    def _target(self, event):
        router = self.routers.get(identifier(event.get('conversation_id')))
        return router if router and router.scope.accepts(event) else None

    def conflicting_proof(self, event):
        return any(row['first_event_key'] == inbound_key(event)
                   and row['first_event_digest'] != digest(event) for row in self.bindings.values())

    def fresh_webhook(self, event):
        try:
            return (isinstance(event.get('created_at'), str)
                    and clock(self.now()) - timedelta(minutes=5) <= clock(event['created_at']) <= clock(self.now()) + timedelta(seconds=30))
        except (ValueError, TypeError, OverflowError):
            return False

    def handle(self, event):
        if not self.claims(event):
            raise ValueError('demo_event_outside_scope')
        with self.guard():
            target = self._target(event)
            if self.conflicting_proof(event):
                return {'accepted': False, 'status': 'demo_conflicting_duplicate', 'production_effects': False}, 202
            if self.binding_failed or target is None:
                return {'accepted': False, 'status': 'demo_identity_rejected', 'production_effects': False}, 202
            if self.effects_blocked(target.scope):
                return {'accepted': False, 'status': 'demo_delivery_unconfirmed', 'repeat_allowed': False, 'production_effects': False}, 202
            return target.handle(event)

    def handle_verified_webhook(self, event):
        with self.guard():
            if not self.claims(event):
                raise ValueError('demo_event_outside_scope')
            if self.binding_failed:
                return {'accepted': False, 'status': 'demo_binding_unavailable', 'production_effects': False}, 202
            if self.conflicting_proof(event):
                return {'accepted': False, 'status': 'demo_conflicting_duplicate', 'production_effects': False}, 202
            target = self._target(event)
            if target is not None:
                if self.effects_blocked(target.scope) and self.fresh_webhook(event):
                    self.reconcile_resolution_blockers(target.scope)
                if self.effects_blocked(target.scope):
                    return {'accepted': False, 'status': 'demo_delivery_unconfirmed', 'repeat_allowed': False, 'production_effects': False}, 202
                return target.handle_verified_webhook(event)
            if not self.enabled:
                return {'accepted': False, 'status': 'demo_identity_rejected', 'production_effects': False}, 202
            try:
                scope = self._candidate(event.get('conversation_id'))
                if (not scope.accepts(event) or scope.conversation_id in self.routers
                        or any(other.claims(event) or scope.conversation_key in other.conversation_keys
                               for other in self.other_scopes)
                        or not self.fresh_webhook(event)):
                    raise ValueError('demo_binding_identity_invalid')
                if len(self.scope.scopes) >= self.MAX_CONVERSATIONS:
                    raise ValueError('demo_conversation_bindings_limit')
                if self.effects_blocked(scope):
                    # Only a fresh, fully matching authenticated webhook may
                    # trigger this bounded read-only provider reconciliation.
                    # It never resends a notice or repeats toggle_status.
                    self.reconcile_resolution_blockers(scope)
                if self.effects_blocked(scope):
                    return {'accepted': False, 'status': 'demo_delivery_unconfirmed',
                            'repeat_allowed': False, 'production_effects': False}, 202
                gateway = self.gateway_factory(scope)
                if (not isinstance(gateway, DemoWhatsAppGateway) or gateway.scope != scope
                        or gateway.verify_inbound(scope, event) is not True):
                    raise ValueError('demo_binding_verifier_required')
            except Exception:
                return {'accepted': False, 'status': 'demo_binding_unverified', 'production_effects': False}, 202
            # Reserve the verified ID even if a write fails, so no production
            # queue or low-level HTTP path gains access during uncertainty.
            self.scope.reserve(scope)
            try:
                with self.store.transaction():
                    self.store.db.execute('INSERT INTO demo_conversation_bindings VALUES(?,?,?,?,?,?)',
                        (self.scope.slot, scope.conversation_id, scope.conversation_key,
                         inbound_key(event), digest(event), clock(self.now()).isoformat()))
                    # A new conversation must not revive reminders in an older one.
                    # Keep the rows as history; do not cancel uncertain effects.
                    for existing in self.scope.scopes:
                        if existing != scope:
                            for table in ('demo_followups', 'demo_closures'):
                                self.store.db.execute('UPDATE ' + table + " SET status='cancelled' WHERE slot=? AND status='pending'",
                                                      (existing.slot,))
                self.routers[scope.conversation_id] = self._router(scope, gateway)
                self._load_bindings()
            except sqlite3.IntegrityError:
                # A concurrent process may have won. Only its committed proof
                # authorizes a send; conflicting replay cannot replace it.
                row = self.store.db.execute(
                    'SELECT * FROM demo_conversation_bindings WHERE owner_slot=? AND conversation_id=?',
                    (self.scope.slot, scope.conversation_id)).fetchone()
                if row is None:
                    self.binding_failed = True
                    return {'accepted': False, 'status': 'demo_binding_unavailable', 'production_effects': False}, 202
                if row['first_event_key'] == inbound_key(event) and row['first_event_digest'] != digest(event):
                    return {'accepted': False, 'status': 'demo_conflicting_duplicate', 'production_effects': False}, 202
                self._load_bindings()
            except Exception:
                self.binding_failed = True
                return {'accepted': False, 'status': 'demo_binding_unavailable', 'production_effects': False}, 202
            return self.routers[scope.conversation_id].handle_verified_webhook(event)


class DemoMultiplexer:
    """Dispatch full identities to independent routers; never broadcast controls."""
    def __init__(self, routers):
        self.routers = tuple(routers)
        self.scope = DemoScopes(tuple(router.scope for router in self.routers))
        if any(router.store is not self.routers[0].store for router in self.routers):
            raise ValueError('demo_multiplexer_store_mismatch')
        self.store = self.routers[0].store

    def claims(self, event):
        return self.scope.claims(event)

    decorate = staticmethod(DemoRouter.decorate)

    def select(self, scope=None):
        # Old control requests continue to address only the original contact.
        if scope is None:
            return self.routers[0]
        for router in self.routers:
            try:
                return router.select(scope)
            except ValueError:
                continue
        raise ValueError('demo_control_scope_invalid')

    def handle(self, event):
        if not self.claims(event):
            raise ValueError('demo_event_outside_scope')
        matches = [router for router in self.routers if router.scope.accepts(event)]
        if len(matches) != 1:
            return {'accepted': False, 'status': 'demo_identity_rejected'}, 202
        return matches[0].handle(event)

    def handle_verified_webhook(self, event):
        renewing = [router for router in self.routers
                    if isinstance(router, DemoConversationRouter) and router.claims(event)]
        if renewing:
            # Partial matches from two people never choose or bind a recipient.
            claims = [router for router in self.routers if router.claims(event)]
            if len(claims) != 1:
                return {'accepted': False, 'status': 'demo_identity_rejected'}, 202
            return renewing[0].handle_verified_webhook(event)
        pending = [router for router in self.routers
                   if isinstance(router, DemoPendingRouter) and router.claims(event)]
        if len(pending) == 1:
            return pending[0].handle_verified_webhook(event)
        if not self.claims(event):
            raise ValueError('demo_event_outside_scope')
        matches = [router for router in self.routers if router.scope.accepts(event)]
        if len(matches) != 1:
            return {'accepted': False, 'status': 'demo_identity_rejected'}, 202
        return matches[0].handle_verified_webhook(event)

    def start(self, request_id):
        return self.select().start(request_id)

    def reconcile(self):
        return self.select().reconcile()

    def stop(self):
        return self.select().stop()

    def simulate(self, operation, fixture='unknown'):
        return self.select().simulate(operation, fixture)


def build_demo_router(settings, *, gateway=None, production_path=None, pending_gateway_factory=None,
                      conversation_gateway_factory=None):
    if not isinstance(settings, dict):
        return None
    if settings.get('demo_enabled') is not True:
        if ('demo_scopes' in settings or 'demo_pending_scope' in settings
                or settings.get('demo_conversation_rollover_enabled') is True):
            raise ValueError('demo_reservations_require_enabled_router')
        return None
    scopes = configured_scopes(settings)
    pending = configured_pending_scope(settings, scopes)
    path = settings.get('demo_state_path')
    if not isinstance(path, str) or not path:
        raise ValueError('demo_state_path_required')
    if path == ':memory:' and settings.get('demo_whatsapp_live') is True:
        raise ValueError('demo_live_delivery_requires_durable_state')
    production_path = production_path or Path(settings.get('state_dir', '/data')) / 'atendimento.sqlite3'
    if gateway is not None and len(scopes) > 1 and not isinstance(gateway, dict):
        raise ValueError('demo_scopes_require_separate_gateways')
    if isinstance(gateway, dict) and set(gateway) != {scope.slot for scope in scopes}:
        raise ValueError('demo_gateway_scopes_mismatch')
    gateways = []
    for scope in scopes:
        scoped_gateway = gateway.get(scope.slot) if isinstance(gateway, dict) else gateway
        if scoped_gateway is None:
            scoped_gateway = (DemoWhatsAppGateway(settings.get('chatwoot_base_url', ''), settings.get('chatwoot_api_token', ''),
                              scope=scope, live_enabled=True,
                              continuation_enabled=settings.get('demo_continuation_enabled') is True)
                              if settings.get('demo_whatsapp_live') is True else RecordingGateway())
        if isinstance(scoped_gateway, DemoWhatsAppGateway) and scoped_gateway.scope != scope:
            raise ValueError('demo_egress_scope_mismatch')
        gateways.append(scoped_gateway)
    if len({id(item) for item in gateways}) != len(gateways):
        raise ValueError('demo_scopes_require_separate_gateways')
    store = DemoStore(path, production_path=production_path)
    try:
        from demo_answers import build_answerer, schedule_smoke_check
        routers = []
        for scope, scoped_gateway in zip(scopes, gateways):
            configure_context_payload(scoped_gateway, store, scope)
            child = DemoRouter(scope, store, scoped_gateway,
                continuation_enabled=settings.get('demo_continuation_enabled') is True,
                question_answerer=build_answerer(settings),
                followup_enabled=settings.get('demo_followup_enabled') is True)
            # Persisted exclusions survive turning admission off. Never discard
            # previously verified history or let those conversations reach production.
            has_bindings = store.db.execute('SELECT 1 FROM demo_conversation_bindings WHERE owner_slot=? LIMIT 1',
                                             (scope.slot,)).fetchone()
            if settings.get('demo_conversation_rollover_enabled') is True or has_bindings:
                if conversation_gateway_factory is None:
                    def conversation_gateway_factory(candidate):
                        return DemoWhatsAppGateway(settings.get('chatwoot_base_url', ''), settings.get('chatwoot_api_token', ''),
                            scope=candidate, live_enabled=settings.get('demo_whatsapp_live') is True,
                            continuation_enabled=settings.get('demo_continuation_enabled') is True)
                child = DemoConversationRouter(child, conversation_gateway_factory,
                    enabled=settings.get('demo_conversation_rollover_enabled') is True)
            routers.append(child)
        if pending is not None:
            if pending_gateway_factory is None:
                def pending_gateway_factory(scope):
                    return DemoWhatsAppGateway(settings.get('chatwoot_base_url', ''), settings.get('chatwoot_api_token', ''),
                        scope=scope, live_enabled=settings.get('demo_whatsapp_live') is True,
                        continuation_enabled=settings.get('demo_continuation_enabled') is True)
            routers.append(DemoPendingRouter(pending, store, tuple(child.scope for child in routers), pending_gateway_factory,
                continuation_enabled=settings.get('demo_continuation_enabled') is True,
                question_answerer=build_answerer(settings),
                followup_enabled=settings.get('demo_followup_enabled') is True,
                conversation_rollover_enabled=settings.get('demo_conversation_rollover_enabled') is True))
        for child in routers:
            if isinstance(child, DemoConversationRouter):
                child.other_scopes = tuple(other.scope for other in routers if other is not child)
        owners = {scope.slot for scope in scopes}
        owners.update(child.router.scope.slot for child in routers
                      if isinstance(child, DemoPendingRouter) and child.router is not None)
        persisted_owners = {row[0] for row in store.db.execute('SELECT DISTINCT owner_slot FROM demo_conversation_bindings')}
        if persisted_owners - owners:
            raise ValueError('demo_conversation_binding_owner_changed')
        router = routers[0] if len(routers) == 1 else DemoMultiplexer(routers)
        settings['_demo_scope'] = router.scope
        # The smoke test is configuration-wide, not one message per contact.
        # It gets no router, gateway, production store or effects adapter.
        schedule_smoke_check(settings, store, scopes[0].slot, routers[0].question_answerer)
        return router
    except Exception:
        store.close()
        raise
