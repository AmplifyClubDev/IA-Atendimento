"""Read-only discovery for one stalled, already-processed pilot conversation.

No replay, inbound reservation, provider operation, reply or repository write.
The optional internal callback must reserve recovery_key against the ORIGINAL
event, recheck scope/guard, project a new revision and atomically enqueue only
lookup/precheck/relationship. It must not change inbound history or the window.

Callback: v5_reconcile_initial(event=actual_event, state=snapshot,
                              recovery_key=opaque_key, provenance=source_kind) ->
    {"status": "scheduled"|"noop"|"blocked"|"outcome_unknown",
     "operations": ["lookup"|"precheck"|"relationship", ...]}

The original webhook digest is never altered. If API timestamp precision/schema
differs, authoritative API identity/time/content plus the last stored inbound
and its completed contact receipt can revalidate the source for technical reads.
No values or variants are guessed to match a hash.
"""

from offline_policy import effects_allowed, require_effects
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from uuid import UUID

from contracts import allow_inbound, inbound_key, phone_matches, same_phone


CONVERSATION = "chatwoot:1:26097"
READS = frozenset({"lookup", "precheck", "relationship"})
PHASES = frozenset({"intro", "origin", "tiktok", "shop", "agency", "checking"})


class SourceError(Exception):
    pass


def _result(status, reason, operations=()):
    return {"status": status, "reason": reason, "operations": list(operations)}


def _utc_now():
    return datetime.now(timezone.utc)


def _time(value):
    if isinstance(value, bool):
        raise ValueError()
    if isinstance(value, (int, float)):
        result = datetime.fromtimestamp(value, timezone.utc)
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError()
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError()
    return result.astimezone(timezone.utc)


def _id(value):
    return str(value) if type(value) in (int, str) and re.fullmatch(r"[1-9][0-9]{0,19}", str(value)) else None


def _dict(value):
    return value if isinstance(value, dict) else {}


def _state_ready(state, now):
    cycle = _dict(state.get("cycle"))
    facts = _dict(cycle.get("facts"))
    creator = facts.get("tiktok_declarado")
    if not isinstance(creator, str) or not re.fullmatch(r"@?[a-zA-Z0-9_][a-zA-Z0-9_.]{1,23}", creator):
        return False
    try:
        identity = UUID(state.get("creator_id"))
        cycle_id = UUID(cycle.get("id"))
        last, expiry = _time(cycle.get("last_inbound_at")), _time(cycle.get("expires_at"))
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        return False
    return bool(identity.int and cycle_id.int and cycle.get("mode") == "real" and cycle.get("status") == "open"
                and cycle.get("phase") in PHASES and facts.get("interesse_agenciamento") is True
                and facts.get("origem_declarada") in {"anuncio", "indicacao", "outro"}
                and not state.get("human_control") and not cycle.get("qualification_paused")
                and not cycle.get("pending_profile_changes") and last <= now < expiry
                and expiry <= last + timedelta(hours=24)
                and type(state.get("revision")) is int and state["revision"] > 0)


def _target(detail, gate):
    sender = _dict(_dict(detail.get("meta")).get("sender"))
    return (type(detail) is dict and _id(detail.get("id")) == "26097"
            and _id(detail.get("account_id")) == "1" and _id(detail.get("inbox_id")) == "3"
            and _id(sender.get("id")) == "3" and phone_matches(gate.get("phone"), sender.get("phone_number")))


