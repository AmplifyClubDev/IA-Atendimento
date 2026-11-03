"""Bounded local retention for closed, unconverted conversations only.

No provider calls, filesystem deletion, transcript logging or outbound effects.
Uncertain operations and any form/invitation/business proof protect a conversation.
One hashed watermark survives its summary so an old delivery cannot run again.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re


def clock(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return parsed.astimezone(timezone.utc) if isinstance(parsed, datetime) and parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def fingerprint(key):
    return hashlib.sha256(key.encode()).hexdigest()


def install(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS retention_watermarks (
            conversation_hash TEXT PRIMARY KEY, before_at TEXT NOT NULL,
            last_message_id TEXT, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS maintenance_jobs (
            task_key TEXT PRIMARY KEY, status TEXT NOT NULL, next_run_at TEXT NOT NULL,
            failures INTEGER NOT NULL DEFAULT 0, state_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS inbound_conversation ON inbound_events(conversation_key);
        CREATE INDEX IF NOT EXISTS outbox_conversation ON outbox(conversation_key);
        CREATE INDEX IF NOT EXISTS jobs_conversation ON real_jobs(conversation_key);
        CREATE INDEX IF NOT EXISTS sessions_retention_age ON sessions(updated_at,conversation_key);
    ''')


def replay_blocked(db, key, conversation, source_at, now):
    """Only normalized provider inbound keys require the surviving watermark."""
    match = re.fullmatch(r'chatwoot:([1-9][0-9]{0,19}):([1-9][0-9]{0,19})', key)
    if not match:
        return False
    mark = db.execute('SELECT * FROM retention_watermarks WHERE conversation_hash=?',
                      (fingerprint(conversation),)).fetchone()
    if not mark:
        return False
    observed, cutoff, at = clock(source_at), clock(mark['before_at']), clock(now)
    if not observed or not cutoff or not at or observed > at + timedelta(minutes=5) or observed <= cutoff:
        return True
    return bool(mark['last_message_id'] and int(match[2]) <= int(mark['last_message_id']))


def _unsafe(value):
    if isinstance(value, list):
        return any(_unsafe(item) for item in value)
    if not isinstance(value, dict):
        return False
    if value.get('status') in {'pending', 'running', 'queued', 'polling', 'result_ready', 'outcome_unknown',
                               'pending_verification', 'verification_pending', 'unknown', 'waiting_for_inbound'}:
        return True
    if value.get('provider_status') == 'unknown':
        return True
    return any(_unsafe(item) for item in value.values())


def _business_receipt(value):
    if isinstance(value, list):
        return any(_business_receipt(item) for item in value)
    if not isinstance(value, dict):
        return False
    if value.get('status') in {'linked', 'sent', 'cadastro_recebido_real', 'cadastro_recebido',
                               'access_delivered', 'acesso_entregue'}:
        return True
    if value.get('cadastro_situacao') in {'confirmado', 'concluido'}:
        return True
    if value.get('post_attempted') is True or value.get('create_accepted') is True:
        return True
    return any(_business_receipt(item) for item in value.values())


def _proof(state):
    if state.get('cadastro_situacao') not in (None, '', 'pendente', 'nao_iniciado'):
        return True
    for name, value in state.items():
        if ('acesso' in name.lower() or 'access' in name.lower()) and value:
            return True
    cycles = [state.get('cycle')] + list(state.get('closed_cycles') or [])
    for cycle in cycles:
        if not isinstance(cycle, dict):
            return True
        if cycle.get('reason') == 'validated_form' or cycle.get('form_effect_id') or cycle.get('invite_consent'):
            return True
        receipts = cycle.get('real_operations') or {}
        if not isinstance(receipts, dict) or receipts.get('invite'):
            return True
        relation = receipts.get('relationship') or {}
        if relation.get('status') == 'linked':
            return True
        facts = cycle.get('facts') or {}
        if any(facts.get(key) for key in ('consentimento_convite', 'aceite_declarado', 'agenciado',
                                         'cadastro_confirmado', 'acessos_entregues')):
            return True
    for effect in (state.get('effects') or {}).values():
        if not isinstance(effect, dict) or effect.get('operation') == 'invite' or effect.get('type') in {
                'generate_form_link', 'send_invite', 'deliver_access', 'send_access', 'submit_form'}:
            return True
    return False


def _summary(state, at):
    def cycle_summary(cycle):
        return {key: deepcopy(cycle[key]) for key in ('id', 'number', 'status', 'phase', 'reason',
                'opened_at', 'last_inbound_at', 'expires_at', 'closed_at') if key in cycle}
    cycles = [state.get('cycle')] + list(state.get('closed_cycles') or [])
    numbers = [item.get('number', 0) for item in cycles if isinstance(item, dict)]
    count = max([0] + [n for n in numbers + [state.get('cycle_number')] if type(n) is int])
    result = {key: deepcopy(state[key]) for key in ('schema_version', 'session_id', 'creator_id',
              'revision', 'human_control') if key in state}
    result.update(cycle=cycle_summary(state['cycle']), cycle_number=count, closed_cycles=[],
                  history=[], effects={}, processed_inbound=[], observations={},
                  retention={'version': 1, 'compacted_at': at, 'details_removed': True})
    # Facts remain in the canonical database, not copied into this operational summary.
    result['cycle']['facts'] = {}
    return result


def _eligible(db, row, state, cutoff):
    cycle = state.get('cycle')
    if not isinstance(cycle, dict) or cycle.get('status') not in {'closed', 'expired'}:
        return False
    closed = clock(cycle.get('closed_at'))
    if not closed or closed > cutoff or _unsafe(state) or _proof(state):
        return False
    tables = {item[0] for item in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'v5_forms' in tables and db.execute('SELECT 1 FROM v5_forms WHERE conversation_key=? LIMIT 1',
                                         (row['conversation_key'],)).fetchone():
        return False
    events = db.execute('SELECT * FROM inbound_events WHERE conversation_key=?',
                        (row['conversation_key'],)).fetchall()
    for event in events:
        if event['status'] not in {'completed', 'failed'}:
            return False
        if not clock(event['updated_at']) or clock(event['updated_at']) > cutoff:
            return False
    jobs = db.execute('SELECT * FROM real_jobs WHERE conversation_key=?', (row['conversation_key'],)).fetchall()
    for job in jobs:
        if job['operation'] == 'invite' or job['status'] not in {'completed', 'cancelled'}:
            return False
        if not clock(job['updated_at']) or clock(job['updated_at']) > cutoff:
            return False
        if job['result_json'] and (_unsafe(json.loads(job['result_json']))
                                  or _business_receipt(json.loads(job['result_json']))):
            return False
    for table, allowed in (('operations', {'completed', 'failed'}), ('outbox', {'accepted', 'failed'})):
        records = db.execute(f'SELECT child.* FROM {table} child JOIN inbound_events event '
                             'ON event.event_key=child.event_key WHERE event.conversation_key=?',
                             (row['conversation_key'],)).fetchall()
        for record in records:
            if record['status'] not in allowed or not clock(record['updated_at']) or clock(record['updated_at']) > cutoff:
                return False
            raw = record['result_json'] if table == 'operations' else record['receipt_json']
            if raw and (_unsafe(json.loads(raw)) or _business_receipt(json.loads(raw))):
                return False
            if table == 'operations' and record['kind'] not in {
                    'answer_question', 'conversation_turn', 'register_contact', 'contact_sync', 'chatwoot_progress',
                    'chatwoot_progress_labels'}:
                return False
    return True


def sweep(db, now, *, limit=100, after_key=''):
    at = clock(now)
    if not at or type(limit) is not int or not 1 <= limit <= 1000 or not isinstance(after_key, str):
        raise ValueError('invalid retention bounds')
    cutoff = at - timedelta(days=30)
    rows = db.execute('SELECT * FROM sessions WHERE conversation_key>? AND updated_at<? '
                      'ORDER BY conversation_key LIMIT ?', (after_key, cutoff.isoformat(), limit)).fetchall()
    counts = {'examined': len(rows), 'compacted': 0, 'summaries_deleted': 0,
              'events_deleted': 0, 'operations_deleted': 0, 'outbox_deleted': 0, 'jobs_deleted': 0,
              'protected': 0, 'invalid': 0}
    for row in rows:
        try:
            state = json.loads(row['state_json'])
            if not isinstance(state, dict) or not _eligible(db, row, state, cutoff):
                counts['protected'] += 1
                continue
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            counts['invalid'] += 1
            continue
        conversation = row['conversation_key']
        # A cross-conversation FK reference is anomalous and blocks deletion.
        if db.execute('SELECT 1 FROM real_jobs j JOIN inbound_events e ON j.event_key=e.event_key '
                      'WHERE (e.conversation_key=? AND j.conversation_key<>?) '
                      'OR (j.conversation_key=? AND e.conversation_key<>?) LIMIT 1',
                      (conversation, conversation, conversation, conversation)).fetchone():
            counts['protected'] += 1
            continue
        if db.execute('SELECT 1 FROM outbox o JOIN inbound_events e ON o.event_key=e.event_key '
                      'WHERE (e.conversation_key=? AND o.conversation_key<>?) '
                      'OR (o.conversation_key=? AND e.conversation_key<>?) LIMIT 1',
                      (conversation, conversation, conversation, conversation)).fetchone():
            counts['protected'] += 1
            continue
        event_keys = [item[0] for item in db.execute('SELECT event_key FROM inbound_events WHERE conversation_key=?',
                                                   (conversation,))]
        ids = [int(key.rsplit(':', 1)[1]) for key in event_keys
               if re.fullmatch(r'chatwoot:[1-9][0-9]{0,19}:[1-9][0-9]{0,19}', key)]
        previous = db.execute('SELECT * FROM retention_watermarks WHERE conversation_hash=?',
                              (fingerprint(conversation),)).fetchone()
        if previous and previous['last_message_id']:
            ids.append(int(previous['last_message_id']))
        boundary = max(cutoff, clock(previous['before_at'])) if previous else cutoff
        db.execute('INSERT INTO retention_watermarks VALUES(?,?,?,?) ON CONFLICT(conversation_hash) '
                   'DO UPDATE SET before_at=excluded.before_at,last_message_id=excluded.last_message_id,'
                   'updated_at=excluded.updated_at', (fingerprint(conversation), boundary.isoformat(),
                    str(max(ids)) if ids else None, at.isoformat()))
        for table, key in (('operations', 'operations_deleted'), ('outbox', 'outbox_deleted')):
            cursor = db.execute(f'DELETE FROM {table} WHERE event_key IN '
                                '(SELECT event_key FROM inbound_events WHERE conversation_key=?)', (conversation,))
            counts[key] += cursor.rowcount
        counts['jobs_deleted'] += db.execute('DELETE FROM real_jobs WHERE conversation_key=?', (conversation,)).rowcount
        counts['events_deleted'] += db.execute('DELETE FROM inbound_events WHERE conversation_key=?', (conversation,)).rowcount
        closed = clock(state['cycle']['closed_at'])
        if closed <= at - timedelta(days=90):
            db.execute('DELETE FROM sessions WHERE conversation_key=?', (conversation,))
            counts['summaries_deleted'] += 1
        elif (not (state.get('retention') or {}).get('details_removed')
              or any(state.get(key) for key in ('history', 'effects', 'processed_inbound', 'closed_cycles'))):
            summary = _summary(state, at.isoformat())
            # Keep original activity time; maintenance never prolongs retention.
            db.execute('UPDATE sessions SET state_json=? WHERE conversation_key=?',
                       (json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(',', ':')), conversation))
            counts['compacted'] += 1
    counts['next_after_key'] = rows[-1]['conversation_key'] if len(rows) == limit else ''
    return counts
