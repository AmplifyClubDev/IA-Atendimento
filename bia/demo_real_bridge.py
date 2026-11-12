"""Opt-in real rehearsal: separate durable runtime, never a production-fence bypass."""
from __future__ import annotations
from datetime import timedelta
import json
from pathlib import Path
import re
import sqlite3
import threading

from contracts import normalize_phone
from demo_router import DemoScope, configured_scopes, clock, digest


def identity(scope):
    return digest([scope.account_id, scope.inbox_id, scope.contact_id, normalize_phone(scope.phone)])


def isolated_settings(settings, scopes):
    """The ordinary account-wide gate is never inherited by the rehearsal."""
    child = {key: value for key, value in settings.items() if not key.startswith('demo_') and key != '_demo_scope'}
    child.update(demo_enabled=False, demo_real_enabled=False,
        state_dir=str(Path(settings['state_dir']).resolve() / 'demo-real-test' / 'runtime'),
        followup_enabled=False, inactivity_close_enabled=False, retention_enabled=False,
        tiktok_require_explicit_consent=True,
        retomada_enabled=False, pos_pausa_enabled=False, reconferencia_enabled=False,
        initial_recheck_event_keys=[], initial_invite_recheck_event_keys=[])
    child['gate'] = {**settings['gate'], 'mode': 'lista', 'phone': scopes[0].phone,
                     'phones': [scope.phone for scope in scopes], 'inactivity_close_enabled': False}
    child['test_phone'] = scopes[0].phone
    child['pilot_scope'] = {name: getattr(scopes[0], name) for name in ('phone', 'contact_id', 'conversation_id')}
    return child


class DemoRealBridge:
    def __init__(self, settings, scopes, directory, *, runtime_factory=None):
        self.settings, self.scopes = settings, tuple(scopes)
        self.allowed = {identity(scope) for scope in scopes}
        self.lock = threading.RLock()
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'handoffs.sqlite3'
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS handoffs (owner TEXT PRIMARY KEY, scope_json TEXT NOT NULL, first_id TEXT NOT NULL, first_digest TEXT NOT NULL, opened_at TEXT NOT NULL)')
        self.path.chmod(0o600)
        # Removing a selected contact does not let a private historical run fall
        # back into the simulator; fail startup until the outstanding run is reviewed.
        if any(row['owner'] not in self.allowed for row in self.db.execute('SELECT owner FROM handoffs')):
            raise ValueError('demo_real_scope_has_active_history')
        self.runtime = (runtime_factory or self._runtime)(isolated_settings(settings, scopes))
        executor = self.runtime.extensions['v5_real_executor']
        original_guard = executor.guard
        executor.guard = lambda event: (original_guard(event) if self.authorized_event(event)
                                        else {'allowed': False, 'reason': 'real_test_scope_rejected'})

    @staticmethod
    def _runtime(settings):
        from server import create_app
        from gateway import Gateway
        from smtp import SmtpSender
        from forms import register_forms
        Path(settings['state_dir']).mkdir(parents=True, exist_ok=True)
        app = create_app(settings=settings)
        app.extensions['v5_data_gateway'] = Gateway(settings)
        app.extensions['v5_email_sender'] = SmtpSender(settings)
        register_forms(app, settings, app.extensions['v5_repository'])
        return app

    def status(self):
        state = self.runtime.extensions['v5_real_executor'].status()
        running = state.get('worker_running') is True
        sessions_ready = (state.get('sessions') or {}).get('ready') is True
        return {'enabled': True, 'selected_count': len(self.allowed),
                'worker_running': running, 'sessions_ready': sessions_ready,
                'ready': running and sessions_ready}

    def start(self):
        executor = self.runtime.extensions['v5_real_executor']
        executor.probe_sessions()
        if not executor.start():
            raise ValueError('demo_real_worker_not_started')

    def enrolled(self, scope):
        with self.lock:
            return self.db.execute('SELECT * FROM handoffs WHERE owner=?', (identity(scope),)).fetchone()

    def selected(self, scope):
        return identity(scope) in self.allowed

    def authorized_event(self, event):
        if not isinstance(event, dict):
            return False
        with self.lock:
            rows = self.db.execute('SELECT * FROM handoffs').fetchall()
        for row in rows:
            scope = DemoScope(**json.loads(row['scope_json']))
            if (identity(scope) in self.allowed and scope.accepts(event)
                    and str(event.get('message_id', '')).isdigit()
                    and int(event['message_id']) >= int(row['first_id'])):
                return True
        return False

    def dispatch(self, router, event, *, begin=False):
        # All ingress paths acquire the existing demo-store lock first. Registry
        # locking is short-lived and never held while calling providers/runtime.
        with router.store.lock:
            return self._dispatch_locked(router, event, begin=begin)

    def _dispatch_locked(self, router, event, *, begin=False):
        """Only the validated, fresh demo join decision may create a handoff."""
        scope = router.scope
        if not self.selected(scope):
            return None
        with self.lock:
            row = self.enrolled(scope)
            if row is None and not begin:
                return None
            failure = lambda reason: ({'accepted': False, 'status': 'demo_real_' + reason}, 202)
            if not scope.accepts(event):
                return failure('identity_rejected')
            try:
                stamp, now = clock(event['created_at']), clock(router.now())
                if not now - timedelta(minutes=5) <= stamp <= now + timedelta(seconds=30):
                    return failure('stale_event')
            except (KeyError, TypeError, ValueError):
                return failure('stale_event')
            if row is not None:
                if json.loads(row['scope_json']) != scope.__dict__:
                    return failure('previous_conversation_active')
                if int(event['message_id']) < int(row['first_id']):
                    return failure('stale_event')
                if (event['message_id'] == row['first_id'] and digest(event) != row['first_digest']):
                    return failure('conflicting_duplicate')
            else:
                for table, statuses in (('demo_outbox', ('outcome_unknown',)),
                                        ('demo_followups', ('outcome_unknown',)),
                                        ('demo_closures', ('notice_unknown', 'resolve_unknown'))):
                    if router.store.db.execute('SELECT 1 FROM ' + table + ' WHERE slot=? AND status IN ('
                            + ','.join('?' for _ in statuses) + ') LIMIT 1', (scope.slot, *statuses)).fetchone():
                        return failure('delivery_unconfirmed')
                # Persist before any external operation, so uncertain outcomes and
                # restarts cannot return this contact to simulated success.
                self.db.execute('INSERT INTO handoffs VALUES(?,?,?,?,?)',
                    (identity(scope), json.dumps(scope.__dict__, sort_keys=True), event['message_id'],
                     digest(event), stamp.isoformat()))
        with router.store.transaction():
            router.store.db.execute("UPDATE demo_followups SET status='cancelled' WHERE slot=? AND status='pending'", (scope.slot,))
            router.store.db.execute("UPDATE demo_closures SET status='cancelled' WHERE slot=? AND status='pending'", (scope.slot,))
        # No demo facts, simulated receipts or invented consent are copied.
        # The real journey obtains its own profile/consent and provider proofs.
        with self.runtime.app_context():
            body, code = self.runtime.extensions['v5_process_inbound'](dict(event))
        return {'accepted': body.get('accepted') is True, 'status': 'demo_real_active',
                'real_status': body.get('status'), 'production_effects': True}, code

    def owns_form(self, token):
        return bool(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token)
                    and self.runtime.extensions['v5_forms_store'].row(token))