def _source_event(message, detail, gate):
    sender = _dict(message.get("sender"))
    contact = _dict(_dict(detail.get("meta")).get("sender"))
    if (_id(sender.get("id")) != "3" or message.get("private") is not False
            or not (message.get("message_type") == "incoming" or type(message.get("message_type")) is int and message["message_type"] == 0)
            or _id(message.get("conversation_id")) != "26097"
            or message.get("inbox_id") is not None and _id(message.get("inbox_id")) != "3"
            or message.get("account_id") is not None and _id(message.get("account_id")) != "1"
            or sender.get("type") is not None and str(sender["type"]).lower() != "contact"
            or not isinstance(message.get("content"), str)):
        raise SourceError("source_identity_mismatch")
    phone = sender.get("phone_number", contact.get("phone_number"))
    if not same_phone(phone, contact.get("phone_number")) or not phone_matches(gate.get("phone"), phone):
        raise SourceError("source_identity_mismatch")
    created = _time(message.get("created_at")).isoformat().replace("+00:00", "Z")
    event = {"provider": "chatwoot", "event": "message_created", "account_id": detail["account_id"],
             "inbox_id": detail["inbox_id"], "conversation_id": detail["id"], "message_id": message["id"],
             "contact_id": "3", "sender_phone": phone, "sender_type": sender.get("type", contact.get("type")),
             "message_type": "incoming", "private": False, "text": message["content"], "created_at": created}
    event["source_ref"] = inbound_key(event)
    if not allow_inbound(gate, event):
        raise SourceError("source_identity_mismatch")
    return event


def _read_source(transport, gate, expected_key):
    seed = {"account_id": "1", "conversation_id": "26097"}
    url = transport._conversation_url(seed)
    headers = {"api_access_token": transport.token, "Accept": "application/json"}
    detail = transport.http(method="GET", url=url, headers=headers, timeout=8)
    if not isinstance(detail, dict) or not _target(detail, gate):
        raise SourceError("source_identity_mismatch")
    target_id = expected_key.rsplit(":", 1)[1]
    matches, before = [], None
    for _ in range(2):
        suffix = "?limit=20" + ("&before=" + before if before else "")
        data = transport.http(method="GET", url=url + "/messages" + suffix, headers=headers, timeout=8)
        messages = data.get("payload") if isinstance(data, dict) else None
        if not isinstance(messages, list) or len(messages) > 20 or any(not isinstance(item, dict) or not _id(item.get("id")) for item in messages):
            raise SourceError("source_page_unconfirmed")
        for message in messages:
            incoming = message.get("message_type") == "incoming" or type(message.get("message_type")) is int and message["message_type"] == 0
            if incoming and message.get("private") is False and int(message["id"]) > int(target_id):
                raise SourceError("new_inbound_pending")
            if _id(message["id"]) == target_id:
                matches.append(message)
        if matches or len(messages) < 20:
            break
        next_before = str(min(int(message["id"]) for message in messages))
        if before is not None and int(next_before) >= int(before):
            raise SourceError("source_page_unconfirmed")
        before = next_before
    if len(matches) != 1:
        raise SourceError("source_message_not_unique")
    return _source_event(matches[0], detail, gate)


