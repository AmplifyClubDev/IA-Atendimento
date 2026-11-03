"""Source-bound, account-scoped label inventory; creation is explicitly opt-in.

Default operation performs GET only. --setup may create missing approved label
definitions after the complete scope/inventory/rules gates. It never changes
existing definitions, automations, contacts, conversations or messages. This
module uses only the standard library, never app bootstrap or providers. Its
phone comparison mirrors the existing pure contracts.phone_matches semantics.

The index contract is Chatwoot 4.15.1, commit
97bb8ecd326299c46eacea74863976427c96fe94: labels and automation_rules are
unpaginated {"payload": [...]} collections. Pagination or an unfamiliar shape
closes the gate. Definitions below are a local candidate for root approval.
"""

import argparse
import hashlib
import json
import os
import re
import ssl
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

SOURCE_COMMIT = "97bb8ecd326299c46eacea74863976427c96fe94"
CHAT_HOST = "chatwoot.t2ffoz.easypanel.host"
ACCOUNT_ID = "1"
INBOX_ID = "3"
CONVERSATION_ID = "26097"
CONTACT_ID = "3"
INBOX_NAME = "Amplify – Aquisição"
DESCRIPTION = "Etapa de atendimento."
APPROVED_LABELS = tuple(
    {"title": title, "color": color, "description": DESCRIPTION, "show_on_sidebar": True}
    for title, color in (
        ("conhecer", "#6153FF"),
        ("qualificação", "#6153FF"),
        ("validação", "#6153FF"),
        ("convite", "#6153FF"),
        ("cadastro", "#6153FF"),
    )
)
INACTIVITY_CLOSED_LABEL = {
    'title': 'encerrado', 'color': '#64748B', 'description': DESCRIPTION, 'show_on_sidebar': True,
}


def _approved_labels(include_closed=False):
    return APPROVED_LABELS + ((INACTIVITY_CLOSED_LABEL,) if include_closed else ())
TIMEOUT = 15
MAX_RESPONSE = 2_097_152
_KNOWN_EVENTS = frozenset(("conversation_created", "conversation_updated", "message_created"))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GateClosed(Exception):
    """Only fixed reason codes may be attached; no provider text is exposed."""


def _client():
    return build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())


def _check(ok, reason="ok", code=None):
    return {"ok": bool(ok), "reason": reason, "code": code if type(code) is int else None}


def _identifier(value):
    if type(value) not in (str, int):
        return None
    value = str(value)
    return value if re.fullmatch(r"[1-9][0-9]{0,19}", value) else None


def _host(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", value):
        return None
    if "." not in value or any(not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
                               for part in value.split(".")):
        return None
    return value


def _base_matches(value, expected_host):
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.netloc == expected_host
                and parsed.hostname == expected_host and parsed.port is None
                and parsed.path in ("", "/")
                and not any((parsed.username, parsed.password, parsed.query, parsed.fragment)))
    except (TypeError, ValueError):
        return False


def _inbox_name(value):
    if not isinstance(value, str):
        return None
    # Only whitespace and the two explicitly approved dash spellings vary.
    return " ".join(value.replace("–", "-").split())


def _normalize_phone(value):
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9() .\-]+", value.strip()):
        return None
    digits = re.sub(r"\D", "", value)
    if not 10 <= len(digits) <= 15 or digits.startswith("0") or len(set(digits)) < 2:
        return None
    return digits


def _phone_matches(configured, received):
    """Mirror contracts.phone_matches without importing runtime modules."""
    number, candidate = _normalize_phone(configured), _normalize_phone(received)
    if number is None or candidate is None:
        return False
    variants = {number}
    if re.fullmatch(r"55[1-9][0-9]9[0-9]{8}", number):
        variants.add(number[:4] + number[5:])
    return candidate in variants