def install(app, settings, *, runtime_factory=None, start=True):
    if settings.get('demo_real_enabled') is not True:
        # A rollback must never reclassify an uncertain real invitation as a
        # simulated journey. Fail closed until its durable history is reviewed.
        path = Path(settings.get('state_dir', '/data')) / 'demo-real-test' / 'handoffs.sqlite3'
        if path.exists():
            with sqlite3.connect('file:' + str(path.resolve()) + '?mode=ro', uri=True) as db:
                if db.execute('SELECT 1 FROM handoffs LIMIT 1').fetchone():
                    raise ValueError('demo_real_disabled_with_active_history')
        return None
    router = app.extensions.get('v5_demo_router')
    phone = normalize_phone(settings.get('demo_real_test_phone'))
    if (router is None or settings.get('demo_continuation_enabled') is not True
            or settings.get('tiktok_mode') != 'real' or settings.get('real_worker_enabled') is not True
            or settings.get('contact_sync_enabled') is not True or settings.get('gate', {}).get('enabled') is not True
            or not phone):
        raise ValueError('demo_real_configuration_invalid')
    scopes = tuple(scope for scope in configured_scopes(settings) if normalize_phone(scope.phone) == phone)
    if len(scopes) != 1:
        raise ValueError('demo_real_contact_not_in_verified_demo')
    bridge = DemoRealBridge(settings, scopes, Path(settings['state_dir']) / 'demo-real-test', runtime_factory=runtime_factory)
    router.store.real_bridge = bridge
    app.extensions['v5_demo_real_bridge'] = bridge
    # Dispatch only an existing bearer token owned by the isolated form store.
    # Main form auth, ownership and production exclusions remain unchanged.
    from flask import request, Response
    @app.before_request
    def route_real_form():
        if not request.path.startswith('/cadastro/'):
            return None
        prefix, _, token = request.headers.get('Authorization', '').partition(' ')
        if prefix.lower() != 'bearer':
            token = request.path.removeprefix('/cadastro/') if request.method == 'GET' else ''
        if not bridge.owns_form(token):
            return None
        return Response.from_app(bridge.runtime.wsgi_app, request.environ)
    if start:
        bridge.start()
    return bridge
