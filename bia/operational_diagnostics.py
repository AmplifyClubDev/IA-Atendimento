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
