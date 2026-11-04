"""Single durable executor for the pilot's real TikTok operations.

Only this module calls the bridge client. Jobs live in the existing local SQLite
file, one row per cycle/handle/action; provider I/O never runs in the webhook.
An interrupted invitation is reconciled by reads and is never automatically sent
again. No tokens or provider response bodies are logged here.
"""
from __future__ import annotations

from offline_policy import effects_allowed, require_effects

import hashlib
import json
import logging
import math
import re
import threading
from uuid import UUID
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contracts import allow_inbound, inbound_key, phone_matches, pilot_phone


def _stamp(now):
    return now.astimezone(timezone.utc).isoformat()


def _clock(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (AttributeError, ValueError, TypeError):
        return None


def _creator(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lstrip('@').lower()
    return value if re.fullmatch(r'[a-z0-9_][a-z0-9._]{1,23}', value) else None


def policy_for(settings):
    try:
        commission = float(settings.get('tiktok_invite_commission', ''))
    except (TypeError, ValueError):
        commission = None
    return {'approved': settings.get('tiktok_policy_approved') is True,
            'commission': commission if commission is not None and math.isfinite(commission) else None,
            'commission_unit': settings.get('tiktok_commission_unit'),
            'duration_fixed_months': 2 if str(settings.get('tiktok_duration_fixed_months')) == '2' else None,
            'duration_label': settings.get('tiktok_duration_label'),
            'version': settings.get('tiktok_policy_version', '')}


def business_key(cycle_id, creator, operation):
    digest = hashlib.sha256(f'{cycle_id}:{creator}:{operation}'.encode()).hexdigest()
    return 'tiktok-job:' + digest


# Release 42: reads of the relations list started by the scan (see real_journey.AGENCY_SOURCES).
AGENCY_SOURCES = frozenset({'invite_list_proof', 'invite_tracking'})


def build_jobs(event, state, effects):
    """Build only known, exact-scope jobs; persist them atomically with state."""
    cycle = state.get('cycle') or {}
    result = []
    for effect in effects or []:
        if not isinstance(effect, dict) or effect.get('type') != 'tiktok_operation':
            continue
        operation, creator = effect.get('operation'), _creator(effect.get('creator'))
        if (operation not in {'precheck', 'invite', 'relationship', 'lookup', 'gmv_report'}
                or not creator or effect.get('cycle_id') != cycle.get('id')
                or state.get('effects', {}).get(effect.get('id')) != effect):
            raise ValueError('invalid real effect binding')
        # The one evidenced retry gets its own row: invite rows are never resubmitted.
        retry = (effect.get('payload') or {}).get('retry') if operation == 'invite' else None
        key_operation = ('invite-retry' if retry == 1 else 'invite-retry:' + str(retry) if type(retry) is int and retry > 1
                         else operation)
        if operation == 'relationship' and (effect.get('payload') or {}).get('source') == 'chat_acceptance':
            # Each acceptance read (now, 5, 15, 60 min) has its own row.
            key_operation = 'relationship-chat:' + effect['id']
        if operation == 'relationship' and (effect.get('payload') or {}).get('source') in AGENCY_SOURCES:
            # Release 42: each read of the relations list (proof or follow-up) has its own row.
            key_operation = 'relationship-agency:' + effect['id']
        if operation == 'precheck' and (effect.get('payload') or {}).get('source') == 'bridge_retry':
            # Each check after the bridge comes back has its own row (release 40).
            key_operation = 'precheck-bridge:' + effect['id']
        result.append({'job_key': business_key(cycle['id'], creator, key_operation),
                       'conversation_key': f"chatwoot:{event['account_id']}:{event['conversation_id']}",
                       'event_key': inbound_key(event), 'effect_id': effect['id'], 'cycle_id': cycle['id'],
                       'creator': creator, 'operation': operation, 'event': dict(event),
                       'payload': dict(effect.get('payload') or {})})
    return result


RENEWAL_LABELS = frozenset({'renovacao de contrato', 'renovacao_de_contrato', 'renovacao-de-contrato'})


def gate_exclusion(gate, event, detail):
    """Release 47: no modo 'todos', quem a Bia não atende (o número de teste sempre entra). None = pode atender."""
    from contracts import gate_mode, is_test_phone
    import unicodedata
    if gate_mode(gate) != 'todos' or is_test_phone(gate, event.get('sender_phone')):
        return None
    labels = detail.get('labels') if isinstance(detail.get('labels'), list) else []
    normal = {''.join(c for c in unicodedata.normalize('NFKD', str(label)).lower() if not unicodedata.combining(c)).strip()
              for label in labels}
    if normal & RENEWAL_LABELS:
        return 'fora_do_gate:renovacao_de_contrato'
    return None


def chatwoot_control_guard(transport, gate, event):
    """Read recipient/control state. Unknown ownership never grants authority."""
    if not allow_inbound(gate, event):
        return {'allowed': False, 'reason': 'outside_pilot'}
    try:
        detail = transport.http(method='GET', url=transport._conversation_url(event),
                                headers={'api_access_token': transport.token, 'Accept': 'application/json'}, timeout=10)
        if not isinstance(detail, dict):
            raise ValueError('unverified recipient')
        meta = detail.get('meta') or {}
        sender = meta.get('sender') or {}
        if not (str(detail.get('id')) == str(event.get('conversation_id'))
                and str(detail.get('account_id')) == str(gate.get('account_id')) == str(event.get('account_id'))
                and str(detail.get('inbox_id')) == str(gate.get('inbox_id')) == str(event.get('inbox_id'))
                and str(sender.get('id')) == str(event.get('contact_id'))
                and pilot_phone(gate, sender.get('phone_number')) is not None
                and pilot_phone(gate, sender.get('phone_number')) == pilot_phone(gate, event.get('sender_phone'))
                and detail.get('can_reply') is True):
            return {'allowed': False, 'reason': 'recipient_or_window_unverified'}
        excluded = gate_exclusion(gate, event, detail)
        if excluded:
            return {'allowed': False, 'reason': excluded}
        custom = detail.get('custom_attributes') or {}
        if not isinstance(custom, dict):
            return {'allowed': False, 'reason': 'human_control_unverified'}
        for key in ('human_control', 'manual', 'manual_mode', 'maintenance', 'automation_paused',
                    'automacao_pausada', 'automacao_pause', 'atendimento_humano', 'bia_paused'):
            value = custom.get(key)
            normalized = str(value).strip().lower()
            if value is True or normalized in {'true', '1', 'yes', 'on', 'enabled', 'paused', 'manual', 'human', 'maintenance'}:
                return {'allowed': False, 'reason': 'human_control_blocked'}
            if value is not None and normalized not in {'false', '0', 'no', 'off', 'disabled', ''}:
                return {'allowed': False, 'reason': 'human_control_unverified'}
        if detail.get('status') != 'open':
            return {'allowed': False, 'reason': 'conversation_not_open'}
        assignee = meta.get('assignee')
        if assignee is not None:
            bot_type = str(meta.get('assignee_type') or (assignee.get('type') if isinstance(assignee, dict) else '')).lower()
            if bot_type not in {'agent_bot', 'agentbot'}:
                return {'allowed': False, 'reason': 'human_assignee_blocked'}
        return {'allowed': True, 'reason': 'automation_control_confirmed'}
    except Exception:
        return {'allowed': False, 'reason': 'human_control_unverified'}


class RealExecutor:
    def __init__(self, repository, client, settings, lock_for, guard, apply_result, *, clock=None):
        self.repository, self.client, self.settings = repository, client, settings
        self.lock_for, self.guard, self.apply_result = lock_for, guard, apply_result
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stop_event, self.wake_event = threading.Event(), threading.Event()
        self.thread = None
        self.last_guard = 'not_checked'
        self.last_error = None
        # Release 43: called when a result could not be applied, so the lead hears something honest.
        self.failure_notice = None
        self._ownership_file = None
        self.session_checks = {}
        self.sessions_checked_at = None
        self.retention_cleanup = None
        self.followup_tick = None
        self.followup_status = None
        self.retention_status = {'enabled': settings.get('retention_enabled') is True, 'status': 'not_run'}

    def configured(self):
        if not effects_allowed(settings=self.settings):
            return False
        try:
            return self.client.configuration().get('configured') is True
        except Exception:
            return False

    def status(self):
        checked = _clock(self.sessions_checked_at)
        fresh = bool(checked and 0 <= (self.clock() - checked).total_seconds() <= 60)
        allowed = effects_allowed(settings=self.settings)
        return {'mode': self.settings.get('tiktok_mode', 'simulated'),
                **({} if allowed else {'status': 'disabled', 'reason': 'nonproduction_external_effects_disabled'}),
                **({'relationship_check_in_form': True}
                   if self.settings.get('relationship_check_in_form') is True else {}),
                'worker_enabled': allowed and self.settings.get('real_worker_enabled') is True,
                'worker_running': bool(self.thread and self.thread.is_alive()),
                'core_configured': self.configured(), 'control': self.last_guard,
                'last_error': self.last_error,
                'retention': dict(self.retention_status),
                'followup': self.followup_status() if callable(self.followup_status) else {'enabled': False, 'configured': False},
                'sessions': {'checked_at': self.sessions_checked_at, 'fresh': fresh,
                             'ready': allowed and fresh and len(self.session_checks) == 3
                                      and all(row['ready'] for row in self.session_checks.values()),
                             'functions': dict(self.session_checks)},
                'functions': {operation: self.client.configuration(operation).get('configured') is True
                              for operation in ('precheck', 'relationship', 'invite', 'lookup', 'gmv_report')}}

    def probe_sessions(self):
        """Three read-only readiness calls, no retries or invitation operations."""
        if not effects_allowed(settings=self.settings):
            return dict({'status': 'disabled', 'reason': 'nonproduction_external_effects_disabled'}, ready=False)
        if self.settings.get('tiktok_mode') != 'real' or not self.configured():
            return {'ready': False, 'reason': 'not_configured'}
        checks = {}
        codes = {'human_verification_required', 'session_not_ready', 'connection_not_configured',
                 'connection_target_invalid', 'timeout_configuration_invalid', 'transport_unconfirmed',
                 'invalid_response', 'redirect_rejected', 'response_too_large'}
        for role in ('precheck', 'agency', 'invites'):
            try:
                self.client._ready(role)
                checks[role] = {'ready': True, 'reason': 'authenticated_read_confirmed'}
            except Exception as error:
                reason = getattr(error, 'reason', None)
                checks[role] = {'ready': False, 'reason': reason if reason in codes else 'probe_unconfirmed'}
        self.session_checks = checks
        self.sessions_checked_at = _stamp(self.clock())
        return self.status()['sessions']

    def _valid(self, job, state, now):
        cycle = state.get('cycle') or {}
        effect = state.get('effects', {}).get(job['effect_id']) or {}
        expires = _clock(cycle.get('expires_at'))
        if (self.settings.get('relationship_check_in_form') is True
                and job.get('operation') == 'relationship'
                and (job.get('payload') or {}).get('source') not in {'form', 'chat_acceptance'} | AGENCY_SOURCES):
            return False
        if (self.settings.get('tiktok_mode') != 'real' or self.settings.get('real_worker_enabled') is not True
                or self.settings.get('contact_sync_enabled') is not True
                or not allow_inbound(self.settings.get('gate') or {}, job['event'])
                or cycle.get('mode') != 'real' or cycle.get('status') != 'open'
                or not expires or now >= expires or cycle.get('id') != job['cycle_id']
                or cycle.get('qualification_paused') or state.get('human_control')
                or _creator(cycle.get('facts', {}).get('tiktok_declarado')) != job['creator']
                or effect.get('status') not in {'pending', 'running'}
                or effect.get('type') != 'tiktok_operation' or effect.get('cycle_id') != job['cycle_id']
                or effect.get('operation') != job['operation'] or _creator(effect.get('creator')) != job['creator']
                or effect.get('payload') != job['payload']):
            return False
        proof = state.get('contact_sync_proof') or {}
        try:
            creator_uuid = UUID(state.get('creator_id'))
            creator_valid = bool(creator_uuid.int) and str(creator_uuid) == state.get('creator_id')
        except (TypeError, ValueError, AttributeError):
            creator_valid = False
        revision = state.get('revision')
        if (not creator_valid or type(revision) is not int or revision < 1
                or proof.get('creator_id') != state.get('creator_id')
                or proof.get('atendimento_id') != job['cycle_id'] or proof.get('revision') != revision
                or not isinstance(proof.get('event_id'), str)):
            return False
        confirmed = self.repository.get_operation(proof['event_id'] + ':contact:' + str(revision))
        source_event = self.repository.event(proof['event_id'])
        if (not source_event or source_event.get('conversation_key') != job['conversation_key']
                or not confirmed or confirmed.get('status') != 'completed'
                or not isinstance(confirmed.get('result'), dict)):
            return False
        if any(confirmed['result'].get(key) != proof.get(key) for key in ('creator_id', 'atendimento_id', 'event_id', 'revision')):
            return False
        if job['operation'] == 'invite':
            from real_journey import policy_valid, precheck_proven, _policy_fingerprint
            policy, consent = policy_for(self.settings), cycle.get('invite_consent') or {}
            if (cycle.get('pending_profile_changes') or not policy_valid(policy)
                    or not precheck_proven(state, now=now) or effect.get('confirmed') is not True
                    or cycle.get('facts', {}).get('consentimento_convite') is not True
                    or consent != effect.get('consent') or consent.get('cycle_id') != cycle['id']
                    or consent.get('policy_hash') != _policy_fingerprint(policy)
                    or effect.get('policy_hash') != consent.get('policy_hash')):
                return False
        return True

    def _authorized(self, job):
        with self.lock_for(job['conversation_key']):
            state = self.repository.load_session(job['conversation_key'])
            if not self._valid(job, state, self.clock()):
                self.last_guard = 'stale_cycle_or_scope'
                return False
            result = self.guard(job['event'])
            self.last_guard = result.get('reason', 'human_control_unverified') if isinstance(result, dict) else 'human_control_unverified'
            return isinstance(result, dict) and result.get('allowed') is True

    @staticmethod
    def _signature(result):
        # Poll timestamps do not create a new notification/history entry.
        payload = {key: result.get(key) for key in ('operation', 'creator', 'status', 'confirmed', 'evidence', 'reason')}
        if result.get('operation') == 'relationship' and result.get('status') in {'pending', 'not_found'}:
            payload.pop('evidence', None)
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def tick(self):
        """One job per call. Tests can exercise this without starting a thread."""
        if not effects_allowed(settings=self.settings):
            return {'status': 'disabled', 'reason': 'nonproduction_external_effects_disabled'}
        if (self.settings.get('tiktok_mode') != 'real' or self.settings.get('real_worker_enabled') is not True
                or not self.configured()):
            return {'status': 'disabled'}
        now = self.clock()
        job = self.repository.claim_real_job(_stamp(now))
        if not job:
            return {'status': 'idle'}
        if job['status'] != 'result_ready':
            if not self._authorized(job):
                self.repository.finish_real_job(job['job_key'], 'cancelled', _stamp(self.clock()))
                return {'status': 'cancelled'}
            if job['attempts'] > 6:
                self.repository.finish_real_job(job['job_key'], 'completed', _stamp(self.clock()))
                return {'status': 'poll_limit_reached'}
            try:
                kwargs = {}
                if job['operation'] == 'invite':
                    kwargs = {'confirmed': True, 'commission': job['payload'].get('commission'),
                              'before_write': lambda: self._authorized(job)}
                result = self.client.execute(job['operation'], job['creator'], **kwargs)
                if not isinstance(result, dict):
                    raise ValueError('invalid client result')
            except Exception:
                result = {'operation': job['operation'], 'creator': job['creator'],
                          'status': 'outcome_unknown' if job['operation'] == 'invite' else 'failed',
                          'confirmed': False, 'observed_at': _stamp(self.clock()), 'evidence': {},
                          'reason': 'executor_result_unconfirmed'}
            self.repository.set_real_result(job['job_key'], result, _stamp(self.clock()))
            job = self.repository.real_job(job['job_key'])
        return self._apply(job)

    def _notify_failure(self, job):
        if callable(self.failure_notice):
            try:
                self.failure_notice(job)
            except Exception:
                pass

    def _apply(self, job):
        require_effects(settings=self.settings)
        result, now = job.get('result'), self.clock()
        if not isinstance(result, dict):
            self.repository.finish_real_job(job['job_key'], 'outcome_unknown', _stamp(now))
            return {'status': 'outcome_unknown'}
        signature = self._signature(result)
        with self.lock_for(job['conversation_key']):
            state = self.repository.load_session(job['conversation_key'])
            if not self._valid(job, state, now):
                self.repository.finish_real_job(job['job_key'], 'cancelled', _stamp(now))
                return {'status': 'stale_result'}
            control = self.guard(job['event'])
            self.last_guard = control.get('reason', 'human_control_unverified') if isinstance(control, dict) else 'human_control_unverified'
            if not isinstance(control, dict) or control.get('allowed') is not True:
                self.repository.finish_real_job(job['job_key'], 'cancelled', _stamp(now))
                return {'status': 'human_control_blocked'}
            if signature != job.get('last_signature'):
                # Reserve the result's own outbox/application before SQL or reply.
                event_key = job['job_key'] + ':result:' + job['effect_id'] + ':' + str(job['attempts'])
                reservation = self.repository.reserve_event(event_key, job['conversation_key'], signature)
                if not reservation.get('reserved'):
                    self.repository.finish_real_job(job['job_key'], 'outcome_unknown', _stamp(now))
                    return {'status': 'application_outcome_unknown'}
                try:
                    applied = self.apply_result(job, state, result, event_key)
                except Exception as error:
                    # Keep the failure visible without logging the provider
                    # body, conversation text, credentials or form links.
                    self.last_error = 'result_application_unconfirmed'
                    logging.getLogger(__name__).warning('real_result_application_failed operation=%s error_type=%s',
                                                       job['operation'], type(error).__name__)
                    self.repository.finish_event(event_key, 'outcome_unknown')
                    self.repository.finish_real_job(job['job_key'], 'outcome_unknown', _stamp(self.clock()))
                    self._notify_failure(job)
                    return {'status': 'application_outcome_unknown'}
                if not isinstance(applied, dict) or applied.get('ignored'):
                    if isinstance(applied, dict) and applied.get('reason') == 'operation_evidence_missing_or_stale':
                        self._notify_failure(job)
                    self.repository.finish_event(event_key, 'failed')
                    self.repository.finish_real_job(job['job_key'], 'cancelled', _stamp(self.clock()))
                    return {'status': 'result_rejected'}
            # One current row and bounded polling. A write is never polled/retried.
            live = self.repository.load_session(job['conversation_key'])
            effect = live.get('effects', {}).get(job['effect_id']) or {}
            pending_read = (job['operation'] == 'relationship' and result.get('status') in {'pending', 'not_found'}
                            and not (self.settings.get('relationship_check_in_form') is True
                                     and (job.get('payload') or {}).get('source') == 'form')
                            and effect.get('status') == 'pending')
            poll = pending_read and job['attempts'] < 6
            delay = (15, 30, 60, 120, 300, 600)[min(job['attempts'] - 1, 5)]
            if pending_read and not poll:
                # This changes only the local technical effect. It does not
                # renew the cycle, advance its phase/revision or write SQL.
                self.repository.park_real_read(job, live, _stamp(self.clock()), signature)
            else:
                self.repository.finish_real_job(job['job_key'], 'polling' if poll else 'completed', _stamp(self.clock()),
                                                next_run_at=_stamp(self.clock() + timedelta(seconds=delay)), signature=signature)
            return {'status': 'polling' if poll else 'completed'}

    def start(self):
        if not effects_allowed(settings=self.settings):
            self.last_error = 'nonproduction_external_effects_disabled'
            return False
        if self.thread and self.thread.is_alive():
            return False
        if (self.settings.get('tiktok_mode') != 'real' or self.settings.get('real_worker_enabled') is not True
                or not self.configured()):
            return False
        path = Path(self.settings.get('state_dir', '/data')) / 'real-worker.lock'
        handle = path.open('a+b')
        try:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except ImportError:
                import msvcrt
                handle.seek(0)
                if not handle.read(1):
                    handle.write(b'0'); handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            handle.close()
            self.last_error = 'worker_already_owned'
            return False
        self._ownership_file = handle
        recovered = self.repository.recover_real_jobs(_stamp(self.clock()))
        if isinstance(recovered, dict) and any(recovered.values()):
            logging.getLogger(__name__).warning('real_job_recovery %s', json.dumps(recovered, sort_keys=True))
        self.thread = threading.Thread(target=self._run, name='v5-real-operations', daemon=True)
        self.thread.start()
        return True

    def _run(self):
        require_effects(settings=self.settings)
        try:
            while not self.stop_event.is_set():
                try:
                    checked = _clock(self.sessions_checked_at)
                    if not checked or (self.clock() - checked).total_seconds() >= 60:
                        self.probe_sessions()
                    outcome = self.tick()
                    if outcome.get('status') == 'idle':
                        self.maintain_retention()
                        if callable(self.followup_tick):
                            self.followup_tick()
                    if outcome.get('status') in {'completed', 'polling'}:
                        self.last_error = None
                except Exception:
                    self.last_error = 'worker_step_unconfirmed'
                self.wake_event.wait(2)
                self.wake_event.clear()
        finally:
            if self._ownership_file:
                self._ownership_file.close()
                self._ownership_file = None

    def wake(self):
        self.wake_event.set()

    def maintain_retention(self):
        """Daily, durable bounded maintenance in the existing worker only.

        Cleanup recomputes idempotent eligibility on every invocation. A failure
        waits at least an hour; a crashed claim waits a day. No message, job,
        email, invitation or login is generated here.
        """
        if not effects_allowed(settings=self.settings):
            return {'status': 'disabled', 'reason': 'nonproduction_external_effects_disabled'}
        if (self.settings.get('retention_enabled') is not True
                or self.settings.get('tiktok_mode') != 'real'
                or self.settings.get('real_worker_enabled') is not True):
            return {'status': 'disabled'}
        outcomes = {}
        for task in ('sqlite_retention', 'sql_retention'):
            if task == 'sql_retention' and (self.settings.get('contact_sync_enabled') is not True
                                           or not callable(self.retention_cleanup)):
                outcomes[task] = 'unconfigured'
                continue
            at = _stamp(self.clock())
            claim = self.repository.claim_maintenance(task, at)
            if claim is None:
                continue
            success, state, counts, has_more = False, claim['state'], {}, False
            try:
                if task == 'sqlite_retention':
                    result = self.repository.retention_pass(at, limit=100,
                                    after_key=state.get('after_key', ''))
                    state = {'after_key': result.pop('next_after_key')}
                    has_more = bool(state['after_key'])
                    counts = result
                else:
                    receipt = self.retention_cleanup()
                    if (not isinstance(receipt, dict) or type(receipt.get('has_more')) is not bool
                            or receipt.keys() != {'technical_deleted', 'summaries_deleted', 'total_deleted', 'has_more'}):
                        raise ValueError('invalid retention receipt')
                    counts = {key: value for key, value in receipt.items() if key != 'has_more'}
                    if (any(type(value) is not int or not 0 <= value <= 1000 for value in counts.values())
                            or counts['total_deleted'] != counts['technical_deleted'] + counts['summaries_deleted']):
                        raise ValueError('invalid retention counts')
                    has_more = receipt['has_more']
                    state = {}
                success = True
            except Exception:
                outcomes[task] = 'unconfirmed'
            self.repository.finish_maintenance(task, _stamp(self.clock()), success=success, state=state, has_more=has_more)
            outcomes[task] = 'completed' if success else 'unconfirmed'
            safe_counts = {key: value for key, value in counts.items() if type(value) is int}
            logging.getLogger(__name__).info('retention_maintenance task=%s status=%s counts=%s',
                                           task, outcomes[task], json.dumps(safe_counts, sort_keys=True))
        if outcomes:
            self.retention_status = {'enabled': True, 'status': 'unconfirmed' if 'unconfirmed' in outcomes.values()
                                    else 'completed', 'last_run_at': _stamp(self.clock()), 'tasks': outcomes}
        return {'status': 'checked', 'tasks': outcomes}

    def stop(self):
        self.stop_event.set()
        self.wake_event.set()