def _settings(environ, target, setup):
    values = os.environ if environ is None else environ
    get = lambda key: str(values.get(key, "")).strip()
    token = get("CHATWOOT_API_TOKEN")
    expected_host = _host(target.get("host"))
    valid = (expected_host == CHAT_HOST
             and target.get("account_id") == ACCOUNT_ID
             and target.get("inbox_id") == INBOX_ID
             and target.get("conversation_id") == CONVERSATION_ID
             and target.get("contact_id") == CONTACT_ID
             and get("V5_ENABLED").lower() == "true"
             and get("CHATWOOT_ACCOUNT_ID") == ACCOUNT_ID
             and get("CHATWOOT_INBOX_ID") == INBOX_ID
             and _base_matches(get("CHATWOOT_BASE_URL"), expected_host)
             and bool(re.fullmatch(r"\+55[1-9][0-9]9[0-9]{8}", get("V5_TEST_PHONE")))
             and bool(token) and len(token) <= 4096
             and not any(ord(char) < 33 or ord(char) > 126 for char in token))
    if setup:
        valid = valid and get("V5_CHATWOOT_STAGES_ENABLED").lower() == "true"
    if not valid:
        raise GateClosed("configuration_or_target_invalid")
    return {"base": "https://" + expected_host, "token": token, "phone": get("V5_TEST_PHONE"),
            "include_closed": get("V5_INACTIVITY_CLOSE_ENABLED").lower() == "true"}


