"""Bounded Chatwoot transport: recipient readback, then exactly one POST."""

from __future__ import annotations

import json
import hashlib
import re
from copy import deepcopy
from datetime import datetime
from uuid import UUID
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from contracts import allow_inbound, normalize_phone, phone_matches, pilot_phone


_PROGRESS_PHASES = {
    "intro": "conhecer", "origin": "qualificação", "tiktok": "qualificação",
    "shop": "qualificação", "agency": "qualificação", "consent": "validação",
    "await_acceptance": "convite", "form": "cadastro",
    "checking": "validação", "checking_acceptance": "convite", "blocked": "validação",
    "consent_real": "convite", "inviting": "convite", "acesso": "cadastro",
}
_PROGRESS_OWNED = frozenset(_PROGRESS_PHASES.values())
_PROGRESS_WITH_CLOSED = _PROGRESS_OWNED | {'encerrado'}
# Release 48: "encerrado" fica junto da etiqueta da etapa, para mostrar onde o lead parou.
_INACTIVITY_REASONS = frozenset({'inactivity_timeout', 'inactivity_user_close'})


def _linked(state):
    """O vínculo já foi comprovado (lista de vínculos, aviso do vínculo, ficha ou acesso)."""
    cycle = state.get('cycle') or {}
    operations = cycle.get('real_operations') if isinstance(cycle.get('real_operations'), dict) else {}
    return bool(any(isinstance(operations.get(name), dict) and operations[name].get('status') == 'linked'
                    and operations[name].get('confirmed') is True for name in ('relationship', 'invite'))
                or cycle.get('linked_notice') or cycle.get('form_receipt') or cycle.get('acesso_liberado')
                or state.get('cadastro_situacao') == 'confirmado')


def _stage_label(state):
    """Release 48: a fase "form" começa logo depois do convite; sem vínculo comprovado, o lead ainda está no convite."""
    phase = (state.get('cycle') or {}).get('phase')
    label = _PROGRESS_PHASES[phase]
    return 'convite' if label == 'cadastro' and not _linked(state) else label


def _window_closed(cycle, now):
    """A janela de 24 h do atendimento aberto já passou (o lead parou de responder)."""
    try:
        expires = datetime.fromisoformat(str(cycle.get('expires_at')).replace('Z', '+00:00'))
        at = datetime.fromisoformat(str(now).replace('Z', '+00:00'))
        return expires.tzinfo is not None and at.tzinfo is not None and at >= expires
    except (TypeError, ValueError):
        return False


def _progress_owned(gate):
    return _PROGRESS_WITH_CLOSED if gate.get('inactivity_close_enabled') is True else _PROGRESS_OWNED


def _progress_fence(state):
    cycle = state.get("cycle") or {}
    return (state.get("session_id"), state.get("creator_id"), cycle.get("id"),
            state.get("revision"), cycle.get("phase"), cycle.get("status"), cycle.get("reason"))


