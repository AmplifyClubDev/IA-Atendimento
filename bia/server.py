"""One-worker Chatwoot rehearsal ingress with durable at-most-once effects."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import pilot_scope
import threading
from contextlib import contextmanager
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from flask import Flask, jsonify, request

import engine
from answers import answer_question
from guided_ai import plan_turn
from contracts import allow_inbound, allow_image_inbound, IMAGE_ONLY_REPLY, inbound_key, same_phone, normalize_phone, pilot_phone
from repository import Repository
from transport import ChatwootTransport, ChatwootProgress
from real_operations import RealExecutor, build_jobs, business_key, chatwoot_control_guard, gate_exclusion, policy_for
from demo_router import build_demo_router, production_blocked, excluded_conversations, ProductionTransportFence


def _get(settings, name, default=None):
    return settings.get(name, default) if isinstance(settings, dict) else getattr(settings, name, default)


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _positive_id(value):
    return str(value) if type(value) in (str, int) and re.fullmatch(r"[1-9][0-9]{0,19}", str(value)) else None


def _creator_uuid(value):
    try:
        return value if isinstance(value, str) and str(UUID(value)) == value and UUID(value).int else None
    except (ValueError, TypeError, AttributeError):
        return None


def observed_timestamp(value):
    """Normalize a provider timestamp; never substitute the processing clock."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            stamp = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            stamp = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                return None
        else:
            return None
        return stamp.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def normalize_chatwoot(payload):
    """Extract actual Chatwoot fields; reject conflicting sender/inbox metadata."""
    if not isinstance(payload, dict) or payload.get("event") != "message_created":
        return None
    conversation, inbox, account = (_mapping(payload.get(key)) for key in ("conversation", "inbox", "account"))
    sender = _mapping(payload.get("sender"))
    nested_sender = _mapping(_mapping(conversation.get("meta")).get("sender"))
    contact_ids = [item for item in (sender.get("id"), nested_sender.get("id"),
                   _mapping(conversation.get("contact_inbox")).get("contact_id")) if item is not None]
    if contact_ids and (any(not _positive_id(item) for item in contact_ids)
                        or len({_positive_id(item) for item in contact_ids}) != 1):
        return None
    phone = sender.get("phone_number", nested_sender.get("phone_number"))
    if (sender.get("phone_number") and nested_sender.get("phone_number")
            and not same_phone(sender["phone_number"], nested_sender["phone_number"])):
        return None
    inbox_id = inbox.get("id", conversation.get("inbox_id"))
    if inbox.get("id") is not None and conversation.get("inbox_id") is not None and str(inbox["id"]) != str(conversation["inbox_id"]):
        return None
    if account.get("id") is not None and conversation.get("account_id") is not None and str(account["id"]) != str(conversation["account_id"]):
        return None
    event = {
        "provider": "chatwoot", "event": payload["event"], "account_id": account.get("id"),
        "inbox_id": inbox_id, "conversation_id": conversation.get("id"), "message_id": payload.get("id"),
        "contact_id": _positive_id(contact_ids[0]) if contact_ids else None,
        "sender_phone": phone, "sender_type": sender.get("type", nested_sender.get("type")),
        "message_type": payload.get("message_type"), "private": payload.get("private"), "text": payload.get("content"),
        "created_at": observed_timestamp(payload.get("created_at")),
    }
    attachments = payload.get("attachments")
    # Retain only bounded provider image IDs, never URLs, bytes or inferred text.
    if (isinstance(attachments, list) and 1 <= len(attachments) <= 4
            and all(isinstance(item, dict) and item.get('file_type') == 'image'
                    and _positive_id(item.get('id')) for item in attachments)):
        event['image_attachment_ids'] = [_positive_id(item['id']) for item in attachments]
    event['source_ref'] = inbound_key(event)
    return event


def conversation_key(event):
    return f"chatwoot:{event['account_id']}:{event['conversation_id']}"


class _InboundReplyFence:
    """Admit reserved turns in FIFO order; suppress only obsolete output.

    Source/reset metadata contains no message text. Duplicate/conflicting and
    retention-blocked events never receive a ticket. The queue keeps one tail
    event per conversation; each request owns only its predecessor/current pair.
    """
    def __init__(self):
        self._lock, self._admission = threading.Lock(), threading.Lock()
        self._heads, self._resets, self._tails = {}, {}, {}

    def admit(self, event, reserve, *, reset=False, supersedes=True):
        # Couple reservation and ticket order without holding the conversation
        # RLock or the source-reader lock during SQLite/provider work.
        with self._admission:
            reservation = reserve()
            ticket = self.observe(event, reset=reset, supersedes=supersedes) if reservation.get('reserved') else None
            return reservation, ticket

    def observe(self, event, *, reset=False, supersedes=True):
        conv, source = conversation_key(event), inbound_key(event)
        identifier = int(_positive_id(event.get('message_id')) or '0')
        with self._lock:
            before, done = self._tails.get(conv), threading.Event()
            self._tails[conv] = done
            old = self._heads.get(conv)
            if (supersedes or reset) and source and identifier and (old is None or identifier > old['message_id']):
                self._heads[conv] = {'source': source, 'message_id': identifier}
            if source and identifier and reset is True:
                self._resets.setdefault(conv, {}).setdefault(source,
                    {'message_id': identifier, 'done': done, 'settled': False})
            return before, done

    def current(self, event, source=None):
        with self._lock:
            head = self._heads.get(conversation_key(event))
            return head is None or head['source'] == (source or inbound_key(event))

    @staticmethod
    def processed(state, event):
        prefix = f"chatwoot:{event['account_id']}:"
        sources = [key for key in state.get('processed_inbound', []) if isinstance(key, str)
                   and key.startswith(prefix) and _positive_id(key[len(prefix):])]
        return max(sources, key=lambda key: int(key[len(prefix):])) if sources else None

    @classmethod
    def keep_latest_cursor(cls, state, event):
        latest = cls.processed(state, event)
        keys = state.get('processed_inbound') or []
        if latest and keys[-1] != latest:
            state['processed_inbound'] = [key for key in keys if key != latest] + [latest]

    @staticmethod
    def reset_boundary(state, event):
        boundary = state.get('chat_reset_boundary') or {}
        identifier = _positive_id(boundary.get('message_id'))
        expected = f"chatwoot:{event['account_id']}:{identifier}" if identifier else None
        return boundary if expected and boundary.get('source') == expected else {}

    @staticmethod
    def control_message(text, *, reset=False, real_mode=False):
        # Reuse the journey's exact control vocabulary. An old answer may not
        # authorize a newer offer or close a newer question/cycle.
        import real_journey
        import conversation
        controls = (real_journey._YES | real_journey._NO | real_journey._REAL_CONSENT
                    | real_journey._ACCEPTANCE | getattr(conversation, '_PAUSE', set())
                    | {'encerrar agora', 'seguir atendimento'})
        return (reset or engine._normal(text) in controls
                or (real_mode and real_journey._pause_requested(text)))

    @contextmanager
    def turn(self, event, ticket):
        before, done = ticket
        if before is not None:
            before.wait()  # Always outside the conversation RLock.
        try:
            yield
        finally:
            done.set()

    def retire_stale_reset(self, event):
        with self._lock:
            row = self._resets.get(conversation_key(event), {}).get(inbound_key(event))
            if row:
                row['settled'] = True

    def reset_waiting(self, state, event):
        processed = set(state.get('processed_inbound') or [])
        with self._lock:
            rows = self._resets.get(conversation_key(event), {})
            proven = max((row['message_id'] for key, row in rows.items() if key in processed), default=0)
            for row in rows.values():
                if row['message_id'] <= proven:
                    row['settled'] = True
            return any(not row['settled'] for row in rows.values())


# 22/11/2026: alerta "Lead parado precisa do time" (cycle['team_alert']) desligado a pedido.
# Os alertas de GMV alto e de especialista (lead_alerts.dispatch) continuam como estão.
TEAM_ALERTS_ENABLED = False


def _log_inbound_failure(error):
    """Auditoria 20/11: uma linha de log por falha, só com tipo e ponto do código (sem dados do lead)."""
    try:
        import os
        import traceback
        frame = traceback.extract_tb(error.__traceback__)[-1] if error.__traceback__ else None
        where = f'{os.path.basename(frame.filename)}:{frame.lineno}:{frame.name}' if frame else 'desconhecido'
        print(f'[bia] inbound_falhou tipo={type(error).__name__} onde={where}', flush=True)
    except Exception:
        pass


