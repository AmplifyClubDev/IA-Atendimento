"""Bounded, authenticated diagnostic projection. No I/O or raw payloads."""
from playwright_client import PlaywrightClient


def operation_diagnostics(cycle, settings):
    sanitizer = PlaywrightClient(settings if isinstance(settings, dict) else {})
    rows = {}
    operations = cycle.get('real_operations') if isinstance(cycle, dict) else None
    if not isinstance(operations, dict):
        return rows
    for name in ('precheck', 'relationship', 'invite', 'lookup', 'gmv_report'):
        record = operations.get(name)
        if not isinstance(record, dict):
            continue
        row = {}
        for field in ('status', 'reason'):
            value = sanitizer._diagnostic_code(record.get(field))
            if value is not None:
                row[field] = value
        if type(record.get('confirmed')) is bool:
            row['confirmed'] = record['confirmed']
        evidence = record.get('evidence')
        evidence = evidence if isinstance(evidence, dict) else {}
        for field in ('http_status', 'provider_http_status'):
            value = evidence.get(field)
            if type(value) is int and 100 <= value <= 599:
                row[field] = value
        for field in ('post_attempted', 'create_accepted'):
            if type(evidence.get(field)) is bool:
                row[field] = evidence[field]
        code = sanitizer._diagnostic_code(evidence.get('upstream_code'))
        message = sanitizer._diagnostic_text(evidence.get('upstream_message'))
        if code is not None:
            row['provider_code'] = code
        if message is not None:
            row['provider_message'] = message
        receipt = sanitizer._invite_receipt(evidence.get('receipt'))
        if receipt:
            if 'stage' in receipt and sanitizer._diagnostic_code(receipt['stage']) != receipt['stage']:
                receipt.pop('stage')
            row['receipt'] = receipt
        row['provider_detail_available'] = bool(code is not None or message is not None or receipt)
        rows[name] = row
    return rows


def invite_attempt_diagnostics(state, job_rows, settings):
    """One row per proved bridge POST, including completed earlier cycles."""
    import re
    from datetime import datetime, timezone

    sanitizer = PlaywrightClient(settings if isinstance(settings, dict) else {})
    state = state if isinstance(state, dict) else {}
    effects = state.get('effects')
    effects = effects if isinstance(effects, dict) else {}
    # Do not widen the legacy diagnostics' free-text surface. Only
    # recognized exact provider sentences can be rendered here. A provider
    # may echo names, handles or other data even inside its "message" field.
    safe_messages = frozenset({
        'the creator has no permission to bind',
        'creator has no permission to bind',
        'the creator does not have permission to bind',
        'permission denied', 'invalid parameter', 'invalid parameters',
        'invalid request', 'too many requests', 'success', 'ok',
    })
    safe_code_names = frozenset({
        'BAD_REQUEST', 'FORBIDDEN', 'PERMISSION_DENIED', 'INVALID_PARAMETER',
        'UNAUTHORIZED', 'TOO_MANY_REQUESTS', 'SUCCESS', 'OK',
        # Actual success/permission codes and the historical UI receipt fixture.
        '0', '16004004', '20044017',
    })

    def status(value):
        return value if type(value) is int and 100 <= value <= 599 else None

    def stamp(value):
        if not isinstance(value, str) or len(value) > 40:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
        except (ValueError, OverflowError):
            pass
        return None

    def safe_code(value, creator):
        code = sanitizer._diagnostic_code(value)
        if code in safe_code_names and code.casefold() != creator.lstrip('@').casefold():
            return code
        return None

    def safe_message(value):
        text = sanitizer._diagnostic_text(value)
        if text and text.casefold().rstrip('.!') in safe_messages:
            return text
        return None

    def project(effect_id, cycle_id, creator, record, updated=None, *, settled=False):
        if not (isinstance(effect_id, str) and re.fullmatch(r'tiktok:[a-f0-9]{64}', effect_id)
                and isinstance(cycle_id, str) and cycle_id and isinstance(creator, str)
                and creator and isinstance(record, dict) and record.get('operation') == 'invite'
                and record.get('creator') == creator
                and record.get('cycle_id', cycle_id) == cycle_id
                and record.get('job_id', effect_id) == effect_id):
            return None
        # A durable real_job has the correlation columns outside its result. A
        # settled in-session receipt must instead explicitly bind both keys.
        if settled and (record.get('job_id') != effect_id or record.get('cycle_id') != cycle_id):
            return None
        evidence = record.get('evidence')
        if not isinstance(evidence, dict) or not (
                evidence.get('post_attempted') is True or evidence.get('bridge_post_attempted') is True):
            return None
        when = stamp(record.get('observed_at')) or stamp(updated)
        if not when:
            return None
        receipt = sanitizer._invite_receipt(evidence.get('receipt')) or {}
        raw_code = evidence.get('upstream_code')
        raw_message = evidence.get('upstream_message')
        code = safe_code(raw_code, creator) or safe_code(receipt.get('provider_code'), creator)
        message = safe_message(raw_message) or safe_message(receipt.get('provider_message'))
        row = {
            'observed_at': when, 'bridge_post_attempted': True,
            'bridge_http_status': status(evidence.get('http_status')),
            'provider_http_status': status(evidence.get('provider_http_status'))
                or status(receipt.get('provider_http_status')),
            'provider_reason_available': bool(code is not None or message is not None),
        }
        if code is not None:
            row['provider_code'] = code
        if message is not None:
            row['provider_message'] = message
        withheld = ((raw_code is not None or receipt.get('provider_code') is not None) and code is None
                    or (raw_message is not None or receipt.get('provider_message') is not None) and message is None)
        if withheld:
            row['provider_detail_withheld'] = True
        if not row['provider_reason_available']:
            row['provider_reason'] = 'detalhe omitido por privacidade' if withheld else 'motivo não informado'
        if type(receipt.get('provider_post_attempted')) is bool:
            row['provider_post_attempted'] = receipt['provider_post_attempted']
        if type(evidence.get('create_accepted')) is bool:
            row['create_accepted'] = evidence['create_accepted']
        if type(record.get('confirmed')) is bool:
            row['confirmed'] = record['confirmed']
        return row

    seen = {}
    # Durable job result is first-hand. A settled effect retained across
    # restarts can recover a receipt missing from jobs, not count it twice.
    for job in (job_rows or [])[:12]:
        if isinstance(job, dict):
            row = project(job.get('effect_id'), job.get('cycle_id'), job.get('creator'),
                          job.get('result'), job.get('updated_at'))
            if row:
                seen[job['effect_id']] = row
    for effect_id, effect in effects.items():
        if (effect_id in seen or not isinstance(effect, dict) or effect.get('type') != 'tiktok_operation'
                or effect.get('id') != effect_id or effect.get('operation') != 'invite'):
            continue
        row = project(effect_id, effect.get('cycle_id'), effect.get('creator'),
                      effect.get('result_receipt'), effect.get('resolved_at'), settled=True)
        if row:
            seen[effect_id] = row
    newest = sorted(seen.items(), key=lambda item: (item[1]['observed_at'], item[0]), reverse=True)[:12]
    return [{'attempt': number, **row} for number, (_, row) in enumerate(newest, 1)]
