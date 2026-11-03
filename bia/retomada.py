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
import threading

from contracts import allow_inbound, inbound_key, pilot_phone
from followup import clock

STEPS = ((1, timedelta(minutes=15)), (2, timedelta(hours=2)), (3, timedelta(hours=23, minutes=30)))
LINKED_STEPS = ((1, timedelta(hours=2)), (2, timedelta(hours=23, minutes=30)))
MIN_GAP = timedelta(minutes=10)
WAITING = frozenset({'intro', 'origin', 'tiktok', 'shop', 'agency', 'consent_real', 'await_acceptance', 'form'})
SCAN_SECONDS = 60
CATCH_UP_MIN_AGE = timedelta(minutes=2)
# Release 44: a mensagem já registrada sem resposta da Bia no Chatwoot é reprocessada uma vez, 3 min depois.
REPROCESS_MIN_AGE = timedelta(minutes=3)
CATCH_UP_MAX_AGE = timedelta(hours=23)
LISTING_PAGES = 20  # até 500 conversas abertas na caixa
# Release 41: lembretes só entre 8h e 21h de Brasília (UTC-3, sem horário de verão).
BRASILIA = timezone(timedelta(hours=-3))
SEND_HOURS = (8, 21)


# Release 46: toda conversa olhada por uma varredura recebe um motivo fixo (nunca "pulado" sem motivo).
# Fica só em memória (nada é gravado) e aparece no /ready e em GET /diagnostico/conversa/<id>.
REASONS = frozenset({
    # o que aconteceu
    'respondida', 'reprocessada', 'lembrete_enviado', 'consulta_na_fila',
    # por que não respondeu
    'conversa_invalida', 'fora_do_piloto', 'outra_caixa', 'ja_respondida_no_chatwoot', 'sem_mensagem_do_lead',
    'fora_da_janela_23h', 'fora_da_janela_24h', 'muito_recente', 'historico_indisponivel', 'mensagem_sem_texto',
    'reprocessamento_ja_usado', 'controle_humano', 'outro_lead_nesta_varredura', 'trava_ocupada', 'sem_atendimento',
    'atendimento_fechado', 'fase_sem_lembrete', 'mensagem_mais_nova', 'pausa_ou_saida', 'nenhuma_etapa_vencida',
    'fora_do_horario', 'intervalo_minimo', 'ficha_ilegivel', 'cadastro_confirmado', 'mudou_no_chatwoot',
    'lembrete_ja_reservado', 'sem_pendencia', 'ponte_fora', 'origem_nao_confirmada', 'resposta_ja_aceita',
    'consulta_ja_na_fila_da_mensagem',
})
ERROR_PREFIX = 'erro_envio:'


def valid_reason(reason):
    return isinstance(reason, str) and (reason in REASONS or bool(re.fullmatch(r'erro_envio:[a-z0-9_]{1,60}', reason)))


def send_error(code):
    code = re.sub(r'[^a-z0-9_]', '_', str(code or 'desconhecido').lower())[:60] or 'desconhecido'
    return ERROR_PREFIX + code


class Decisoes:
    """A última decisão de cada varredura por conversa e a contagem de motivos da última varredura."""

    def __init__(self):
        self._lock = threading.Lock()
        self.by_conversation, self.last_scan, self._current = {}, {}, {}

    def start(self, scan):
        with self._lock:
            self._current[scan] = {}

    def record(self, scan, conversation, reason, at, **extra):
        if not valid_reason(reason):
            raise ValueError('motivo fora da lista: ' + repr(reason))
        with self._lock:
            entry = {'motivo': reason, 'em': at.isoformat() if hasattr(at, 'isoformat') else str(at), **extra}
            self.by_conversation.setdefault(str(conversation), {})[scan] = entry
            counts = self._current.setdefault(scan, {})
            counts[reason] = counts.get(reason, 0) + 1
        return reason

    def finish(self, scan):
        with self._lock:
            self.last_scan[scan] = dict(self._current.get(scan) or {})
            return dict(self.last_scan[scan])

    def for_conversation(self, conversation):
        with self._lock:
            return {scan: dict(entry) for scan, entry in (self.by_conversation.get(str(conversation)) or {}).items()}


DECISOES = Decisoes()


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


