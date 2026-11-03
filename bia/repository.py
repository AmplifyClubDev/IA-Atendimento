"""Durable operational rehearsal state. No remote database or provider I/O."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now():
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    conversation_key TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inbound_events (
                    event_key TEXT PRIMARY KEY, conversation_key TEXT NOT NULL, digest TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                    operation_key TEXT PRIMARY KEY, event_key TEXT NOT NULL REFERENCES inbound_events(event_key),
                    kind TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (
                    outbox_key TEXT PRIMARY KEY, event_key TEXT NOT NULL REFERENCES inbound_events(event_key),
                    conversation_key TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL,
                    receipt_json TEXT, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS real_jobs (
                    job_key TEXT PRIMARY KEY, conversation_key TEXT NOT NULL,
                    event_key TEXT NOT NULL REFERENCES inbound_events(event_key),
                    effect_id TEXT NOT NULL, cycle_id TEXT NOT NULL, creator TEXT NOT NULL,
                    operation TEXT NOT NULL, event_json TEXT NOT NULL, payload_json TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    next_run_at TEXT NOT NULL, result_json TEXT, last_signature TEXT,
                    updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS real_jobs_due ON real_jobs(status,next_run_at);
                CREATE TABLE IF NOT EXISTS followup_sources (
                    conversation_key TEXT PRIMARY KEY REFERENCES sessions(conversation_key) ON DELETE CASCADE,
                    cycle_id TEXT NOT NULL, event_key TEXT NOT NULL, event_json TEXT NOT NULL);
            """)
            from retention import install
            install(db)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def ready(self):
        with self._connection() as db:
            return db.execute("SELECT 1").fetchone()[0] == 1

    def reserve_event(self, event_key, conversation_key, digest, *, source_at=None):
        """Commit uncertainty before any provider call. Existing rows never retry."""
        at = _now()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM inbound_events WHERE event_key=?", (event_key,)).fetchone()
            if row:
                return {"reserved": False, "status": row["status"],
                        "conflict": row["digest"] != digest or row["conversation_key"] != conversation_key}
            from retention import replay_blocked
            if replay_blocked(db, event_key, conversation_key, source_at, at):
                return {"reserved": False, "status": "retention_replay_blocked", "conflict": False}
            db.execute("INSERT INTO inbound_events(event_key,conversation_key,digest,status,created_at,updated_at) "
                       "VALUES (?,?,?,?,?,?)", (event_key, conversation_key, digest, "outcome_unknown", at, at))
            return {"reserved": True, "status": "outcome_unknown", "conflict": False}

    def retention_pass(self, at, *, limit=100, after_key=''):
        """Delete only eligible closed conversations atomically in FK order."""
        from retention import sweep
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            return sweep(db, at, limit=limit, after_key=after_key)

    def claim_maintenance(self, task_key, at):
        """Persist a daily claim before I/O. A crash cannot immediately repeat it."""
        from retention import clock
        current = clock(at)
        if task_key not in {'sqlite_retention', 'sql_retention'} or not current:
            raise ValueError('invalid maintenance claim')
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM maintenance_jobs WHERE task_key=?', (task_key,)).fetchone()
            if row and (not clock(row['next_run_at']) or current < clock(row['next_run_at'])):
                return None
            state = json.loads(row['state_json']) if row else {}
            failures = row['failures'] if row else 0
            db.execute('INSERT INTO maintenance_jobs VALUES(?,?,?,?,?,?) ON CONFLICT(task_key) DO UPDATE SET '
                       "status='running',next_run_at=excluded.next_run_at,updated_at=excluded.updated_at",
                       (task_key, 'running', (current + timedelta(days=1)).isoformat(), failures, _json(state), at))
            return {'failures': failures, 'state': state}

    def finish_maintenance(self, task_key, at, *, success, state=None, has_more=False):
        from retention import clock
        current = clock(at)
        if (task_key not in {'sqlite_retention', 'sql_retention'} or not current
                or type(success) is not bool or type(has_more) is not bool):
            raise ValueError('invalid maintenance receipt')
        with self._connection() as db:
            row = db.execute('SELECT * FROM maintenance_jobs WHERE task_key=?', (task_key,)).fetchone()
            if not row or row['status'] != 'running':
                raise ValueError('maintenance claim required')
            failures = 0 if success else min(row['failures'] + 1, 6)
            delay = (60 if has_more else 86400) if success else min(3600 * (2 ** (failures - 1)), 86400)
            db.execute('UPDATE maintenance_jobs SET status=?,next_run_at=?,failures=?,state_json=?,updated_at=? '
                       'WHERE task_key=?', ('completed' if success else 'unconfirmed',
                        (current + timedelta(seconds=delay)).isoformat(), failures,
                        _json(state if state is not None else json.loads(row['state_json'])), at, task_key))

    def load_session(self, conversation_key):
        with self._connection() as db:
            row = db.execute("SELECT state_json FROM sessions WHERE conversation_key=?", (conversation_key,)).fetchone()
            return json.loads(row[0]) if row else {}

    get_session = load_session

    def remember_followup_source(self, conversation_key, event, state):
        """One replaceable actual inbound per conversation; never a fake lead event."""
        from contracts import inbound_key
        cycle = state.get('cycle') or {}
        key = inbound_key(event)
        if not key or not cycle.get('id'):
            return False
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            source = db.execute('SELECT status FROM inbound_events WHERE event_key=? AND conversation_key=?',
                                (key, conversation_key)).fetchone()
            current = db.execute('SELECT state_json FROM sessions WHERE conversation_key=?',
                                 (conversation_key,)).fetchone()
            if not source or source['status'] != 'completed' or not current or json.loads(current[0]) != state:
                return False
            db.execute('INSERT INTO followup_sources VALUES(?,?,?,?) ON CONFLICT(conversation_key) DO UPDATE SET '
                       'cycle_id=excluded.cycle_id,event_key=excluded.event_key,event_json=excluded.event_json',
                       (conversation_key, cycle['id'], key, _json(event)))
            return True

    def followup_source(self, conversation_key):
        with self._connection() as db:
            row = db.execute('SELECT * FROM followup_sources WHERE conversation_key=?', (conversation_key,)).fetchone()
            return {**dict(row), 'event': json.loads(row['event_json'])} if row else None

    def followup_conversations(self):
        """Every chat with a remembered actual inbound (release 39 retomada scan)."""
        with self._connection() as db:
            return [row[0] for row in db.execute('SELECT conversation_key FROM followup_sources ORDER BY conversation_key')]

    def followup_accepted_message_ids(self, conversation_key, cycle_opened_at):
        """Only provider receipts prove that a public outgoing belongs to Bia."""
        with self._connection() as db:
            rows = db.execute("SELECT receipt_json FROM outbox WHERE conversation_key=? AND status='accepted' "
                              'AND updated_at>=? ORDER BY updated_at DESC LIMIT 100',
                              (conversation_key, cycle_opened_at)).fetchall()
            result = set()
            for row in rows:
                receipt = json.loads(row[0]) if row[0] else {}
                identifier = receipt.get('message_id') if isinstance(receipt, dict) else None
                if isinstance(identifier, str) and identifier.isdigit() and int(identifier) > 0:
                    result.add(identifier)
            return result

    @staticmethod
    def _followup_clear(db, conversation_key, state):
        cycle = state.get('cycle') or {}
        # A pending/uncertain external action is never converted into a nudge.
        if db.execute("SELECT 1 FROM real_jobs WHERE conversation_key=? AND cycle_id=? "
                      "AND status NOT IN ('completed','cancelled') LIMIT 1", (conversation_key, cycle.get('id'))).fetchone():
            return False
        if db.execute("SELECT 1 FROM outbox WHERE conversation_key=? AND status NOT IN ('accepted','failed') LIMIT 1",
                      (conversation_key,)).fetchone():
            return False
        if db.execute("SELECT 1 FROM operations o JOIN inbound_events i ON i.event_key=o.event_key "
                      "WHERE i.conversation_key=? AND o.status='outcome_unknown' LIMIT 1",
                      (conversation_key,)).fetchone():
            return False
        return True

    def followup_clear(self, conversation_key, state):
        with self._connection() as db:
            return self._followup_clear(db, conversation_key, state)

    def reserve_followup(self, conversation_key, source, state, operation_key, payload):
        """Atomically reserve one send/cycle against unchanged state and actual source."""
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT state_json FROM sessions WHERE conversation_key=?', (conversation_key,)).fetchone()
            latest = db.execute('SELECT cycle_id,event_key FROM followup_sources WHERE conversation_key=?',
                                (conversation_key,)).fetchone()
            prior = db.execute('SELECT 1 FROM operations WHERE operation_key=?', (operation_key,)).fetchone()
            if (not current or json.loads(current[0]) != state or not latest or prior
                    or latest['cycle_id'] != source['cycle_id'] or latest['event_key'] != source['event_key']
                    or not self._followup_clear(db, conversation_key, state)):
                return False
            at = _now()
            db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',
                       (operation_key, source['event_key'], 'followup', 'outcome_unknown', None, at))
            db.execute('INSERT INTO outbox VALUES(?,?,?,?,?,?,?)',
                       (operation_key, source['event_key'], conversation_key, _json(payload), 'outcome_unknown', None, at))
            return True

    def save_session(self, conversation_key, state):
        with self._connection() as db:
            db.execute("INSERT INTO sessions VALUES (?,?,?) ON CONFLICT(conversation_key) DO UPDATE SET "
                       "state_json=excluded.state_json,updated_at=excluded.updated_at", (conversation_key, _json(state), _now()))

    def reserve_operation(self, operation_key, event_key, kind):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("INSERT OR IGNORE INTO operations VALUES (?,?,?,?,?,?)",
                                (operation_key, event_key, kind, "outcome_unknown", None, _now()))
            return cursor.rowcount == 1

    def complete_operation(self, operation_key, result, status="completed"):
        with self._connection() as db:
            db.execute("UPDATE operations SET status=?,result_json=?,updated_at=? WHERE operation_key=?",
                       (status, _json(result), _now(), operation_key))

    def get_operation(self, operation_key):
        with self._connection() as db:
            row = db.execute("SELECT * FROM operations WHERE operation_key=?", (operation_key,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["result"] = json.loads(result.pop("result_json")) if row["result_json"] else None
            return result

    def prepare_reply(self, event_key, conversation_key, state, outbox_key, payload, real_jobs=None):
        """Persist engine state + reserved outbox atomically, before sending."""
        at = _now()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO sessions VALUES (?,?,?) ON CONFLICT(conversation_key) DO UPDATE SET "
                       "state_json=excluded.state_json,updated_at=excluded.updated_at", (conversation_key, _json(state), at))
            if payload:
                db.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?)",
                           (outbox_key, event_key, conversation_key, _json(payload), "outcome_unknown", None, at,))
            self._enqueue_real_jobs(db, real_jobs or [], at)

    @staticmethod
    def _enqueue_real_jobs(db, jobs, at):
        for job in jobs:
            # A scheduled retry check waits until its explicit not_before time.
            not_before = (job.get('payload') or {}).get('not_before')
            run_at = not_before if isinstance(not_before, str) and not_before > at else at
            previous = db.execute("SELECT * FROM real_jobs WHERE job_key=?", (job['job_key'],)).fetchone()
            if previous:
                # A write is never resubmitted, including after a new inbound.
                # Explicit new read effects reuse this row; no row per poll.
                if (job['operation'] == 'invite' or previous['status'] in {'running', 'result_ready'}
                        or previous['effect_id'] == job['effect_id']):
                    continue
                db.execute("UPDATE real_jobs SET event_key=?,effect_id=?,event_json=?,payload_json=?,"
                           "status='queued',attempts=0,next_run_at=?,result_json=NULL,last_signature=NULL,updated_at=? "
                           "WHERE job_key=?",
                           (job['event_key'], job['effect_id'], _json(job['event']), _json(job['payload']),
                            run_at, at, job['job_key']))
                continue
            db.execute("INSERT INTO real_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (job['job_key'], job['conversation_key'], job['event_key'], job['effect_id'],
                        job['cycle_id'], job['creator'], job['operation'], _json(job['event']),
                        _json(job['payload']), 'queued', 0, run_at, None, None, at))

    @staticmethod
    def _real_row(row):
        if not row:
            return None
        result = dict(row)
        for column, target in [('event_json', 'event'), ('payload_json', 'payload'), ('result_json', 'result')]:
            raw = result.pop(column)
            result[target] = json.loads(raw) if raw else None
        return result

    def real_job(self, job_key):
        with self._connection() as db:
            return self._real_row(db.execute('SELECT * FROM real_jobs WHERE job_key=?', (job_key,)).fetchone())

    def real_job_for_effect(self, effect_id):
        with self._connection() as db:
            return self._real_row(db.execute('SELECT * FROM real_jobs WHERE effect_id=? ORDER BY updated_at DESC LIMIT 1',
                                             (effect_id,)).fetchone())

    def precheck_conversations(self):
        """Every chat that ever queued a profile check (release 40 reconferência scan)."""
        with self._connection() as db:
            return [row[0] for row in db.execute(
                "SELECT DISTINCT conversation_key FROM real_jobs WHERE operation='precheck' ORDER BY conversation_key")]

    def claim_real_job(self, at):
        """Commit the running/uncertain state before leaving SQLite for a provider."""
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM real_jobs WHERE status='result_ready' OR "
                             "(status IN ('queued','polling') AND next_run_at<=?) "
                             "ORDER BY CASE status WHEN 'result_ready' THEN 0 ELSE 1 END,next_run_at,job_key LIMIT 1",
                             (at,)).fetchone()
            if not row:
                return None
            if row['status'] != 'result_ready':
                db.execute("UPDATE real_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE job_key=?",
                           (at, row['job_key']))
                row = db.execute('SELECT * FROM real_jobs WHERE job_key=?', (row['job_key'],)).fetchone()
            return self._real_row(row)

    def set_real_result(self, job_key, result, at):
        with self._connection() as db:
            db.execute("UPDATE real_jobs SET status='result_ready',result_json=?,updated_at=? "
                       "WHERE job_key=? AND status='running'", (_json(result), at, job_key))

    def finish_real_job(self, job_key, status, at, *, next_run_at=None, signature=None):
        if status not in {'completed', 'polling', 'cancelled', 'outcome_unknown'}:
            raise ValueError('invalid real job status')
        with self._connection() as db:
            db.execute('UPDATE real_jobs SET status=?,next_run_at=?,last_signature=COALESCE(?,last_signature),'
                       'updated_at=? WHERE job_key=?', (status, next_run_at or at, signature, at, job_key))

    def park_real_read(self, job, state, at, signature):
        """Atomically stop bounded reads and permit a later explicit inbound."""
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM real_jobs WHERE job_key=?', (job['job_key'],)).fetchone()
            if (not row or row['operation'] != 'relationship' or row['attempts'] < 6
                    or row['status'] != 'result_ready' or row['effect_id'] != job['effect_id']
                    or row['conversation_key'] != job['conversation_key']):
                raise ValueError('invalid read parking')
            state['effects'][job['effect_id']]['status'] = 'waiting_for_inbound'
            db.execute('UPDATE sessions SET state_json=?,updated_at=? WHERE conversation_key=?',
                       (_json(state), at, job['conversation_key']))
            db.execute("UPDATE real_jobs SET status='completed',next_run_at=?,last_signature=?,updated_at=? "
                       'WHERE job_key=?', (at, signature, at, job['job_key']))

    def recover_real_jobs(self, at):
        """An interrupted POST becomes a reconciliable result; it never goes back to queued."""
        summary = {'requeued_reads': 0, 'interrupted_writes': 0}
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute("SELECT * FROM real_jobs WHERE status='running'").fetchall():
                if row['operation'] == 'invite':
                    result = {'operation': 'invite', 'creator': row['creator'], 'status': 'outcome_unknown',
                              'confirmed': False, 'observed_at': at, 'evidence': {}, 'reason': 'interrupted_write_reconcile'}
                    db.execute("UPDATE real_jobs SET status='result_ready',result_json=?,updated_at=? WHERE job_key=?",
                               (_json(result), at, row['job_key']))
                    summary['interrupted_writes'] += 1
                else:
                    db.execute("UPDATE real_jobs SET status='queued',next_run_at=?,updated_at=? WHERE job_key=?",
                               (at, at, row['job_key']))
                    summary['requeued_reads'] += 1
            # A failed local application can leave a valid read effect pending.
            # Only fetch again when its exact technical attempt is uncertain
            # and no reply outbox was created. Never replay the old result or a
            # write, reset the attempt budget, or resume a human cancellation.
            rows = db.execute("SELECT * FROM real_jobs WHERE status='outcome_unknown' "
                              "AND operation IN ('lookup','precheck','relationship') "
                              "AND attempts BETWEEN 1 AND 5").fetchall()
            for row in rows:
                session = db.execute('SELECT state_json FROM sessions WHERE conversation_key=?',
                                     (row['conversation_key'],)).fetchone()
                try:
                    state = json.loads(session['state_json']) if session else {}
                    cycle = state.get('cycle') or {}
                    effect = (state.get('effects') or {}).get(row['effect_id']) or {}
                    result, payload = json.loads(row['result_json']), json.loads(row['payload_json'])
                    observed_now = datetime.fromisoformat(at.replace('Z', '+00:00'))
                    expires = datetime.fromisoformat(cycle['expires_at'].replace('Z', '+00:00'))
                    normalize = lambda value: value.lower().removeprefix('@') if isinstance(value, str) else None
                    creator = normalize(row['creator'])
                    valid = (isinstance(result, dict) and result.get('operation') == row['operation']
                             and normalize(result.get('creator')) == creator and creator
                             and cycle.get('mode') == 'real' and cycle.get('status') == 'open'
                             and cycle.get('id') == row['cycle_id'] and observed_now.tzinfo is not None
                             and expires.tzinfo is not None and observed_now < expires
                             and not state.get('human_control') and not cycle.get('qualification_paused')
                             and not cycle.get('pending_profile_changes')
                             and normalize((cycle.get('facts') or {}).get('tiktok_declarado')) == creator
                             and effect.get('id') == row['effect_id'] and effect.get('status') == 'pending'
                             and effect.get('type') == 'tiktok_operation' and effect.get('operation') == row['operation']
                             and effect.get('cycle_id') == row['cycle_id'] and normalize(effect.get('creator')) == creator
                             and effect.get('payload') == payload)
                except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
                    continue
                if not valid:
                    continue
                application_key = row['job_key'] + ':result:' + row['effect_id'] + ':' + str(row['attempts'])
                application = db.execute('SELECT conversation_key,status FROM inbound_events WHERE event_key=?',
                                         (application_key,)).fetchone()
                outbox = db.execute('SELECT 1 FROM outbox WHERE event_key=? LIMIT 1', (application_key,)).fetchone()
                if (not application or application['status'] != 'outcome_unknown'
                        or application['conversation_key'] != row['conversation_key'] or outbox):
                    continue
                db.execute("UPDATE real_jobs SET status='queued',next_run_at=?,result_json=NULL,"
                           "last_signature=NULL,updated_at=? WHERE job_key=? AND status='outcome_unknown'",
                           (at, at, row['job_key']))
                summary['requeued_reads'] += 1
        return summary

    def finish_outbox(self, outbox_key, status, receipt):
        if status not in {"accepted", "failed", "outcome_unknown"}:
            raise ValueError("invalid outbox status")
        with self._connection() as db:
            db.execute("UPDATE outbox SET status=?,receipt_json=?,updated_at=? WHERE outbox_key=?",
                       (status, _json(receipt), _now(), outbox_key))

    def finish_event(self, event_key, status):
        if status not in {"completed", "failed", "outcome_unknown"}:
            raise ValueError("invalid event status")
        with self._connection() as db:
            db.execute("UPDATE inbound_events SET status=?,updated_at=? WHERE event_key=?", (status, _now(), event_key))

    def event(self, event_key):
        with self._connection() as db:
            row = db.execute("SELECT * FROM inbound_events WHERE event_key=?", (event_key,)).fetchone()
            return dict(row) if row else None

    def outbox(self, event_key):
        with self._connection() as db:
            rows = db.execute("SELECT * FROM outbox WHERE event_key=? ORDER BY outbox_key", (event_key,)).fetchall()
            return [{**dict(row), "payload": json.loads(row["payload_json"]),
                     "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None} for row in rows]

    def conversation_delivery_context(self, conversation_key, cycle_opened_at):
        """Read accepted Chatwoot payloads, never infer delivery from engine history.

        No schema or state writes. The caller provides the active cycle's opening
        boundary; uncertain/failed attempts remain distinct from accepted replies.
        Accepted means accepted by Chatwoot, not WhatsApp delivery/read proof.
        """
        empty = {"source": "outbox", "accepted_history": [], "last_accepted_reply": None,
                 "latest_attempt_status": "unknown"}
        if not isinstance(cycle_opened_at, str) or not cycle_opened_at:
            return empty
        with self._connection() as db:
            latest = db.execute("SELECT status FROM outbox WHERE conversation_key=? AND updated_at>=? "
                                "ORDER BY updated_at DESC,rowid DESC LIMIT 1",
                                (conversation_key, cycle_opened_at)).fetchone()
            rows = db.execute("SELECT payload_json,updated_at FROM outbox WHERE conversation_key=? "
                              "AND status='accepted' AND updated_at>=? "
                              "ORDER BY updated_at DESC,rowid DESC LIMIT 12",
                              (conversation_key, cycle_opened_at)).fetchall()
        accepted = []
        for row in reversed(rows):
            body = json.loads(row["payload_json"])
            if isinstance(body, dict) and isinstance(body.get("text"), str):
                accepted.append({"direction": "outbound", "text": body["text"][:2200], "at": row["updated_at"]})
        return {**empty, "accepted_history": accepted,
                "last_accepted_reply": accepted[-1] if accepted else None,
                "latest_attempt_status": latest["status"] if latest else "unknown"}