def _request(client, method, url, token, body=None):
    """Return bounded provider data privately; never expose URL/error/body text."""
    headers = {"api_access_token": token, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        request = Request(url, headers=headers, data=data, method=method)
        with client.open(request, timeout=TIMEOUT) as response:
            status = response.status
            raw = response.read(MAX_RESPONSE + 1)
            response_headers = dict(response.headers.items())
            if len(raw) > MAX_RESPONSE:
                return _check(False, "response_too_large", status), None, response_headers
            if status not in ((200,) if method == "GET" else (200, 201)):
                return _check(False, "http_rejected", status), None, response_headers
            try:
                value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
            except (ValueError, UnicodeError):
                return _check(False, "invalid_json", status), None, response_headers
            return _check(True, code=status), value, response_headers
    except HTTPError as error:
        code = error.code
        error.close()
        return _check(False, "redirect_rejected" if 300 <= code < 400 else "http_rejected", code), None, {}
    except Exception:
        return _check(False, "transport_failed"), None, {}


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError("non_json_constant")


def _collection(value, headers):
    if not isinstance(value, dict) or set(value) != {"payload"} or not isinstance(value["payload"], list):
        raise GateClosed("inventory_shape_invalid")
    lowered = {str(key).lower(): str(item).strip() for key, item in headers.items()}
    # These source-bound indexes are not paginated. Any pagination signal needs
    # a new reviewed contract, even if the current response appears to be page 1.
    for key in ("link", "content-range", "x-page", "x-current-page", "x-next-page", "x-prev-page", "x-total-pages",
                "x-per-page", "x-offset", "x-limit"):
        if lowered.get(key):
            raise GateClosed("inventory_pagination_detected")
    if any(value for key, value in lowered.items() if "pagination" in key):
        raise GateClosed("inventory_pagination_detected")
    if "x-total-count" in lowered and lowered["x-total-count"] != str(len(value["payload"])):
        raise GateClosed("inventory_count_mismatch")
    if not all(isinstance(row, dict) for row in value["payload"]):
        raise GateClosed("inventory_row_invalid")
    return value["payload"]


def _inventory(client, settings, resource):
    result, value, headers = _request(client, "GET", settings["base"] + "/api/v1/accounts/" + ACCOUNT_ID + "/" + resource,
                                      settings["token"])
    if not result["ok"]:
        raise GateClosed(resource + "_unavailable")
    return _collection(value, headers)


def _label_key(value):
    text = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub("[‐‑‒–—―−]", "-", text)


def inspect_labels(rows, *, include_closed=False):
    """Return only fixed allowlist names; keep unrelated labels private."""
    by_key = {}
    ids = set()
    for row in rows:
        label_id, title = _identifier(row.get("id")), row.get("title")
        if (label_id is None or label_id in ids or not isinstance(title, str) or not title.strip()
                or len(title) > 255 or any(ord(char) < 32 or ord(char) == 127 for char in title)):
            raise GateClosed("labels_malformed")
        ids.add(label_id)
        key = _label_key(title)
        if key in by_key:
            raise GateClosed("labels_ambiguous_duplicate")
        by_key[key] = row
    existing, missing, collisions = [], [], []
    for definition in _approved_labels(include_closed):
        title = definition["title"]
        row = by_key.get(title)
        if row is None:
            missing.append(title)
        elif all(type(row.get(key)) is type(value) and row.get(key) == value for key, value in definition.items()):
            existing.append(title)
        else:
            collisions.append(title)
    return {"total": len(rows), "existing": existing, "missing": missing, "collisions": collisions}


def _mentions_labels(value):
    if isinstance(value, dict):
        return any(_mentions_labels(key) or _mentions_labels(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_mentions_labels(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        # Stage names are ordinary Portuguese words. Their occurrence in a
        # maintenance message is not a label condition/action or a new trigger.
        return "label" in lowered
    return False


def inspect_rules(rows):
    ids, summary, review_required = set(), [], False
    for row in rows:
        rule_id, active, event = _identifier(row.get("id")), row.get("active"), row.get("event_name")
        if (rule_id is None or rule_id in ids or type(active) is not bool or not isinstance(event, str)
                or not event or not isinstance(row.get("conditions"), list) or not isinstance(row.get("actions"), list)
                or not all(isinstance(item, dict) for item in row["conditions"] + row["actions"])):
            raise GateClosed("automation_rules_malformed")
        ids.add(rule_id)
        reason = "inactive" if not active else "unrelated_event"
        if active:
            if event not in _KNOWN_EVENTS:
                reason = "unknown_event"
            elif event == "conversation_updated":
                reason = "conversation_update_trigger"
            elif _mentions_labels(row["conditions"]) or _mentions_labels(row["actions"]):
                reason = "label_reference"
        risky = active and reason in ("unknown_event", "conversation_update_trigger", "label_reference")
        review_required = review_required or risky
        summary.append({"id": int(rule_id), "active": active, "event": event if event in _KNOWN_EVENTS else "other",
                        "conditions": len(row["conditions"]), "actions": len(row["actions"]),
                        "review_required": risky, "reason": reason})
    ordered = sorted(rows, key=lambda row: int(row["id"]))
    digest = hashlib.sha256(json.dumps(ordered, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return {"total": len(rows), "active": sum(1 for row in rows if row["active"]),
            "sha256": digest, "review_required": review_required,
            "rules": sorted(summary, key=lambda row: row["id"])}


def _scope(client, settings, target):
    prefix = settings["base"] + "/api/v1/accounts/" + ACCOUNT_ID
    result, inbox, _ = _request(client, "GET", prefix + "/inboxes/" + INBOX_ID, settings["token"])
    if (not result["ok"] or not isinstance(inbox, dict) or _identifier(inbox.get("id")) != INBOX_ID
            or _inbox_name(inbox.get("name")) != _inbox_name(INBOX_NAME)
            or ("account_id" in inbox and _identifier(inbox["account_id"]) != ACCOUNT_ID)):
        raise GateClosed("inbox_scope_unverified")
    result, conversation, _ = _request(client, "GET", prefix + "/conversations/" + CONVERSATION_ID, settings["token"])
    if not result["ok"] or not isinstance(conversation, dict):
        raise GateClosed("conversation_scope_unverified")
    meta = conversation.get("meta")
    sender = meta.get("sender") if isinstance(meta, dict) else None
    if (not isinstance(sender, dict) or _identifier(conversation.get("id")) != CONVERSATION_ID
            or _identifier(conversation.get("account_id")) != ACCOUNT_ID
            or _identifier(conversation.get("inbox_id")) != INBOX_ID
            or _identifier(sender.get("id")) != target["contact_id"]
            or ("type" in sender and sender["type"] != "contact")
            or not _phone_matches(settings["phone"], sender.get("phone_number"))):
        raise GateClosed("conversation_scope_unverified")


def run_preflight(environ=None, *, expected_host=None, expected_account_id=None, expected_inbox_id=None,
                  expected_conversation_id=None, expected_contact_id=None, setup=False,
                  approved_rules_sha256=None, require_labels=False, http_factory=None):
    """Use an injected urllib-compatible client in tests; return sanitized JSON."""
    output = {"passed": False, "mode": "setup" if setup else "readonly", "source_commit": SOURCE_COMMIT,
              "checks": {}, "post_attempts": 0, "created": [], "reconciled": [], "outcome_unknown": False}
    checks = output["checks"]
    target = {"host": expected_host, "account_id": expected_account_id, "inbox_id": expected_inbox_id,
              "conversation_id": expected_conversation_id, "contact_id": expected_contact_id}
    try:
        settings = _settings(environ, target, setup)
        if approved_rules_sha256 is not None and not re.fullmatch(r"[a-f0-9]{64}", approved_rules_sha256):
            raise GateClosed("approved_rules_hash_invalid")
        checks["configuration"] = _check(True)
        client = (http_factory or _client)()
        _scope(client, settings, target)
        checks["scope"] = _check(True)
        label_rows = _inventory(client, settings, "labels")
        definitions = _approved_labels(settings['include_closed'])
        labels = inspect_labels(label_rows, include_closed=settings['include_closed'])
        output["labels"] = labels
        checks["labels_inventory"] = _check(True)
        rules = inspect_rules(_inventory(client, settings, "automation_rules"))
        output["automation_rules"] = rules
        checks["rules_inventory"] = _check(True)
        if setup and labels["collisions"]:
            raise GateClosed("label_definition_collision")
        if approved_rules_sha256 is not None and approved_rules_sha256 != rules["sha256"]:
            raise GateClosed("approved_rules_hash_mismatch")
        if rules["review_required"] and approved_rules_sha256 != rules["sha256"]:
            raise GateClosed("automation_rules_review_required")
        checks["rules_gate"] = _check(True)
        if require_labels and labels["missing"]:
            raise GateClosed("required_stage_labels_missing")
        if require_labels and any(definition["title"] not in {row["title"] for row in label_rows}
                                  for definition in definitions):
            raise GateClosed("required_stage_titles_not_exact")
        if not setup:
            output["passed"] = True
            return output
        for definition in definitions:
            title = definition["title"]
            if title not in labels["missing"]:
                continue
            # Recheck the entire scope and both inventories immediately before
            # each POST. A race/change closes the gate rather than being ignored.
            _scope(client, settings, target)
            latest_labels = inspect_labels(_inventory(client, settings, "labels"), include_closed=settings['include_closed'])
            latest_rules = inspect_rules(_inventory(client, settings, "automation_rules"))
            if latest_labels["collisions"]:
                raise GateClosed("label_definition_collision")
            if latest_rules["sha256"] != rules["sha256"]:
                raise GateClosed("automation_rules_changed")
            if title in latest_labels["existing"]:
                continue
            output["post_attempts"] += 1
            result, _, _ = _request(client, "POST", settings["base"] + "/api/v1/accounts/" + ACCOUNT_ID + "/labels",
                                      settings["token"], dict(definition))
            # Every POST is followed by independent GET readback. If the ACK was
            # lost, only reconciliation is permitted; this invocation stops.
            try:
                after = inspect_labels(_inventory(client, settings, "labels"), include_closed=settings['include_closed'])
            except GateClosed:
                output["outcome_unknown"] = True
                raise GateClosed("label_create_outcome_unknown")
            if after["collisions"] or title not in after["existing"]:
                output["outcome_unknown"] = True
                raise GateClosed("label_create_outcome_unknown")
            if not result["ok"]:
                output["reconciled"].append(title)
                raise GateClosed("label_create_ack_uncertain_reconciled_stop")
            output["created"].append(title)
        output["labels"] = inspect_labels(_inventory(client, settings, "labels"), include_closed=settings['include_closed'])
        final_rules = inspect_rules(_inventory(client, settings, "automation_rules"))
        if output["labels"]["collisions"] or output["labels"]["missing"]:
            raise GateClosed("final_labels_unverified")
        if final_rules["sha256"] != rules["sha256"]:
            raise GateClosed("automation_rules_changed")
        checks["setup"] = _check(True)
        output["passed"] = True
    except GateClosed as error:
        checks["gate"] = _check(False, str(error))
    except Exception:
        checks["gate"] = _check(False, "preflight_failed")
    return output


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal error includes arbitrary supplied values.
        raise GateClosed("arguments_invalid")


def main(argv=None, environ=None, *, http_factory=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--expected-inbox-id", required=True)
    parser.add_argument("--expected-conversation-id", required=True)
    parser.add_argument("--expected-contact-id", required=True)
    parser.add_argument("--approved-rules-sha256")
    parser.add_argument("--require-labels", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = run_preflight(environ, expected_host=args.expected_host, expected_account_id=args.expected_account_id,
                               expected_inbox_id=args.expected_inbox_id, expected_conversation_id=args.expected_conversation_id,
                               expected_contact_id=args.expected_contact_id, setup=args.setup,
                               approved_rules_sha256=args.approved_rules_sha256, require_labels=args.require_labels,
                               http_factory=http_factory)
    except GateClosed:
        result = {"passed": False, "checks": {"arguments": _check(False, "arguments_invalid")}}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