def reminder_base(state, last_inbound):
    """Os lembretes contam da última mensagem do lead ou do último envio de convite, o que vier depois.

    Release 43: a 42 reenviou o convite da @gabinaresse às 18:16 e, 11 min depois, saiu o lembrete
    "Seu convite continua no TikTok", contado da mensagem dela de manhã.
    """
    cycle = state.get('cycle') or {}
    moments = [last_inbound]
    for effect in (state.get('effects') or {}).values():
        if (isinstance(effect, dict) and effect.get('operation') == 'invite' and effect.get('cycle_id') == cycle.get('id')
                and clock(effect.get('created_at'))):
            moments.append(clock(effect['created_at']))
    return max(moments)


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
        DECISOES.start('retomada')
        for conv in self.repository.followup_conversations():
            try:
                outcome = self._conversation(conv, now)
            except Exception as error:
                outcome = {'status': 'unconfirmed', 'motivo': send_error(type(error).__name__)}
            sent += outcome.get('status') == 'accepted'
            DECISOES.record('retomada', conv.rsplit(':', 1)[-1], outcome.get('motivo') or send_error(outcome.get('status')),
                            now, **({'etapa': outcome['step']} if outcome.get('step') else {}))
        self.last = {'status': 'completed', 'at': now.isoformat(), 'sent': sent,
                     'puladas_por_motivo': DECISOES.finish('retomada')}
        return dict(self.last)

    def _due(self, state, source, now):
        """Maior etapa vencida ainda não reservada para esta última mensagem do lead."""
        cycle = state.get("cycle") or {}
        last_inbound = clock(cycle.get("last_inbound_at"))
        if not last_inbound:
            return None
        base = reminder_base(state, last_inbound)
        due = [step for step, after in steps_for(state) if now - base >= after]
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
            # Release 46: cada "não" tem o seu motivo (antes, tudo virava "idle").
            idle = lambda reason: {'status': 'idle', 'motivo': reason}
            if not source or not cycle or source.get('cycle_id') != cycle.get('id') or cycle.get('mode') != 'real':
                return idle('sem_atendimento')
            if cycle.get('status') != 'open':
                return idle('atendimento_fechado')
            if not expires or now >= expires:
                return idle('fora_da_janela_24h')
            if cycle.get('phase') not in WAITING:
                return idle('fase_sem_lembrete')
            if (state.get('processed_inbound') or [None])[-1] != source.get('event_key') or inbound_key(event) != source.get('event_key'):
                return idle('mensagem_mais_nova')
            if not allow_inbound(self.settings.get('gate'), event):
                return idle('fora_do_piloto')
            if state.get('human_control'):
                return idle('controle_humano')
            if (cycle.get('qualification_paused') or cycle.get('pending_profile_changes')
                    or state.get('opt_out') or cycle.get('opt_out')):
                return idle('pausa_ou_saida')
            step = self._due(state, source, now)
            if step is None:
                return idle('nenhuma_etapa_vencida')
            if not send_hour(now):
                # A etapa vencida espera as 8h; as anteriores se juntam nela (nunca dois lembretes seguidos).
                return {'status': 'quiet_hours', 'motivo': 'fora_do_horario'}
            delivery = self.repository.conversation_delivery_context(conv, cycle['opened_at'])
            last_reply = clock((delivery.get('last_accepted_reply') or {}).get('at'))
            if (delivery.get('latest_attempt_status') != 'accepted' or not last_reply
                    or now - last_reply < MIN_GAP or not self.repository.followup_clear(conv, state)):
                return idle('intervalo_minimo')
            if callable(self.registration):
                situation = self.registration(event)
                if not isinstance(situation, str):
                    # Sem ler a ficha, nenhum lembrete: ele pode contradizer um cadastro já feito.
                    return {'status': 'unconfirmed', 'motivo': 'ficha_ilegivel'}
                if situation != state.get('cadastro_situacao'):
                    state['cadastro_situacao'] = situation
                    self.repository.save_session(conv, state)
            payload = message(state, step, self.policy())
            if payload is None:
                return idle('cadastro_confirmado' if state.get('cadastro_situacao') == 'confirmado'
                            or cycle.get('acesso_liberado') else 'fase_sem_lembrete')
            control = self.guard(event)
            if not isinstance(control, dict) or control.get('allowed') is not True:
                return {'status': 'blocked', 'motivo': 'controle_humano'}
            if not self._source_unchanged(event, state, conv):
                return {'status': 'source_changed', 'motivo': 'mudou_no_chatwoot'}
            key = step_key(cycle['id'], source['event_key'], step)
            # Earlier missed steps are retired with this one: never two nudges in a row.
            if not self.repository.reserve_followup(conv, source, state, key, {'text': payload[0], 'buttons': payload[1]}):
                return {'status': 'blocked', 'motivo': 'lembrete_ja_reservado'}
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
            return {'status': status, 'step': step,
                    'motivo': 'lembrete_enviado' if status == 'accepted' else send_error(safe.get('reason') or status)}

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
    Release 43: o aviso de fora do horário da caixa é do tipo ``template`` (3), não ``outgoing``
    (56938 escreveu às 05:42 e a pós-pausa não a via).
    """
    kind = msg.get('message_type')
    if (kind == 'template' or (type(kind) is int and kind == 3)) and msg.get('private') is False:
        return True
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
        # Release 44: as mensagens já entregues nesta execução (a nova tentativa ou a 1ª resposta) nunca voltam;
        # entre reinícios, a marca 'reprocessed' do atendimento faz o mesmo.
        self.handled = set()
        self.decisions = DECISOES
        # Release 45: contagem para o /ready (a varredura roda a cada minuto, de dia e de noite).
        self.counts = {'varreduras': 0, 'respondidas': 0, 'reprocessadas': 0}

    def status(self):
        return {'enabled': enabled(self.settings, 'pos_pausa_enabled'), 'intervalo_segundos': SCAN_SECONDS,
                'horario_silencioso': False, **self.counts, **self.last}

    def tick(self):
        now = clock(self.now())
        if not enabled(self.settings, 'pos_pausa_enabled') or not now:
            return {'status': 'disabled'}
        if self.next_scan_at and now < self.next_scan_at:
            return {'status': 'cooldown'}
        self.next_scan_at = now + timedelta(seconds=SCAN_SECONDS)
        self.counts['varreduras'] += 1
        try:
            outcome = self._scan(now)
        except Exception:
            outcome = {'status': 'unconfirmed'}
        if outcome.get('status') == 'resumed' and outcome.get('result') in {'completed', 'accepted'}:
            # Release 46: "respondidas" conta toda resposta (a Cristiane, reprocessada, ficou de fora na 45).
            self.counts['respondidas'] += 1
            if outcome.get('reprocess'):
                self.counts['reprocessadas'] += 1
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
        decisions = self.decisions
        decisions.start('pos_pausa')
        outcome = {'status': 'idle'}
        for conversation in listing:
            conv = str((conversation or {}).get('id', '?')) if isinstance(conversation, dict) else '?'
            if outcome['status'] == 'resumed':
                # One lead per scan keeps each catch-up reply supervised by the next.
                decisions.record('pos_pausa', conv, 'outro_lead_nesta_varredura', now)
                continue
            event, reason = self._candidate(conversation, now, base)
            if event is None:
                decisions.record('pos_pausa', conv, reason, now)
                continue
            texts = event.pop('_texts')
            reprocess = event.pop('_reprocess', False)
            control = self.guard(event)
            if not isinstance(control, dict) or control.get('allowed') is not True:
                decisions.record('pos_pausa', conv, 'controle_humano', now,
                                 detalhe=(control or {}).get('reason') if isinstance(control, dict) else None)
                continue
            resumed = {'texts': texts, **({'reprocess': True} if reprocess else {})}
            self.handled.add(inbound_key(event))
            result = self.process(event, resumed=resumed) or {}
            status = result.get('status')
            if status in {'completed', 'accepted'}:
                reason = 'reprocessada' if reprocess else 'respondida'
            elif status == 'skipped':
                reason = {'already_reprocessed': 'reprocessamento_ja_usado', 'reply_already_accepted': 'resposta_ja_aceita',
                          'operation_queued_for_message': 'consulta_ja_na_fila_da_mensagem'}.get(result.get('reason'),
                                                                                             send_error(result.get('reason')))
            elif status == 'blocked':
                reason = 'controle_humano'
            else:
                reason = send_error(status)
            decisions.record('pos_pausa', conv, reason, now)
            outcome = {'status': 'resumed', 'result': status, 'reprocess': reprocess, 'motivo': reason,
                       'conversation': event.get('conversation_id')}
        outcome['puladas_por_motivo'] = decisions.finish('pos_pausa')
        outcome['conversas_lidas'] = len(listing)
        return outcome

    def _listing(self, base, gate, now):
        """Todas as conversas abertas da caixa com atividade nas últimas 23 h, página a página.

        O Chatwoot devolve 25 conversas por página, da atividade mais recente para a mais antiga.
        A 40 lia só a primeira: em 02/11, 56866 e 56865 (13 h e 16 h sem resposta) ficaram de fora.
        """
        listing, seen = [], set()
        for page in range(1, LISTING_PAGES + 1):
            data = self._get(base + '/conversations?inbox_id=' + str(gate.get('inbox_id'))
                             + '&status=open&assignee_type=all&sort_by=last_activity_at_desc&page=' + str(page))
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
            return None, 'conversa_invalida'
        sender = (conversation.get('meta') or {}).get('sender') or {}
        if str(conversation.get('inbox_id')) != str(gate.get('inbox_id')):
            return None, 'outra_caixa'
        if not pilot_phone(gate, sender.get('phone_number')):
            return None, 'fora_do_piloto'
        # The maintenance notice is an automation reply, so it can be the newest message.
        listed = conversation.get('last_non_activity_message') or (conversation.get('messages') or [None])[-1]
        # Release 46: nota privada não é resposta ao lead (a regra é saída da Bia não privada).
        if not isinstance(listed, dict):
            return None, 'sem_mensagem_do_lead'
        if listed.get('private') is not True and not (_incoming(listed) or _automatic(listed)):
            return None, 'ja_respondida_no_chatwoot'
        listed_at = clock(listed.get('created_at'))
        if not listed_at or now - listed_at > CATCH_UP_MAX_AGE:
            return None, 'fora_da_janela_23h'
        if _incoming(listed) and now - listed_at < CATCH_UP_MIN_AGE:
            return None, 'muito_recente'
        conv = 'chatwoot:' + str(gate.get('account_id')) + ':' + str(conversation['id'])
        history = self._get(base + '/conversations/' + str(conversation['id']) + '/messages')
        messages = history.get('payload') if isinstance(history, dict) else None
        if not isinstance(messages, list):
            return None, 'historico_indisponivel'
        messages = sorted((m for m in messages if isinstance(m, dict) and re.fullmatch(r'[1-9][0-9]{0,19}', str(m.get('id', '')))
                           and not _activity(m) and m.get('private') is not True), key=lambda m: int(m['id']))
        if not messages or (listed.get('private') is not True and str(messages[-1].get('id')) != str(listed.get('id'))):
            return None, 'historico_indisponivel'
        while messages and _automatic(messages[-1]):
            messages.pop()
        if not messages:
            return None, 'sem_mensagem_do_lead'
        if not _incoming(messages[-1]):
            return None, 'ja_respondida_no_chatwoot'
        last = messages[-1]
        created = clock(last.get('created_at')) or (listed_at if str(last['id']) == str(listed.get('id')) else None)
        if not created or now - created > CATCH_UP_MAX_AGE:
            return None, 'fora_da_janela_23h'
        if now - created < CATCH_UP_MIN_AGE:
            return None, 'muito_recente'
        key = 'chatwoot:' + str(gate.get('account_id')) + ':' + str(last.get('id'))
        session = self.repository.load_session(conv)
        processed = session.get('processed_inbound') or []
        newest = max((int(item.rsplit(':', 1)[1]) for item in processed
                      if isinstance(item, str) and re.fullmatch(r'chatwoot:1:[1-9][0-9]{0,19}', item)), default=0)
        reprocess = False
        if self.repository.event(key) or newest >= int(last['id']):
            # Release 44/45 (aprovado pelo usuário): a decisão é pelo Chatwoot. Sem saída da Bia depois da última
            # mensagem do lead (o aviso de manutenção e o de fora do horário não contam), ela responde uma vez,
            # mesmo com a mensagem já registrada ou já marcada como processada (56938, 56935).
            # Atendente humano depois dela já fez a mensagem cair acima; 'reprocessed' impede repetir.
            if now - created < REPROCESS_MIN_AGE:
                return None, 'muito_recente'
            if key in self.handled or key in (session.get('reprocessed') or {}):
                return None, 'reprocessamento_ja_usado'
            reprocess = True
            newest = min(newest, max((int(m['id']) for m in messages if _bia(m)), default=0))
        texts = []
        for msg in reversed(messages):
            if _bia(msg):
                break
            if _incoming(msg) and int(msg['id']) > newest and isinstance(msg.get('content'), str) and msg['content'].strip():
                texts.insert(0, msg['content'].strip()[:500])
        texts = texts[-5:]
        if not texts:
            return None, 'mensagem_sem_texto'
        event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': gate.get('account_id'),
                 'inbox_id': conversation.get('inbox_id'), 'conversation_id': conversation['id'],
                 'message_id': last['id'], 'contact_id': str(sender.get('id')) if sender.get('id') else None,
                 'sender_phone': sender.get('phone_number'), 'sender_type': 'contact',
                 'message_type': 'incoming', 'private': False, 'text': last.get('content'),
                 'created_at': created.isoformat().replace('+00:00', 'Z')}
        event['source_ref'] = inbound_key(event)
        if not allow_inbound(gate, event):
            return None, 'fora_do_piloto'
        event['_texts'] = texts
        event['_reprocess'] = reprocess
        return event, None
