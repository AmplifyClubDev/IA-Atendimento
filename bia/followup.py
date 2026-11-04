"""Pilot reminders and optional 5+5 closure; no AI call or uncertain-send retry."""

from offline_policy import effects_allowed, require_effects
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import re

from contracts import allow_inbound, inbound_key, phone_matches
from real_operations import policy_for

CONVERSATION = 'chatwoot:1:26097'
WAITING = frozenset({'intro', 'origin', 'tiktok', 'shop', 'agency', 'consent_real', 'await_acceptance', 'form'})


def clock(value):
    try:
        if type(value) in (int, float):
            return datetime.fromtimestamp(value, timezone.utc)
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (AttributeError, TypeError, ValueError, OverflowError, OSError):
        return None


def configured(settings):
    if not effects_allowed(settings=settings):
        return False
    gate = settings.get('gate') or {}
    baseline = clock(settings.get('followup_start_at'))
    return (settings.get('followup_enabled') is True
            and str(settings.get('followup_delay_seconds')) == '300'
            and baseline is not None
            and isinstance(settings.get('followup_start_at'), str)
            and re.search(r'(?:Z|\+00:00)$', settings['followup_start_at']) is not None
            and settings.get('tiktok_mode') == 'real' and settings.get('real_worker_enabled') is True
            and settings.get('contact_sync_enabled') is True and settings.get('conversation_enabled') is True
            and gate.get('enabled') is True and gate.get('provider') == 'chatwoot'
            and str(gate.get('account_id')) == '1' and str(gate.get('inbox_id')) == '3'
            and gate.get('phone') == '+5547991154859'
            and (settings.get('inactivity_close_enabled') is not True
                 or str(settings.get('inactivity_close_delay_seconds')) == '300'))


def sequence_keys(cycle_id, source_key):
    """One warning/closure pair per actual inbound pause, never a replay key."""
    if not isinstance(cycle_id, str) or not cycle_id or not re.fullmatch(r'chatwoot:1:[1-9][0-9]{0,19}', source_key or ''):
        raise ValueError('invalid inactivity episode')
    digest = hashlib.sha256(('pilot-inactivity-v2:' + cycle_id + ':' + source_key).encode()).hexdigest()
    return 'inactivity-warning:' + digest, 'inactivity-close:' + digest


def reminder(state, settings):
    """Use the confirmed current question, never guess a missing provider result."""
    from real_journey import _consent_prompt, _policy_fingerprint, policy_valid
    cycle = state['cycle']
    phase = cycle.get('phase')
    texts = {
        'intro': 'Sigo por aqui se precisar 💙 O que você gostaria de conhecer sobre a Amplify?',
        'origin': 'Para seguirmos: como você conheceu a Amplify? 😊 Se preferir, pode não informar.',
        'tiktok': 'Me passa seu @ do TikTok para eu conferir o caminho do agenciamento? 😊',
        'shop': 'Você sabe se o seu TikTok Shop Creator já está ativo?',
        'agency': 'Você tem vínculo com alguma agência atualmente?',
        'await_acceptance': 'Conseguiu encontrar o convite da Amplify em *Parcerias* ou *Notificações* do TikTok Shop Creator? 😊',
    }
    if phase == 'consent_real':
        policy = policy_for(settings)
        offer = cycle.get('invite_offer') or {}
        if (not policy_valid(policy) or offer.get('policy_hash') != _policy_fingerprint(policy)
                or offer.get('creator') != cycle.get('facts', {}).get('tiktok_declarado')):
            return None
        return _consent_prompt(deepcopy(cycle), policy), ['Autorizo enviar o convite']
    if phase == 'form':
        url = cycle.get('form_url')
        # Only an already-issued private link may be repeated; never mint one.
        if not isinstance(url, str) or not re.fullmatch(
                r'https://amplify-cadastro\.up\.railway\.app/cadastro/ensaio#s=[A-Za-z0-9_-]{43}', url):
            return None
        return 'Conseguiu abrir seu cadastro? Confira e complete seus dados por aqui: ' + url, []
    return (texts[phase], []) if phase in texts else None


