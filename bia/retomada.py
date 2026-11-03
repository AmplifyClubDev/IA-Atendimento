"""Retomada de quem parou de responder e de quem ficou sem resposta (release 39).

Retomada: 15 min, 2 h e 23h30 depois da última mensagem do lead (dentro da
janela de 24 h do WhatsApp), uma vez cada, sempre com uma ação concreta. Nunca
logo depois de uma resposta da Bia, nunca com operação pendente ou incerta,
nunca sob controle humano/manutenção, e para quando o lead encerra.

Pós-pausa: mensagens de lead do piloto que ficaram sem nenhuma resposta da Bia
(manutenção, pausa, webhook perdido) são respondidas pelo fluxo normal,
retomando o pedido de cada um em vez de uma saudação genérica.

Nenhum caminho aqui envia convite, cria permissão ou repete uma resposta.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import re

from contracts import allow_inbound, inbound_key, pilot_phone
from followup import clock

STEPS = ((1, timedelta(minutes=15)), (2, timedelta(hours=2)), (3, timedelta(hours=23, minutes=30)))
LINKED_STEPS = ((1, timedelta(hours=2)), (2, timedelta(hours=23, minutes=30)))
MIN_GAP = timedelta(minutes=10)
WAITING = frozenset({'intro', 'origin', 'tiktok', 'shop', 'agency', 'consent_real', 'await_acceptance', 'form'})
SCAN_SECONDS = 60
CATCH_UP_MIN_AGE = timedelta(minutes=2)
CATCH_UP_MAX_AGE = timedelta(hours=23)
LISTING_PAGES = 20  # até 500 conversas abertas na caixa
# Release 41: lembretes só entre 8h e 21h de Brasília (UTC-3, sem horário de verão).
BRASILIA = timezone(timedelta(hours=-3))
SEND_HOURS = (8, 21)


def send_hour(now):
    """True das 8h às 20h59 de Brasília."""
    hour = now.astimezone(BRASILIA).hour
    return SEND_HOURS[0] <= hour < SEND_HOURS[1]


def enabled(settings, name):
    """config.load_settings liga por padrão; V5_RETOMADA_ENABLED=false ou V5_POS_PAUSA_ENABLED=false desligam."""
    return (settings.get(name) is True and settings.get('tiktok_mode') == 'real'
            and settings.get('real_worker_enabled') is True and settings.get('conversation_enabled') is True
            and (settings.get('gate') or {}).get('enabled') is True)


def steps_for(state):
    """Vínculo confirmado sem cadastro: 2 h e 23h30 (a janela do WhatsApp não permite 72 h)."""
    from real_journey import _linked
    return LINKED_STEPS if _linked((state.get('cycle') or {})) else STEPS


def message(state, step, policy):
    """O lembrete da etapa atual, sempre com uma ação concreta e um ângulo novo; None se não couber."""
    import conversao
    from real_journey import PUBLIC_FORM_URL, _first_name, _invite_known, _linked, _policy_fingerprint, policy_valid
    cycle = state.get('cycle') or {}
    facts, phase = cycle.get('facts') or {}, cycle.get('phase')
    if state.get('cadastro_situacao') == 'confirmado' or cycle.get('acesso_liberado'):
        return None
    name = _first_name(cycle)
    hello = 'Oi' + (', ' + name if name else '') + '! '
    if _linked(cycle):
        return conversao.registration_reminder(step, name, PUBLIC_FORM_URL), []
    if phase in {'await_acceptance', 'form'} or _invite_known(cycle):
        text = (hello + 'Conseguiu aceitar o convite da *Amplify* no TikTok? Ele fica em *Parcerias* ou '
                '*Notificações* do TikTok Shop Creator. Quando aceitar, me manda “aceitei” que eu confiro na hora.'
                if step == 1 else
                hello + 'Seu convite da *Amplify* continua no TikTok. Aceitando, você já pode fazer o cadastro e '
                'entrar no Club. Depois de aceitar, me manda “aceitei” 😊')
        if step == len(STEPS):
            text += '\n\nSe preferir parar por aqui, é só me dizer “encerrar atendimento”.'
        return text, ['Já aceitei']
    if phase == 'consent_real':
        offer = cycle.get('invite_offer') or {}
        if (not policy_valid(policy) or offer.get('policy_hash') != _policy_fingerprint(policy)
                or offer.get('creator') != facts.get('tiktok_declarado')):
            return None
        return hello + conversao.consent_reminder(step, policy), list(conversao.CONSENT_BUTTONS)
    if not facts.get('tiktok_declarado') and phase in {'intro', 'origin', 'tiktok', 'shop', 'agency'}:
        text, buttons = conversao.intro_reminder(step)
        return hello + text, buttons
    return None


def step_key(cycle_id, source_key, step):
    digest = hashlib.sha256(('retomada-v1:' + cycle_id + ':' + source_key + ':' + str(step)).encode()).hexdigest()
    return 'retomada:' + digest


class Retomada:
    def __init__(self, repository, settings, transport, lock_for, guard, *, now=None, policy=None, registration=None):
        self.repository, self.settings, self.transport = repository, settings, transport
        self.lock_for, self.guard = lock_for, guard
        # Release 41: lê a ficha antes de cada lembrete (Cristiane, 56935: "convite continua" depois do acesso).
        self.registration = registration
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.policy = policy or (lambda: None)
        self.next_scan_at = None
        self.last = {'status': 'not_run'}

    def status(self):
        return {'enabled': enabled(self.settings, 'retomada_enabled'), **self.last}

    def tick(self):
        now = clock(self.now())
        if not enabled(self.settings, 'retomada_enabled') or not now:
            return {'status': 'disabled'}
        if self.next_scan_at and now < self.next_scan_at:
            return {'status': 'cooldown'}
        self.next_scan_at = now + timedelta(seconds=SCAN_SECONDS)
        sent = 0
        for conv in self.repository.followup_conversations():
            try:
                outcome = self._conversation(conv, now)
            except Exception:
                outcome = {'status': 'unconfirmed'}
            sent += outcome.get('status') == 'accepted'
        self.last = {'status': 'completed', 'at': now.isoformat(), 'sent': sent}
        return dict(self.last)

    def _due(self, state, source, now):
        """Maior etapa vencida ainda não reservada para esta última mensagem do lead."""
        cycle = state.get("cycle") or {}
        last_inbound = clock(cycle.get("last_inbound_at"))
        if not last_inbound:
            return None
        due = [step for step, after in steps_for(state) if now - last_inbound >= after]
        if not due or self.repository.get_operation(step_key(cycle['id'], source['event_key'], due[-1])):
            return None
        return due[-1]

    def _conversation(self, conv, now):
        with self.lock_for(conv):
            source = self.repository.followup_source(conv)
            state = self.repository.load_session(conv)
            cycle = state.get('cycle') or {}
            event = (source or {}).get('event') or {}
            expires = clock(cycle.get('expires_at'))
            if (not source or source.get('cycle_id') != cycle.get('id') or cycle.get('mode') != 'real'
                    or cycle.get('status') != 'open' or cycle.get('phase') not in WAITING
                    or not expires or now >= expires
                    or (state.get('processed_inbound') or [None])[-1] != source.get('event_key')
                    or not allow_inbound(self.settings.get('gate'), event) or inbound_key(event) != source.get('event_key')
                    or state.get('human_control') or cycle.get('qualification_paused') or cycle.get('pending_profile_changes')
                    or state.get('opt_out') or cycle.get('opt_out')):
                return {'status': 'idle'}
            step = self._due(state, source, now)
            if step is None:
                return {'status': 'idle'}
            if not send_hour(now):
                # A etapa vencida espera as 8h; as anteriores se juntam nela (nunca dois lembretes seguidos).
                return {'status': 'quiet_hours'}
            delivery = self.repository.conversation_delivery_context(conv, cycle['opened_at'])
            last_reply = clock((delivery.get('last_accepted_reply') or {}).get('at'))
            if (delivery.get('latest_attempt_status') != 'accepted' or not last_reply
                    or now - last_reply < MIN_GAP or not self.repository.followup_clear(conv, state)):
                return {'status': 'idle'}
            if callable(self.registration):
                situation = self.registration(event)
                if not isinstance(situation, str):
                    # Sem ler a ficha, nenhum lembrete: ele pode contradizer um cadastro já feito.
                    return {'status': 'unconfirmed'}
                if situation != state.get('cadastro_situacao'):
                    state['cadastro_situacao'] = situation
                    self.repository.save_session(conv, state)
            payload = message(state, step, self.policy())
            if payload is None:
                return {'status': 'idle'}
            control = self.guard(event)
            if not isinstance(control, dict) or control.get('allowed') is not True:
                return {'status': 'blocked'}
            if not self._source_unchanged(event, state, conv):
                return {'status': 'source_changed'}
            key = step_key(cycle['id'], source['event_key'], step)
            # Earlier missed steps are retired with this one: never two nudges in a row.
            if not self.repository.reserve_followup(conv, source, state, key, {'text': payload[0], 'buttons': payload[1]}):
                return {'status': 'blocked'}
            for earlier, _ in steps_for(state)[:step - 1]:
                retired = step_key(cycle['id'], source['event_key'], earlier)
                if self.repository.reserve_operation(retired, source['event_key'], 'followup'):
                    self.repository.complete_operation(retired, {'status': 'skipped'}, 'completed')

            def before_write():
                current = clock(self.now())
                control = self.guard(event)
                return bool(current and current < expires and isinstance(control, dict)
                            and control.get('allowed') is True and self._source_unchanged(event, state, conv))
            try:
                receipt = self.transport.send_reply(event, payload[0], payload[1], key, before_write=before_write)
            except Exception:
                receipt = {'status': 'outcome_unknown', 'reason': 'retomada_send_unconfirmed'}
            status = receipt.get('status') if isinstance(receipt, dict) else None
            status = status if status in {'accepted', 'failed', 'outcome_unknown'} else 'outcome_unknown'
            safe = {name: receipt[name][:240] for name in ('status', 'message_id', 'reason')
                    if isinstance(receipt, dict) and isinstance(receipt.get(name), str)}
            safe.update(cycle_id=cycle['id'], source_key=source['event_key'], step=step)
            self.repository.finish_outbox(key, status, safe)
            self.repository.complete_operation(key, safe, 'completed' if status == 'accepted' else status)
            if status == 'accepted':
                live = self.repository.load_session(conv)
                if (live.get('cycle') or {}).get('id') == cycle['id']:
                    live['cycle']['retomada'] = {'step': step, 'at': now.isoformat()}
                    if not (live['cycle'].get('facts') or {}).get('tiktok_declarado'):
                        # The lead may answer this ask with the bare @.
                        live['cycle']['arroba_pedido'] = True
                    self.repository.save_session(conv, live)
            return {'status': status, 'step': step}

    def _source_unchanged(self, event, state, conv):
        """A fresh provider read: no newer lead message and no unknown public outgoing."""
        if self.repository.load_session(conv) != state:
            return False
        headers = {'api_access_token': self.transport.token, 'Accept': 'application/json'}
        data = self.transport.http(method='GET', url=self.transport._conversation_url(event) + '/messages',
                                   headers=headers, timeout=8)
        messages = data.get('payload') if isinstance(data, dict) else None
        if not isinstance(messages, list) or not messages:
            return False
        source_id = int(event['message_id'])
        for msg in messages:
            if not isinstance(msg, dict) or not re.fullmatch(r'[1-9][0-9]{0,19}', str(msg.get('id', ''))):
                return False
            incoming = msg.get('message_type') == 'incoming' or (type(msg.get('message_type')) is int and msg['message_type'] == 0)
            if incoming and int(msg['id']) > source_id:
                return False
        return self.repository.load_session(conv) == state


def _incoming(msg):
    kind = msg.get('message_type')
    return (kind == 'incoming' or (type(kind) is int and kind == 0)) and msg.get('private') is False


def _bia(msg):
    kind = msg.get('message_type')
    outgoing = kind == 'outgoing' or (type(kind) is int and kind == 1)
    return outgoing and (msg.get('content_attributes') or {}).get('amplify_actor') == 'v5_rehearsal'


def _automatic(msg):
    """Aviso automático do Chatwoot (regra de automação, como o de manutenção): não é uma resposta.

    Mensagem de atendente tem remetente; a de regra de automação não tem e leva automation_rule_id.
    """
    kind = msg.get('message_type')
    outgoing = kind == 'outgoing' or (type(kind) is int and kind == 1)
    return (outgoing and not _bia(msg) and msg.get('private') is False
            and (bool((msg.get('content_attributes') or {}).get('automation_rule_id')) or msg.get('sender') is None))


def _activity(msg):
    kind = msg.get('message_type')
    return kind == 'activity' or (type(kind) is int and kind == 2)


class PosPausa:
    """Responde, retomando o pedido, quem escreveu e não recebeu resposta da Bia."""

    def __init__(self, repository, settings, transport, guard, process, *, now=None):
        self.repository, self.settings, self.transport = repository, settings, transport
        self.guard, self.process = guard, process
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.next_scan_at = None
        self.last = {'status': 'not_run'}

    def status(self):
        return {'enabled': enabled(self.settings, 'pos_pausa_enabled'), **self.last}

    def tick(self):
        now = clock(self.now())
        if not enabled(self.settings, 'pos_pausa_enabled') or not now:
            return {'status': 'disabled'}
        if self.next_scan_at and now < self.next_scan_at:
            return {'status': 'cooldown'}
        self.next_scan_at = now + timedelta(seconds=SCAN_SECONDS)
        try:
            outcome = self._scan(now)
        except Exception:
            outcome = {'status': 'unconfirmed'}
        self.last = {**outcome, 'at': now.isoformat()}
        return outcome

    def _get(self, url):
        return self.transport.http(method='GET', url=url, headers={'api_access_token': self.transport.token,
                                   'Accept': 'application/json'}, timeout=10)

    def _scan(self, now):
        gate = self.settings.get('gate') or {}
        base = self.transport.base_url + '/api/v1/accounts/' + str(gate.get('account_id'))
        listing = self._listing(base, gate, now)
        if listing is None:
            return {'status': 'unavailable'}
        for conversation in listing:
            event = self._candidate(conversation, now, base)
            if event is None:
                continue
            texts = event.pop('_texts')
            control = self.guard(event)
            if not isinstance(control, dict) or control.get('allowed') is not True:
                continue
            # One lead per scan keeps each catch-up reply supervised by the next.
            result = self.process(event, resumed={'texts': texts})
            return {'status': 'resumed', 'result': (result or {}).get('status')}
        return {'status': 'idle'}

    def _listing(self, base, gate, now):
        """Todas as conversas abertas da caixa com atividade nas últimas 23 h, página a página.

        O Chatwoot devolve 25 conversas por página, da atividade mais recente para a mais antiga.
        A 40 lia só a primeira: em 02/11, 56866 e 56865 (13 h e 16 h sem resposta) ficaram de fora.
        """
        listing, seen = [], set()
        for page in range(1, LISTING_PAGES + 1):
            data = self._get(base + '/conversations?inbox_id=' + str(gate.get('inbox_id'))
                             + '&status=open&assignee_type=all&page=' + str(page))
            payload = ((data or {}).get('data') or {}).get('payload') if isinstance(data, dict) else None
            if not isinstance(payload, list):
                return listing if page > 1 else None
            fresh = [item for item in payload if isinstance(item, dict) and item.get('id') not in seen]
            if not fresh:
                break
            seen.update(item.get('id') for item in fresh)
            listing.extend(fresh)
            activity = [clock(item.get('last_activity_at')) for item in fresh]
            if all(at and now - at > CATCH_UP_MAX_AGE for at in activity):
                # A página inteira é mais antiga que a janela: as próximas também são.
                break
        return listing

    def _candidate(self, conversation, now, base):
        gate = self.settings.get('gate') or {}
        if not isinstance(conversation, dict) or not re.fullmatch(r'[1-9][0-9]{0,19}', str(conversation.get('id', ''))):
            return None
        sender = (conversation.get('meta') or {}).get('sender') or {}
        if not pilot_phone(gate, sender.get('phone_number')) or str(conversation.get('inbox_id')) != str(gate.get('inbox_id')):
            return None
        # The maintenance notice is an automation reply, so it can be the newest message.
        listed = conversation.get('last_non_activity_message') or (conversation.get('messages') or [None])[-1]
        if not isinstance(listed, dict) or not (_incoming(listed) or _automatic(listed)):
            return None
        listed_at = clock(listed.get('created_at'))
        if not listed_at or now - listed_at > CATCH_UP_MAX_AGE or (_incoming(listed) and now - listed_at < CATCH_UP_MIN_AGE):
            return None
        conv = 'chatwoot:' + str(gate.get('account_id')) + ':' + str(conversation['id'])
        history = self._get(base + '/conversations/' + str(conversation['id']) + '/messages')
        messages = history.get('payload') if isinstance(history, dict) else None
        if not isinstance(messages, list):
            return None
        messages = sorted((m for m in messages if isinstance(m, dict) and re.fullmatch(r'[1-9][0-9]{0,19}', str(m.get('id', '')))
                           and not _activity(m)), key=lambda m: int(m['id']))
        if not messages or str(messages[-1].get('id')) != str(listed.get('id')):
            return None
        while messages and _automatic(messages[-1]):
            messages.pop()
        if not messages or not _incoming(messages[-1]):
            return None
        last = messages[-1]
        created = clock(last.get('created_at')) or (listed_at if str(last['id']) == str(listed.get('id')) else None)
        if not created or not CATCH_UP_MIN_AGE <= now - created <= CATCH_UP_MAX_AGE:
            return None
        key = 'chatwoot:' + str(gate.get('account_id')) + ':' + str(last.get('id'))
        if self.repository.event(key):
            return None
        processed = self.repository.load_session(conv).get('processed_inbound') or []
        newest = max((int(item.rsplit(':', 1)[1]) for item in processed
                      if isinstance(item, str) and re.fullmatch(r'chatwoot:1:[1-9][0-9]{0,19}', item)), default=0)
        if newest >= int(last['id']):
            return None
        texts = []
        for msg in reversed(messages):
            if _bia(msg):
                break
            if _incoming(msg) and int(msg['id']) > newest and isinstance(msg.get('content'), str) and msg['content'].strip():
                texts.insert(0, msg['content'].strip()[:500])
        texts = texts[-5:]
        if not texts:
            return None
        event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': gate.get('account_id'),
                 'inbox_id': conversation.get('inbox_id'), 'conversation_id': conversation['id'],
                 'message_id': last['id'], 'contact_id': str(sender.get('id')) if sender.get('id') else None,
                 'sender_phone': sender.get('phone_number'), 'sender_type': 'contact',
                 'message_type': 'incoming', 'private': False, 'text': last.get('content'),
                 'created_at': created.isoformat().replace('+00:00', 'Z')}
        event['source_ref'] = inbound_key(event)
        if not allow_inbound(gate, event):
            return None
        event['_texts'] = texts
        return event
