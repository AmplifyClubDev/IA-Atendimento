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


def _text(event, state, url, kind):
    cycle = state['cycle']; record = cycle['bia_validation']; facts = cycle.get('facts') or {}
    handle = facts.get('tiktok_declarado')
    handle = handle if isinstance(handle, str) and re.fullmatch(r'@[A-Za-z0-9_.]{1,24}', handle) else 'Não informado'
    amount = facts['gmv_30d_declarado_centavos']
    money = f'{amount // 100:,}'.replace(',', '.') + ',' + f'{amount % 100:02}'
    choice = {'machine': 'Continuar com a Bia', 'specialist': 'Especialista da Amplify'}.get(record.get('preference'), 'Ainda não escolhida')
    heading = 'Bia: lead com GMV a partir de R$ 50 mil' if kind == 'threshold' else 'Bia: preferência de atendimento registrada'
    lines = [heading, 'Nome: ' + _safe_name(facts.get('nome_declarado')), 'Perfil: ' + handle,
             'GMV declarado nos últimos 30 dias: R$ ' + money, 'Preferência: ' + choice]
    if kind == 'specialist':
        lines.append('Solicitou especialista. Agenciamento automático pausado; atendimento humano ainda precisa assumir a conversa.')
    elif kind == 'machine':
        lines.append('Optou por continuar o agenciamento automático.')
    lines.append('Conversa: ' + url)
    return '\n'.join(lines)


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
    url = _conversation_url(settings, event)
    source = inbound_key(event)
    cycle_id = cycle.get('id')
    if not url or not source or not isinstance(cycle_id, str) or not cycle_id or len(cycle_id) > 200:
        return {'status': 'blocked', 'reason': 'invalid_scope', 'events': {}}
    if state.get('opt_out') or cycle.get('opt_out'):
        return {'status': 'blocked', 'reason': 'opt_out', 'events': {}}
    kinds = ['threshold']
    preference = record.get('preference')
    if preference == 'machine' or (preference == 'specialist' and record.get('handoff_requested') is True):
        kinds.append(preference)
    statuses = record.setdefault('alert_statuses', {})
    results = {}
    send = http or _http
    token, channel = settings.get('slack_bot_token'), settings.get('slack_gmv_channel_id')
    valid_config = (isinstance(token, str) and bool(token.strip()) and isinstance(channel, str)
                    and bool(re.fullmatch(r'[CG][A-Z0-9]{8,}', channel)))
    for kind in kinds:
        digest = hashlib.sha256((str(event['account_id']) + ':' + str(event['conversation_id']) + ':' + cycle_id + ':' + kind).encode()).hexdigest()
        key = 'bia_gmv_alert:' + digest
        old = repository.get_operation(key)
        if old:
            result = old.get('result') or {'status': 'outcome_unknown', 'reason': 'reserved_without_receipt'}
            results[kind] = statuses[kind] = result
            continue
        if not valid_config:
            results[kind] = statuses[kind] = {'status': 'blocked', 'reason': 'slack_not_configured'}
            continue
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json; charset=utf-8'}
        # Read-only verification is safe to retry; a failed read never consumes the
        # send reservation, and never implies a delivered alert or human assignment.
        verified = probe(settings, http=send)['verified']
        if not verified:
            results[kind] = statuses[kind] = {'status': 'blocked', 'reason': 'slack_channel_unverified'}
            continue
        if not repository.reserve_operation(key, source, 'bia_gmv_alert'):
            old = repository.get_operation(key) or {}
            results[kind] = statuses[kind] = old.get('result') or {'status': 'outcome_unknown', 'reason': 'reserved_without_receipt'}
            continue
        payload = {'channel': channel, 'text': _text(event, state, url, kind), 'mrkdwn': False,
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
        results[kind] = statuses[kind] = result
    return {'status': 'processed', 'events': results}