class Followup:
    def __init__(self, repository, settings, transport, lock_for, guard, *, now=None, close_for_inactivity=None):
        self.repository, self.settings, self.transport = repository, settings, transport
        self.lock_for, self.guard = lock_for, guard
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.last_status = 'not_run'
        self.last_tick_at = None
        self.next_probe_at = None
        self.close_for_inactivity = close_for_inactivity
        self.last_stage = None
        self.close_due_at = None

    def status(self):
        baseline = clock(self.settings.get('followup_start_at'))
        return {'enabled': self.settings.get('followup_enabled') is True,
                'configured': configured(self.settings), 'status': self.last_status,
                'delay_seconds': 300 if str(self.settings.get('followup_delay_seconds')) == '300' else None,
                'start_at': baseline.isoformat() if baseline else None, 'last_tick_at': self.last_tick_at,
                'inactivity_close_enabled': self.settings.get('inactivity_close_enabled') is True,
                'inactivity_close_delay_seconds': 300 if str(self.settings.get('inactivity_close_delay_seconds')) == '300' else None,
                'inactivity_callback_configured': callable(self.close_for_inactivity),
                'last_stage': self.last_stage, 'close_due_at': self.close_due_at}

    def _eligible(self, source, state, now):
        cycle = state.get('cycle') or {}
        # The SDR has handed off to the existing form. Its original 24-hour
        # deadline stays intact; the chat test's 5+5 must not revoke it while
        # the person accepts the invitation or fills the form.
        if self.settings.get('relationship_check_in_form') is True and cycle.get('phase') == 'form':
            return False
        event = source.get('event') or {}
        created, expires = clock(event.get('created_at')), clock(cycle.get('expires_at'))
        last, baseline = clock(cycle.get('last_inbound_at')), clock(self.settings.get('followup_start_at'))
        processed = state.get('processed_inbound') or []
        if (not configured(self.settings) or cycle.get('mode') != 'real' or cycle.get('status') != 'open'
                or cycle.get('phase') not in WAITING or source.get('cycle_id') != cycle.get('id')
                or type(state.get('revision')) is not int or state['revision'] < 1
                or not allow_inbound(self.settings.get('gate'), event) or str(event.get('contact_id')) != '3'
                or str(event.get('conversation_id')) != '26097' or inbound_key(event) != source.get('event_key')
                or not processed or processed[-1] != source.get('event_key')
                or not all((created, expires, last, baseline)) or not baseline < created <= last <= now
                or not timedelta(seconds=300) <= now-created < timedelta(hours=24) or now >= expires
                or state.get('human_control') or cycle.get('qualification_paused') or cycle.get('pending_profile_changes')
                or state.get('cadastro_situacao') == 'confirmado' or cycle.get('opt_out') or state.get('opt_out')):
            return False
        if any(isinstance(effect, dict) and effect.get('cycle_id') == cycle.get('id')
               and effect.get('status') in {'pending', 'running', 'outcome_unknown'}
               for effect in (state.get('effects') or {}).values()):
            return False
        if any(isinstance(result, dict) and result.get('status') == 'outcome_unknown'
               for result in (cycle.get('real_operations') or {}).values()):
            return False
        if cycle.get('phase') == 'await_acceptance':
            from real_journey import _operation_proven
            if not any(_operation_proven(state, operation, status, now=now, maximum_age_seconds=86400)
                       for operation, status in (('invite', 'sent'), ('invite', 'pending'), ('relationship', 'pending'))):
                # Accepted POST / parked reads are not proof that an invitation
                # is available to the lead. Never ask them to act on uncertainty.
                return False
        source_row = self.repository.event(source['event_key'])
        proof = state.get('contact_sync_proof') or {}
        receipt = self.repository.get_operation(str(proof.get('event_id')) + ':contact:' + str(state.get('revision')))
        expected = {'creator_id': state.get('creator_id'), 'atendimento_id': cycle.get('id'),
                    'event_id': proof.get('event_id'), 'revision': state.get('revision')}
        return bool(source_row and source_row.get('status') == 'completed'
                    and source_row.get('conversation_key') == CONVERSATION and state.get('creator_id')
                    and receipt and receipt.get('status') == 'completed'
                    and all(proof.get(key) == value and (receipt.get('result') or {}).get(key) == value
                            for key, value in expected.items())
                    and self.repository.followup_clear(CONVERSATION, state))

    def _source_unchanged(self, event, state, *, contact_verified=False):
        """Fresh provider read catches messages not yet processed by the webhook."""
        if self.repository.load_session(CONVERSATION) != state:
            return False
        headers = {'api_access_token': self.transport.token, 'Accept': 'application/json'}
        data = self.transport.http(method='GET', url=self.transport._conversation_url(event) + '/messages?limit=20',
                                   headers=headers, timeout=8)
        messages = data.get('payload') if isinstance(data, dict) else None
        if not isinstance(messages, list) or not 0 < len(messages) <= 20:
            return False
        accepted_ids = self.repository.followup_accepted_message_ids(CONVERSATION, state['cycle']['opened_at'])
        found = []
        for msg in messages:
            if not isinstance(msg, dict) or not re.fullmatch(r'[1-9][0-9]{0,19}', str(msg.get('id', ''))):
                return False
            incoming = msg.get('message_type') == 'incoming' or type(msg.get('message_type')) is int and msg['message_type'] == 0
            if incoming and int(msg['id']) > int(event['message_id']):
                return False
            outgoing = msg.get('message_type') == 'outgoing' or type(msg.get('message_type')) is int and msg['message_type'] == 1
            if (outgoing and msg.get('private') is not True and int(msg['id']) > int(event['message_id'])
                    and str(msg['id']) not in accepted_ids):
                return False
            if str(msg['id']) == str(event['message_id']):
                found.append(msg)
        if len(found) != 1:
            return False
        msg, sender = found[0], found[0].get('sender') or {}
        created = clock(msg.get('created_at'))
        expected = clock(event.get('created_at'))
        phone_verified = (phone_matches(self.settings['gate']['phone'], sender['phone_number'])
                          if 'phone_number' in sender else contact_verified is True)
        return bool((msg.get('message_type') == 'incoming' or type(msg.get('message_type')) is int and msg['message_type'] == 0)
                    and msg.get('private') is False and str(msg.get('conversation_id')) == '26097'
                    and str(sender.get('id')) == '3' and sender.get('type', 'contact').lower() == 'contact'
                    and phone_verified
                    and (msg.get('account_id') is None or str(msg['account_id']) == '1')
                    and (msg.get('inbox_id') is None or str(msg['inbox_id']) == '3')
                    and msg.get('content') == event.get('text') and created and expected
                    and abs((created-expected).total_seconds()) < 1
                    and self.repository.load_session(CONVERSATION) == state)

    def tick(self):
        if not effects_allowed(settings=self.settings):
            return {'status': 'disabled', 'reason': 'nonproduction_external_effects_disabled'}
        outcome = self._tick()
        self.last_status = outcome['status']
        self.last_stage = outcome.get('stage')
        self.close_due_at = outcome.get('close_due_at')
        current = clock(self.now())
        self.last_tick_at = current.isoformat() if current else None
        return outcome

    def _tick(self):
        if self.settings.get('inactivity_close_enabled') is True:
            return self._tick_inactivity()
        if not configured(self.settings):
            return {'status': 'disabled'}
        try:
            with self.lock_for(CONVERSATION):
                source = self.repository.followup_source(CONVERSATION)
                state = self.repository.load_session(CONVERSATION)
                now = clock(self.now())
                if not source or not now or not self._eligible(source, state, now):
                    return {'status': 'idle'}
                key = 'followup:' + hashlib.sha256(('pilot-followup-v1:' + source['cycle_id']).encode()).hexdigest()
                if self.repository.get_operation(key):
                    return {'status': 'already_reserved'}
                if self.next_probe_at and now < self.next_probe_at:
                    return {'status': 'cooldown'}
                delivery = self.repository.conversation_delivery_context(CONVERSATION, state['cycle']['opened_at'])
                if not delivery.get('last_accepted_reply') or delivery.get('latest_attempt_status') != 'accepted':
                    return {'status': 'blocked'}
                last_reply_at = clock(delivery['last_accepted_reply'].get('at'))
                if not last_reply_at or not timedelta(seconds=300) <= now-last_reply_at:
                    # A slow provider may have just produced the real answer;
                    # never follow that fresh reply with an immediate nudge.
                    return {'status': 'idle'}
                payload = reminder(state, self.settings)
                if payload is None:
                    return {'status': 'blocked'}
                # Provider/control reads are bounded during a prolonged pause;
                # an unavailable source never produces repeated send attempts.
                self.next_probe_at = now + timedelta(seconds=30)
                control = self.guard(source['event'])
                if not isinstance(control, dict) or control.get('allowed') is not True:
                    return {'status': 'blocked'}
                if not self._source_unchanged(source['event'], state, contact_verified=True):
                    return {'status': 'source_changed'}
                body = {'text': payload[0], 'buttons': payload[1]}
                if not self.repository.reserve_followup(CONVERSATION, source, state, key, body):
                    return {'status': 'blocked'}
                def before_write():
                    current = clock(self.now())
                    control = self.guard(source['event'])
                    return bool(current and current < clock(state['cycle']['expires_at'])
                                and current-clock(source['event']['created_at']) < timedelta(hours=24)
                                and isinstance(control, dict) and control.get('allowed') is True
                                and self._source_unchanged(source['event'], state, contact_verified=True))
                try:
                    receipt = self.transport.send_reply(source['event'], payload[0], payload[1], key,
                                                        before_write=before_write)
                except Exception:
                    receipt = {'status': 'outcome_unknown', 'reason': 'followup_send_unconfirmed'}
                status = receipt.get('status') if isinstance(receipt, dict) else None
                status = status if status in {'accepted', 'failed', 'outcome_unknown'} else 'outcome_unknown'
                safe = {name: receipt[name][:240] for name in ('status', 'message_id', 'reason')
                        if isinstance(receipt, dict) and isinstance(receipt.get(name), str)}
                self.repository.finish_outbox(key, status, safe)
                self.repository.complete_operation(key, safe, 'completed' if status == 'accepted' else status)
                self.last_status = status
                return {'status': status}
        except Exception:
            self.last_status = 'unconfirmed'
            return {'status': 'unconfirmed'}

    def _accepted(self, key, source, *, warning=None):
        """Both durable receipts must agree; an accepted POST alone is insufficient."""
        operation = self.repository.get_operation(key)
        if (not operation or operation.get('kind') != 'followup' or operation.get('status') != 'completed'
                or operation.get('event_key') != source['event_key']):
            return None
        receipt = operation.get('result')
        if (not isinstance(receipt, dict) or receipt.get('status') != 'accepted'
                or receipt.get('cycle_id') != source['cycle_id'] or receipt.get('source_key') != source['event_key']
                or not re.fullmatch(r'[1-9][0-9]{0,19}', str(receipt.get('message_id', '')))
                or not clock(receipt.get('accepted_at'))):
            return None
        if warning is not None and (receipt.get('warning_key') != warning[0]
                or receipt.get('warning_accepted_at') != warning[1]['accepted_at']):
            return None
        rows = [row for row in self.repository.outbox(source['event_key']) if row.get('outbox_key') == key]
        if len(rows) != 1 or rows[0].get('status') != 'accepted' or rows[0].get('receipt') != receipt:
            return None
        return receipt

    def _send_inactivity(self, source, state, key, text, buttons, *, warning=None):
        body = {'text': text, 'buttons': buttons}
        if not self.repository.reserve_followup(CONVERSATION, source, state, key, body):
            return {'status': 'blocked'}
        def before_write():
            current = clock(self.now())
            control = self.guard(source['event'])
            # The just-reserved outbox is deliberately outcome_unknown. Do not
            # reject our own reservation through the general uncertainty gate.
            # The immutable state/source plus the live recipient guard are
            # rechecked immediately before this one write, as in the legacy path.
            return bool(current and configured(self.settings)
                and current < clock(state['cycle']['expires_at'])
                and current-clock(source['event']['created_at']) < timedelta(hours=24)
                and isinstance(control, dict) and control.get('allowed') is True
                and self._source_unchanged(source['event'], state, contact_verified=True)
                and (warning is None or self._accepted(warning[0], source)
                     and current-clock(warning[1]['accepted_at']) >= timedelta(seconds=300)))
        try:
            receipt = self.transport.send_reply(source['event'], text, buttons, key, before_write=before_write)
        except Exception:
            receipt = {'status': 'outcome_unknown', 'reason': 'inactivity_send_unconfirmed'}
        status = receipt.get('status') if isinstance(receipt, dict) else None
        status = status if status in {'accepted', 'failed', 'outcome_unknown'} else 'outcome_unknown'
        safe = {name: receipt[name][:240] for name in ('status', 'message_id', 'reason')
                if isinstance(receipt, dict) and isinstance(receipt.get(name), str)}
        safe.update(cycle_id=source['cycle_id'], source_key=source['event_key'])
        if status == 'accepted':
            accepted = clock(self.now())
            if not accepted:
                status = 'outcome_unknown'
                safe.update(status=status, reason='inactivity_clock_unconfirmed')
            else:
                safe['accepted_at'] = accepted.isoformat()
        if warning is not None:
            safe.update(warning_key=warning[0], warning_accepted_at=warning[1]['accepted_at'])
        self.repository.finish_outbox(key, status, safe)
        self.repository.complete_operation(key, safe, 'completed' if status == 'accepted' else status)
        return {'status': status}

    def _finish_inactivity(self, source, state, warning_key, closure_key, now):
        control = self.guard(source['event'])
        if (not isinstance(control, dict) or control.get('allowed') is not True
                or not self._source_unchanged(source['event'], state, contact_verified=True)):
            return {'status': 'source_changed', 'stage': 'closure'}
        result = self.close_for_inactivity(source['event'], source['cycle_id'], source['event_key'],
                                         warning_key, closure_key, now=now)
        status = result.get('status') if isinstance(result, dict) else None
        return {'status': 'closed' if status == 'closed' else 'source_changed' if status == 'stale' else 'unconfirmed',
                'stage': 'closure'}

    def _tick_inactivity(self):
        if not configured(self.settings) or not callable(self.close_for_inactivity):
            return {'status': 'disabled', 'stage': 'inactivity'}
        try:
            with self.lock_for(CONVERSATION):
                source = self.repository.followup_source(CONVERSATION)
                state = self.repository.load_session(CONVERSATION)
                now = clock(self.now())
                cycle = state.get('cycle') or {}
                if (not source or not now or source.get('cycle_id') != cycle.get('id')
                        or source.get('event_key') != (state.get('processed_inbound') or [None])[-1]):
                    return {'status': 'idle', 'stage': 'inactivity'}
                warning_key, closure_key = sequence_keys(source['cycle_id'], source['event_key'])
                warning_row = self.repository.get_operation(warning_key)
                closure_row = self.repository.get_operation(closure_key)
                warning = self._accepted(warning_key, source) if warning_row else None
                if closure_row:
                    if not warning or not self._accepted(closure_key, source, warning=(warning_key, warning)):
                        return {'status': 'already_reserved', 'stage': 'closure'}
                    closed = cycle.get('inactivity_closure') or {}
                    if (cycle.get('status') == 'closed' and cycle.get('reason') == 'inactivity_timeout'
                            and closed.get('source_key') == source['event_key']
                            and closed.get('warning_key') == warning_key and closed.get('closure_key') == closure_key):
                        # Closing is persisted before SQL/label projection. Once
                        # terminal, never turn an uncertain projection into an
                        # automatic retry or repeat provider reads every tick.
                        return {'status': 'closed', 'stage': 'closure'}
                    return self._finish_inactivity(source, state, warning_key, closure_key, now)
                if not self._eligible(source, state, now):
                    return {'status': 'idle', 'stage': 'inactivity'}
                if warning_row:
                    if not warning:
                        return {'status': 'already_reserved', 'stage': 'warning'}
                    due = clock(warning['accepted_at']) + timedelta(seconds=300)
                    if now < due:
                        return {'status': 'awaiting_close', 'stage': 'warning', 'close_due_at': due.isoformat()}
                    text = ('Como não tivemos resposta, encerrei este atendimento por agora. '
                            'Quando quiser voltar, é só me chamar. 💙')
                    stage = 'closure'
                    buttons = []
                    key = closure_key
                else:
                    delivery = self.repository.conversation_delivery_context(CONVERSATION, cycle['opened_at'])
                    last = delivery.get('last_accepted_reply') or {}
                    if (delivery.get('latest_attempt_status') != 'accepted' or not clock(last.get('at'))
                            or now-clock(last['at']) < timedelta(seconds=300)):
                        return {'status': 'idle', 'stage': 'warning'}
                    topic = 'conhecendo a Amplify' if cycle.get('phase') == 'intro' else 'com seu atendimento'
                    text = (f'Vi que nossa conversa ficou pendente. 😊 Quer seguir {topic} ou prefere encerrar por agora? '
                            'Se ficar sem resposta por mais 5 minutos, encerro este atendimento por enquanto.')
                    buttons = ['Seguir atendimento', 'Encerrar agora']
                    key, stage = warning_key, 'warning'
                if self.next_probe_at and now < self.next_probe_at:
                    return {'status': 'cooldown', 'stage': stage}
                self.next_probe_at = now + timedelta(seconds=30)
                control = self.guard(source['event'])
                if not isinstance(control, dict) or control.get('allowed') is not True:
                    return {'status': 'blocked', 'stage': stage}
                if not self._source_unchanged(source['event'], state, contact_verified=True):
                    return {'status': 'source_changed', 'stage': stage}
                outcome = self._send_inactivity(source, state, key, text, buttons,
                    warning=(warning_key, warning) if stage == 'closure' else None)
                if stage == 'closure' and outcome['status'] == 'accepted':
                    return self._finish_inactivity(source, state, warning_key, closure_key, clock(self.now()))
                return {**outcome, 'stage': stage}
        except Exception:
            return {'status': 'unconfirmed', 'stage': 'inactivity'}