def create_app(settings=None, repository=None, transport=None, answerer=None, planner=None,
               real_client=None, real_guard=None, demo_gateway=None):
    if settings is None:
        from config import load_settings
        settings = load_settings()
    settings = dict(settings) if isinstance(settings, dict) else settings
    demo_router = build_demo_router(settings, gateway=demo_gateway, production_path=getattr(repository, 'path', None))
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=128_000, JSON_SORT_KEYS=False)
    gate = _mapping(_get(settings, "gate", {}))
    if _get(settings, 'inactivity_close_enabled', False) is True:
        gate = {**gate, 'inactivity_close_enabled': True}
    if _get(settings, 'resolve_on_close_enabled', False) is True:
        gate = {**gate, 'resolve_on_close_enabled': True}
    conversational = _get(settings, "conversation_enabled", False) is True
    contact_sync = _get(settings, "contact_sync_enabled", False) is True
    repository = repository or Repository(Path(_get(settings, "state_dir", Path(__file__).with_name("data"))) / "atendimento.sqlite3")
    if demo_router:
        if not callable(getattr(repository, 'set_demo_scope', None)):
            raise ValueError('demo_requires_filtered_repository')
        repository.set_demo_scope(demo_router.scope)
    transport = transport or ChatwootTransport(_get(settings, "chatwoot_base_url"), _get(settings, "chatwoot_api_token"), gate,
                                               interactive=True,
                                               cloud={"token": _get(settings, "whatsapp_cloud_token"),
                                                      "phone_number_id": _get(settings, "whatsapp_cloud_phone_number_id")})
    if demo_router:
        transport = ProductionTransportFence(transport, demo_router.scope)
    answerer = answerer or answer_question
    planner = planner or plan_turn
    if settings.get('same_engine_enabled') is True:
        from real_answer_adapter import build_real_planner
        planner = build_real_planner(settings, planner)
    locks, lock_guard = {}, threading.Lock()
    reply_fence = _InboundReplyFence()

    def lock_for(key):
        with lock_guard:
            return locks.setdefault(key, threading.RLock())

    app.extensions.update(v5_repository=repository, v5_settings=settings, v5_transport=transport,
                          v5_form_link_factory=None, v5_conversation_locks=locks,
                          v5_conversation_lock_for=lock_for, v5_reply_fence=reply_fence)
    app.extensions['v5_demo_router'] = demo_router
    # With a pilot phone list every listed chat gets its stage labels; the
    # single-contact pilot keeps its exact conversation/contact pin.
    progress = (ChatwootProgress(repository, gate if gate.get("phones") else {**gate, "conversation_id": pilot_scope.conversation_id(), "contact_id": pilot_scope.contact_id()}, transport)
                if contact_sync and _get(settings, "chatwoot_stages_enabled", False) is True else None)
    def persist_chatwoot_labels(event, state, labels):
        gateway = app.extensions.get("v5_data_gateway")
        if not callable(getattr(gateway, "register_chatwoot_labels", None)):
            return {"status": "unavailable"}
        cycle = state.get("cycle") or {}
        signature = hashlib.sha256(json.dumps(labels, ensure_ascii=False).encode()).hexdigest()
        return gateway.register_chatwoot_labels({
            "instancia": _get(settings, "instance_id"),
            "account_id": str(event["account_id"]), "contact_id": str(event["contact_id"]),
            "conversation_id": str(event["conversation_id"]),
            "creator_id": state.get("creator_id"), "atendimento_id": cycle.get("id"),
            "revision": state.get("revision"), "labels": labels, "signature": signature,
            "observed_at": datetime.now(timezone.utc).isoformat()})

    if progress is not None:
        progress.confirmed_sink = persist_chatwoot_labels
    app.extensions["v5_chatwoot_progress"] = progress

    def send_current_reply(event, text, buttons, outbox_key, *, source=None, fenced=True):
        if production_blocked(settings, event=event):
            return {'status': 'failed', 'reason': 'demo_contact_excluded_from_production'}
        # Release 43: a TikTok result (fenced=False) is news the lead is waiting for; it is sent even when a

        authority = (lambda: reply_fence.current(event, source)) if fenced else (lambda: True)
        if not authority():
            return {'status': 'failed', 'reason': 'reply_superseded_by_new_inbound'}
        # The concrete transport checks again after its recipient GET, directly
        # before POST. Trusted legacy test adapters keep their original contract.
        options = {'before_write': authority} if getattr(transport, 'supports_reply_fencing', False) is True else {}
        import conversao
        text = conversao.without_repeated_paragraphs(text)
        receipt = transport.send_reply(event, text, buttons, outbox_key, **options)
        if (isinstance(receipt, dict) and receipt.get('status') == 'failed'
                and receipt.get('reason') == 'send_cancelled_before_post' and not authority()):
            return {'status': 'failed', 'reason': 'reply_superseded_by_new_inbound'}
        return receipt

    def mark_linked_notice(conv, state, text, status):
        """Release 43: o aviso do vínculo (com o cadastro) foi entregue? Se não, a varredura lê e avisa de novo."""
        import real_journey
        notice = _mapping(state.get('cycle')).get('linked_notice')
        if (isinstance(notice, dict) and notice.get('delivered') is None and isinstance(text, str)
                and real_journey.PUBLIC_FORM_URL in text):
            notice['delivered'] = status == 'accepted'
            repository.save_session(conv, state)

    def honest_notice(event, text, key):
        """Release 43: nenhum lead sem resposta em silêncio. Uma mensagem honesta por conversa e por hora."""
        try:
            hour = datetime.now(timezone.utc).strftime('%Y%m%d%H')
            if not allow_inbound(gate, event) or not repository.reserve_operation(
                    'honest-notice:' + conversation_key(event) + ':' + hour, inbound_key(event), 'honest_notice'):
                return None
            control = operation_guard(event)
            if not isinstance(control, dict) or control.get('allowed') is not True:
                return None
            return transport.send_reply(event, text, [], key)
        except Exception:
            return None

    def project_registration(row, state, receipt):
        if production_blocked(settings, conversation_key=row.get('conversation_key')):
            return {'status': 'disabled', 'reason': 'demo_contact_excluded_from_production'}
        if progress is None or row.get("conversation_key") != pilot_scope.conversation_key():
            return {"status": "disabled"}
        prior = state.get("processed_inbound") or []
        reference = prior[-1] if prior else ""
        if not isinstance(reference, str) or not re.fullmatch(r"chatwoot:1:[1-9][0-9]{0,19}", reference):
            return {"status": "ignored", "reason": "source_event_required"}
        event = {"provider": "chatwoot", "account_id": str(row["account_id"]), "inbox_id": str(row["inbox_id"]),
                 "conversation_id": pilot_scope.conversation_id(), "contact_id": pilot_scope.contact_id(), "message_id": reference.rsplit(":", 1)[1],
                 "sender_phone": gate.get("phone"), "message_type": "incoming", "private": False,
                 "text": "formulario_confirmado"}
        return progress.sync(event, state, {"kind": "registration", "receipt": receipt})

    app.extensions["v5_project_registration"] = project_registration

    def issues():
        found = list(_get(settings, "readiness_issues", []) or [])
        if contact_sync and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", str(_get(settings, "instance_id", ""))):
            found.append("contact_instance_invalid")
        if contact_sync and not callable(getattr(app.extensions.get("v5_data_gateway"), "register_contact", None)):
            found.append("contact_gateway_unavailable")
        if conversational and _get(settings, "ai_enabled", False) is not True:
            found.append("conversation_requires_ai")
        if _get(settings, 'tiktok_mode') == 'real':
            if not contact_sync:
                found.append('real_mode_requires_data_sync')
            if not executor.configured():
                found.append('real_tiktok_configuration_incomplete')
            if _get(settings, 'real_worker_enabled', False) is not True:
                found.append('real_worker_disabled')
        if gate.get("enabled") is not True:
            found.append("pilot_disabled")
        probe = {"provider": gate.get("provider"), "account_id": gate.get("account_id"), "inbox_id": gate.get("inbox_id"),
                 "conversation_id": "1", "message_id": "1", "sender_phone": gate.get("phone"),
                 "message_type": "incoming", "private": False, "text": "ready"}
        if not allow_inbound(gate, probe):
            found.append("pilot_gate_incomplete")
        token = _get(settings, "webhook_token")
        if not isinstance(token, str) or len(token) < 16:
            found.append("webhook_token")
        if not transport.ready():
            found.append("chatwoot_transport")
        try:
            if not repository.ready():
                found.append("operational_state")
        except Exception:
            found.append("operational_state")
        return sorted(set(found))

    def sync_contact(event, state, *, before=False):
        """Reserve each remote revision before its one POST; never retry unknown outcomes."""
        if not contact_sync:
            return state
        if not _positive_id(event.get("contact_id")):
            raise ValueError("contact_identity_missing")
        gateway = app.extensions.get("v5_data_gateway")
        if not callable(getattr(gateway, "register_contact", None)):
            raise ValueError("contact_gateway_unavailable")
        cycle = _mapping(state.get("cycle"))
        revision = 0 if before else max(1, int(state.get("revision", 1)))
        entrada = {"instancia": _get(settings, "instance_id"),
                   "account_id": str(event["account_id"]), "contact_id": str(event["contact_id"]),
                   "conversation_id": str(event["conversation_id"]), "message_id": str(event["message_id"]),
                   "event_id": inbound_key(event), "revision": revision,
                   "atendimento_id": None if before else cycle.get("id"),
                   "etapa": "entrada" if before else cycle.get("phase", "entrada"),
                   "situacao": "aberto" if before else {"open": "aberto", "closed": "encerrado", "expired": "expirado"}.get(cycle.get("status"), "aberto"),
                   "whatsapp": normalize_phone(pilot_phone(gate, event.get("sender_phone")) or gate.get("phone"))}
        if before:
            # Identity is idempotent; the final call alone retains its durable receipt.
            entrada["modo_identidade"] = "consulta"
        if event.get("created_at"):
            entrada["observado_em"] = event["created_at"]
        preferred = state.get("creator_id")
        hint = app.extensions.get("v5_form_creator_hint")
        form_creator = hint(state, event) if callable(hint) else None
        if form_creator and preferred and form_creator != preferred:
            raise ValueError("active_form_identity_conflict")
        preferred = preferred or form_creator
        if preferred:
            if not _creator_uuid(preferred):
                raise ValueError("creator_identity_invalid")
            entrada["creator_id"] = preferred
        if not before:
            if not _creator_uuid(cycle.get("id")):
                raise ValueError("attendance_identity_missing")
            for source, target in (("last_inbound_at", "ultima_mensagem_em"), ("expires_at", "expires_at")):
                if cycle.get(source):
                    entrada[target] = cycle[source]
            fields = {"interesse_agenciamento", "origem_declarada", "origem_canal_declarado", "tiktok_declarado", "shop_ativo_declarado",
                      "possui_agencia_declarada", "consentimento_ensaio", "aceite_no_ensaio",
                      "consentimento_convite", "aceite_declarado"}
            entrada["qualificacao"] = {name: value for name, value in _mapping(cycle.get("facts")).items()
                                       if name in fields and type(value) in (str, bool, type(None))}
            profile = cycle.get('perfil_tiktok')
            if isinstance(profile, dict) and profile.get('handle') == _mapping(cycle.get('facts')).get('tiktok_declarado'):
                entrada['qualificacao']['perfil_tiktok'] = profile
            if cycle.get('mode') == 'real':
                from gateway import tiktok_projection
                verified = tiktok_projection(state)
                if verified:
                    entrada['verificacoes_tiktok'] = verified
            origin = _mapping(_mapping(state.get("observations")).get("origin"))
            if origin:
                entrada["origem"] = {name: origin[name] for name in ("at", "reference", "value", "source") if name in origin}
            draft = _mapping(cycle.get("rascunho"))
            confirmed_name = _mapping(cycle.get('facts')).get('nome_declarado')
            if isinstance(confirmed_name, str) and confirmed_name.strip():
                draft = {**draft, 'nome': confirmed_name.strip()}
            if draft:
                contract = json.loads(Path(__file__).with_name("data").joinpath("cadastro_contract.json").read_text(encoding="utf-8-sig"))
                allowed = {field["id"] for field in contract["fields"] if field.get("type") != "file"}
                entrada["rascunho"] = {name: value for name, value in draft.items() if name in allowed}
        operation = inbound_key(event) + ":contact:" + str(revision)
        if not before:
            pending = cycle.get('chat_declarations_pending') or []
            declarations = [row for row in pending if row.get('mensagem_id') == str(event['message_id'])]
            if declarations:
                entrada['declaracoes_chat'] = declarations
        if not repository.reserve_operation(operation, inbound_key(event), "contact_sync"):
            previous = repository.get_operation(operation)
            if not previous or previous.get("status") != "completed" or not isinstance(previous.get("result"), dict):
                raise ValueError("contact_sync_requires_reconciliation")
            result = previous["result"]
        else:
            # A lost database ACK must not discard the real cycle UUID/facts.
            # The operation is already fenced and no reply has been sent.
            if not before:
                repository.save_session(conversation_key(event), state)
            result = gateway.register_contact(entrada)
            if (not isinstance(result, dict) or not _creator_uuid(result.get("creator_id"))
                    or result.get("event_id") != entrada["event_id"]
                    or type(result.get("revision")) is not int or result.get("revision") != revision
                    or result.get("atendimento_id") != entrada["atendimento_id"]
                    or preferred and result.get("creator_id") != preferred):
                raise ValueError("contact_receipt_invalid")
            result = {key: result[key] for key in ("creator_id", "atendimento_id", "event_id", "revision", "cadastro_situacao", "replayed") if key in result}
            repository.complete_operation(operation, result)
        state["creator_id"] = result["creator_id"]
        state["cadastro_situacao"] = result.get("cadastro_situacao")
        handle = _mapping(cycle.get('facts')).get('tiktok_declarado')
        if handle and callable(getattr(gateway, 'registration_status', None)):
            try:
                verified = gateway.registration_status(entrada['whatsapp'], handle)
                if verified in {'confirmado', 'conferencia'}:
                    state['cadastro_situacao'] = verified
            except Exception:
                # Uma leitura indisponível não autoriza conclusão nem troca de identidade.
                pass
        if not before:
            state['contact_sync_proof'] = {name: result[name] for name in
                ('creator_id', 'atendimento_id', 'event_id', 'revision')}
        repository.save_session(conversation_key(event), state)
        return state

    def send_team_alert(event, conv, state):
        """Auditoria 20/11: cycle['team_alert'] vira alerta no canal da Bia (uma vez por motivo e ciclo).

        Opcional: uma falha aqui nunca muda a resposta ao lead nem o estado da conversa.
        22/11: desligado a pedido (alerta "Lead parado precisa do time" saía demais no Slack)."""
        if TEAM_ALERTS_ENABLED is not True:
            return
        alert = (state.get('cycle') or {}).get('team_alert') if isinstance(state, dict) else None
        if not isinstance(alert, dict) or alert.get('status') == 'accepted':
            return
        try:
            from lead_alerts import dispatch_team
            if dispatch_team(settings, repository, event, state).get('status') != 'not_requested':
                repository.save_session(conv, state)
        except Exception:
            pass

    def apply_real(job, state, result, result_event_key):
        """Called under the same conversation lock as inbound handling."""
        import conversation
        event, conv = job['event'], job['conversation_key']
        if settings.get('relationship_check_in_form') is True and (state.get('cycle') or {}).get('mode') == 'real':
            state['cycle']['relationship_check_in_form'] = True
        resolved = conversation.resolve_tiktok_result(state, job['effect_id'], result,
                                                     operation_policy=policy_for(settings))
        if resolved.get('ignored'):
            return resolved
        state = resolved['state']
        reply, buttons = resolved.get('reply', ''), resolved.get('buttons', [])
        jobs = build_jobs(event, state, resolved.get('effects', []))
        for effect in resolved.get('effects', []):
            if effect.get('type') != 'generate_form_link':
                continue
            factory = app.extensions.get('v5_form_link_factory')
            if not callable(factory):
                raise ValueError('real_form_operation_requires_reconciliation')
            reconciled_from = None
            if not repository.reserve_operation(effect['id'], result_event_key, 'generate_form_link'):
                # Only the idempotent local SQLite form factory may be resumed.
                # An earlier application with any outbox is never replayed.
                from forms import FormStore
                previous = repository.get_operation(effect['id']) or {}
                old_key = previous.get('event_key')
                prefix = job['job_key'] + ':result:' + job['effect_id'] + ':'
                attempts = job.get('attempts', 0)
                old_keys = {prefix + str(index) for index in range(1, attempts)} if type(attempts) is int and 1 < attempts <= 6 else set()
                prior_event = repository.event(old_key) if isinstance(old_key, str) else None
                current_event = repository.event(result_event_key)
                cycle = _mapping(state.get('cycle'))
                bound = (job.get('operation') == 'relationship' and old_key in old_keys
                    and previous.get('kind') == 'generate_form_link' and previous.get('status') == 'outcome_unknown'
                    and isinstance(prior_event, dict) and prior_event.get('status') == 'outcome_unknown'
                    and prior_event.get('conversation_key') == conv and not repository.outbox(old_key)
                    and isinstance(current_event, dict) and current_event.get('status') == 'outcome_unknown'
                    and current_event.get('conversation_key') == conv and not repository.outbox(result_event_key)
                    and cycle.get('mode') == 'real' and cycle.get('status') == 'open' and cycle.get('id') == job.get('cycle_id')
                    and str(_mapping(cycle.get('facts')).get('tiktok_declarado', '')).lstrip('@').lower() == job.get('creator')
                    and effect.get('cycle_id') == cycle.get('id')
                    and _mapping(effect.get('payload')).get('relationship_job_id') == job.get('effect_id')
                    and isinstance(app.extensions.get('v5_forms_store'), FormStore)
                    and getattr(factory, '__module__', None) == 'forms'
                    and getattr(factory, '__name__', None) == 'link_factory')
                if not bound:
                    raise ValueError('real_form_operation_requires_reconciliation')
                reconciled_from = old_key
            url = factory(state, effect, event)
            form = conversation.resolve_effect(state, effect['id'], form_url=url)
            state = form['state']
            reply = '\n\n'.join(part for part in (reply, form.get('reply')) if part)
            buttons = form.get('buttons', buttons)
            repository.complete_operation(effect['id'], {'generated': True,
                **({'reconciled_from': reconciled_from, 'reconciled_by': result_event_key} if reconciled_from else {})})
        state = sync_contact(event, state)
        reply_source = reply_fence.processed(state, event) or inbound_key(event)
        body = {'text': reply, 'buttons': buttons} if reply else None
        outbox_key = result_event_key + ':reply'
        repository.prepare_reply(result_event_key, conv, state, outbox_key, body, real_jobs=jobs)
        final = 'completed'
        if body:
            # A human may have taken over while the database/form was updated.
            control = operation_guard(event)
            if not isinstance(control, dict) or control.get('allowed') is not True:
                status, receipt = 'failed', {'reason': 'human_control_changed'}
            else:
                receipt = send_current_reply(event, reply, buttons, outbox_key, source=reply_source, fenced=False)
                status = receipt.get('status', 'outcome_unknown') if isinstance(receipt, dict) else 'outcome_unknown'
                if status not in {'accepted', 'failed', 'outcome_unknown'}:
                    status = 'outcome_unknown'
            safe = {name: receipt[name] for name in ('status', 'message_id', 'reason')
                    if isinstance(receipt, dict) and isinstance(receipt.get(name), str)}
            repository.finish_outbox(outbox_key, status, safe)
            mark_linked_notice(conv, state, reply, status)
            final = 'completed' if status == 'accepted' or safe.get('reason') == 'reply_superseded_by_new_inbound' else status
        repository.finish_event(result_event_key, final)
        send_team_alert(event, conv, state)
        if progress is not None:
            revision = max(1, int(state.get('revision', 1)))
            confirmed = repository.get_operation(inbound_key(event) + ':contact:' + str(revision))
            if confirmed and confirmed.get('status') == 'completed':
                cycle = state.get('cycle') or {}
                progress.sync(event, state, {'kind': 'contact', 'receipt': confirmed.get('result'),
                                            'snapshot': {'cycle_id': cycle.get('id'), 'phase': cycle.get('phase'),
                                                         'status': cycle.get('status'), 'revision': revision}})
        return resolved

    if real_client is None:
        from playwright_client import PlaywrightClient
        real_client = PlaywrightClient(settings)
    base_operation_guard = real_guard or (lambda event: chatwoot_control_guard(transport, gate, event))
    def operation_guard(event):
        if production_blocked(settings, event=event):
            return {'allowed': False, 'reason': 'demo_contact_excluded_from_production'}
        # A reserved reset may be waiting while the current turn/worker holds the
        # lock. Other questions do not invalidate an already authorized job.
        live = repository.load_session(conversation_key(event))
        if reply_fence.reset_waiting(live, event):
            return {'allowed': False, 'reason': 'new_reset_pending'}
        return base_operation_guard(event)
    def apply_real_in_app_context(job, state, result, result_event_key):
        # Worker ticks run outside requests. Form helpers use current_app, so
        # bind only this callback to its owning app and always pop afterwards.
        with app.app_context():
            return apply_real(job, state, result, result_event_key)

    executor = RealExecutor(repository, real_client, settings, lock_for, operation_guard, apply_real_in_app_context)

    def operation_failure(job):
        """Release 43: uma consulta pedida pelo lead que falhou vira um aviso honesto; as da varredura seguem em silêncio."""
        import conversao
        from real_operations import AGENCY_SOURCES
        source = (job.get('payload') or {}).get('source')
        if job.get('operation') == 'lookup' or source in AGENCY_SOURCES | {'bridge_retry', 'invite_bridge_retry', 'invite_list_proof'}:
            return None
        return honest_notice(job.get('event') or {}, conversao.OPERATION_FALLBACK, 'falha:' + job['job_key'])
    executor.failure_notice = operation_failure
    app.extensions['v5_real_executor'] = executor

    def verify_form_relationship(state, event=None, *, creator, operation_key=None, now=None, start=True,
                                 form_conversation=None):
        """Queue a form-owned read or inspect it; never send chat or invite."""
        if production_blocked(settings, event=event, conversation_key=form_conversation or pilot_scope.conversation_key()):
            return {'status': 'failed', 'reason': 'demo_contact_excluded_from_production'}
        from real_journey import form_entry_allowed, form_relationship_proven, _result_creator
        if settings.get('relationship_check_in_form') is not True:
            return {'status': 'failed', 'reason': 'form_relationship_disabled'}
        requested = _result_creator(creator)
        # The form row names its own chat; the original pilot chat stays the default.
        conv = (form_conversation if isinstance(form_conversation, str)
                and re.fullmatch(r'chatwoot:1:[1-9][0-9]{0,19}', form_conversation) else pilot_scope.conversation_key())
        with app.app_context(), lock_for(conv):
            try:
                live = repository.load_session(conv)
                cycle, expected = live.get('cycle') or {}, state.get('cycle') or {}
                at = engine._clock(now)
                if (live.get('session_id') != state.get('session_id')
                        or live.get('creator_id') != state.get('creator_id')
                        or cycle.get('id') != expected.get('id') or not requested
                        or requested != _result_creator((cycle.get('facts') or {}).get('tiktok_declarado'))
                        or not form_entry_allowed(live, now=at)
                        or live.get('human_control') or cycle.get('qualification_paused')
                        or cycle.get('pending_profile_changes')):
                    return {'status': 'failed', 'reason': 'form_scope_changed'}
                if not isinstance(operation_key, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{10,200}', operation_key):
                    return {'status': 'failed' if start is True else 'verification_pending',
                            'reason': 'form_operation_required'}
                digest = hashlib.sha256((cycle['id'] + ':' + requested + ':' + operation_key).encode()).hexdigest()
                proof = live.get('contact_sync_proof') or {}
                confirmed = repository.get_operation(str(proof.get('event_id')) + ':contact:' + str(live.get('revision')))
                sql_proven = (proof.get('creator_id') == live.get('creator_id')
                    and proof.get('atendimento_id') == cycle['id'] and proof.get('revision') == live.get('revision')
                    and confirmed and confirmed.get('status') == 'completed'
                    and isinstance(confirmed.get('result'), dict)
                    and all(confirmed['result'].get(key) == proof.get(key)
                            for key in ('creator_id', 'atendimento_id', 'event_id', 'revision')))
                if form_relationship_proven(live, now=at):
                    record = (cycle.get('real_operations') or {}).get('relationship') or {}
                    effect = (live.get('effects') or {}).get(record.get('job_id')) or {}
                    if (effect.get('payload') or {}).get('form_operation_key') != digest:
                        return {'status': 'failed', 'reason': 'form_operation_changed'}
                    return ({'status': 'linked', 'confirmed': True} if sql_proven else
                            {'status': 'outcome_unknown', 'reason': 'relationship_projection_unconfirmed'})
                job_key = business_key(cycle['id'], requested.lstrip('@'), 'relationship')
                job = repository.real_job(job_key)
                form_job = bool(job and job.get('cycle_id') == cycle['id']
                    and job.get('creator') == requested.lstrip('@') and job.get('conversation_key') == conv
                    and (job.get('payload') or {}).get('source') == 'form')
                if form_job and start is not True and (job.get('payload') or {}).get('form_operation_key') != digest:
                    return {'status': 'failed', 'reason': 'form_operation_changed'}
                if form_job and job.get('status') in {'queued', 'running', 'result_ready', 'polling'}:
                    return {'status': 'running' if job['status'] == 'polling' else job['status'],
                            'reason': 'verification_in_progress'}
                if start is not True:
                    result = (cycle.get('real_operations') or {}).get('relationship') or {}
                    effect = (live.get('effects') or {}).get(result.get('job_id')) or {}
                    if form_job and job.get('effect_id') == result.get('job_id') and (effect.get('payload') or {}).get('source') == 'form':
                        status = result.get('status')
                        if status in {'pending', 'not_found', 'verification_pending', 'failed', 'outcome_unknown'}:
                            return {'status': status, 'confirmed': result.get('confirmed') is True}
                    return {'status': 'verification_pending', 'reason': 'verification_not_confirmed'}
                if not sql_proven:
                    return {'status': 'outcome_unknown', 'reason': 'contact_projection_unconfirmed'}
                # Reuse an actual stored inbound. A form click creates no
                # synthetic contact message, invitation or message counter.
                direct = cycle.get('form_entry_request') or {}
                if direct.get('reason') in {'existing_amplify', 'registration_access'}:
                    origin = direct.get('event')
                else:
                    invite_record = (cycle.get('real_operations') or {}).get('invite') or {}
                    invite_job = repository.real_job(business_key(cycle['id'], requested.lstrip('@'), 'invite'))
                    retried = repository.real_job(business_key(cycle['id'], requested.lstrip('@'), 'invite-retry'))
                    if retried and retried.get('effect_id') == invite_record.get('job_id'):
                        invite_job = retried
                    if (not invite_job or invite_job.get('effect_id') != invite_record.get('job_id')
                            or invite_job.get('cycle_id') != cycle['id'] or invite_job.get('creator') != requested.lstrip('@')
                            or invite_job.get('conversation_key') != conv):
                        return {'status': 'failed', 'reason': 'form_source_unverified'}
                    origin = invite_job.get('event')
                if (not isinstance(origin, dict) or not allow_inbound(gate, origin) or conversation_key(origin) != conv
                        or not _positive_id(origin.get('contact_id'))
                        or (event is not None and event != origin)):
                    return {'status': 'failed', 'reason': 'form_source_unverified'}
                source_key = inbound_key(origin)
                stored_source = repository.event(source_key)
                if (not stored_source or stored_source.get('conversation_key') != conv
                        or stored_source.get('status') != 'completed'):
                    return {'status': 'failed', 'reason': 'form_source_unverified'}
                effect_id = 'form-relationship:' + digest
                previous = repository.get_operation(effect_id)
                if previous:
                    return {'status': 'verification_pending', 'reason': 'form_operation_already_reserved'}
                if not repository.reserve_operation(effect_id, source_key, 'form_relationship_request'):
                    return {'status': 'verification_pending', 'reason': 'form_operation_already_reserved'}
                for old in live.get('effects', {}).values():
                    if (old.get('cycle_id') == cycle['id'] and old.get('creator') == requested
                            and old.get('operation') == 'relationship' and (old.get('payload') or {}).get('source') == 'form'
                            and old.get('status') in {'pending', 'running', 'outcome_unknown'}):
                        old['status'] = 'superseded'
                effect = {'id': effect_id, 'type': 'tiktok_operation', 'operation': 'relationship',
                          'creator': requested, 'cycle_id': cycle['id'], 'status': 'pending',
                          'payload': {'source': 'form', 'form_operation_key': digest}}
                live['effects'][effect_id] = effect
                live['revision'] += 1
                live = sync_contact(origin, live)
                jobs = build_jobs(origin, live, [effect])
                repository.prepare_reply(source_key, conv, live, effect_id + ':no-reply', None, real_jobs=jobs)
                repository.complete_operation(effect_id, {'queued': True, 'cycle_id': cycle['id']})
                executor.wake()
                return {'status': 'queued', 'reason': 'verification_in_progress'}
            except Exception:
                return {'status': 'outcome_unknown', 'reason': 'form_verification_unconfirmed'}

    verify_form_relationship.accepts_form_conversation = True
    app.extensions['v5_verify_form_relationship'] = verify_form_relationship

    def close_for_inactivity(event, expected_cycle_id, expected_source_key, warning_key, closure_key, *, now):
        """Project an accepted pilot closure without another inbound or send."""
        if production_blocked(settings, event=event):
            return {'status': 'blocked', 'reason': 'demo_contact_excluded_from_production'}
        from followup import CONVERSATION, configured, sequence_keys
        from real_journey import close_inactive_cycle
        if (settings.get('inactivity_close_enabled') is not True or not configured(settings)
                or not allow_inbound(gate, event) or conversation_key(event) != CONVERSATION
                or inbound_key(event) != expected_source_key
                or (warning_key, closure_key) != sequence_keys(expected_cycle_id, expected_source_key)):
            return {'status': 'stale'}
        with app.app_context(), lock_for(CONVERSATION):
            try:
                state = repository.load_session(CONVERSATION)
                cycle = state.get('cycle') or {}
                source = repository.followup_source(CONVERSATION)
                if (not source or source.get('cycle_id') != expected_cycle_id
                        or source.get('event_key') != expected_source_key or source.get('event') != event
                        or cycle.get('id') != expected_cycle_id
                        or not state.get('processed_inbound')
                        or state['processed_inbound'][-1] != expected_source_key):
                    return {'status': 'stale'}
                rows = {row['outbox_key']: row for row in repository.outbox(expected_source_key)}
                receipts = []
                for key in (warning_key, closure_key):
                    row, operation = rows.get(key), repository.get_operation(key)
                    receipt = row.get('receipt') if row else None
                    if (not row or row.get('conversation_key') != CONVERSATION or row.get('status') != 'accepted'
                            or not isinstance(receipt, dict) or receipt.get('status') != 'accepted'
                            or not _positive_id(receipt.get('message_id'))
                            or receipt.get('cycle_id') != expected_cycle_id
                            or receipt.get('source_key') != expected_source_key
                            or not isinstance(receipt.get('accepted_at'), str)
                            or not operation or operation.get('kind') != 'followup'
                            or operation.get('event_key') != expected_source_key
                            or operation.get('status') != 'completed' or operation.get('result') != receipt):
                        return {'status': 'stale'}
                    receipts.append(receipt)
                warning, closure = receipts
                at = engine._clock(now)
                warning_at, closure_at = engine._clock(warning['accepted_at']), engine._clock(closure['accepted_at'])
                if (closure.get('warning_key') != warning_key
                        or closure.get('warning_accepted_at') != warning['accepted_at']
                        or (closure_at - warning_at).total_seconds() < 300 or closure_at > at):
                    return {'status': 'stale'}
                prior = cycle.get('inactivity_closure') or {}
                already_closed = (cycle.get('status') == 'closed' and cycle.get('reason') == 'inactivity_timeout'
                                  and prior.get('closure_key') == closure_key
                                  and prior.get('source_key') == expected_source_key)
                if not already_closed:
                    if not repository.followup_clear(CONVERSATION, state):
                        return {'status': 'stale'}
                    result = close_inactive_cycle(state, expected_cycle_id=expected_cycle_id,
                        source_key=expected_source_key, warning_key=warning_key, closure_key=closure_key,
                        warning_accepted_at=warning['accepted_at'], now=at)
                    if result.get('inactivity_closed') is not True:
                        return {'status': 'stale'}
                    state = result['state']
                    repository.save_session(CONVERSATION, state)
                state = sync_contact(event, state)
                cycle = state['cycle']
                receipt = repository.get_operation(expected_source_key + ':contact:' + str(state['revision']))
                if progress is not None and receipt and receipt.get('status') == 'completed':
                    proof = {'kind': 'contact', 'receipt': receipt.get('result'),
                             'snapshot': {'cycle_id': cycle['id'], 'phase': cycle['phase'],
                                          'status': cycle['status'], 'revision': state['revision']}}
                    progress.sync(event, state, proof)
                return {'status': 'closed'}
            except Exception:
                # Local closure and every uncertain SQL receipt stay fenced.
                return {'status': 'outcome_unknown'}

    app.extensions['v5_close_for_inactivity'] = close_for_inactivity
    from followup import Followup
    followup = Followup(repository, settings, transport, lock_for, operation_guard, now=lambda: executor.clock(),
                        close_for_inactivity=close_for_inactivity)
    app.extensions['v5_followup'] = followup
    app.extensions['v5_followup_tick'] = followup.tick
    executor.followup_tick = followup.tick
    executor.followup_status = followup.status

    from retomada import PosPausa, Retomada, enabled as conduct_enabled
    def registration_status(event):
        """Situação do cadastro na ficha, lida na hora (modo consulta: sem recibo e sem mudar o atendimento)."""
        if production_blocked(settings, event=event):
            return 'conferencia'
        if not contact_sync:
            return 'pendente'
        try:
            gateway = app.extensions.get('v5_data_gateway')
            current = repository.load_session(conversation_key(event))
            handle = ((current.get('cycle') or {}).get('facts') or {}).get('tiktok_declarado')
            if handle and hasattr(gateway, 'registration_status'):
                return gateway.registration_status(
                    normalize_phone(pilot_phone(gate, event.get('sender_phone')) or gate.get('phone')), handle)
            entrada = {'instancia': _get(settings, 'instance_id'), 'account_id': str(event['account_id']),
                       'contact_id': str(event['contact_id']), 'conversation_id': str(event['conversation_id']),
                       'message_id': str(event['message_id']), 'event_id': inbound_key(event), 'revision': 0,
                       'atendimento_id': None, 'etapa': 'entrada', 'situacao': 'aberto', 'modo_identidade': 'consulta',
                       'whatsapp': normalize_phone(pilot_phone(gate, event.get('sender_phone')) or gate.get('phone'))}
            result = gateway.register_contact(entrada)
            return result.get('cadastro_situacao') if isinstance(result, dict) else None
        except Exception:
            return None

    def mark_stopped(event, state, now):
        """Release 48: etiqueta da etapa + "encerrado" quando o lead para; some quando ele volta a escrever."""
        if progress is not None:
            progress.sync(event, state, {'kind': 'parado', 'now': now.isoformat()})

    retomada = Retomada(repository, settings, transport, lock_for, operation_guard, now=lambda: executor.clock(),
                        policy=lambda: policy_for(settings), registration=registration_status,
                        on_stopped=mark_stopped)

    def resend_stored_reply(event, state, stored, outbox_key):
        """Release 45: a resposta que a Bia já calculou e não saiu é enviada agora, com o pedido de desculpas."""
        if production_blocked(settings, event=event):
            return {'status': 'blocked', 'reason': 'demo_contact_excluded_from_production'}
        import conversao
        import real_journey
        conv = conversation_key(event)
        text, buttons = stored['payload']['text'], list(stored['payload'].get('buttons') or [])
        if real_journey._RESUME_SORRY not in text:
            for opening in (conversao.OPENING, real_journey._RESUME_OPENING):
                if text.startswith(opening):
                    text = opening + ' ' + real_journey._RESUME_SORRY + text[len(opening):]
                    break
            else:
                text = real_journey._RESUME_SORRY + '\n\n' + text
        control = operation_guard(event)
        if not isinstance(control, dict) or control.get('allowed') is not True:
            return {'status': 'blocked', 'reason': 'human_control'}
        repository.prepare_reply(inbound_key(event), conv, state, outbox_key, {'text': text, 'buttons': buttons})
        receipt = transport.send_reply(event, text, buttons, outbox_key)
        status = receipt.get('status', 'outcome_unknown') if isinstance(receipt, dict) else 'outcome_unknown'
        status = status if status in {'accepted', 'failed', 'outcome_unknown'} else 'outcome_unknown'
        repository.finish_outbox(outbox_key, status, {name: receipt[name] for name in ('status', 'message_id', 'reason')
                                                      if isinstance(receipt, dict) and isinstance(receipt.get(name), str)})
        mark_linked_notice(conv, state, text, status)
        return {'status': 'completed' if status == 'accepted' else status}

    def resume_unanswered(event, resumed):
        if production_blocked(settings, event=event):
            return {'status': 'blocked', 'reason': 'demo_contact_excluded_from_production'}
        if isinstance(resumed, dict) and resumed.pop('reprocess', False):
            # Release 44/45: a mensagem do lead sem resposta da Bia no Chatwoot é respondida uma vez, com a trava da
            # conversa (o webhook da mesma mensagem não corre junto) e o registro em 'reprocessed' no atendimento.
            # Se a Bia já tinha a resposta e ela não saiu, envia essa resposta; senão, processa a mensagem de novo.
            key, conv = inbound_key(event), conversation_key(event)
            log = logging.getLogger(__name__)
            with lock_for(conv):
                state = repository.load_session(conv)
                if key in (state.get('reprocessed') or {}):
                    return {'status': 'skipped', 'reason': 'already_reprocessed'}
                rows = repository.outbox(key) if repository.event(key) else []
                if any(row.get('status') == 'accepted' for row in rows):
                    return {'status': 'skipped', 'reason': 'reply_already_accepted'}
                stored = next((row for row in reversed(rows) if isinstance((row.get('payload') or {}).get('text'), str)
                               and row['payload']['text'].strip()), None)
                mark = {'at': datetime.now(timezone.utc).isoformat()}
                if key in (state.get('processed_inbound') or []) and stored:
                    state.setdefault('reprocessed', {})[key] = {**mark, 'mode': 'resend_stored_reply',
                                                                'previous_outbox': {'key': stored['outbox_key'],
                                                                                    'status': stored['status']}}
                    repository.save_session(conv, state)
                    log.warning('unanswered_event_reprocessed conversation=%s mode=resend previous_status=%s',
                                conv, stored['status'])
                    with app.app_context():
                        return resend_stored_reply(event, state, stored, key + ':reenvio')
                archive = repository.release_unanswered_event(key, conv) if repository.event(key) else {'status': None}
                if archive is None:
                    return {'status': 'skipped', 'reason': 'operation_queued_for_message'}
                if key in (state.get('processed_inbound') or []):
                    state['processed_inbound'] = [item for item in state['processed_inbound'] if item != key]
                state.setdefault('reprocessed', {})[key] = {**mark, 'mode': 'process_again', 'previous': archive}
                repository.save_session(conv, state)
                log.warning('unanswered_event_reprocessed conversation=%s mode=process previous_status=%s',
                            conv, archive.get('status'))
        with app.app_context():
            body, _ = process_inbound(event, resumed=resumed)
            return body

    pos_pausa = PosPausa(repository, settings, transport, operation_guard, resume_unanswered, now=lambda: executor.clock())

    def precheck_bridge_ready(kind='precheck'):
        """A live read-only GET /bridge/ready, never the worker's cached probe.

        Release 41: ``kind='invite'`` reads the Convites bridge (role ``invites``).
        Release 42: ``kind='agency'`` reads the Agenciamento bridge (the relations list).
        """
        try:
            real_client._ready({'invite': 'invites', 'consent': 'invites', 'agency': 'agency'}.get(kind, 'precheck'))
            return True
        except Exception:
            return False

    def retry_bridge_precheck(conv, reason, forced=False, kind='precheck'):
        """Queue one silent profile check for a chat stuck while the bridge was down.

        Release 41: ``kind='invite'`` queues the check that re-sends a consented
        invite that never reached TikTok (the chain continues in the journey).
        """
        if production_blocked(settings, conversation_key=conv):
            return {'status': 'blocked', 'reason': 'demo_contact_excluded_from_production'}
        import real_journey
        with app.app_context(), lock_for(conv):
            try:
                live = repository.load_session(conv)
                cycle = live.get('cycle') or {}
                operations = cycle.get('real_operations') or {}
                if kind == 'agency':
                    # The read answers the chat of the latest TikTok job of this cycle (invite, relationship, precheck).
                    record = next((operations[name] for name in ('invite', 'relationship', 'precheck')
                                   if (operations.get(name) or {}).get('cycle_id') == cycle.get('id')
                                   and (operations.get(name) or {}).get('job_id')), {})
                else:
                    record = operations.get('invite' if kind == 'invite' else 'precheck') or {}
                previous = repository.real_job_for_effect(record.get('job_id')) if record.get('job_id') else None
                origin = (previous or {}).get('event')
                if (not isinstance(origin, dict) or not allow_inbound(gate, origin) or conversation_key(origin) != conv
                        or (previous or {}).get('cycle_id') != cycle.get('id') or not _positive_id(origin.get('contact_id'))):
                    return {'status': 'failed', 'reason': 'precheck_source_unverified'}
                source_key = inbound_key(origin)
                stored = repository.event(source_key)
                if not stored or stored.get('conversation_key') != conv or stored.get('status') != 'completed':
                    return {'status': 'failed', 'reason': 'precheck_source_unverified'}
                control = operation_guard(origin)
                if not isinstance(control, dict) or control.get('allowed') is not True:
                    return {'status': 'blocked', 'reason': control.get('reason') if isinstance(control, dict) else None}
                if kind == 'agency':
                    # Release 42: o vínculo vira "falta só o cadastro"; a ficha é lida antes de cada leitura.
                    situation = registration_status(origin)
                    if not isinstance(situation, str):
                        return {'status': 'unconfirmed', 'reason': 'registration_unreadable'}
                    if situation != live.get('cadastro_situacao'):
                        live['cadastro_situacao'] = situation
                        repository.save_session(conv, live)
                    if situation == 'confirmado':
                        return {'status': 'idle', 'reason': 'registered'}
                effect = (real_journey.invite_retry_effect(live, executor.clock(), forced=forced) if kind == 'invite'
                          else real_journey.auto_invite_effect(live, executor.clock(), policy_for(settings))
                          if kind == 'consent'
                          else real_journey.agency_read_effect(live, executor.clock()) if kind == 'agency'
                          else real_journey.bridge_retry_effect(live, executor.clock(), reason=reason, forced=forced))
                if not effect:
                    return {'status': 'idle'}
                prefix, purpose = {'invite': ('invite-bridge-retry:', 'bridge_invite_retry'),
                                   'consent': ('auto-invite:', 'auto_invite_after_eligible'),
                                   'agency': ('agency-read:', 'agency_relations_read')}.get(
                                       kind, ('bridge-retry:', 'bridge_precheck_retry'))
                operation_key = prefix + effect['id']
                if not repository.reserve_operation(operation_key, source_key, purpose):
                    return {'status': 'failed', 'reason': 'retry_already_reserved'}
                live = sync_contact(origin, live)
                jobs = build_jobs(origin, live, [effect])
                repository.prepare_reply(source_key, conv, live, operation_key + ':no-reply', None, real_jobs=jobs)
                repository.complete_operation(operation_key, {'queued': True, 'cycle_id': cycle['id']})
                executor.wake()
                return {'status': 'queued'}
            except Exception:
                return {'status': 'outcome_unknown', 'reason': 'bridge_retry_unconfirmed'}

    from reconferencia import Reconferencia, enabled as recheck_enabled
    reconferencia = Reconferencia(repository, settings, precheck_bridge_ready, retry_bridge_precheck,
                                  now=lambda: executor.clock(), policy=lambda: policy_for(settings))
    app.extensions.update(v5_retomada=retomada, v5_pos_pausa=pos_pausa, v5_reconferencia=reconferencia)
    if (conduct_enabled(settings, 'retomada_enabled') or conduct_enabled(settings, 'pos_pausa_enabled')
            or recheck_enabled(settings)):
        # Release 39 replaces the single-chat 5+5 reminder for every pilot chat.
        conduct_callbacks = (reconferencia.tick, pos_pausa.tick, retomada.tick)
        conduct_cursor = 0
        def conduct_tick():
            # One bounded maintenance slice, then return to the real-job worker.
            nonlocal conduct_cursor
            callback = conduct_callbacks[conduct_cursor]
            conduct_cursor = (conduct_cursor + 1) % len(conduct_callbacks)
            return callback()
        executor.followup_tick = conduct_tick
        executor.followup_status = lambda: {**followup.status(), 'retomada': retomada.status(),
                                            'pos_pausa': pos_pausa.status(), 'reconferencia': reconferencia.status()}

    if demo_router and settings.get('demo_followup_enabled') is True:
        from demo_followup import tick_all
        executor.demo_followup_tick = lambda: tick_all(demo_router)
        app.extensions['v5_demo_followup_tick'] = lambda: tick_all(demo_router)

    def inactivity_notice(state):
        """Project a question only when the last accepted outbox is its warning."""
        from followup import configured, sequence_keys
        CONVERSATION = pilot_scope.conversation_key(settings.get('pilot_scope') or {})
        if settings.get('inactivity_close_enabled') is not True or not configured(settings):
            return None
        try:
            cycle = state.get('cycle') or {}
            source = repository.followup_source(CONVERSATION)
            if (cycle.get('mode') != 'real' or cycle.get('status') != 'open' or not source
                    or source.get('cycle_id') != cycle.get('id')
                    or not state.get('processed_inbound')
                    or state['processed_inbound'][-1] != source.get('event_key')
                    or not allow_inbound(gate, source.get('event', {}))):
                return None
            warning_key, _ = sequence_keys(cycle['id'], source['event_key'])
            rows = [row for row in repository.outbox(source['event_key'])
                    if row.get('outbox_key') == warning_key and row.get('conversation_key') == CONVERSATION]
            if len(rows) != 1:
                return None
            row = rows[0]
            delivery = repository.conversation_delivery_context(CONVERSATION, cycle['opened_at'])
            receipt = followup._accepted(warning_key, source)
            if not receipt:
                # An unconfirmed warning might have changed what the person
                # saw. Re-ask a boolean/consent question, without pretending the
                # warning was accepted or treating its answer as permission.
                operation = repository.get_operation(warning_key)
                uncertain = row.get('receipt') or {}
                if (row.get('status') == 'outcome_unknown' and delivery.get('latest_attempt_status') == 'outcome_unknown'
                        and operation and operation.get('kind') == 'followup'
                        and operation.get('status') == 'outcome_unknown'
                        and operation.get('event_key') == source['event_key']
                        and operation.get('result') == uncertain
                        and uncertain.get('cycle_id') == cycle['id']
                        and uncertain.get('source_key') == source['event_key']):
                    return {'source': 'uncertain_outbox', 'cycle_id': cycle['id'], 'source_key': source['event_key'],
                            'warning_key': warning_key, 'observed_at': row['updated_at']}
                return None
            last = delivery.get('last_accepted_reply') or {}
            if (delivery.get('latest_attempt_status') != 'accepted'
                    or last.get('at') != row['updated_at'] or last.get('text') != row['payload'].get('text')):
                return None
            return {'source': 'accepted_outbox', 'cycle_id': cycle['id'], 'source_key': source['event_key'],
                    'warning_key': warning_key, 'accepted_at': receipt['accepted_at']}
        except Exception:
            return None

    app.extensions['v5_inactivity_notice'] = inactivity_notice

    def reconcile_initial(*, event, state, recovery_key, provenance):
        if production_blocked(settings, event=event):
            return {'status': 'blocked', 'operations': []}
        """Resume evidenced read-only work; never replay or count an inbound."""
        from copy import deepcopy
        import real_journey
        if (not contact_sync or _get(settings, 'tiktok_mode') != 'real'
                or _get(settings, 'real_worker_enabled') is not True
                or not isinstance(recovery_key, str) or not re.fullmatch(r'[0-9a-f]{64}', recovery_key)
                or provenance not in {'webhook_digest_confirmed', 'revalidated_chatwoot_source'}
                or not allow_inbound(gate, event) or conversation_key(event) != pilot_scope.conversation_key()):
            return {'status': 'blocked', 'operations': []}
        conv, reference = conversation_key(event), inbound_key(event)
        with lock_for(conv):
            current = repository.load_session(conv)
            cycle = current.get('cycle') or {}
            now = engine._clock()
            if (current != state or cycle.get('mode') != 'real' or cycle.get('status') != 'open'
                    or not cycle.get('expires_at') or now >= engine._clock(cycle['expires_at'])
                    or cycle.get('pending_profile_changes') or cycle.get('qualification_paused')
                    or current.get('human_control') or (current.get('processed_inbound') or [None])[-1] != reference):
                return {'status': 'noop', 'operations': []}
            control = operation_guard(event)
            if not isinstance(control, dict) or control.get('allowed') is not True:
                return {'status': 'blocked', 'operations': []}
            proposed = deepcopy(current)
            if settings.get('relationship_check_in_form') is True:
                proposed['cycle']['relationship_check_in_form'] = True
            effects = real_journey._initial_checks(proposed, now)
            if not effects:
                return {'status': 'noop', 'operations': []}
            operations = [effect.get('operation') for effect in effects]
            if any(operation not in {'lookup', 'precheck', 'relationship'} for operation in operations):
                return {'status': 'blocked', 'operations': []}
            proposed['revision'] += 1
            key = 'reconcile:' + recovery_key
            digest = hashlib.sha256(json.dumps({'reference': reference, 'cycle_id': cycle['id'],
                'revision': current.get('revision'), 'operations': operations}, sort_keys=True).encode()).hexdigest()
            reservation = repository.reserve_event(key, conv, digest)
            if reservation.get('reserved') is not True:
                return {'status': 'noop', 'operations': []}
            try:
                proposed = sync_contact(event, proposed)
                jobs = build_jobs(event, proposed, effects)
                repository.prepare_reply(key, conv, proposed, key + ':reply', None, real_jobs=jobs)
                repository.finish_event(key, 'completed')
                executor.wake()
                return {'status': 'scheduled', 'operations': operations}
            except Exception:
                repository.finish_event(key, 'outcome_unknown')
                return {'status': 'outcome_unknown', 'operations': []}

    app.extensions['v5_reconcile_initial'] = reconcile_initial

    def authorized():
        secret = _get(settings, "webhook_token")
        if not isinstance(secret, str) or len(secret) < 16:
            return False
        header, query = request.headers.get("X-Amplify-Webhook-Token"), request.args.get("token")
        if len(request.args.getlist("token")) > 1:
            return False
        if header is not None and query is not None and not hmac.compare_digest(header.encode(), query.encode()):
            return False
        candidate = header if header is not None else query
        return isinstance(candidate, str) and len(candidate) <= 512 and hmac.compare_digest(secret.encode(), candidate.encode())

    def diagnostico_authorized():
        """Release 46: o mesmo segredo do webhook (V5_WEBHOOK_TOKEN), como Authorization: Bearer."""
        secret = _get(settings, "webhook_token")
        header = request.headers.get("Authorization") or ""
        return (isinstance(secret, str) and len(secret) >= 16 and header.startswith("Bearer ")
                and len(header) <= 600 and hmac.compare_digest(secret.encode(), header[7:].strip().encode()))

    def diagnostico_chatwoot(conversation_id):
        """Uma leitura do Chatwoot (detalhe e mensagens), sem escrever nada."""
        from retomada import _automatic, _bia, _incoming
        target = {"account_id": gate.get("account_id"), "conversation_id": conversation_id}
        headers = {"api_access_token": transport.token, "Accept": "application/json"}
        detail = transport.http(method="GET", url=transport._conversation_url(target), headers=headers, timeout=8)
        data = transport.http(method="GET", url=transport._conversation_url(target) + "/messages", headers=headers, timeout=8)
        meta = (detail or {}).get("meta") or {}
        sender = meta.get("sender") or {}
        received = normalize_phone(sender.get("phone_number"))
        listed = pilot_phone(gate, sender.get("phone_number"))
        listed_digits = normalize_phone(listed) if listed else None
        variation = (None if not listed else "igual" if listed_digits == received
                     else "lista_com_9_chatwoot_sem" if len(listed_digits or "") > len(received or "") else "lista_sem_9_chatwoot_com")
        messages = sorted((m for m in ((data or {}).get("payload") or []) if isinstance(m, dict)
                           and re.fullmatch(r"[1-9][0-9]{0,19}", str(m.get("id", "")))), key=lambda m: int(m["id"]))
        incoming = [m for m in messages if _incoming(m)]
        last = incoming[-1] if incoming else None

        def kind(message):
            if message.get("private") is True:
                return "nota_privada"
            if _bia(message):
                return "bia"
            if _automatic(message):
                return "automatica"
            mtype = message.get("message_type")
            return "humano" if mtype in (1, "outgoing") else "atividade" if mtype in (2, "activity") else "outro"
        after = [{"id": m["id"], "tipo": kind(m), "em": m.get("created_at")} for m in messages
                 if last and int(m["id"]) > int(last["id"]) and not _incoming(m)]
        return {"piloto": {"no_piloto": bool(listed), "variacao": variation,
                           "final_do_telefone": (received or "")[-4:] or None},
                "status": detail.get("status") if isinstance(detail, dict) else None,
                "pode_responder": detail.get("can_reply") if isinstance(detail, dict) else None,
                "tem_responsavel": meta.get("assignee") is not None,
                "ultima_do_lead": {"id": last["id"], "em": last.get("created_at")} if last else None,
                "depois_dela": after,
                "resposta_publica_depois": any(item["tipo"] in {"bia", "humano"} for item in after)}

    @app.get("/diagnostico/conversa/<conversation_id>")
    def diagnostico_conversa(conversation_id):
        """Release 46: o estado da Bia para uma conversa, só leitura (nada é gravado nem enviado)."""
        if not diagnostico_authorized():
            return jsonify(error="unauthorized"), 401
        if not re.fullmatch(r"[1-9][0-9]{0,19}", str(conversation_id)):
            return jsonify(error="conversa_invalida"), 400
        from retomada import DECISOES
        conv = "chatwoot:" + str(gate.get("account_id")) + ":" + str(conversation_id)
        try:
            chatwoot = diagnostico_chatwoot(conversation_id)
        except Exception as error:
            chatwoot = {"leitura": "indisponivel", "erro": type(error).__name__}
        state = repository.load_session(conv) or {}
        cycle = _mapping(state.get("cycle"))
        processed = [item for item in (state.get("processed_inbound") or []) if isinstance(item, str)]
        last = (chatwoot.get("ultima_do_lead") or {}).get("id") if isinstance(chatwoot, dict) else None
        last_key = "chatwoot:" + str(gate.get("account_id")) + ":" + str(last) if last else None
        event = repository.event(last_key) if last_key else None
        source = repository.followup_source(conv)
        attendance = {
            "existe": bool(state.get("cycle")),
            "etapa": cycle.get("phase"), "situacao": cycle.get("status"), "expira": cycle.get("expires_at"),
            "ultima_processada": processed[-1] if processed else None,
            "processed_inbound_tem_ultima_do_lead": (last_key in processed) if last_key else None,
            "evento_da_ultima_do_lead": event.get("status") if event else None,
            "envios_da_ultima_do_lead": [row.get("status") for row in repository.outbox(last_key)] if event else [],
            "reprocessed": {key: {"modo": value.get("mode"), "em": value.get("at")}
                            for key, value in (state.get("reprocessed") or {}).items() if isinstance(value, dict)},
            "retomada": {"ultimo_lembrete": cycle.get("retomada"), "fonte": (source or {}).get("event_key")},
            "controle_humano": bool(state.get("human_control")),
            "pausa_ou_saida": bool(cycle.get("qualification_paused") or state.get("opt_out") or cycle.get("opt_out")),
            "cadastro": state.get("cadastro_situacao"),
        }
        from operational_diagnostics import invite_attempt_diagnostics, operation_diagnostics
        attendance['operacoes_tiktok'] = operation_diagnostics(cycle, settings)
        attendance['tentativas_convite'] = invite_attempt_diagnostics(
            state, repository.invite_attempt_rows(conv), settings)
        return jsonify(conversa=str(conversation_id), chatwoot=chatwoot, atendimento=attendance,
                       decisoes=DECISOES.for_conversation(conversation_id)), 200

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", mode="one_contact_real" if _get(settings, 'tiktok_mode') == 'real' else "one_contact_rehearsal")

    @app.get("/ready")
    def ready():
        missing = issues()
        if settings.get('same_engine_enabled') is True and not getattr(planner, 'shared_engine_available', False):
            missing.append('shared_answer_engine_unavailable')
        tiktok = executor.status()
        if _get(settings, 'tiktok_mode') == 'real' and not tiktok['worker_running']:
            missing.append('real_worker_not_running')
        if _get(settings, 'tiktok_mode') == 'real' and not tiktok['sessions']['ready']:
            missing.append('real_tiktok_sessions_unverified')
        real_bridge = app.extensions.get('v5_demo_real_bridge')
        demo_real = real_bridge.status() if real_bridge is not None else {'enabled': False}
        if demo_real.get('enabled') and demo_real.get('ready') is not True:
            missing.append('demo_real_not_ready')
        context_info = None
        if _get(settings, 'context_db_enabled', False) is True:
            try:
                from context_ia import load_context
                snapshot = load_context(settings)
                context_info = {'source': snapshot['source'], 'version': snapshot['knowledge_version'],
                                'active_cards': snapshot['card_count']}
            except Exception:
                missing.append('context_ia_unavailable')
        return jsonify(ready=not missing, issues=sorted(set(missing)), context_ia=context_info,
                       tiktok=tiktok, demo_real=demo_real,
                       approved_experience={'enabled': settings.get('approved_experience_enabled') is True, 'new_cycles_only': True},
                       answer_engine={'enabled': settings.get('same_engine_enabled') is True,
                                      'version': 'shared-answer-v1' if settings.get('same_engine_enabled') is True else 'legacy',
                                      'available': getattr(planner, 'shared_engine_available', False),
                                      'profile_id': settings.get('context_profile_id', 'amplify-v1')},
                       qualification={'enabled': settings.get('qualification_enabled') is True,
                                      'new_cycles_only': settings.get('qualification_new_cycles_only') is True}), 503 if missing else 200

    def process_inbound(event, resumed=None):
        """One admitted lead message; the webhook and the post-pause catch-up share it."""
        if demo_router and demo_router.claims(event):
            return handle_demo(event)
        key, conv = inbound_key(event), conversation_key(event)
        digest = hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        import conversation as conversation_commands
        recognize_reset = getattr(conversation_commands, '_chat_reset_requested', None)
        real_mode = _get(settings, 'tiktok_mode') == 'real'
        reset_requested = bool(callable(recognize_reset) and recognize_reset(event.get('text'), real_mode=real_mode))
        from real_journey import _acknowledgment_only
        # A bare acknowledgment still takes its FIFO turn, but it cannot
        # cancel the answer to an earlier real question that is still running.
        ack_only = (conversational and real_mode and isinstance(event.get('text'), str)
                    and _acknowledgment_only(event['text'], engine._normal(event['text'])))
        try:
            reservation, ticket = reply_fence.admit(event, lambda: repository.reserve_event(
                key, conv, digest, source_at=event.get('created_at')), reset=reset_requested,
                supersedes=not ack_only)
        except Exception:
            return dict(accepted=False, status="operational_state_unavailable"), 503
        if not reservation["reserved"]:
            return dict(accepted=not reservation["conflict"], duplicate=True,
                           status="event_conflict" if reservation["conflict"] else reservation["status"]), 200
        lock = lock_for(conv)
        # Exactly one Gunicorn worker; FIFO admission precedes serialized state.
        with reply_fence.turn(event, ticket):
            with lock:
                try:
                    state = repository.load_session(conv)
                    processed = reply_fence.processed(state, event)
                    boundary = reply_fence.reset_boundary(state, event)
                    before_reset = bool(boundary and int(event['message_id']) < int(boundary['message_id']))
                    late_control = bool(reply_fence.control_message(event['text'], reset=reset_requested,
                                        real_mode=_get(settings, 'tiktok_mode') == 'real')
                                        and processed and int(processed.rsplit(':', 1)[-1]) > int(event['message_id']))
                    if before_reset or late_control:
                        # Preserve the received event and its historical context;
                        # do not feed old facts into a cycle opened by a real reset.
                        state.setdefault('history', []).append({'direction': 'inbound', 'text': event['text'],
                            'at': event.get('created_at'), 'source_ref': key,
                            'cycle_id': boundary.get('previous_cycle_id'),
                            'late_before_reset': before_reset, 'late_control': late_control})
                        state.setdefault('processed_inbound', []).append(key)
                        reply_fence.keep_latest_cursor(state, event)
                        repository.prepare_reply(key, conv, state, key + ':no-reply', None)
                        repository.finish_event(key, 'completed')
                        reply_fence.retire_stale_reset(event)
                        return dict(accepted=True, duplicate=False, status='completed', reply_suppressed=True), 200
                    previous_cycle_id = _mapping(state.get('cycle')).get('id')
                    state = sync_contact(event, state, before=True)
                    # One immutable context snapshot per inbound. Never cache it in
                    # global service settings: the next message must see DB edits.
                    turn_settings = dict(settings)
                    from real_answer_adapter import (pending_information_questions, remember_suppressed_question,
                                                     clear_answered_questions)
                    faq_controls = reply_fence.control_message(
                        event.get('text'), reset=reset_requested, real_mode=True)
                    faq_enabled = (conversational and _get(settings, 'tiktok_mode') == 'real'
                                   and settings.get('same_engine_enabled') is True and resumed is None
                                   and not faq_controls and not state.get('human_control') and not state.get('opt_out'))
                    answered_faq = {}

                    def knowledge(question, context):
                        operation_key = key + ":answer"
                        if not repository.reserve_operation(operation_key, key, "answer_question"):
                            existing = repository.get_operation(operation_key)
                            if existing and existing.get("result"):
                                return existing["result"]["text"]
                            return "Não consegui confirmar a resposta desta dúvida. Pode continuar o atendimento ou fazer outra pergunta."
                        answer = answerer(question, context.get("history", []), turn_settings)
                        if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
                            raise ValueError("invalid_answer_contract")
                        status = "outcome_unknown" if answer.get("provider_status") == "unknown" else "completed"
                        repository.complete_operation(operation_key, answer, status)
                        return answer["text"]

                    def plan(question, context):
                        operation_key = key + ":conversation"
                        if not repository.reserve_operation(operation_key, key, "conversation_turn"):
                            existing = repository.get_operation(operation_key)
                            if existing and isinstance(existing.get("result"), dict):
                                return existing["result"]
                            return {"provider_status": "unknown", "claims": [], "reply": "", "intent": "clarify"}
                        if context.get("real_mode") is True:
                            # Ephemeral read projection; planned history is not proof
                            # of what the lead actually received in Chatwoot.
                            try:
                                context["delivery_context"] = repository.conversation_delivery_context(
                                    conv, _mapping(context.get("cycle")).get("opened_at"))
                            except Exception:
                                context["delivery_context"] = {"source": "unavailable", "accepted_history": [],
                                    "last_accepted_reply": None, "latest_attempt_status": "unknown"}
                            # Effect state can outlive a failed worker application.
                            # Only an exactly bound durable job proves ongoing work;
                            # a terminal/missing row never becomes "still running".
                            cycle_id = _mapping(context.get("cycle")).get("id")
                            creator = _mapping(context.get("facts")).get("tiktok_declarado")
                            projected = []
                            for effect in _mapping(state.get("effects")).values():
                                if (not isinstance(effect, dict) or effect.get("type") != "tiktok_operation"
                                        or effect.get("cycle_id") != cycle_id or effect.get("creator") != creator
                                        or not isinstance(creator, str) or not creator.startswith("@")
                                        or effect.get("operation") not in {"lookup", "precheck", "invite", "relationship"}
                                        or effect.get("status") not in {"pending", "running", "outcome_unknown"}):
                                    continue
                                operation = effect["operation"]
                                status = "outcome_unknown"
                                try:
                                    job = repository.real_job(business_key(cycle_id, creator.lstrip("@").lower(), operation))
                                    bound = (isinstance(job, dict) and job.get("conversation_key") == conv
                                        and job.get("cycle_id") == cycle_id and job.get("creator") == creator.lstrip("@").lower()
                                        and job.get("effect_id") == effect.get("id") and job.get("operation") == operation
                                        and job.get("payload") == effect.get("payload"))
                                    if bound and job.get("status") in {"queued", "running", "polling", "result_ready"}:
                                        status = "running" if job["status"] == "running" else "pending"
                                except Exception:
                                    pass
                                projected.append({"operation": operation, "status": status})
                            context["pending_operations"] = projected
                            if faq_enabled and question == event.get('text') and not projected:
                                context['pending_information_questions'] = pending_information_questions(state, event)
                            if any(row["status"] == "outcome_unknown" for row in projected):
                                context["current_question"] = ("O resultado dessa operação ainda não foi confirmado. "
                                    "É preciso conferir o que aconteceu antes de prosseguir; não há confirmação de consulta em andamento.")
                        answer = planner(question, context, turn_settings)
                        if not isinstance(answer, dict):
                            raise ValueError("invalid_conversation_contract")
                        status = "outcome_unknown" if answer.get("provider_status") == "unknown" else "completed"
                        repository.complete_operation(operation_key, answer, status)
                        if faq_enabled and answer.get('carried_information_sources'):
                            marker = _mapping(answer.get('shared_answer'))
                            if marker.get('status') == 'supported' and isinstance(marker.get('text'), str):
                                answered_faq.update({'sources': answer['carried_information_sources'],
                                                     'text': marker['text']})
                        return answer

                    from copy import deepcopy
                    declaration_before = deepcopy(state.get('cycle') or {})
                    if conversational:
                        import conversation
                        turn_options = {'real_mode': _get(settings, 'tiktok_mode') == 'real',
                                        'operation_policy': policy_for(settings),
                                        'approved_experience_enabled': settings.get('approved_experience_enabled') is True,
                                        'same_engine_enabled': settings.get('same_engine_enabled') is True,
                                        'qualification_enabled': settings.get('qualification_enabled') is True,
                                        'qualification_new_cycles_only': settings.get('qualification_new_cycles_only') is True}
                        if turn_options['real_mode'] and settings.get('relationship_check_in_form') is True:
                            turn_options['relationship_check_in_form'] = True
                        if turn_options['real_mode'] and engine._normal(event.get('text', '')) in {'sim', 'nao'}:
                            notice = inactivity_notice(state)
                            if notice is not None:
                                turn_options['inactivity_notice'] = notice
                        if resumed is not None:
                            turn_options['resumed'] = resumed
                        result = conversation.handle_event(state, event, gate, plan, **turn_options)
                    else:
                        result = engine.handle_event(state, event, gate, knowledge)
                    reply, buttons, state = result.get("reply", ""), result.get("buttons", []), result["state"]
                    reply_fence.keep_latest_cursor(state, event)
                    cycle = _mapping(state.get('cycle'))
                    if (reset_requested and key in state.get('processed_inbound', [])
                            and cycle.get('phase') == 'intro' and cycle.get('id') != previous_cycle_id):
                        state['chat_reset_boundary'] = {'source': key, 'message_id': str(event['message_id']),
                            'cycle_id': cycle.get('id'), 'previous_cycle_id': previous_cycle_id}
                    from chat_declarations import collect, remember_profile
                    declarations = collect(event, declaration_before, cycle)
                    remember_profile(event, declaration_before, cycle)
                    if declarations:
                        cycle['chat_declarations_pending'] = declarations
                        for declaration in declarations:
                            if declaration['campo'] == 'seguidores':
                                cycle.setdefault('facts', {})['seguidores_declarados'] = declaration['valor']
                    state = sync_contact(event, state)
                    priority = (state.get('cycle') or {}).get('bia_validation') or {}
                    if priority.get('priority_flow_version') == 2 and priority.get('stage') == 'priority_alert':
                        # Contact/profile persistence precedes Slack; the lead's
                        # choice is released only on a durable Slack receipt.
                        from lead_alerts import dispatch
                        from lead_validation import release_priority_choice
                        dispatched = dispatch(settings, repository, event, state)
                        threshold = dispatched.get('events', {}).get('threshold', {})
                        if threshold.get('status') == 'accepted':
                            released = release_priority_choice(state)
                            if released:
                                reply, buttons = released
                        repository.save_session(conv, state)
                    progress_proof = None
                    if progress is not None:
                        confirmed = repository.get_operation(key + ":contact:" + str(max(1, int(state.get("revision", 1)))))
                        if confirmed and confirmed.get("status") == "completed":
                            cycle = state.get("cycle") or {}
                            progress_proof = {"kind": "contact", "receipt": confirmed.get("result"),
                                              "snapshot": {"cycle_id": cycle.get("id"), "phase": cycle.get("phase"),
                                                           "status": cycle.get("status"), "revision": state.get("revision")}}
                    for effect in result.get("effects", []):
                        factory = app.extensions.get("v5_form_link_factory")
                        if effect.get("type") == "generate_form_link" and callable(factory):
                            op_key = effect["id"]
                            if repository.reserve_operation(op_key, key, "generate_form_link"):
                                url = factory(state, effect, event)
                                resolver = conversation.resolve_effect if conversational else engine.resolve_effect
                                resolved = resolver(state, effect["id"], form_url=url)
                                state = resolved["state"]
                                reply = "\n\n".join(part for part in (reply, resolved.get("reply")) if part)
                                buttons = resolved.get("buttons", buttons)
                                repository.complete_operation(op_key, {"generated": True})
                    outbox_key = key + ":reply"
                    body = {"text": reply, "buttons": buttons} if reply and reply_fence.current(event) else None
                    effects = result.get('effects', [])
                    faq_reply = (faq_enabled and reply and not effects and not result.get('fixed_greeting')
                                 and not _mapping(state.get('cycle')).get('opt_out'))
                    if faq_reply and not body:
                        remember_suppressed_question(state, event)
                    real_jobs = build_jobs(event, state, effects)
                    repository.prepare_reply(key, conv, state, outbox_key, body, real_jobs=real_jobs)
                    if body:
                        receipt = send_current_reply(event, reply, buttons, outbox_key)
                        status = receipt.get("status", "outcome_unknown") if isinstance(receipt, dict) else "outcome_unknown"
                        status = status if status in {"accepted", "failed", "outcome_unknown"} else "outcome_unknown"
                        # Preserve only bounded transport receipt fields, never raw requests/credentials.
                        safe_receipt = {name: receipt[name] for name in ("status", "message_id", "reason")
                                        if isinstance(receipt, dict) and name in receipt and isinstance(receipt[name], str)}
                        repository.finish_outbox(outbox_key, status, safe_receipt)
                        if faq_reply and safe_receipt.get('reason') == 'reply_superseded_by_new_inbound':
                            if remember_suppressed_question(state, event):
                                repository.save_session(conv, state)
                        if (status == 'accepted' and answered_faq.get('text')
                                and answered_faq['text'] in reply
                                and clear_answered_questions(state, answered_faq['sources'])):
                            repository.save_session(conv, state)
                        mark_linked_notice(conv, state, reply, status)
                        final = "completed" if status == "accepted" or safe_receipt.get("reason") == "reply_superseded_by_new_inbound" else status
                    else:
                        final = "completed"
                    repository.finish_event(key, final)
                    if ((settings.get('followup_enabled') is True or settings.get('retomada_enabled') is True)
                            and final == 'completed' and reply_fence.current(event)):
                        try:
                            repository.remember_followup_source(conv, event, state)
                        except Exception:
                            # Optional reminder metadata must never reclassify an
                            # already accepted lead reply as an uncertain inbound.
                            pass
                    if (settings.get('qualification_enabled') is True
                            or (state.get('cycle') or {}).get('experience_version') == 'bia-approved-v1'):
                        try:
                            from lead_alerts import dispatch
                            dispatch(settings, repository, event, state)
                            repository.save_session(conv, state)
                        except Exception:
                            pass
                    send_team_alert(event, conv, state)
                    if real_jobs:
                        executor.wake()
                    if progress_proof is not None and reply_fence.current(event):
                        # The lead's reply is attempted first; visual projection cannot fail the journey.
                        try:
                            progress.sync(event, state, progress_proof)
                        except Exception:
                            pass
                    return dict(accepted=True, duplicate=False, status=final), 200
                except Exception as error:
                    # Auditoria 20/11 (conversa 55626): o erro era engolido sem log. Registra só o
                    # tipo e o ponto do código (sem texto do lead, telefone ou payload).
                    _log_inbound_failure(error)
                    # Reservation survives every uncertain effect; do not ask Chatwoot to retry it.
                    try:
                        repository.finish_event(key, "outcome_unknown")
                    except Exception:
                        pass
                    try:
                        answered = any(row.get("status") == "accepted" for row in repository.outbox(key) or [])
                    except Exception:
                        answered = False
                    if not answered:
                        import conversao
                        honest_notice(event, conversao.INBOUND_FALLBACK, key.replace('chatwoot:', 'falha:') + ':fallback')
                    return dict(accepted=True, duplicate=False, status="outcome_unknown"), 202

    app.extensions['v5_process_inbound'] = process_inbound

    def handle_demo(event, payload=None):
        try:
            if payload is not None:
                event = demo_router.decorate(event, payload)
                result, code = demo_router.handle_verified_webhook(event)
            else:
                result, code = demo_router.handle(event)
        except Exception:
            result, code = {'accepted': False, 'status': 'demo_unavailable'}, 503
        # Only bounded routing metadata; never message text, phone or exception details.
        status = result.get('status')
        if not isinstance(status, str) or not re.fullmatch(r'demo_[a-z_]{1,60}', status):
            status = 'demo_unavailable'
        print(json.dumps({
            'message_id': _positive_id(event.get('message_id')),
            'conversation_id': _positive_id(event.get('conversation_id')),
            'status': status}, sort_keys=True), flush=True)
        return result, code

    @app.post('/demo/<action>')
    def demo_control(action):
        if not authorized():
            return jsonify(status='unauthorized'), 401
        if demo_router is None:
            return jsonify(status='demo_disabled'), 404
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(status='json_required'), 415
        allowed = {'start': {'request_id'}, 'reconcile': set(), 'stop': set(), 'simulate': {'operation', 'fixture'}}
        if action not in allowed or set(payload) - (allowed[action] | {'scope'}):
            return jsonify(status='demo_control_rejected'), 400
        try:
            target = demo_router.select(payload.get('scope'))
            if action == 'start':
                result = target.start(payload.get('request_id'))
            elif action == 'reconcile':
                result = target.reconcile()
            elif action == 'stop':
                result = target.stop()
            else:
                result = target.simulate(payload.get('operation'), payload.get('fixture', 'unknown'))
            return jsonify(**result), 200
        except Exception:
            return jsonify(status='demo_control_unconfirmed'), 409

    def process_image_inbound(event):
        """Reply once to verified captionless images, without business effects."""
        key, conv = inbound_key(event), conversation_key(event)

        def image_control():
            if production_blocked(settings, event=event):
                return False
            live = repository.load_session(conv)
            if (live.get('human_control') or live.get('opt_out')
                    or _mapping(live.get('cycle')).get('opt_out')
                    or reply_fence.reset_waiting(live, event)):
                return False
            return chatwoot_control_guard(transport, gate, event, image_only=True).get('allowed') is True

        try:
            if not allow_image_inbound(gate, event) or not image_control():
                return dict(accepted=False, status='image_ignored'), 202
            digest = hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            reservation, ticket = reply_fence.admit(event, lambda: repository.reserve_event(
                key, conv, digest, source_at=event.get('created_at')))
            if not reservation['reserved']:
                return dict(accepted=not reservation['conflict'], duplicate=True,
                            status='event_conflict' if reservation['conflict'] else reservation['status']), 200
        except Exception:
            return dict(accepted=False, status='operational_state_unavailable'), 503
        with reply_fence.turn(event, ticket):
            with lock_for(conv):
                try:
                    state = repository.load_session(conv)
                    latest = reply_fence.processed(state, event)
                    stale = bool(latest and int(latest.rsplit(':', 1)[-1]) > int(event['message_id']))
                    current = not stale and reply_fence.current(event) and image_control()
                    state.setdefault('processed_inbound', []).append(key)
                    reply_fence.keep_latest_cursor(state, event)
                    # Preserve all cycle facts/consents/effects. The new cursor
                    # invalidates old follow-up sources until a real text arrives.
                    body = {'text': IMAGE_ONLY_REPLY, 'buttons': []} if current else None
                    outbox_key = key + ':image-guidance'
                    repository.prepare_reply(key, conv, state, outbox_key, body)
                    final = 'completed'
                    if body:
                        receipt = transport.send_reply(event, IMAGE_ONLY_REPLY, [], outbox_key,
                            image_only=True, before_write=lambda: reply_fence.current(event) and image_control())
                        receipt = receipt if isinstance(receipt, dict) else {}
                        status = receipt.get('status', 'outcome_unknown')
                        status = status if status in {'accepted', 'failed', 'outcome_unknown'} else 'outcome_unknown'
                        safe = {name: receipt[name] for name in ('status', 'message_id', 'reason')
                                if isinstance(receipt.get(name), str)}
                        repository.finish_outbox(outbox_key, status, safe)
                        final = 'completed' if status == 'accepted' else status
                    repository.finish_event(key, final)
                    return dict(accepted=True, duplicate=False, status=final), 200
                except Exception:
                    # Persist uncertainty and never retry an unconfirmed send.
                    repository.finish_event(key, 'outcome_unknown')
                    return dict(accepted=True, duplicate=False, status='outcome_unknown'), 202

    @app.post("/webhook/chatwoot")
    def webhook():
        if not authorized():
            return jsonify(accepted=False, status="unauthorized"), 401
        if issues():
            return jsonify(accepted=False, status="not_ready"), 503
        if not request.is_json:
            return jsonify(accepted=False, status="json_required"), 415
        payload = request.get_json(silent=True)
        event = normalize_chatwoot(payload)
        # The demo has its own exact recipient gate. Never add its second phone
        # to the production allowlist, and never bypass the global enabled flag.
        if event and gate.get('enabled') is True and demo_router and demo_router.claims(event):
            body, code = handle_demo(event, payload)
            return jsonify(**body), code
        # 27/11/2026: "Já sou Amplify" na caixa da Bia é atendido pelo serviço de renovação (a Bia dos agenciados).
        if (event and str(event.get('inbox_id')) == str(gate.get('inbox_id'))
                and gate_exclusion(gate, event, {}) == 'fora_do_gate:renovacao_de_contrato'):
            return jsonify(accepted=False, status="ignored", reason='fora_do_gate:renovacao_de_contrato'), 202
        if event and allow_image_inbound(gate, event):
            body, code = process_image_inbound(event)
            return jsonify(**body), code
        if not event or not allow_inbound(gate, event):
            return jsonify(accepted=False, status="ignored"), 202
        from contracts import gate_mode, is_test_phone
        if gate_mode(gate) == 'todos' and not is_test_phone(gate, event.get('sender_phone')):
            # Release 47: com a caixa inteira, quem está excluído (etiqueta "Renovacao de contrato", responsável ou
            # controle humano) não recebe resposta; o motivo fica no diagnóstico. Nada é registrado no banco.
            from retomada import DECISOES, guard_reason
            control = operation_guard(event)
            if not isinstance(control, dict) or control.get('allowed') is not True:
                reason = guard_reason(control, gate)
                DECISOES.record('entrada', str(event.get('conversation_id')), reason, datetime.now(timezone.utc),
                                detalhe=control.get('reason') if isinstance(control, dict) else None)
                return jsonify(accepted=False, status="ignored", reason=reason), 202
        body, code = process_inbound(event)
        return jsonify(**body), code

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify(accepted=False, status="request_too_large"), 413

    return app
