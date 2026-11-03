"""Pure, fail-closed contract for one-contact Chatwoot rehearsal ingress."""

from __future__ import annotations

import re


def _identifier(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    return text if re.fullmatch(r"[1-9][0-9]{0,19}", text) else None


def normalize_phone(value) -> str | None:
    """Normalize one international phone, rejecting lists and ambiguous input."""
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9() .\-]+", value.strip()):
        return None
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15 or digits.startswith("0") or len(set(digits)) < 2:
        return None
    return digits


def _phone_variants(value) -> frozenset[str]:
    """At most two exact identities: the number and its Brazilian mobile alias.

    The alias removes only the mobile ninth digit immediately after country/DDD.
    It never removes arbitrary digits or authorizes a prefix/suffix match.
    """
    number = normalize_phone(value)
    if number is None:
        return frozenset()
    values = {number}
    # Release 43: only a mobile (first local digit 6-9) has the ninth-digit alias, in either direction.
    if re.fullmatch(r"55[1-9][0-9]9[6-9][0-9]{7}", number):
        values.add(number[:4] + number[5:])
    elif re.fullmatch(r"55[1-9][0-9][6-9][0-9]{7}", number):
        # Release 43: the same identity from the other side (56938, +558396914946 sem o 9).
        values.add(number[:4] + "9" + number[4:])
    return frozenset(values)


def phone_matches(configured, received) -> bool:
    """Match only exact variants derived from the configured pilot number."""
    candidate = normalize_phone(received)
    return candidate is not None and bool(_phone_variants(candidate) & _phone_variants(configured))


def same_phone(first, second) -> bool:
    """Compare two provider representations without inferring another identity."""
    return bool(_phone_variants(first) & _phone_variants(second))


MAX_PILOT_PHONES = 100


def parse_pilot_phones(raw, primary) -> tuple[tuple[str, ...] | None, str | None]:
    """Closed comma list of pilot phones; empty keeps the single-contact pilot.

    The configured primary phone must stay in the list, every entry must be a
    distinct exact number and the list is capped. Any defect closes readiness.
    """
    if raw is None or not str(raw).strip():
        return None, None
    phones, seen = [], set()
    for item in str(raw).split(","):
        number = normalize_phone(item)
        variants = _phone_variants(item)
        if number is None or not number.startswith("55") or variants & seen:
            return None, "pilot_phones_invalid"
        seen |= variants
        phones.append("+" + number)
    if not 1 <= len(phones) <= MAX_PILOT_PHONES:
        return None, "pilot_phones_invalid"
    if not any(same_phone(phone, primary) for phone in phones):
        return None, "pilot_phones_primary_missing"
    return tuple(phones), None


def pilot_phones(config) -> tuple[str, ...]:
    """Every phone the gate authorizes; without a list, only the gate phone."""
    if not isinstance(config, dict):
        return ()
    listed = config.get("phones")
    if isinstance(listed, (list, tuple)) and listed:
        return tuple(listed)
    return (config.get("phone"),) if config.get("phone") else ()


def gate_mode(config) -> str:
    """Release 47: V5_GATE_MODE. 'lista' (padrão) atende só V5_PILOT_PHONES; 'todos' atende toda a caixa."""
    return 'todos' if isinstance(config, dict) and config.get('mode') == 'todos' else 'lista'


def is_test_phone(config, received) -> bool:
    return isinstance(config, dict) and bool(config.get('phone')) and same_phone(config.get('phone'), received)


def pilot_phone(config, received) -> str | None:
    """Return the one configured phone that exactly matches ``received``.

    Release 47: no modo 'todos', todo telefone válido entra (o número que o próprio WhatsApp informou);
    as exclusões (etiqueta, responsável, controle humano) são lidas no Chatwoot pelo controle humano.
    """
    if gate_mode(config) == 'todos':
        number = normalize_phone(received)
        return '+' + number if number else None
    matches = [phone for phone in pilot_phones(config) if phone_matches(phone, received)]
    return matches[0] if len(matches) == 1 else None


def inbound_key(event: dict) -> str | None:
    if not isinstance(event, dict):
        return None
    provider = event.get("provider")
    account = _identifier(event.get("account_id"))
    message = _identifier(event.get("message_id"))
    if (not isinstance(provider, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", provider)
            or not account or not message):
        return None
    return f"{provider}:{account}:{message}"


def allow_inbound(config: dict, event: dict) -> bool:
    """Authorize exactly one configured phone/account/inbox; empty means off.

    No default account, inbox, phone or enabled flag is inferred. A valid phone
    and conversation are mandatory; private, outgoing, anonymous and foreign
    events are ignored without creating a conversation or business record.
    """
    if not isinstance(config, dict) or not isinstance(event, dict) or config.get("enabled") is not True:
        return False
    account, inbox = _identifier(config.get("account_id")), _identifier(config.get("inbox_id"))
    phone = normalize_phone(config.get("phone"))
    provider = config.get("provider")
    if not all((account, inbox, phone, isinstance(provider, str), inbound_key(event))):
        return False
    if event.get("event", "message_created") != "message_created":
        return False
    message_type = event.get("message_type")
    incoming = message_type == "incoming" or (type(message_type) is int and message_type == 0)
    if not incoming or event.get("private") is not False:
        return False
    sender_type = event.get("sender_type")
    if sender_type is not None and str(sender_type).lower() != "contact":
        return False
    return bool(
        provider == event.get("provider")
        and account == _identifier(event.get("account_id"))
        and inbox == _identifier(event.get("inbox_id"))
        and pilot_phone(config, event.get("sender_phone")) is not None
        and _identifier(event.get("conversation_id"))
        and isinstance(event.get("text"), str)
        and 0 < len(event["text"].strip()) <= 4000
    )