class ChatwootProgress:
    """Optional visual projection, never a source of truth or a message sender.

    The adapter limits server-side add/remove to owned labels with
    progress_owned_merge=True, read_progress(event)->labels or None, and
    write_progress(event, labels, operation_key)->status. Other teams' labels
    are never resent or included in the removal set.
    Callers serialize this projection with their existing conversation lock.
    """

    def __init__(self, repository, gate, adapter=None):
        self.repository, self.gate, self.adapter = repository, dict(gate or {}), adapter

    def _live(self, event, state):
        key = f"chatwoot:{event['account_id']}:{event['conversation_id']}"
        return _progress_fence(self.repository.load_session(key)) == _progress_fence(state)

    def _persist(self, event, state, cache):
        key = f"chatwoot:{event['account_id']}:{event['conversation_id']}"
        live = self.repository.load_session(key)
        if _progress_fence(live) != _progress_fence(state):
            return False
        live["chatwoot_progress"] = deepcopy(cache)
        self.repository.save_session(key, live)
        state["chatwoot_progress"] = deepcopy(cache)
        return True

    def _read(self, event):
        try:
            value = self.adapter.read_progress(event)
            if not isinstance(value, list) or any(not isinstance(label, str) for label in value):
                return None
            return sorted(set(value) & _progress_owned(self.gate))
        except Exception:
            return None

    def sync(self, event, state, proof):
        """Project only an exact SQL-confirmed snapshot; visual failures stay local."""
        try:
            return self._sync(event, state, proof)
        except Exception:
            return {"status": "failed", "reason": "projection_unavailable"}

    def _sync(self, event, state, proof):
        pinned = not self.gate.get("phones")
        if (not allow_inbound(self.gate, event) or not _id(event.get("contact_id"))
                or pinned and (_id(event.get("conversation_id")) != _id(self.gate.get("conversation_id"))
                               or _id(event.get("contact_id")) != _id(self.gate.get("contact_id")))):
            return {"status": "ignored", "reason": "outside_pilot"}
        if (getattr(self.adapter, "progress_owned_merge", None) is not True
                or not callable(getattr(self.adapter, "read_progress", None))
                or not callable(getattr(self.adapter, "write_progress", None))):
            return {"status": "disabled", "reason": "owned_label_adapter_required"}
        cycle = state.get("cycle") or {}
        receipt = proof.get("receipt") if isinstance(proof, dict) else None
        receipt = receipt if isinstance(receipt, dict) else {}
        revision = state.get("revision")
        if (type(revision) is not int or revision < 1 or not isinstance(cycle.get("id"), str)
                or str(UUID(cycle["id"])) != cycle["id"] or cycle.get("phase") not in _PROGRESS_PHASES
                or proof.get("kind") != "parado" and receipt.get("creator_id") != state.get("creator_id")):
            return {"status": "ignored", "reason": "sql_proof_required"}
        form = proof.get("kind") == "registration"
        stopped = proof.get("kind") == "parado"
        if stopped:
            # Sem mensagem nova: só conversas que já tiveram uma etapa confirmada (e projetada) antes.
            confirmed_labels = (state.get("chatwoot_progress") or {}).get("confirmed_labels") or []
            prior = state.get("processed_inbound") or []
            event_key = prior[-1] if prior else None
            valid = ('encerrado' in _progress_owned(self.gate) and cycle.get("status") == "open"
                     and _window_closed(cycle, proof.get("now"))
                     and bool(set(confirmed_labels) & _PROGRESS_OWNED))
        elif form:
            form_receipt = cycle.get("form_receipt") or {}
            valid = (receipt.get("status") in {"cadastro_recebido_ensaio", "cadastro_recebido_real"}
                     and cycle.get("status") == "closed" and cycle.get("reason") == "validated_form"
                     and form_receipt.get("creator_id") == state.get("creator_id")
                     and form_receipt.get("event_id") == receipt.get("event_id"))
            prior = state.get("processed_inbound") or []
            event_key = prior[-1] if prior else None
        else:
            event_key = f"chatwoot:{event['account_id']}:{event['message_id']}"
            confirmed = proof.get("snapshot") or {}
            valid = (proof.get("kind") == "contact" and receipt.get("atendimento_id") == cycle["id"]
                     and receipt.get("event_id") == event_key
                     and type(receipt.get("revision")) is int and 1 <= receipt["revision"] <= revision
                     and confirmed == {"cycle_id": cycle["id"], "phase": cycle["phase"],
                                       "status": cycle["status"], "revision": receipt["revision"]})
        stored_event = self.repository.event(event_key) if isinstance(event_key, str) else None
        conversation = f"chatwoot:{event['account_id']}:{event['conversation_id']}"
        if not valid or not stored_event or stored_event.get("conversation_key") != conversation:
            return {"status": "ignored", "reason": "sql_proof_required"}
        if not self._live(event, state):
            return {"status": "ignored", "reason": "stale_snapshot"}
        if cycle.get("status") not in {"open", "closed", "expired"}:
            return {"status": "ignored", "reason": "unmapped_state"}
        closed = 'encerrado' in _progress_owned(self.gate) and (
            stopped or cycle.get('status') == 'expired'
            or cycle.get('status') == 'closed' and cycle.get('reason') in _INACTIVITY_REASONS)
        desired = sorted({_stage_label(state)} | ({'encerrado'} if closed else set()))
        signature = hashlib.sha256(json.dumps(desired, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache = deepcopy(state.get("chatwoot_progress") or {})
        pending = cache.get("pending")
        if isinstance(pending, dict):
            # A lost ACK is settled by GET only, including after a process restart.
            actual = self._read(event)
            if actual != pending.get("labels"):
                return {"status": "outcome_unknown", "reason": "pending_readback_required"}
            self.repository.complete_operation(pending["operation_key"], {"labels": actual}, "completed")
            cache = {"confirmed_signature": pending["signature"], "confirmed_labels": actual}
            if not self._persist(event, state, cache):
                return {"status": "ignored", "reason": "stale_snapshot"}
        if cache.get("confirmed_signature") == signature:
            return {"status": "unchanged"}
        if cache.get("failed_signature") == signature:
            return {"status": "failed", "reason": "previous_rejection"}
        actual = self._read(event)
        if actual is None:
            return {"status": "failed", "reason": "target_unverified"}
        if actual == desired:
            self._persist(event, state, {"confirmed_signature": signature, "confirmed_labels": desired})
            return {"status": "confirmed", "changed": False}
        if not self._live(event, state):
            return {"status": "ignored", "reason": "stale_snapshot"}
        operation = f"{event_key}:labels:{cycle['id']}:{revision}:{signature[:16]}"
        if not self.repository.reserve_operation(operation, event_key, "chatwoot_progress_labels"):
            return {"status": "outcome_unknown", "reason": "operation_already_reserved"}
        cache["pending"] = {"operation_key": operation, "signature": signature, "labels": desired,
                            "cycle_id": cycle["id"], "revision": revision}
        if not self._persist(event, state, cache):
            return {"status": "ignored", "reason": "stale_snapshot"}
        try:
            outcome = self.adapter.write_progress(event, desired, operation)
        except Exception:
            outcome = {"status": "outcome_unknown"}
        if isinstance(outcome, dict) and outcome.get("status") == "failed":
            self.repository.complete_operation(operation, {"reason": "labels_rejected"}, "failed")
            cache.pop("pending", None)
            cache["failed_signature"] = signature
            self._persist(event, state, cache)
            return {"status": "failed", "reason": "labels_rejected"}
        actual = self._read(event)
        if actual == desired:
            self.repository.complete_operation(operation, {"labels": actual}, "completed")
            if not self._persist(event, state, {"confirmed_signature": signature, "confirmed_labels": desired}):
                return {"status": "ignored", "reason": "stale_snapshot"}
            return {"status": "confirmed", "changed": True}
        return {"status": "outcome_unknown", "reason": "readback_unconfirmed"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _http(*, method, url, headers, json_body=None, timeout=15):
    encoded = json.dumps(json_body, ensure_ascii=False).encode() if json_body is not None else None
    request = Request(url, data=encoded, headers=headers, method=method)
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        data = response.read(1_000_001)
    if len(data) > 1_000_000:
        raise ValueError("response_too_large")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("invalid_response")
    return payload


def _id(value):
    return str(value) if type(value) in {str, int} and re.fullmatch(r"[1-9][0-9]{0,19}", str(value)) else None


class ChatwootTransport:
    progress_owned_merge = True
    supports_reply_fencing = True

    def __init__(self, base_url, token, gate, http=None, interactive=True, cloud=None):
        self.base_url = str(base_url or "").rstrip("/")
        # Optional WhatsApp Cloud API access, used only for the form URL button.
        cloud = cloud if isinstance(cloud, dict) else {}
        self.cloud = ({"token": str(cloud["token"]), "phone_number_id": str(cloud["phone_number_id"])}
                      if cloud.get("token") and re.fullmatch(r"[0-9]{5,30}", str(cloud.get("phone_number_id") or "")) else None)
        self.token = str(token or "")
        self.gate = dict(gate or {})
        self.http = http or _http
        self.interactive = interactive is True

    def ready(self):
        try:
            parsed = urlsplit(self.base_url)
            parsed.port
        except ValueError:
            return False
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment and parsed.path in {"", "/"}
                    and self.token and not re.search(r"[\r\n]", self.token))

    def _conversation_url(self, event):
        account, conversation = _id(event.get("account_id")), _id(event.get("conversation_id"))
        if not account or not conversation:
            raise ValueError("invalid_target")
        return f"{self.base_url}/api/v1/accounts/{account}/conversations/{conversation}"

    def _read_target(self, event, require_reply_window=True, *, timeout=15, require_contact=False):
        detail = self.http(method="GET", url=self._conversation_url(event),
                           headers={"api_access_token": self.token, "Accept": "application/json"}, timeout=timeout)
        if not isinstance(detail, dict):
            return False
        sender = (detail.get("meta") or {}).get("sender") or {}
        return bool(
            _id(detail.get("id")) == _id(event.get("conversation_id"))
            and _id(detail.get("account_id")) == _id(self.gate.get("account_id")) == _id(event.get("account_id"))
            and _id(detail.get("inbox_id")) == _id(self.gate.get("inbox_id")) == _id(event.get("inbox_id"))
            and pilot_phone(self.gate, sender.get("phone_number")) is not None
            and pilot_phone(self.gate, sender.get("phone_number")) == pilot_phone(self.gate, event.get("sender_phone"))
            and (not require_contact or (_id(sender.get("id")) == _id(event.get("contact_id"))
                                         and (bool(self.gate.get("phones")) or _id(event.get("contact_id")) == "3")))
            and (not require_reply_window or detail.get("can_reply") is True)
        )

    def _progress_allowed(self, event):
        # The metadata pilot is narrower than the message gate: one proven chat.
        return (self.ready() and allow_inbound(self.gate, event)
                and urlsplit(self.base_url).hostname == "chatwoot.t2ffoz.easypanel.host"
                and urlsplit(self.base_url).port in (None, 443)
                and _id(event.get("account_id")) == "1" and _id(event.get("inbox_id")) == "3"
                and (bool(self.gate.get("phones")) and bool(_id(event.get("conversation_id"))) and bool(_id(event.get("contact_id")))
                     or _id(event.get("conversation_id")) == "26097" and _id(event.get("contact_id")) == "3"))

    def read_progress(self, event):
        if not self._progress_allowed(event):
            return None
        try:
            if not self._read_target(event, require_reply_window=False, timeout=3, require_contact=True):
                return None
            value = self.http(method="GET", url=self._conversation_url(event) + "/labels",
                              headers={"api_access_token": self.token, "Accept": "application/json"}, timeout=3)
            labels = value.get("payload") if isinstance(value, dict) else None
            return labels if isinstance(labels, list) and len(labels) <= 500 and all(isinstance(x, str) for x in labels) else None
        except Exception:
            return None

    def write_progress(self, event, labels, operation_key):
        """Enqueue one bounded label delta; HTTP 200 alone is never completion."""
        if not self._progress_allowed(event):
            return {"status": "failed", "reason": "outside_stage_pilot"}
        owned = _progress_owned(self.gate)
        # Exatamente uma etiqueta de etapa; "encerrado" só vem junto dela (release 48).
        if (not isinstance(labels, list) or any(not isinstance(x, str) for x in labels)
                or set(labels) - owned or len(set(labels) & _PROGRESS_OWNED) != 1
                or not isinstance(operation_key, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,255}", operation_key)):
            return {"status": "failed", "reason": "invalid_stage_delta"}
        try:
            if not self._read_target(event, require_reply_window=False, timeout=3, require_contact=True):
                return {"status": "failed", "reason": "stage_recipient_unverified"}
        except Exception:
            return {"status": "failed", "reason": "stage_recipient_unverified"}
        body = {"type": "Conversation", "ids": [int(event["conversation_id"])],
                "labels": {"add": sorted(set(labels)), "remove": sorted(owned - set(labels))}}
        try:
            self.http(method="POST", url=f"{self.base_url}/api/v1/accounts/1/bulk_actions",
                      headers={"api_access_token": self.token, "Content-Type": "application/json",
                               "Idempotency-Key": operation_key}, json_body=body, timeout=3)
        except HTTPError as error:
            failed = 400 <= error.code < 500 and error.code != 408
            error.close()
            return {"status": "failed" if failed else "outcome_unknown", "reason": "stage_write_unconfirmed"}
        except Exception:
            return {"status": "outcome_unknown", "reason": "stage_write_unconfirmed"}
        return {"status": "outcome_unknown", "reason": "stage_job_enqueued"}

    def send_reply(self, event, text, buttons, idempotency_key, *, before_write=None):
        if not allow_inbound(self.gate, event):
            return {"status": "failed", "reason": "outside_pilot"}
        if not self.ready():
            return {"status": "failed", "reason": "transport_not_configured"}
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            return {"status": "failed", "reason": "invalid_reply"}
        if not isinstance(idempotency_key, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,255}", idempotency_key):
            return {"status": "failed", "reason": "invalid_idempotency_key"}
        try:
            if not self._read_target(event):
                return {"status": "failed", "reason": "recipient_mismatch_or_window_closed"}
        except Exception:
            return {"status": "failed", "reason": "recipient_unverified"}

        # Chatwoot renders up to three items as reply buttons; four to ten
        # items use WhatsApp's list picker. Values remain the full declaration.
        choices = [value.strip() for value in (buttons or [])[:10]
                   if isinstance(value, str) and 0 < len(value.strip()) <= 200]
        title_limit = 20 if len(choices) <= 3 else 24
        # Chatwoot returns the native button title as incoming content. Keep
        # this short title in the journey's existing consent vocabulary while
        # preserving the full value and all offer/precheck authority checks.
        items = [{"title": "Pode enviar" if value == "Autorizo o convite real" else value[:title_limit],
                  "value": value} for value in choices]
        if not self.interactive:
            items = []
        attributes = {"amplify_actor": "v5_rehearsal", "amplify_idempotency_key": idempotency_key}
        if items:
            attributes["items"] = items
        payload = {"content": text, "message_type": "outgoing", "private": False,
                   "content_type": "input_select" if items else "text", "content_attributes": attributes}
        if before_write is not None:
            try:
                if before_write() is not True:
                    return {"status": "failed", "reason": "send_cancelled_before_post"}
            except Exception:
                return {"status": "failed", "reason": "send_cancelled_before_post"}
        button = None if items else self._form_button(text)
        if button and self._send_url_button(event, button):
            # The lead got the WhatsApp button; Chatwoot keeps a private mirror
            # with the same idempotency key so the transcript and reconcile agree.
            payload = {"content": "🔗 Botão enviado pelo WhatsApp: *" + button["label"] + "* → " + button["url"]
                                  + "\n\n" + button["body"],
                       "message_type": "outgoing", "private": True, "content_type": "text",
                       "content_attributes": {**attributes, "amplify_url_button": True}}
        try:
            reply = self.http(method="POST", url=self._conversation_url(event) + "/messages",
                              headers={"api_access_token": self.token, "Content-Type": "application/json",
                                       "Idempotency-Key": idempotency_key}, json_body=payload, timeout=15)
        except HTTPError as exc:
            status = "failed" if 400 <= exc.code < 500 and exc.code != 408 else "outcome_unknown"
            exc.close()
            return {"status": status, "reason": "chatwoot_rejected" if status == "failed" else "send_ambiguous"}
        except Exception:
            return {"status": "outcome_unknown", "reason": "send_ambiguous"}
        if not isinstance(reply, dict) or not _id(reply.get("id")):
            return {"status": "outcome_unknown", "reason": "missing_message_receipt"}
        return {"status": "accepted", "message_id": _id(reply["id"])}

    def _form_button(self, text):
        from real_journey import PUBLIC_FORM_URL
        if not self.cloud or PUBLIC_FORM_URL not in text:
            return None
        body = re.sub(r"\n{3,}", "\n\n", text.replace(PUBLIC_FORM_URL, "").replace("por aqui:", "no botão abaixo.")).strip()
        if not body or len(body) > 1024:
            return None
        return {"label": "Fazer cadastro", "url": PUBLIC_FORM_URL, "body": body}

    def _send_url_button(self, event, button):
        """One Cloud API cta_url message to the verified pilot phone; False on any doubt."""
        if not pilot_phone(self.gate, event.get("sender_phone")):
            return False
        # Release 43: the number WhatsApp itself reported for the lead, never the list's spelling of it
        # (with or without the Brazilian ninth digit), so the button reaches the same chat as the text.
        phone = normalize_phone(event.get("sender_phone"))
        if not phone:
            return False
        payload = {"messaging_product": "whatsapp", "recipient_type": "individual",
                   "to": phone, "type": "interactive",
                   "interactive": {"type": "cta_url", "body": {"text": button["body"]},
                                   "action": {"name": "cta_url", "parameters": {"display_text": button["label"][:20],
                                                                                "url": button["url"]}}}}
        try:
            answer = self.http(method="POST", url="https://graph.facebook.com/v24.0/" + self.cloud["phone_number_id"] + "/messages",
                               headers={"Authorization": "Bearer " + self.cloud["token"], "Content-Type": "application/json"},
                               json_body=payload, timeout=20)
        except Exception:
            return False
        messages = answer.get("messages") if isinstance(answer, dict) else None
        return bool(isinstance(messages, list) and messages and isinstance(messages[0], dict) and messages[0].get("id"))

    def reconcile_reply(self, event, idempotency_key):
        """Read-only lookup; never a retry and never proof of WhatsApp delivery."""
        if not self.ready() or not allow_inbound(self.gate, event):
            return {"status": "outcome_unknown"}
        try:
            if not self._read_target(event, require_reply_window=False):
                return {"status": "outcome_unknown"}
            data = self.http(method="GET", url=self._conversation_url(event) + "/messages",
                             headers={"api_access_token": self.token, "Accept": "application/json"}, timeout=15)
            for message in data.get("payload", []):
                attributes = message.get("content_attributes") or {}
                if attributes.get("amplify_idempotency_key") == idempotency_key and _id(message.get("id")):
                    return {"status": "accepted", "message_id": _id(message["id"])}
        except Exception:
            pass
        return {"status": "outcome_unknown"}