def recover_stalled(app):
    """Discover one exact real source and invoke the optional internal callback.

    No external request is made unless the callback and exact pilot are enabled.
    All source/projection checks happen while holding the normal conversation
    lock; the callback owns durable at-most-once reservation and scheduling.
    """
    if not effects_allowed(settings=app.extensions.get('v5_settings')):
        return {'status': 'disabled', 'reason': 'nonproduction_external_effects_disabled'}
    extensions = app.extensions
    callback = extensions.get("v5_reconcile_initial")
    if not callable(callback):
        return _result("noop", "recovery_not_installed")
    settings = _dict(extensions.get("v5_settings"))
    gate = _dict(settings.get("gate"))
    repository, transport = extensions.get("v5_repository"), extensions.get("v5_transport")
    lock_for = extensions.get("v5_conversation_lock_for")
    guard = getattr(extensions.get("v5_real_executor"), "guard", None)
    if (settings.get("tiktok_mode") != "real" or settings.get("contact_sync_enabled") is not True
            or settings.get("real_worker_enabled") is not True or gate.get("enabled") is not True
            or gate.get("provider") != "chatwoot" or _id(gate.get("account_id")) != "1"
            or _id(gate.get("inbox_id")) != "3" or not callable(lock_for) or not callable(guard)
            or not repository or not transport or not transport.ready()):
        return _result("blocked", "recovery_scope_invalid")
    try:
        with lock_for(CONVERSATION):
            state = repository.load_session(CONVERSATION)
            now = _utc_now()
            if not _state_ready(state, now):
                return _result("noop", "qualification_not_stalled")
            processed = state.get("processed_inbound")
            source_key = processed[-1] if isinstance(processed, list) and processed else None
            if not isinstance(source_key, str) or not re.fullmatch(r"chatwoot:1:[1-9][0-9]{0,19}", source_key):
                return _result("blocked", "source_reference_missing")
            cycle, revision = state["cycle"], state["revision"]
            proof = _dict(state.get("contact_sync_proof"))
            expected = {"creator_id": state["creator_id"], "atendimento_id": cycle["id"],
                        "event_id": source_key, "revision": revision}
            source = repository.event(source_key)
            receipt = repository.get_operation(source_key + ":contact:" + str(revision))
            if (any(proof.get(key) != value for key, value in expected.items())
                    or not source or source.get("conversation_key") != CONVERSATION or source.get("status") != "completed"
                    or not receipt or receipt.get("status") != "completed"
                    or any(_dict(receipt.get("result")).get(key) != value for key, value in expected.items())):
                return _result("blocked", "contact_projection_unconfirmed")
            event = _read_source(transport, gate, source_key)
            digest = hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            created = _time(event["created_at"])
            received = _time(source.get("created_at"))
            if not (now - timedelta(hours=24) <= created <= received + timedelta(seconds=2)
                    and received <= now and created <= _time(cycle["last_inbound_at"]) <= now):
                return _result("blocked", "source_time_invalid")
            if not isinstance(source.get("digest"), str) or not re.fullmatch(r"[a-f0-9]{64}", source["digest"]):
                return _result("blocked", "source_digest_missing")
            provenance = "webhook_digest_confirmed"
            if digest != source["digest"]:
                inbound = [item for item in state.get("history", []) if isinstance(item, dict)
                           and item.get("direction") == "inbound" and item.get("cycle_id") == cycle["id"]]
                if (not inbound or inbound[-1].get("text") != event["text"]
                        or _time(inbound[-1].get("at")) != _time(cycle["last_inbound_at"])
                        or received > _time(inbound[-1].get("at")) + timedelta(seconds=2)):
                    return _result("blocked", "source_content_unconfirmed")
                provenance = "revalidated_chatwoot_source"
            key_data = f"initial-checks-v1:{cycle['id']}:{cycle['facts']['tiktok_declarado'].lower().removeprefix('@')}:{source_key}"
            recovery_key = hashlib.sha256(key_data.encode()).hexdigest()
            previous = repository.event("reconcile:" + recovery_key) or repository.get_operation("reconcile:" + recovery_key)
            if previous:
                return _result("noop" if previous.get("status") == "completed" else "blocked", "recovery_already_reserved")
            control = guard(event)
            if not isinstance(control, dict) or control.get("allowed") is not True:
                return _result("blocked", "human_control_unconfirmed")
            if repository.load_session(CONVERSATION) != state:
                return _result("blocked", "state_changed")
            # This callback may persist a technical projection, never a replay.
            try:
                result = callback(event=deepcopy(event), state=deepcopy(state), recovery_key=recovery_key,
                                  provenance=provenance)
            except Exception:
                return _result("outcome_unknown", "recovery_callback_unconfirmed")
            operations = result.get("operations", []) if isinstance(result, dict) else None
            if (not isinstance(result, dict) or result.get("status") not in {"scheduled", "noop", "blocked", "outcome_unknown"}
                    or not isinstance(operations, list) or len(operations) > 3
                    or any(operation not in READS for operation in operations) or len(set(operations)) != len(operations)):
                return _result("outcome_unknown", "recovery_callback_unconfirmed")
            return _result(result["status"], "recovery_callback_observed", operations)
    except SourceError as error:
        return _result("blocked", error.args[0])
    except Exception:
        return _result("blocked", "source_unconfirmed")
