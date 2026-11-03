"""Original six-step form protocol over the existing pilot-bound V5 form.

The browser supplies answers, never identity, relationship evidence or a target
creator. Drafts occupy one private SQLite row per already authenticated form.
OTP, image sanitation and the final 63-field mapping keep their original owner.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re
import threading
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, send_file

from contracts import normalize_phone
from data.mapper import MappingError, _convert, load_mapping
from forms import FormError, MAX_IMAGE, _email, _json, _now, _sha, _time
from real_journey import _result_creator, relationship_proven


def register_compat(app, settings, repository, store, helpers):
    bp = Blueprint("v5_original_form_compat", __name__, url_prefix="/cadastro/compat")
    mapping = load_mapping()
    fields = {field["id"]: field for field in mapping["fields"]}
    version = mapping["form_version"]
    authenticate, body = helpers["authenticate"], helpers["body"]
    with store.db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS v5_form_drafts (
            form_id TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0,
            step INTEGER NOT NULL DEFAULT 0,answers_json TEXT NOT NULL DEFAULT '{}',
            last_hash TEXT,agency_handle TEXT,initial_email_hash TEXT,updated_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS v5_form_relationship_checks (
            form_id TEXT PRIMARY KEY REFERENCES v5_forms(form_id) ON DELETE CASCADE,
            creator TEXT NOT NULL,operation_key TEXT NOT NULL,
            created_at TEXT NOT NULL)""")

    @bp.errorhandler(FormError)
    def error(exc):
        messages = {
            "form_unauthorized": "Este link não é válido. Volte ao atendimento para receber seu formulário.",
            "form_expired": "Este formulário venceu. Volte ao atendimento pelo WhatsApp.",
            "form_cycle_inactive": "Este atendimento foi encerrado. Volte ao WhatsApp.",
            "real_relationship_not_proven": "Confirme seu vínculo com a Amplify no início deste formulário antes de continuar.",
            "draft_conflict": "Existe uma versão mais recente deste cadastro. Atualize a página para conferir.",
            "email_not_verified": "Confirme o e-mail informado antes de continuar.",
            "email_already_bound": "O envio anterior precisa ser conferido antes de trocar o e-mail.",
            "submission_requires_reconciliation": "Ainda não foi possível confirmar o recebimento. Não reenvie: o atendimento fará a conferência.",
            "phone_outside_pilot": "Use o mesmo WhatsApp deste atendimento.",
            "tiktok_profile_changed": "Use o perfil do TikTok validado neste atendimento.",
            "initial_validation_required": "Confira seus dados e confirme seu e-mail na primeira etapa.",
            "agency_gate_required": "Confirme primeiro seu perfil do TikTok na abertura do cadastro.",
            "form_already_submitted": "Este cadastro já foi recebido.",
        }
        value = {"erro": messages.get(exc.code, "Confira os dados informados e tente novamente."), "code": exc.code}
        if exc.field:
            value["field"] = exc.field
        return jsonify(value), exc.status

    bp.after_request(helpers["private_headers"])

    def locked(row):
        locks = current_app.extensions.setdefault("v5_conversation_locks", {})
        return locks.setdefault(row["conversation_key"], threading.RLock())

    def draft(db, row):
        db.execute("INSERT OR IGNORE INTO v5_form_drafts(form_id,updated_at) VALUES(?,?)",
                   (row["form_id"], _now().isoformat()))
        return dict(db.execute("SELECT * FROM v5_form_drafts WHERE form_id=?", (row["form_id"],)).fetchone())

    def mutable(row):
        if row["status"] != "draft":
            raise FormError("form_already_submitted" if row["status"] == "completed"
                            else "submission_requires_reconciliation", 409)

    def expected_handle(row):
        state = repository.load_session(row["conversation_key"])
        expected = _result_creator((state.get("cycle") or {}).get("facts", {}).get("tiktok_declarado"))
        if not expected:
            raise FormError("tiktok_profile_changed", 409, "tiktok")
        return state, expected

    def profile(row, value, *, require_proof=True):
        state, expected = expected_handle(row)
        if _result_creator(value) != expected:
            raise FormError("tiktok_profile_changed", 409, "tiktok")
        # This public-form adapter is a real linked journey, never a declaration
        # based gate or a way to promote a simulated cycle into a real one.
        if require_proof:
            helpers["require_relationship"](row, state)
        return expected

    def scoped_identity(row, answers, *, require=False):
        if "tiktok" in answers:
            profile(row, answers["tiktok"])
        elif require:
            raise FormError("invalid_answers", field="tiktok")
        phone = answers.get("whatsapp")
        if (phone is not None or require) and _sha(normalize_phone(phone) or "") != row["phone_hash"]:
            raise FormError("phone_outside_pilot", 403, "whatsapp")

    def checked_email(row, value):
        email = _email(value)
        if not row["verified_at"] or not hmac.compare_digest(row["otp_email_hash"] or "", _sha(email)):
            raise FormError("email_not_verified", 403, "email")
        return email

    def partial_answers(row, answers):
        if not isinstance(answers, dict) or answers.keys() - fields.keys():
            raise FormError("invalid_answers")
        scoped_identity(row, answers)
        for key, value in answers.items():
            if value is None or value == "" or value == []:
                continue
            field = fields[key]
            if field["type"] == "file":
                if (not isinstance(value, dict) or value.keys() != {"receipt"}
                        or not isinstance(value["receipt"], str) or len(value["receipt"]) != 43):
                    raise FormError("attachment_invalid", field=key)
                with store.db() as db:
                    present = db.execute("SELECT 1 FROM v5_form_files WHERE form_id=? AND field=? AND receipt_hash=?",
                                         (row["form_id"], key, _sha(value["receipt"]))).fetchone()
                if not present:
                    raise FormError("attachment_invalid", field=key)
            else:
                try:
                    _convert(field, value, {}, _now())
                except MappingError as exc:
                    raise FormError(exc.code, field=exc.field) from None
        return answers

    def payload_shape(value, final=False):
        keys = {"version", "revision", "step", "answers"} | ({"consent"} if final else set())
        if (value.keys() != keys or value.get("version") != version
                or type(value.get("revision")) is not int or value["revision"] < 0
                or type(value.get("step")) is not int or not 0 <= value["step"] < 6):
            raise FormError("invalid_draft")
        return value

    def agency_gate(row, item, handle):
        state = repository.load_session(row["conversation_key"])
        if helpers["relationship_in_form"](state):
            helpers["require_relationship"](row, state)
            receipt = (state.get("cycle") or {}).get("real_operations", {}).get("relationship") or {}
            effect = state.get("effects", {}).get(receipt.get("job_id")) or {}
            with store.db() as db:
                check = db.execute("SELECT * FROM v5_form_relationship_checks WHERE form_id=?",
                                   (row["form_id"],)).fetchone()
            digest = _sha(state['cycle']['id'] + ':' + handle + ':' + check["operation_key"]) if check else None
            if (not check or check["creator"] != handle
                    or digest != effect.get("payload", {}).get("form_operation_key")):
                raise FormError("agency_gate_required", 409)
        elif item["agency_handle"] != handle:
            raise FormError("agency_gate_required", 409)

    def ready_to_advance(row, item, answers):
        agency_gate(row, item, profile(row, answers.get("tiktok")))
        scoped_identity(row, answers, require=True)
        email = checked_email(row, answers.get("email"))
        if item["initial_email_hash"] != _sha(email):
            raise FormError("initial_validation_required", 409)

    def outcome(row):
        # A form receipt is not proof of Circle invitation, category or access.
        return {"status": "cadastro_recebido"} if row["status"] == "completed" else None

    @bp.get("/contexto")
    def context():
        token, row = authenticate(completed=True)
        native = helpers["context"]().get_json()
        with store.db() as db:
            item = draft(db, row)
        value = {"version": version, "token": token, "revision": item["revision"], "step": item["step"],
                 "prefill": native["prefill"], "answers": json.loads(item["answers_json"]),
                 "submitted": row["status"] == "completed", "cycle_bound": True, "resume_key": row["form_id"]}
        if row["status"] == "completed":
            value["outcome"] = outcome(row)
        elif row["status"] == "outcome_unknown":
            raise FormError("submission_requires_reconciliation", 409)
        return jsonify(value)

    def relationship_result(row, state, handle, operation_key, *, start):
        callback = current_app.extensions.get("v5_verify_form_relationship")
        if not callable(callback):
            return {"status": "conferencia", "reason": "verificacao_indisponivel"}
        try:
            scope = ({'form_conversation': row['conversation_key']}
                     if getattr(callback, 'accepts_form_conversation', False) is True else {})
            result = callback(state, None, creator=handle, operation_key=operation_key,
                              now=_now(), start=start, **scope)
        except Exception:
            # A failed read is never a confirmed relationship. Keep the key so
            # a GET can reconcile it without another automatic POST.
            return {"status": "conferencia", "reason": "verificacao_indisponivel"}
        status = result.get("status") if isinstance(result, dict) else None
        if status == "linked":
            latest = helpers["require_relationship"](row)
            receipt = (latest.get("cycle") or {}).get("real_operations", {}).get("relationship") or {}
            effect = latest.get("effects", {}).get(receipt.get("job_id")) or {}
            digest = _sha(latest['cycle']['id'] + ':' + handle + ':' + operation_key)
            if effect.get("payload", {}).get("form_operation_key") != digest:
                raise FormError("real_relationship_not_proven", 409)
            if start:
                with store.db() as db:
                    draft(db, row)
                    db.execute("UPDATE v5_form_drafts SET agency_handle=?,updated_at=? WHERE form_id=?",
                               (handle, _now().isoformat(), row["form_id"]))
            return {"status": "aprovada"}
        if status in {"queued", "running", "result_ready"}:
            return {"status": "conferencia", "reason": "verificacao_em_andamento", "retry_after_seconds": 3}
        if status in {"pending", "not_found"}:
            return {"status": "aguardando_vinculo", "reason": "agenciamento_nao_confirmado"}
        return {"status": "conferencia", "reason": "verificacao_indisponivel"}

    @bp.route("/agenciamento", methods=["POST", "GET"])
    def agency():
        _, row = authenticate()
        mutable(row)
        if request.args:
            raise FormError("invalid_answers")
        state, expected = expected_handle(row)
        if not helpers["relationship_in_form"](state):
            if request.method == "GET":
                raise FormError("invalid_answers", 405)
            value = body()
            if value.keys() != {"tiktok"}:
                raise FormError("invalid_answers")
            handle = profile(row, value["tiktok"])
            with store.db() as db:
                draft(db, row)
                db.execute("UPDATE v5_form_drafts SET agency_handle=?,updated_at=? WHERE form_id=?",
                           (handle, _now().isoformat(), row["form_id"]))
            return jsonify(status="aprovada")
        with locked(row):
            if request.method == "POST":
                value = body()
                if value.keys() != {"tiktok"}:
                    raise FormError("invalid_answers")
                handle = profile(row, value["tiktok"], require_proof=False)
            else:
                handle = expected
            with store.db() as db:
                previous = db.execute("SELECT * FROM v5_form_relationship_checks WHERE form_id=?",
                                      (row["form_id"],)).fetchone()
            if request.method == "GET":
                if not previous or previous["creator"] != handle:
                    return jsonify(status="conferencia", reason="verificacao_nao_iniciada")
                return jsonify(relationship_result(row, state, handle, previous["operation_key"], start=False))
            if previous and previous["creator"] == handle:
                existing = relationship_result(row, state, handle, previous["operation_key"], start=False)
                if existing.get("reason") == "verificacao_em_andamento" or existing.get("status") == "aprovada":
                    return jsonify(existing)
            operation_key = "form:" + row["form_id"] + ":relationship:" + uuid4().hex
            with store.db() as db:
                db.execute("INSERT INTO v5_form_relationship_checks(form_id,creator,operation_key,created_at) VALUES(?,?,?,?) "
                           "ON CONFLICT(form_id) DO UPDATE SET creator=excluded.creator,operation_key=excluded.operation_key,created_at=excluded.created_at",
                           (row["form_id"], handle, operation_key, _now().isoformat()))
            return jsonify(relationship_result(row, state, handle, operation_key, start=True))

    @bp.route("/respostas", methods=["PUT", "POST"])
    def answers():
        token, row = authenticate(completed=request.method == "POST")
        value = payload_shape(body(), final=request.method == "POST")
        with locked(row):
            row = store.row(token)
            with store.db() as db:
                item = draft(db, row)
            if request.method == "POST":
                # The existing final owner fences both a completed replay and an
                # uncertain first POST by its durable exact-payload digest.
                if row["payload_hash"] is None:
                    mutable(row)
                    if value["revision"] != item["revision"]:
                        raise FormError("draft_conflict", 409)
                    ready_to_advance(row, item, value["answers"])
                response = current_app.make_response(helpers["submit"](token))
                if response.status_code >= 400:
                    return response
                latest = store.row(token)
                if latest["status"] != "completed":
                    raise FormError("submission_requires_reconciliation", 409)
                return jsonify(submitted=True, revision=item["revision"], outcome=outcome(latest))
            mutable(row)
            clean = partial_answers(row, value["answers"])
            if helpers["relationship_in_form"](repository.load_session(row["conversation_key"])):
                agency_gate(row, item, profile(row, clean.get("tiktok")))
            elif not item["agency_handle"]:
                raise FormError("agency_gate_required", 409)
            if value["step"] > 0:
                ready_to_advance(row, item, clean)
            digest = _sha(_json(value))
            with store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                current = draft(db, row)
                if value["revision"] != current["revision"]:
                    if value["revision"] == current["revision"] - 1 and digest == current["last_hash"]:
                        return jsonify(revision=current["revision"], step=current["step"], submitted=False)
                    raise FormError("draft_conflict", 409)
                if "email" in clean and clean["email"]:
                    email_hash = _sha(_email(clean["email"]))
                    if row["otp_email_hash"] and email_hash != row["otp_email_hash"]:
                        db.execute("UPDATE v5_forms SET verified_at=NULL,confirmation_reference=NULL WHERE form_id=?", (row["form_id"],))
                        db.execute("UPDATE v5_form_drafts SET initial_email_hash=NULL WHERE form_id=?", (row["form_id"],))
                revision = current["revision"] + 1
                db.execute("UPDATE v5_form_drafts SET revision=?,step=?,answers_json=?,last_hash=?,updated_at=? WHERE form_id=?",
                           (revision, value["step"], _json(clean), digest, _now().isoformat(), row["form_id"]))
            return jsonify(revision=revision, step=value["step"], submitted=False)

    @bp.post("/validacao-inicial")
    def initial():
        _, row = authenticate()
        mutable(row)
        value = body()
        if value.keys() != {"nome", "email", "whatsapp", "tiktok"}:
            raise FormError("invalid_answers")
        partial_answers(row, value)
        scoped_identity(row, value, require=True)
        if not isinstance(value["nome"], str) or not value["nome"].strip():
            raise FormError("invalid_answers", field="nome")
        email = checked_email(row, value["email"])
        with store.db() as db:
            item = draft(db, row)
            agency_gate(row, item, profile(row, value["tiktok"]))
            db.execute("UPDATE v5_form_drafts SET initial_email_hash=?,updated_at=? WHERE form_id=?",
                       (_sha(email), _now().isoformat(), row["form_id"]))
        return jsonify(status="aprovada")

    def email_state(row, email):
        same = row["otp_email_hash"] == _sha(email)
        verified = same and bool(row["verified_at"])
        remaining = max(0, int((_time(row["otp_expires_at"]) - _now()).total_seconds())) if same and row["otp_expires_at"] else 0
        if verified:
            status = "verificado"
        elif not same or not row["otp_operation"]:
            status = "nao_solicitado"
        elif row["otp_tries"] >= 5:
            status = "tentativas_esgotadas"
        elif remaining == 0:
            status = "expirado"
        else:
            status = "enviado" if row["otp_status"] == "accepted" else "incerto"
        return {"required": True, "verified": verified, "status": status, "retry_after": remaining if not verified else 0}

    @bp.post("/email/estado")
    def email_status():
        _, row = authenticate(completed=True)
        return jsonify(email_state(row, _email(body().get("email"))))

    @bp.post("/email/solicitar")
    @bp.post("/email/enviar")
    def email_send():
        token, row = authenticate()
        mutable(row)
        email = _email(body().get("email"))
        response = current_app.make_response(helpers["send_otp"](allow_resend=True, allow_email_change=True))
        if response.status_code >= 400:
            return response
        return jsonify(email_state(store.row(token), email))

    @bp.post("/email/confirmar")
    def email_confirm():
        token, row = authenticate()
        mutable(row)
        email = _email(body().get("email"))
        response = current_app.make_response(helpers["verify_otp"]())
        if response.status_code >= 400:
            if response.get_json().get("code") == "invalid_code":
                return jsonify(required=True, verified=False, status="codigo_incorreto", retry_after=0)
            return response
        return jsonify(email_state(store.row(token), email))

    @bp.post("/anexos")
    def upload():
        _, row = authenticate()
        mutable(row)
        request.max_content_length = MAX_IMAGE + 128_000
        raw = request.get_data(cache=False)
        response = current_app.make_response(helpers["upload"](field_name=request.args.get("campo"), uploaded_bytes=raw))
        if response.status_code >= 400:
            return response
        # The original UI stores this entire object as an answer. The reviewed
        # full mapper accepts exactly one opaque receipt, not client metadata.
        return jsonify(receipt=response.get_json()["receipt"]), 201

    @bp.post("/imagem")
    def image():
        _, row = authenticate(completed=True)
        value = body()
        field, receipt = value.get("field"), value.get("receipt")
        if (field not in {"foto_perfil", "print_gmv"} or not isinstance(receipt, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", receipt)):
            raise FormError("attachment_invalid")
        with store.db() as db:
            item = db.execute("SELECT * FROM v5_form_files WHERE form_id=? AND field=? AND receipt_hash=?",
                              (row["form_id"], field, _sha(receipt))).fetchone()
        if not item:
            raise FormError("attachment_invalid", 404, field)
        target = Path(item["path"]).resolve()
        if (not target.is_relative_to(helpers["state_dir"]) or not target.is_file()
                or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]):
            raise FormError("attachment_integrity_failed", 409, field)
        return send_file(target, mimetype="image/jpeg", conditional=False, max_age=0)

    app.register_blueprint(bp)
