"""Private, one-contact form with durable OTP and final-submission receipts.

No environment is read and no mail/database provider is instantiated here.
Inject v5_email_sender and v5_data_gateway into the Flask app extensions.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.headerregistry import Address
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from flask import Blueprint, current_app, jsonify, redirect, render_template_string, request

from contracts import allow_inbound, normalize_phone, pilot_phone, pilot_phones
from data import MappingError, map_submission, submission_id


MAX_IMAGE = 5 * 1024 * 1024
_EMAIL = re.compile(r"[^\s@]{1,64}@[^\s@.]+(?:\.[^\s@.]+)+\Z")


class FormError(ValueError):
    def __init__(self, code, status=400, field=None):
        self.code, self.status, self.field = code, status, field
        super().__init__(code)


def _get(settings, key, default=None):
    return settings.get(key, default) if isinstance(settings, dict) else getattr(settings, key, default)


def _real_enabled(settings, state):
    return (_get(settings, "tiktok_mode") == "real" or _get(settings, "real_mode", False) is True
            or state.get("real_mode") is True)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _phone_hashes(gate):
    """Hashes of every authorized pilot phone; a form is bound to exactly one."""
    return {_sha(normalize_phone(phone)) for phone in pilot_phones(gate) if normalize_phone(phone)}


def _row_phone(gate, row):
    """The configured phone whose hash owns this form, or None."""
    matches = [phone for phone in pilot_phones(gate) if normalize_phone(phone) and _sha(normalize_phone(phone)) == row["phone_hash"]]
    return matches[0] if len(matches) == 1 else None


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise FormError("invalid_clock", 503)
    return parsed.astimezone(timezone.utc)


def _now():
    clock = current_app.extensions.get("v5_form_clock")
    return _time(clock() if clock else datetime.now(timezone.utc))


def _email(value):
    if (not isinstance(value, str) or len(value.strip()) > 254 or not _EMAIL.fullmatch(value.strip())
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or any(character in value for character in ',;<>"\\')):
        raise FormError("invalid_email", field="email")
    normalized = value.strip().lower()
    try:
        address = Address(addr_spec=normalized)
        if not address.username or not address.domain or address.addr_spec != normalized:
            raise ValueError("not a single mailbox")
    except (ValueError, IndexError):
        raise FormError("invalid_email", field="email") from None
    return normalized


def _attendance_observations(state, received_at, account_id):
    """Forward sourced session observations, never infer them from form answers."""
    observations = state.get("observations") if isinstance(state, dict) else None
    if not isinstance(observations, dict):
        return {}
    received = _time(received_at)
    reference = re.compile(r"chatwoot:" + re.escape(str(account_id)) + r":[1-9][0-9]{0,19}\Z")
    result = {}
    for name, source in (("first_inbound", "chatwoot_webhook"), ("origin", "declaracao_pessoa")):
        value = observations.get(name)
        keys = {"at", "source", "reference"} | ({"value"} if name == "origin" else set())
        if (not isinstance(value, dict) or value.keys() != keys or value.get("source") != source
                or not isinstance(value.get("reference"), str) or not reference.fullmatch(value["reference"])
                or not isinstance(value.get("at"), str) or len(value["at"]) > 40
                or (name == "origin" and value.get("value") not in {"anuncio", "indicacao", "outro"})):
            continue
        try:
            observed_at = _time(value["at"])
        except (FormError, ValueError, TypeError, OverflowError):
            continue
        if observed_at <= received:
            result[name] = {**value, "at": observed_at.isoformat()}
    return result


class FormStore:
    def __init__(self, path):
        self.path = Path(path)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS v5_forms (
                    token_hash TEXT PRIMARY KEY, form_id TEXT UNIQUE NOT NULL, creator_id TEXT NOT NULL,
                    event_id TEXT NOT NULL, conversation_key TEXT NOT NULL, session_id TEXT NOT NULL,
                    cycle_id TEXT NOT NULL, account_id TEXT NOT NULL, inbox_id TEXT NOT NULL,
                    phone_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft', payload_hash TEXT, context_json TEXT,
                    receipt_json TEXT, receipt_email_status TEXT, receipt_email_operation TEXT NOT NULL,
                    otp_hash TEXT, otp_nonce TEXT, otp_email_hash TEXT, otp_expires_at TEXT,
                    otp_tries INTEGER NOT NULL DEFAULT 0, otp_status TEXT, otp_operation TEXT,
                    verified_at TEXT, confirmation_reference TEXT,
                    UNIQUE(session_id,cycle_id,conversation_key));
                CREATE TABLE IF NOT EXISTS v5_form_files (
                    receipt_hash TEXT PRIMARY KEY, form_id TEXT NOT NULL, field TEXT NOT NULL,
                    reference TEXT UNIQUE NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS v5_form_otp_operations (
                    operation_id TEXT PRIMARY KEY,form_id TEXT NOT NULL,email_hash TEXT NOT NULL,
                    status TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def row(self, token):
        with self.db() as db:
            row = db.execute("SELECT * FROM v5_forms WHERE token_hash=?", (_sha(token),)).fetchone()
            return dict(row) if row else None


def register_forms(app, settings, repository):
    """Register the form and expose the transport's durable form-link factory."""
    store = FormStore(repository.path)
    gate = _get(settings, "gate", {})
    gate = gate if isinstance(gate, dict) else {}
    state_dir = Path(_get(settings, "state_dir", Path(repository.path).parent)).resolve()
    secret = _get(settings, "form_secret")
    public_url = str(_get(settings, "public_url", "")).rstrip("/")
    form_public_url = str(_get(settings, "form_public_url", "")).rstrip("/")
    original_form = form_public_url == "https://amplify-cadastro.up.railway.app/cadastro/ensaio"
    bp = Blueprint("v5_forms", __name__)
    app.extensions["v5_forms_store"] = store

    def active():
        if not isinstance(secret, str) or len(secret) < 32 or not normalize_phone(gate.get("phone")) or gate.get("enabled") is not True:
            raise FormError("form_unavailable", 503)
        parsed = urlsplit(public_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise FormError("form_unavailable", 503)
        if form_public_url and not original_form:
            raise FormError("form_unavailable", 503)

    def sign(value):
        return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()

    def form_token(form_id):
        raw = hmac.new(secret.encode(), ("form:" + form_id).encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def form_link(token):
        return form_public_url + "#s=" + token if original_form else public_url + "/cadastro/" + token

    def creator_hint(state, event):
        """Preserve an already issued form's identity; never silently re-key it."""
        conv = f"chatwoot:{event['account_id']}:{event['conversation_id']}"
        cycle = state.get("cycle") or {}
        with store.db() as db:
            rows = db.execute("SELECT creator_id FROM v5_forms WHERE conversation_key=? AND session_id=? AND cycle_id=?",
                              (conv, state.get("session_id"), cycle.get("id"))).fetchall()
        values = {row["creator_id"] for row in rows}
        if len(values) > 1:
            raise FormError("form_identity_conflict", 409)
        return next(iter(values), None)

    app.extensions["v5_form_creator_hint"] = creator_hint

    def relationship_in_form(state):
        return (_get(settings, "relationship_check_in_form", False) is True
                and (state.get("cycle") or {}).get("relationship_check_in_form") is True)

    def require_relationship(row, state=None):
        """Final authority stays server-side; a form answer never proves a link."""
        state = repository.load_session(row["conversation_key"]) if state is None else state
        cycle = state.get("cycle") or {}
        if not _real_enabled(settings, state):
            return state
        from real_journey import relationship_proven
        if (cycle.get("mode") != "real" or cycle.get("id") != row["cycle_id"]
                or not relationship_proven(state, now=_now(), maximum_age_seconds=24 * 3600)):
            raise FormError("real_relationship_not_proven", 409)
        if relationship_in_form(state):
            relationship = (cycle.get("real_operations") or {}).get("relationship") or {}
            effect = (state.get("effects") or {}).get(relationship.get("job_id")) or {}
            proof = state.get("contact_sync_proof") or {}
            expected = {"creator_id": row["creator_id"], "atendimento_id": row["cycle_id"],
                        "event_id": proof.get("event_id"), "revision": state.get("revision")}
            operation = repository.get_operation(str(proof.get("event_id")) + ":contact:" + str(state.get("revision")))
            if (state.get("creator_id") != row["creator_id"] or effect.get("payload", {}).get("source") != "form"
                    or not isinstance(effect.get("payload", {}).get("form_operation_key"), str)
                    or not effect["payload"]["form_operation_key"] or not proof.get("event_id")
                    or type(state.get("revision")) is not int or state["revision"] < 1
                    or not operation or operation.get("kind") != "contact_sync"
                    or operation.get("status") != "completed"
                    or not isinstance(operation.get("result"), dict)
                    or any(proof.get(key) != value or operation["result"].get(key) != value
                           for key, value in expected.items())):
                raise FormError("real_relationship_not_proven", 409)
        return state

    def link_factory(state, effect, event):
        active()
        cycle = state.get("cycle") or {}
        if (not allow_inbound(gate, event) or effect.get("type") != "generate_form_link"
                or cycle.get("status") != "open" or cycle.get("phase") != "form"
                or effect.get("cycle_id") != cycle.get("id") or not state.get("session_id")):
            raise FormError("form_context_invalid", 409)
        at = _now()
        if _real_enabled(settings, state):
            if relationship_in_form(state):
                from real_journey import form_entry_allowed
                if not form_entry_allowed(state, effect, now=at):
                    raise FormError("form_context_invalid", 409)
            else:
                from real_journey import relationship_proven
                if (cycle.get("mode") != "real" or effect.get("payload", {}).get("verification_mode") != "real"
                        or not relationship_proven(state, now=at)
                        or effect.get("payload", {}).get("relationship_job_id") !=
                           cycle.get("real_operations", {}).get("relationship", {}).get("job_id")):
                    raise FormError("real_relationship_not_proven", 409)
        if at >= _time(cycle["expires_at"]):
            raise FormError("form_expired", 410)
        conv = f"chatwoot:{event['account_id']}:{event['conversation_id']}"
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM v5_forms WHERE session_id=? AND cycle_id=? AND conversation_key=?",
                             (state["session_id"], cycle["id"], conv)).fetchone()
            if row:
                if state.get("creator_id") and state["creator_id"] != row["creator_id"]:
                    raise FormError("form_identity_conflict", 409)
                return form_link(form_token(row["form_id"]))
            creator_id = state.get("creator_id")
            if creator_id is not None:
                try:
                    if str(UUID(creator_id)) != creator_id or UUID(creator_id).int == 0:
                        raise ValueError()
                except (ValueError, TypeError, AttributeError):
                    raise FormError("form_identity_invalid", 409) from None
            elif _get(settings, "contact_sync_enabled", False) is True:
                raise FormError("form_identity_unconfirmed", 409)
            else:
                creator_id = str(uuid4())
            form_id = str(uuid4())
            token = form_token(form_id)
            db.execute("""INSERT INTO v5_forms(token_hash,form_id,creator_id,event_id,conversation_key,session_id,cycle_id,
                       account_id,inbox_id,phone_hash,created_at,expires_at,receipt_email_operation)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (_sha(token), form_id, creator_id, submission_id(creator_id, form_id), conv, state["session_id"],
                        cycle["id"], str(event["account_id"]), str(event["inbox_id"]), _sha(normalize_phone(pilot_phone(gate, event.get("sender_phone")))),
                        at.isoformat(), (at + timedelta(hours=24)).isoformat(), str(uuid4())))
        return form_link(token)

    app.extensions["v5_form_link_factory"] = link_factory

    def authenticate(path_token=None, *, completed=False):
        active()
        header = request.headers.get("Authorization", "")
        prefix, _, token = header.partition(" ")
        if prefix.lower() != "bearer" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise FormError("form_unauthorized", 401)
        if path_token is not None and not hmac.compare_digest(path_token, token):
            raise FormError("form_unauthorized", 401)
        row = store.row(token)
        if not row:
            raise FormError("form_unauthorized", 401)
        validate_row(row, completed=completed)
        origin = request.headers.get("Origin")
        expected = urlsplit(public_url)
        allowed_origin = f"{expected.scheme}://{expected.netloc}"
        allowed_origins = {allowed_origin}
        if original_form:
            allowed_origins.add("https://amplify-cadastro.up.railway.app")
        if origin and origin not in allowed_origins:
            raise FormError("origin_invalid", 403)
        return token, row

    def validate_row(row, *, completed=False):
        if (row["account_id"] != str(gate.get("account_id")) or row["inbox_id"] != str(gate.get("inbox_id"))
                or row["phone_hash"] not in _phone_hashes(gate)):
            raise FormError("form_scope_changed", 403)
        if _now() >= _time(row["expires_at"]):
            raise FormError("form_expired", 410)
        state = repository.load_session(row["conversation_key"])
        cycle = state.get("cycle") or {}
        if (state.get("session_id") != row["session_id"] or cycle.get("id") != row["cycle_id"]
                or _now() >= _time(cycle["expires_at"])):
            raise FormError("form_cycle_inactive", 410)
        if _real_enabled(settings, state) and not relationship_in_form(state):
            require_relationship(row, state)
        elif _real_enabled(settings, state) and (cycle.get("mode") != "real" or state.get("creator_id") != row["creator_id"]):
            raise FormError("form_identity_conflict", 409)
        if completed and row["status"] == "completed" and cycle.get("status") == "closed" and cycle.get("reason") == "validated_form":
            return
        if cycle.get("status") != "open" or cycle.get("phase") != "form":
            raise FormError("form_cycle_inactive", 410)

    def relink_existing():
        """Change only an existing exact V5 link's presentation for this pilot.

        Called explicitly by the bootstrap in this app's context. No form, cycle,
        event, expiry, counter or provider operation is created by this helper.
        """
        if not original_form:
            return {"updated": 0, "skipped": 0}
        active()
        with store.db() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT * FROM v5_forms WHERE account_id=? AND inbox_id=? AND status='draft'",
                (str(gate.get("account_id")), str(gate.get("inbox_id"))))
                if row["phone_hash"] in _phone_hashes(gate)]
        counts = {"updated": 0, "skipped": 0}
        locks = current_app.extensions.setdefault("v5_conversation_locks", {})
        for row in rows:
            with locks.setdefault(row["conversation_key"], threading.RLock()):
                try:
                    validate_row(row)
                except (FormError, KeyError, ValueError):
                    counts["skipped"] += 1
                    continue
                state = repository.load_session(row["conversation_key"])
                token = form_token(row["form_id"])
                old_link = public_url + "/cadastro/" + token
                if state.get("cycle", {}).get("form_url") != old_link:
                    counts["skipped"] += 1
                    continue
                state["cycle"]["form_url"] = form_link(token)
                repository.save_session(row["conversation_key"], state)
                counts["updated"] += 1
        return counts

    app.extensions["v5_form_relink_existing"] = relink_existing

    def body():
        if not request.is_json:
            raise FormError("json_required", 415)
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise FormError("invalid_json")
        return value

    @bp.errorhandler(FormError)
    def error(error):
        response = {"status": "rejected", "code": error.code}
        if error.field:
            response["field"] = error.field
        return jsonify(response), error.status

    @bp.after_request
    def private_headers(response):
        response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"})
        return response

    @bp.get("/cadastro/<token>")
    def page(token):
        active()
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise FormError("form_unauthorized", 401)
        row = store.row(token)
        if not row:
            raise FormError("form_unauthorized", 401)
        validate_row(row, completed=True)
        if original_form:
            return redirect(form_link(token), code=303)
        nonce = secrets.token_urlsafe(18)
        response = current_app.make_response(render_template_string(_HTML, nonce=nonce))
        response.headers["Content-Security-Policy"] = ("default-src 'self'; script-src 'nonce-" + nonce +
            "'; style-src 'nonce-" + nonce + "'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    @bp.get("/cadastro/api/contexto")
    def context():
        _, row = authenticate(completed=True)
        contract = json.loads(Path(__file__).with_name("data").joinpath("cadastro_contract.json").read_text(encoding="utf-8-sig"))
        state = repository.load_session(row["conversation_key"])
        facts = (state.get("cycle") or {}).get("facts") or {}
        return jsonify(contract=contract, status=row["status"], expires_at=row["expires_at"],
                       email_verified=bool(row["verified_at"]), prefill={"whatsapp": _row_phone(gate, row) or "",
                       "tiktok": facts.get("tiktok_declarado", ""), "nome": facts.get("nome_declarado", ""),
                       "canal_origem": ("Conheci no instagram" if facts.get("origem_canal_declarado") == "instagram" else
                                        "Conheci no TikTok" if facts.get("origem_canal_declarado") == "tiktok" else
                                        {"indicacao": "Me indicaram", "anuncio": "Outro jeito", "outro": "Outro jeito"}.get(facts.get("origem_declarada"), "")),
                       "origem_outro": "Anúncio" if facts.get("origem_declarada") == "anuncio" else ""})

    @bp.post("/cadastro/api/email/enviar")
    def send_otp(*, allow_resend=False, allow_email_change=False):
        token, row = authenticate()
        payload = body()
        email = _email(payload.get("email"))
        sender = current_app.extensions.get("v5_email_sender")
        if not callable(getattr(sender, "send_otp", None)):
            raise FormError("email_unavailable", 503)
        at, code, nonce = _now(), f"{secrets.randbelow(1_000_000):06d}", str(uuid4())
        operation_id = str(uuid4())
        email_hash = _sha(email)
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = dict(db.execute("SELECT * FROM v5_forms WHERE token_hash=?", (_sha(token),)).fetchone())
            if existing["otp_operation"]:
                # A lost ACK never sends again. The received code still proves ownership.
                same_email = existing["otp_email_hash"] == email_hash
                resend = allow_resend or payload.get("resend") is True
                if (not same_email and (not resend or (existing["verified_at"] and not allow_email_change)
                                        or existing["otp_status"] == "outcome_unknown")):
                    raise FormError("email_already_bound", 409, "email")
                can_resend = (resend and (not existing["verified_at"] or (allow_email_change and not same_email))
                              and existing["otp_status"] in {"accepted", "failed", "verified"}
                              and (not same_email or at >= _time(existing["otp_expires_at"])))
                if not can_resend:
                    return jsonify(status=existing["otp_status"], expires_at=existing["otp_expires_at"],
                                   verified=bool(existing["verified_at"]), reused=True), 202
            count = db.execute("SELECT count(*) FROM v5_form_otp_operations WHERE form_id=?", (row["form_id"],)).fetchone()[0]
            if count >= 3:
                raise FormError("email_send_limit", 429)
            db.execute("INSERT INTO v5_form_otp_operations VALUES(?,?,?,?,?,?)",
                       (operation_id,row["form_id"],email_hash,"outcome_unknown",at.isoformat(),
                        (at+timedelta(minutes=10)).isoformat()))
            db.execute("""UPDATE v5_forms SET otp_hash=?,otp_nonce=?,otp_email_hash=?,otp_expires_at=?,otp_tries=0,
                       otp_status='outcome_unknown',otp_operation=?,verified_at=NULL,confirmation_reference=NULL WHERE token_hash=?""",
                       (sign("otp:" + row["form_id"] + ":" + nonce + ":" + code), nonce, email_hash,
                        (at + timedelta(minutes=10)).isoformat(), operation_id, _sha(token)))
        try:
            result = sender.send_otp(email, code, operation_id)
            status = result.get("status") if isinstance(result, dict) else "outcome_unknown"
            if status not in {"accepted", "failed", "outcome_unknown"}:
                status = "outcome_unknown"
        except Exception:
            status = "outcome_unknown"
        with store.db() as db:
            db.execute("UPDATE v5_form_otp_operations SET status=? WHERE operation_id=?", (status, operation_id))
            db.execute("UPDATE v5_forms SET otp_status=? WHERE token_hash=? AND otp_operation=? AND verified_at IS NULL",
                       (status, _sha(token), operation_id))
        return jsonify(status=status, expires_at=(at + timedelta(minutes=10)).isoformat()), 202 if status != "failed" else 503

    @bp.post("/cadastro/api/email/verificar")
    def verify_otp():
        token, _ = authenticate()
        payload = body()
        email, code = _email(payload.get("email")), payload.get("code")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise FormError("invalid_code", field="code")
        at = _now()
        with store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = dict(db.execute("SELECT * FROM v5_forms WHERE token_hash=?", (_sha(token),)).fetchone())
            if not row["otp_hash"]:
                raise FormError("code_not_requested", 409)
            if row["verified_at"] and row["otp_email_hash"] == _sha(email):
                return jsonify(status="verified")
            if at >= _time(row["otp_expires_at"]):
                raise FormError("code_expired", 410)
            if row["otp_tries"] >= 5:
                raise FormError("code_attempts_exhausted", 429)
            digest = sign("otp:" + row["form_id"] + ":" + row["otp_nonce"] + ":" + code)
            matches = hmac.compare_digest(row["otp_hash"], digest) and hmac.compare_digest(row["otp_email_hash"], _sha(email))
            db.execute("UPDATE v5_forms SET otp_tries=otp_tries+1 WHERE token_hash=?", (_sha(token),))
            if not matches:
                # Return rather than raise so the failed attempt is committed.
                return jsonify(status="rejected", code="invalid_code"), 400
            db.execute("UPDATE v5_forms SET verified_at=?,confirmation_reference=?,otp_status='verified' WHERE token_hash=?",
                       (at.isoformat(), "confirmation:" + str(uuid4()), _sha(token)))
        return jsonify(status="verified")

    @bp.post("/cadastro/api/anexos")
    def upload(*, field_name=None, uploaded_bytes=None):
        token, row = authenticate()
        with store.db() as db:
            if db.execute("SELECT count(*) FROM v5_form_files WHERE form_id=?", (row["form_id"],)).fetchone()[0] >= 12:
                raise FormError("attachment_upload_limit", 429)
        request.max_content_length = MAX_IMAGE + 128_000
        field = field_name if field_name is not None else request.form.get("field")
        uploaded = request.files.get("file") if uploaded_bytes is None else None
        if field not in {"foto_perfil", "print_gmv"} or (uploaded_bytes is None and not uploaded):
            raise FormError("invalid_attachment")
        raw = uploaded_bytes if uploaded_bytes is not None else uploaded.read(MAX_IMAGE + 1)
        if not raw or len(raw) > MAX_IMAGE:
            raise FormError("attachment_too_large", 413)
        try:
            from PIL import Image, ImageOps
        except ImportError:
            raise FormError("image_validation_unavailable", 503)
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 12_000_000:
                    raise ValueError("invalid image")
                image.load()
                clean = ImageOps.exif_transpose(image).convert("RGB")
                clean.thumbnail((2048, 2048))
                output = io.BytesIO()
                clean.save(output, "JPEG", quality=90)
                content = output.getvalue()
        except Exception:
            raise FormError("invalid_image", field=field)
        name, receipt = str(uuid4()) + ".jpg", secrets.token_urlsafe(32)
        folder = state_dir / "private-uploads" / row["form_id"]
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = (folder / name).resolve()
        if not target.is_relative_to(state_dir):
            raise FormError("attachment_storage_unavailable", 503)
        descriptor = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(content)
        reference = f"storage:ensaio/{row['form_id']}/{name}"
        with store.db() as db:
            db.execute("INSERT INTO v5_form_files VALUES(?,?,?,?,?,?,?)", (_sha(receipt), row["form_id"], field,
                       reference, str(target), _sha(content), _now().isoformat()))
        return jsonify(receipt=receipt, sha256=_sha(content)), 201

    def attachments_for(db, row, answers):
        result = {}
        for field in ("foto_perfil", "print_gmv"):
            value = answers.get(field)
            receipt = value.get("receipt") if isinstance(value, dict) else None
            if not isinstance(receipt, str) or len(receipt) > 512:
                raise FormError("attachment_required", field=field)
            item = db.execute("SELECT * FROM v5_form_files WHERE receipt_hash=? AND form_id=? AND field=?",
                              (_sha(receipt), row["form_id"], field)).fetchone()
            if not item:
                raise FormError("attachment_invalid", field=field)
            target = Path(item["path"]).resolve()
            if not target.is_relative_to(state_dir) or not target.is_file() or _sha(target.read_bytes()) != item["sha256"]:
                raise FormError("attachment_integrity_failed", 409, field)
            result[field] = {"reference": item["reference"], "receipt_sha256": item["receipt_hash"], "source": "upload_validado"}
        return result

    @bp.post("/cadastro/<path_token>")
    def submit(path_token):
        token, row = authenticate(path_token, completed=True)
        payload = body()
        digest = _sha(_json(payload))
        locks = current_app.extensions.setdefault("v5_conversation_locks", {})
        lock = locks.setdefault(row["conversation_key"], threading.RLock())
        with lock:
            gateway = current_app.extensions.get("v5_data_gateway")
            with store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = dict(db.execute("SELECT * FROM v5_forms WHERE token_hash=?", (_sha(token),)).fetchone())
                if row["payload_hash"]:
                    if not hmac.compare_digest(row["payload_hash"], digest):
                        raise FormError("submission_conflict", 409)
                    return jsonify(status=row["status"], receipt=json.loads(row["receipt_json"]) if row["receipt_json"] else None,
                                   receipt_email_status=row["receipt_email_status"]), 200 if row["status"] == "completed" else 202
                if not callable(getattr(gateway, "submit", None)):
                    raise FormError("data_gateway_unavailable", 503)
                validate_row(row)
                answers = payload.get("answers")
                if not isinstance(answers, dict):
                    raise FormError("invalid_answers")
                current_state = repository.load_session(row["conversation_key"])
                if _real_enabled(settings, current_state):
                    from real_journey import _result_creator
                    require_relationship(row, current_state)
                    expected = (current_state.get("cycle") or {}).get("facts", {}).get("tiktok_declarado")
                    if _result_creator(answers.get("tiktok")) != expected:
                        raise FormError("tiktok_profile_changed", 409, "tiktok")
                email = _email(answers.get("email"))
                if not normalize_phone(answers.get("whatsapp")) or _sha(normalize_phone(answers.get("whatsapp"))) != row["phone_hash"]:
                    raise FormError("phone_outside_pilot", 403, "whatsapp")
                if not row["verified_at"] or not hmac.compare_digest(row["otp_email_hash"] or "", _sha(email)):
                    raise FormError("email_not_verified", 403, "email")
                context = {"creator_id": row["creator_id"], "form_instance_id": row["form_id"], "event_id": row["event_id"],
                           "received_at": _now().isoformat(), "source": {"kind": "formulario_ensaio", "reference": "formulario:" + row["form_id"]},
                           "attachments": attachments_for(db, row, answers), "email_confirmation": {"at": row["verified_at"],
                           "source": "email_token_validado", "reference": row["confirmation_reference"], "email_sha256": row["otp_email_hash"]}}
                real_submission = _real_enabled(settings, current_state)
                if real_submission:
                    context["source"]["kind"] = "formulario_whatsapp"
                    context["execution_mode"] = "real"
                if _get(settings, "contact_sync_enabled", False) is True:
                    context["atendimento_id"] = row["cycle_id"]
                context.update(_attendance_observations(repository.load_session(row["conversation_key"]),
                                                       context["received_at"], row["account_id"]))
                try:
                    plan = map_submission(payload, context)
                except MappingError as error:
                    raise FormError(error.code, field=error.field)
                db.execute("UPDATE v5_forms SET status='outcome_unknown',payload_hash=?,context_json=? WHERE token_hash=?",
                           (digest, _json(context), _sha(token)))
            try:
                receipt = gateway.submit(plan)
                committed = (isinstance(receipt, dict) and receipt.get("status") ==
                             ("cadastro_recebido_real" if real_submission else "cadastro_recebido_ensaio")
                             and receipt.get("creator_id") == row["creator_id"]
                             and receipt.get("event_id") == row["event_id"])
            except Exception:
                receipt, committed = {"status": "outcome_unknown"}, False
            status = "completed" if committed else "outcome_unknown"
            with store.db() as db:
                db.execute("UPDATE v5_forms SET status=?,receipt_json=?,receipt_email_status=? WHERE token_hash=?",
                           (status, _json(receipt), "outcome_unknown" if committed else None, _sha(token)))
            if not committed:
                return jsonify(status="outcome_unknown", code="submission_requires_reconciliation"), 202
            # The committed receipt is durable before either the session or email is changed.
            state = repository.load_session(row["conversation_key"])
            cycle = state.get("cycle") or {}
            if cycle.get("id") == row["cycle_id"]:
                cycle.update(status="closed", reason="validated_form", closed_at=_now().isoformat(),
                             form_receipt={"creator_id": row["creator_id"], "event_id": row["event_id"]})
                state["creator_id"] = row["creator_id"]
                state["cadastro_situacao"] = "confirmado"
                repository.save_session(row["conversation_key"], state)
            sender = current_app.extensions.get("v5_email_sender")
            try:
                result = sender.send_receipt(email, receipt, row["receipt_email_operation"])
                email_status = result.get("status") if isinstance(result, dict) else "outcome_unknown"
                if email_status not in {"accepted", "failed", "outcome_unknown"}:
                    email_status = "outcome_unknown"
            except Exception:
                email_status = "outcome_unknown"
            with store.db() as db:
                db.execute("UPDATE v5_forms SET receipt_email_status=? WHERE token_hash=?", (email_status, _sha(token)))
            projector = current_app.extensions.get("v5_project_registration")
            if callable(projector):
                try:
                    projector(row, state, receipt)
                except Exception:
                    pass
            return jsonify(status="completed", receipt=receipt, receipt_email_status=email_status)

    app.register_blueprint(bp)
    if original_form:
        from forms_compat import register_compat
        register_compat(app, settings, repository, store, {
            "authenticate": authenticate, "body": body, "context": context,
            "send_otp": send_otp, "verify_otp": verify_otp, "upload": upload,
            "submit": submit, "validate_row": validate_row, "private_headers": private_headers,
            "relationship_in_form": relationship_in_form, "require_relationship": require_relationship,
            "state_dir": state_dir,
        })


_HTML = """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cadastro Amplify</title><style nonce="{{nonce}}">*{box-sizing:border-box}body{margin:0;background:#f6f4fb;color:#242038;font:16px system-ui}main{max-width:920px;margin:32px auto;padding:24px;background:white;border-radius:20px}h1{color:#6550d5}section{border-top:1px solid #ddd;padding:24px 0}.fields{display:grid;grid-template-columns:1fr 1fr;gap:18px}.field{display:flex;flex-direction:column;gap:6px}input,select,textarea,button{font:inherit;padding:11px;border:1px solid #bbb;border-radius:8px}textarea{min-height:100px}button{cursor:pointer;background:#6550d5;color:white}button:disabled{opacity:.5}.wide{grid-column:1/-1}.muted{color:#686077}#status{white-space:pre-wrap}fieldset{border:0;padding:0}label.option{display:block;padding:6px 0}.otp{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}.otp input{max-width:180px}[hidden]{display:none!important}@media(max-width:650px){main{margin:0;border-radius:0}.fields{grid-template-columns:1fr}}</style>
<main><h1>Seu cadastro na Amplify</h1><p>Preencha os dados abaixo. Confirme seu e-mail antes de concluir.</p><p id="status" role="status" aria-live="polite">Carregando seu formulário…</p><form id="form" hidden><div id="sections"></div><section><h2>Confirme seu e-mail</h2><p>O código tem validade de 10 minutos. Não compartilhe com outras pessoas.</p><div class="otp"><button id="send-code" type="button">Enviar código</button><label>Código<input id="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}"></label><button id="verify-code" type="button">Confirmar e-mail</button></div><p id="email-status" role="status"></p></section><section id="consent"></section><button id="submit" type="submit">Concluir cadastro</button></form></main>
<script nonce="{{nonce}}">"use strict";
const token=decodeURIComponent(location.pathname.split('/').pop()),headers={Authorization:'Bearer '+token};let contract,receipts={},verified=false;
const byId=id=>document.getElementById(id),message=text=>{byId('status').textContent=text};
async function api(path,options={}){const response=await fetch(path,{...options,headers:{...headers,...options.headers}});let value;try{value=await response.json()}catch{throw Error('Resposta indisponível. Atualize a página antes de tentar novamente.')}if(!response.ok){const messages={invalid_code:'Confira o código recebido.',code_expired:'O código venceu. Peça um novo código.',code_attempts_exhausted:'O limite de tentativas deste código foi atingido.',email_not_verified:'Confirme este e-mail antes de concluir.',phone_outside_pilot:'Use o mesmo WhatsApp deste atendimento.',form_expired:'Este formulário venceu. Inicie outro atendimento pelo WhatsApp.',form_cycle_inactive:'Este atendimento foi encerrado. Volte ao WhatsApp.',email_already_bound:'Use o e-mail confirmado neste cadastro.',email_send_limit:'O limite de envios de código foi atingido. Volte ao atendimento.',attachment_required:'Envie este anexo.',attachment_invalid:'Envie este anexo novamente.',invalid_image:'Escolha uma foto ou imagem válida.',email_unavailable:'O envio de e-mail está indisponível agora.'};const label=contract?.fields.find(field=>field.id===value.field)?.label;throw Error((label?label+': ':'')+(messages[value.code]||'Confira os dados informados e tente novamente.'))}return value}
function fieldValue(field){const box=byId('field-'+field.id);if(field.type==='multi_select')return [...box.querySelectorAll('input:checked')].map(input=>input.value);const input=byId('input-'+field.id);return field.type==='file'?receipts[field.id]:input.value}
function visibility(){for(const field of contract.fields){const condition=field.conditionProposed,box=byId('field-'+field.id);let show=true;if(condition){const source=contract.fields.find(item=>item.id===condition.field),value=fieldValue(source);show=!byId('field-'+source.id).hidden&&(condition.equals!==undefined?value===condition.equals:Array.isArray(value)&&value.includes(condition.includes))}box.hidden=!show;for(const input of box.querySelectorAll('input,select,textarea')){input.disabled=!show;input.required=show&&field.type!=='multi_select'}}}
function render(data){contract=data.contract;for(const section of contract.sections){const area=document.createElement('section'),title=document.createElement('h2'),description=document.createElement('p'),grid=document.createElement('div');title.textContent=section.title;description.textContent=section.subtitle;grid.className='fields';area.append(title,description,grid);for(const field of contract.fields.filter(item=>item.section===section.id)){const box=document.createElement('div'),label=document.createElement('label');box.className='field'+(['textarea','multi_select'].includes(field.type)?' wide':'');box.id='field-'+field.id;label.textContent=field.label;label.htmlFor='input-'+field.id;box.append(label);let input;if(field.type==='multi_select'){input=document.createElement('fieldset');for(const option of field.options){const line=document.createElement('label'),checkbox=document.createElement('input');line.className='option';checkbox.type='checkbox';checkbox.value=option;line.append(checkbox,document.createTextNode(' '+option));input.append(line)}}else if(field.type==='select'){input=document.createElement('select');input.append(new Option('Selecione',''));for(const option of field.options)input.append(new Option(option,option))}else if(field.type==='textarea'){input=document.createElement('textarea')}else{input=document.createElement('input');input.type={phone_number:'tel',number:'text',file:'file',date:'date',email:'email',url:'url'}[field.type]||'text';if(field.type==='file')input.accept='image/jpeg,image/png,image/webp';if(field.type==='number')input.inputMode='decimal'}input.id='input-'+field.id;input.name=field.id;if(data.prefill[field.id])input.value=data.prefill[field.id];if(field.id==='whatsapp')input.readOnly=true;input.addEventListener('change',visibility);if(field.type==='file')input.addEventListener('change',async()=>{delete receipts[field.id];const file=input.files[0];if(!file)return;const body=new FormData();body.append('field',field.id);body.append('file',file);try{message('Validando anexo…');const result=await api('/cadastro/api/anexos',{method:'POST',body});receipts[field.id]={receipt:result.receipt};message('Anexo validado.')}catch(error){input.value='';message(error.message)}});box.append(input);grid.append(box)}byId('sections').append(area)}const consent=byId('consent'),title=document.createElement('h2');title.textContent=contract.consent.title;consent.append(title);for(const text of contract.consent.paragraphs){const p=document.createElement('p');p.textContent=text;consent.append(p)}const label=document.createElement('label'),checkbox=document.createElement('input');checkbox.type='checkbox';checkbox.id='consent-accepted';checkbox.required=true;label.append(checkbox,document.createTextNode(' '+contract.consent.label));consent.append(label);visibility();byId('form').hidden=false;message('Confira todos os dados antes de concluir.');if(data.status==='completed'){byId('form').hidden=true;message('Cadastro concluído e confirmado.')}else if(data.status==='outcome_unknown'){byId('form').hidden=true;message('Sua conclusão está aguardando conferência. Não é necessário reenviar.')}}
byId('send-code').onclick=async()=>{const button=byId('send-code');button.disabled=true;try{const result=await api('/cadastro/api/email/enviar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:byId('input-email').value,resend:true})});if(result.verified){verified=true;byId('input-email').readOnly=true}byId('email-status').textContent=result.verified?'E-mail confirmado.':result.status==='accepted'?(result.reused?'Use o código já enviado ao seu e-mail.':'Código enviado. Confira seu e-mail.'):'Não foi possível confirmar o envio. Se recebeu o código, pode digitá-lo abaixo.'}catch(error){byId('email-status').textContent=error.message}finally{button.disabled=false}};
byId('verify-code').onclick=async()=>{try{await api('/cadastro/api/email/verificar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:byId('input-email').value,code:byId('otp').value})});verified=true;byId('input-email').readOnly=true;byId('email-status').textContent='E-mail confirmado.'}catch(error){byId('email-status').textContent=error.message}};
byId('form').onsubmit=async event=>{event.preventDefault();if(!verified){message('Confirme seu e-mail antes de concluir.');return}const answers={};for(const field of contract.fields){if(byId('field-'+field.id).hidden)continue;const value=fieldValue(field);if(field.type==='file'&&!value){message('Envie o anexo: '+field.label);return}answers[field.id]=value}const payload={version:contract.revision,revision:0,step:5,answers,consent:{accepted:byId('consent-accepted').checked,version:contract.consent.version}};byId('submit').disabled=true;try{const result=await api(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(result.status==='completed'){byId('form').hidden=true;message('Cadastro concluído e confirmado. '+(result.receipt_email_status==='accepted'?'A confirmação também foi enviada ao seu e-mail.':'O envio do e-mail de confirmação ainda não foi confirmado.'))}else{byId('form').hidden=true;message('Sua conclusão está aguardando conferência. Não reenvie o cadastro.')}}catch(error){message(error.message)}finally{byId('submit').disabled=false}};
api('/cadastro/api/contexto').then(render).catch(error=>message(error.message));
</script></html>"""
