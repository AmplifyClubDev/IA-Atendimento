"""Explicit private pilot configuration, with no embedded contact identities."""
import os
import re


def load_scope(environ=None):
    values = os.environ if environ is None else environ
    get = lambda name: str(values.get(name, '')).strip()
    phone = get('V5_RESTRICTED_PILOT_PHONE')
    identifier = lambda name: get(name) if re.fullmatch(r'[1-9][0-9]{0,19}', get(name)) else ''
    return {
        'phone': phone if re.fullmatch(r'\+55[1-9][0-9]9[0-9]{8}', phone) else '',
        'conversation_id': identifier('V5_PILOT_CONVERSATION_ID'),
        'contact_id': identifier('V5_PILOT_CONTACT_ID'),
    }


def scope_ready(scope):
    return (isinstance(scope, dict)
            and bool(re.fullmatch(r'\+55[1-9][0-9]9[0-9]{8}', str(scope.get('phone', ''))))
            and all(re.fullmatch(r'[1-9][0-9]{0,19}', str(scope.get(key, '')))
                    for key in ('conversation_id', 'contact_id')))


def restricted_phone(settings):
    scope = settings.get('pilot_scope') or {}
    return scope['phone'] if scope_ready(scope) else ''


def conversation_id(scope=None):
    scope = load_scope() if scope is None else scope
    return str(scope['conversation_id']) if scope_ready(scope) else ''


def contact_id(scope=None):
    scope = load_scope() if scope is None else scope
    return str(scope['contact_id']) if scope_ready(scope) else ''


def conversation_key(scope=None):
    identifier = conversation_id(scope)
    return 'chatwoot:1:' + identifier if identifier else ''


def historical_event_keys(name):
    """An explicit bounded list; no historical customer identifiers by default."""
    raw = os.environ.get(name, '').strip()
    if not raw:
        return frozenset()
    items = raw.split(',')
    if len(items) > 100 or any(not re.fullmatch(r'chatwoot:1:[1-9][0-9]{0,19}', item.strip()) for item in items):
        return frozenset()
    return frozenset(item.strip() for item in items)
