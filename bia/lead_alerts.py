"""Bounded, receipt-backed Slack alerts for declared high-GMV qualification.

No calls at import time. dispatch is invoked only by the validated inbound path,
under its conversation lock, after persisting the qualification state. It mutates
only bia_validation.alert_statuses for caller persistence; operations are durable.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from contracts import inbound_key

CHANNEL_NAMES = frozenset({'alerta-bia', 'alertas-bia'})
THRESHOLD_CENTS = 5_000_000
RESPONSIBLES = ('U0AF0DWMD1U', 'U0CA10SDPDJ')  # Bruno Zardo / Keize Passos, resolved in Slack.


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http(*, method, url, headers, payload=None):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = Request(url, data=data, headers=headers, method=method)
    with build_opener(_NoRedirect).open(request, timeout=10) as response:
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('oversized_response')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('invalid_response')
        return result


def _positive(value):
    return isinstance(value, (int, str)) and not isinstance(value, bool) and bool(re.fullmatch(r'[1-9][0-9]{0,19}', str(value)))


def _conversation_url(settings, event):
    base = settings.get('chatwoot_base_url')
    if not isinstance(base, str):
        return None
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
        return None
    if not all(_positive(event.get(key)) for key in ('account_id', 'conversation_id', 'contact_id', 'inbox_id')):
        return None
    gate = settings.get('gate') or {}
    if (str(event['account_id']) != str(gate.get('account_id'))
            or str(event['inbox_id']) != str(gate.get('inbox_id'))):
        return None
    return base.rstrip('/') + '/app/accounts/' + str(event['account_id']) + '/conversations/' + str(event['conversation_id'])


def _safe_name(value):
    if not isinstance(value, str):
        return 'Não informado'
    # A declared name is untrusted. Do not expose phone, links, emails, mention
    # syntax or arbitrary pasted content to the alert audience.
    value = re.sub(r'\s+', ' ', value).strip()
    if (not value or len(value) > 80 or re.search(r'[0-9@<>|:/\\]', value)
            or any(ord(c) < 32 for c in value)):
        return 'Não informado'
    return value.replace('&', '&amp;')


def _format_fields(event, state, kind):
    cycle = state['cycle']
    record = cycle['bia_validation']
    facts = cycle.get('facts') or {}
    handle = facts.get('tiktok_declarado')
    handle = handle if isinstance(handle, str) and re.fullmatch(r'@[A-Za-z0-9_.]{1,24}', handle) else 'Não informado'
    amount = facts['gmv_30d_declarado_centavos']
    money = f'{amount // 100:,}'.replace(',', '.') + ',' + f'{amount % 100:02}'
    declared = {True: 'Ativo (declaração do lead)', False: 'Inativo (declaração do lead)'}.get(
        facts.get('shop_ativo_declarado')) if type(facts.get('shop_ativo_declarado')) is bool else None

    # Use the same receipt binding used by the journey: a declaration or a
    # different creator/cycle is not official confirmation.
    from real_journey import _operation_proven
    try:
        evidence = cycle.get('real_operations', {}).get('precheck', {}).get('evidence', {})
        active = (type(evidence.get('shop_account_status')) is int and evidence['shop_account_status'] == 1
                  and evidence.get('source') == 'partner_precheck'
                  and _operation_proven(state, 'precheck', 'eligible'))
    except (AttributeError, KeyError, TypeError, ValueError):
        active = False
    verified_shop = 'Ativo (confirmado no TikTok)' if active else 'Não confirmado'
    pref = {'machine': 'Continuar com a Bia', 'specialist': 'Especialista da Amplify'}.get(
        record.get('preference'), 'Ainda não escolhida')
    headings = {'threshold': '🚨 LEAD PRIORITÁRIO — GMV ALTO',
                'specialist': '🎯 Bia | Especialista solicitado',
                'machine': '🤖 Bia | Escolheu seguir com a Bia'}
    phone = event.get('sender_phone')
    phone = re.sub(r'[+ ()-]', '', phone) if isinstance(phone, str) else ''
    phone = '+' + phone if re.fullmatch(r'[1-9][0-9]{9,14}', phone) else 'Não informado'
    followers = facts.get('seguidores_declarados')
    followers = (f'{followers:,}'.replace(',', '.') + ' — declarado pelo criador'
                 if type(followers) is int and 0 <= followers <= 1_000_000_000 else 'Não disponíveis')
    fields = [('Nome', _safe_name(facts.get('nome_declarado'))), ('WhatsApp', phone),
              ('GMV declarado', 'R$ ' + money + ' / últimos 30 dias'),
              ('Perfil TikTok', handle), ('Seguidores', followers),
              ('TikTok Shop', verified_shop if active else declared or 'Não informado'),
              ('Verificação do GMV', 'Pendente — declarado, não verificado'),
              ('Atendimento', '#' + str(event['conversation_id']))]
    # No category or verified followers enter today's authoritative alert
    # state; no deduction from the declared GMV or profile.
    action = {'specialist': 'Agenciamento automático pausado. A equipe precisa assumir a conversa.',
              'threshold': 'Acompanhe a conversa e aguarde a escolha do lead.',
              'machine': 'A Bia segue com o atendimento automático.'}[kind]
    return headings[kind], fields, action


def _text(event, state, url, kind):
    heading, fields, action = _format_fields(event, state, kind)
    return '\n'.join([heading, *(f'{label}: {value}' for label, value in fields),
                      action, 'Abrir conversa no Chatwoot: ' + url])


def _presentation(event, state, url, kind):
    heading, fields, action = _format_fields(event, state, kind)
    text = '\n'.join([heading, *(f'{label}: {value}' for label, value in fields),
                      action, 'Abrir conversa no Chatwoot: ' + url])
    plain = lambda value: {'type': 'plain_text', 'text': value, 'emoji': True}
    blocks = [{'type': 'header', 'text': plain(heading)},
              {'type': 'section', 'text': plain('\n'.join(label + ': ' + value for label, value in fields))},
              {'type': 'context', 'elements': [plain(action)]}]
    # Only use Slack link markup for our trusted, constrained Chatwoot URL.
    # A link needs no Slack interactions endpoint or new permissions.
    if re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?/app/accounts/[1-9][0-9]{0,19}/conversations/[1-9][0-9]{0,19}', url):
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn',
                       'text': '<' + url + '|Abrir conversa no Chatwoot>', 'verbatim': True}})
    handle = (state.get('cycle', {}).get('facts') or {}).get('tiktok_declarado')
    from lead_validation import profile_handle
    handle = profile_handle(handle)
    links = []
    if handle:
        links.append('<https://www.tiktok.com/' + handle + '|Perfil TikTok>')
    phone = dict(fields).get('WhatsApp', '')
    if re.fullmatch(r'\+[1-9][0-9]{9,14}', phone):
        links.append('<https://wa.me/' + phone[1:] + '|Falar com o lead>')
    if links:
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': ' · '.join(links), 'verbatim': True}})
        text += '\n' + ' · '.join(links)
    mentions = '👥 *Responsáveis:* ' + ' '.join('<@' + user + '>' for user in RESPONSIBLES)
    blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': mentions, 'verbatim': True}})
    return {'text': text + '\n' + mentions, 'blocks': blocks}


def probe(settings, *, http=None):
    """Read-only destination check. Never returns tokens or channel identifiers."""
    token, channel = settings.get('slack_bot_token'), settings.get('slack_gmv_channel_id')
    configured = (isinstance(token, str) and bool(token.strip()) and isinstance(channel, str)
                  and bool(re.fullmatch(r'[CG][A-Z0-9]{8,}', channel)))
    if not configured:
        return {'configured': False, 'verified': False, 'reason': 'slack_not_configured', 'channel_name': None}
    try:
        info = (http or _http)(method='GET',
            url='https://slack.com/api/conversations.info?' + urlencode({'channel': channel}),
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json; charset=utf-8'})
        if isinstance(info, dict) and info.get('ok') is not True:
            error = info.get('error')
            safe = {'missing_scope', 'not_in_channel', 'channel_not_found', 'invalid_auth', 'token_revoked', 'account_inactive', 'ratelimited'}
            return {'configured': True, 'verified': False, 'reason': 'slack_' + (error if error in safe else 'api_error'), 'channel_name': None}
        target = info.get('channel') if isinstance(info, dict) else None
        verified = (info.get('ok') is True and isinstance(target, dict)
                    and target.get('id') == channel and target.get('name') in CHANNEL_NAMES
                    and target.get('is_archived') is False and target.get('is_im') is not True
                    and target.get('is_mpim') is not True and target.get('is_member') is True)
        if verified:
            return {'configured': True, 'verified': True, 'reason': 'verified', 'channel_name': target['name']}
    except Exception:
        pass
    return {'configured': True, 'verified': False, 'reason': 'slack_channel_unverified', 'channel_name': None}


def dispatch(settings, repository, event, state, *, http=None):
    """Return per-event statuses; never retry a reserved send, including timeout.

    Per cycle there can be one threshold alert and at most one notification for
    each preference (machine/specialist). Sender accepts no arbitrary destination.
    `http` is an injectable synchronous transport for offline tests only.
    """
    cycle = state.get('cycle') if isinstance(state, dict) else None
    record = cycle.get('bia_validation') if isinstance(cycle, dict) else None
    facts = cycle.get('facts') or {} if isinstance(cycle, dict) else {}
    amount = facts.get('gmv_30d_declarado_centavos')
    if (not isinstance(record, dict) or record.get('high_gmv') is not True
            or record.get('alert_requested') is not True
            or isinstance(amount, bool) or not isinstance(amount, int) or amount < THRESHOLD_CENTS
            or amount > 100_000_000_000 or facts.get('gmv_30d_moeda') != 'BRL'):
        return {'status': 'not_requested', 'events': {}}
    from lead_validation import profile_handle
    if not profile_handle(facts.get('tiktok_declarado')):
        return {'status': 'pending_profile', 'events': {}}
    # v1 cycles retain their old pause/choice state but never acquire a new
    # retroactive threshold alert or preference notification after deployment.
    if record.get('priority_flow_version') != 2:
        return {'status': 'legacy_cycle', 'events': {}}
    url = _conversation_url(settings, event)
    source = inbound_key(event)
    cycle_id = cycle.get('id')
    if not url or not source or not isinstance(cycle_id, str) or not cycle_id or len(cycle_id) > 200:
        return {'status': 'blocked', 'reason': 'invalid_scope', 'events': {}}
    if state.get('opt_out') or cycle.get('opt_out'):
        return {'status': 'blocked', 'reason': 'opt_out', 'events': {}}
    # 22/11/2026: ficam só os alertas de GMV (pedido do Vitor). O alerta extra de
    # "Especialista solicitado" foi desligado; a escolha Bia/Especialista do lead continua.
    kinds = ['threshold']
    statuses = record.setdefault('alert_statuses', {})
    results = {}
    for kind in kinds:
        results[kind] = statuses[kind] = _deliver(
            settings, repository, event, cycle_id, kind, source,
            lambda kind=kind: _presentation(event, state, url, kind), http=http)
    return {'status': 'processed', 'events': results}


def _deliver(settings, repository, event, cycle_id, kind, source, render, *, http=None):
    """One receipt-backed Slack post per (conversation, cycle, kind); a reserved send is never retried."""
    send = http or _http
    token, channel = settings.get('slack_bot_token'), settings.get('slack_gmv_channel_id')
    valid_config = (isinstance(token, str) and bool(token.strip()) and isinstance(channel, str)
                    and bool(re.fullmatch(r'[CG][A-Z0-9]{8,}', channel)))
    digest = hashlib.sha256((str(event['account_id']) + ':' + str(event['conversation_id']) + ':' + cycle_id + ':' + kind).encode()).hexdigest()
    key = 'bia_gmv_alert:' + digest
    old = repository.get_operation(key)
    if old:
        return old.get('result') or {'status': 'outcome_unknown', 'reason': 'reserved_without_receipt'}
    if not valid_config:
        return {'status': 'blocked', 'reason': 'slack_not_configured'}
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json; charset=utf-8'}
    # Read-only verification is safe to retry; a failed read never consumes the
    # send reservation, and never implies a delivered alert or human assignment.
    verified = probe(settings, http=send)['verified']
    if not verified:
        return {'status': 'blocked', 'reason': 'slack_channel_unverified'}
    if not repository.reserve_operation(key, source, 'bia_gmv_alert'):
        old = repository.get_operation(key) or {}
        return old.get('result') or {'status': 'outcome_unknown', 'reason': 'reserved_without_receipt'}
    payload = {'channel': channel, **render(), 'mrkdwn': False,
               'parse': 'none', 'link_names': False, 'unfurl_links': False, 'unfurl_media': False}
    try:
        response = send(method='POST', url='https://slack.com/api/chat.postMessage', headers=headers, payload=payload)
        if (isinstance(response, dict) and response.get('ok') is True and response.get('channel') == channel
                and isinstance(response.get('ts'), str) and re.fullmatch(r'\d+\.\d+', response['ts'])):
            result = {'status': 'accepted', 'channel_id': channel, 'message_ts': response['ts']}
        elif isinstance(response, dict) and response.get('ok') is False:
            result = {'status': 'failed', 'reason': 'slack_rejected'}
        else:
            result = {'status': 'outcome_unknown', 'reason': 'receipt_unconfirmed'}
    except Exception:
        result = {'status': 'outcome_unknown', 'reason': 'send_unconfirmed'}
    repository.complete_operation(key, result, status='outcome_unknown' if result['status'] == 'outcome_unknown' else 'completed')
    return result


# Auditoria 20/11: lead parado que depende do time. Antes, cycle['team_alert'] era gravado
# e nada lia. Vale para qualquer GMV; um alerta por motivo e por ciclo.
TEAM_REASONS = {
    'invite_failed_twice': 'O convite no TikTok falhou duas vezes.',
    'creator_binding_not_permitted': 'O TikTok não permite vincular este perfil a uma agência.',
    'shop_unknown_limit': ('O TikTok não traz o status do Shop depois de 2 reconferências; '
                           'o lead segue mandando "pronto".'),
}


def _team_presentation(event, state, url, reason):
    cycle = state['cycle']
    facts = cycle.get('facts') or {}
    from lead_validation import profile_handle
    handle = profile_handle(facts.get('tiktok_declarado')) or 'Não informado'
    phone = event.get('sender_phone')
    phone = re.sub(r'[+ ()-]', '', phone) if isinstance(phone, str) else ''
    phone = '+' + phone if re.fullmatch(r'[1-9][0-9]{9,14}', phone) else 'Não informado'
    heading = '⚠️ Bia | Lead parado precisa do time'
    fields = [('Nome', _safe_name(facts.get('nome_declarado'))), ('WhatsApp', phone),
              ('Perfil TikTok', handle), ('Motivo', TEAM_REASONS[reason]),
              ('Atendimento', '#' + str(event['conversation_id']))]
    action = 'Assuma a conversa no Chatwoot e responda o lead.'
    text = '\n'.join([heading, *(f'{label}: {value}' for label, value in fields),
                      action, 'Abrir conversa no Chatwoot: ' + url])
    plain = lambda value: {'type': 'plain_text', 'text': value, 'emoji': True}
    blocks = [{'type': 'header', 'text': plain(heading)},
              {'type': 'section', 'text': plain('\n'.join(label + ': ' + value for label, value in fields))},
              {'type': 'context', 'elements': [plain(action)]}]
    if re.fullmatch(r'https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?/app/accounts/[1-9][0-9]{0,19}/conversations/[1-9][0-9]{0,19}', url):
        blocks.append({'type': 'section', 'text': {'type': 'mrkdwn',
                       'text': '<' + url + '|Abrir conversa no Chatwoot>', 'verbatim': True}})
    mentions = '👥 *Responsáveis:* ' + ' '.join('<@' + user + '>' for user in RESPONSIBLES)
    blocks.append({'type': 'section', 'text': {'type': 'mrkdwn', 'text': mentions, 'verbatim': True}})
    return {'text': text + '\n' + mentions, 'blocks': blocks}


def dispatch_team(settings, repository, event, state, *, http=None):
    """Alerta do time para cycle['team_alert'], uma vez por motivo e ciclo."""
    cycle = state.get('cycle') if isinstance(state, dict) else None
    alert = cycle.get('team_alert') if isinstance(cycle, dict) else None
    reason = alert.get('reason') if isinstance(alert, dict) else None
    if reason not in TEAM_REASONS:
        return {'status': 'not_requested'}
    if state.get('opt_out') or cycle.get('opt_out'):
        return {'status': 'blocked', 'reason': 'opt_out'}
    url = _conversation_url(settings, event)
    source = inbound_key(event)
    cycle_id = cycle.get('id')
    if not url or not source or not isinstance(cycle_id, str) or not cycle_id or len(cycle_id) > 200:
        return {'status': 'blocked', 'reason': 'invalid_scope'}
    result = _deliver(settings, repository, event, cycle_id, 'team:' + reason, source,
                      lambda: _team_presentation(event, state, url, reason), http=http)
    alert['status'] = result.get('status')
    return result
