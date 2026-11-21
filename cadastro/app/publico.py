"""API do formulário público único, no mesmo protocolo que o cadastro.html original usa
(`/onboarding/api/v2/publico/...`). Um link para todos; cada preenchimento tem a sua
sessão assinada. Tudo o que é cadastro vai para o AmplifyOS-v5.
"""
from __future__ import annotations

import hashlib
import io
import json
import secrets
import threading
import time
import warnings
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

import tokens
from agency import proof
from form import FILES, FIELDS, VERSION, FormError, build_payload, check_envelope, check_partial, event_id, now_iso
from v5 import MAX_IMAGE, V5Error

bp = Blueprint("cadastro_publico_v5", __name__, url_prefix="/onboarding/api/v2/publico")
SESSION_TTL = 7 * 24 * 3600
AGENCY_REFRESH = 6 * 3600
OTP_TTL, OTP_WAIT, OTP_MAX_ATTEMPTS = 600, 60, 10  # tentativas por e-mail na sessão (NIST: reenvio não zera)

PENDING_GUIDE = ("Seu @ tem um convite de agenciamento da Amplify aguardando aceite. No TikTok Shop Creator, "
                 "abra Parcerias ou Notificações, aceite o convite da Amplify e depois toque em Verificar novamente.")
CONFERENCIA = {
    "perfil_divergente": "Este WhatsApp já está ligado a outro @ na Amplify. Confira o @ digitado e use o perfil do seu atendimento. Depois toque em Continuar novamente. Suas respostas permanecem neste navegador.",
    "contato_divergente": "Este @ já está ligado a outro WhatsApp na Amplify. Confira o @ e informe o mesmo WhatsApp do seu atendimento, com DDD. Depois toque em Continuar novamente. Suas respostas permanecem neste navegador.",
    "email_em_outra_ficha": "Este e-mail já está em outro cadastro. Use outro e-mail ou fale com o atendimento.",
}
FORM_ERRORS = {
    "envelope_invalido": "Este formulário foi atualizado. Recarregue a página.",
    "consentimento_obrigatorio": "Leia o termo e marque sua concordância para concluir.",
    "campo_obrigatorio": "Responda todas as perguntas antes de enviar.",
    "cpf_invalido": "Confira o CPF: informe os 11 dígitos de um CPF válido.",
    "anexo_invalido": "Selecione novamente a imagem deste cadastro.",
}


class CadastroError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


@bp.errorhandler(CadastroError)
def known_error(error):
    return jsonify({"erro": error.message}), error.status


@bp.errorhandler(FormError)
def form_error(error):
    label = FIELDS.get(error.field, {}).get("name")
    message = FORM_ERRORS.get(error.code) or ("Confira: " + label if label else "Confira os dados informados.")
    return jsonify({"erro": message}), 400


@bp.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    return jsonify({"erro": "O arquivo excede o tamanho permitido."}), 413


@bp.errorhandler(Exception)
def unavailable(error):
    # Sem payload, URL, PII ou segredo nos logs: só o tipo do erro.
    print(f"[cadastro-publico-v5] indisponivel: {type(error).__name__}")
    return jsonify({"erro": "Serviço temporariamente indisponível. Tente novamente."}), 503


@bp.before_request
def limit_size():
    request.max_content_length = MAX_IMAGE + 65536 if request.path.endswith("/anexos") else 65536


@bp.after_request
def private_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Content-Security-Policy"] = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                                   "img-src data: blob:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return response


def deps():
    return current_app.extensions["cadastro_v5"]


def client_hash():
    remote = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[-1].strip()[:128]
    return tokens.digest(deps().secret, "cliente", remote)


def body(keys):
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) != set(keys):
        raise CadastroError("Pedido inválido. Recarregue a página.")
    return value


def session():
    d = deps()
    header = request.headers.get("Authorization", "")
    try:
        claims = tokens.verify(d.secret, "sessao", header[7:] if header.startswith("Bearer ") else "", ttl=SESSION_TTL)
        form_id = str(UUID(claims["f"]))
    except (tokens.TokenInvalido, KeyError, ValueError):
        raise CadastroError("Sessão inválida ou expirada. Abra novamente o formulário.", 404) from None
    row = d.store.session(form_id)
    if row is None:
        # Estado temporário perdido (ex.: reinício do serviço): a sessão recomeça vazia;
        # o rascunho continua no navegador, mas e-mail e @ precisam ser conferidos de novo.
        d.store.open_session(form_id, client_hash())
        row = d.store.session(form_id)
    return form_id, row


def open_row(row):
    if row["submitted_json"]:
        raise CadastroError("Seu cadastro já foi recebido.", 409)


def context_body(form_id, row):
    token = tokens.sign(deps().secret, "sessao", {"f": form_id})
    value = {"token": token, "version": VERSION, "revision": 0, "step": 0, "answers": {}, "prefill": {},
             "submitted": bool(row["submitted_json"])}
    if row["submitted_json"]:
        value["outcome"] = json.loads(row["submitted_json"])["outcome"]
    return value


def handle_of(value):
    try:
        return check_partial({"tiktok": value}, datetime.now(timezone.utc), None)["tiktok"]
    except FormError:
        raise CadastroError("Informe seu @ do TikTok, como @seuusuario.") from None


# ---------------------------------------------------------------- sessão

@bp.post("/sessao")
def start():
    d = deps()
    expected = d.public_url.rstrip("/")
    parsed = urlsplit(expected)
    local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")  # só teste local
    if not (parsed.scheme == "https" or local) or not parsed.hostname or request.headers.get("Origin") != expected:
        raise CadastroError("Abra o formulário pelo endereço da Amplify.", 403)
    value = request.get_json(silent=True)
    try:
        if not isinstance(value, dict) or set(value) != {"nonce"}:
            raise ValueError()
        nonce = str(UUID(value["nonce"]))
    except (ValueError, TypeError, AttributeError):
        raise CadastroError("Não foi possível iniciar o cadastro. Recarregue a página.") from None
    who = client_hash()
    if not d.store.allow("sessao:" + who, 30, 3600) or not d.store.allow("sessao:global", 2000, 3600):
        raise CadastroError("Muitas tentativas de abertura. Aguarde alguns minutos e tente novamente.", 429)
    # Mesmo navegador (mesmo nonce) volta para a mesma sessão.
    form_id = str(UUID(hex=tokens.digest(d.secret, "sessao", nonce)[:32], version=4))
    d.store.open_session(form_id, who)
    return jsonify(context_body(form_id, d.store.session(form_id)))


@bp.get("/contexto")
def get_context():
    form_id, row = session()
    return jsonify(context_body(form_id, row))


# ---------------------------------------------------------------- agenciamento (1ª etapa)

def run_agency(handle):
    result = deps().agency.check(handle)
    if result is None:
        raise CadastroError("Ainda estamos consultando o TikTok. Toque em Verificar novamente em alguns segundos.", 503)
    return result


@bp.post("/agenciamento")
def check_agency():
    d = deps()
    form_id, row = session()
    open_row(row)
    handle = handle_of(body({"tiktok"})["tiktok"])
    if not d.store.allow("agenciamento:" + form_id, 8, 600) or not d.store.allow("agenciamento:" + client_hash(), 20, 600):
        raise CadastroError("Muitas consultas seguidas. Aguarde alguns minutos e tente novamente.", 429)
    if not (row["agency_handle"] == handle and row["agency_at"] and time.time() - row["agency_at"] < 600):
        approve_agency(form_id, handle)
    return jsonify({"status": "aprovada"})


def approve_agency(form_id, handle):
    """Só segue quem está VINCULADO; pendente e não encontrado recebem orientação."""
    result = run_agency(handle)
    status = result.get("status")
    if status == "linked" and proof(result):
        deps().store.update(form_id, agency_handle=handle, agency_json=json.dumps(proof(result)), agency_at=time.time())
        return
    if status == "pending":
        raise CadastroError(PENDING_GUIDE, 409)
    if status == "not_found":
        raise CadastroError("Não encontramos vínculo de agenciamento da Amplify para @" + handle + ". Confira se digitou "
                            "o @ certo. Se você ainda não é agenciado(a) pela Amplify, fale com a gente no WhatsApp "
                            "para receber o convite.", 409)
    raise CadastroError("Não foi possível consultar o TikTok agora. Tente novamente em alguns minutos.", 503)


# ---------------------------------------------------------------- e-mail

def email_of(value, *, optional=False):
    if not isinstance(value, str):
        raise CadastroError("Informe um e-mail válido.")
    email = value.strip().lower()
    if optional and email == "":
        return email
    try:
        return check_partial({"email": email}, datetime.now(timezone.utc), None)["email"]
    except FormError:
        raise CadastroError("Informe um e-mail válido.") from None


def email_state(row, email):
    secret = deps().secret
    sent = json.loads(row["otp_sent_json"])
    wait = max(0, int(OTP_WAIT - (time.time() - sent[-1]))) if sent else 0
    if email and row["email_hash"] == tokens.digest(secret, "email", email) and row["email_verified_at"]:
        return {"required": True, "verified": True, "status": "confirmado", "retry_after": 0}
    if not email or row["otp_email_hash"] != tokens.digest(secret, "email", email):
        return {"required": True, "verified": False, "status": "nao_solicitado", "retry_after": wait}
    status = row["otp_status"] or "nao_solicitado"
    if status in ("enviado", "incerto", "enviando") and (row["otp_expires_at"] or 0) <= time.time():
        status = "expirado"
    if row["otp_attempts"] >= OTP_MAX_ATTEMPTS:
        status = "tentativas_esgotadas"
    return {"required": True, "verified": False, "status": status, "retry_after": wait,
            "requested_at": sent[-1] if sent else None, "expires_at": row["otp_expires_at"],
            "request_reference": str(int(sent[-1]))[-6:] if sent else None}


@bp.post("/email/estado")
def email_status():
    _form_id, row = session()
    return jsonify(email_state(row, email_of(body({"email"})["email"], optional=True)))


@bp.post("/email/solicitar")
def email_request():
    d = deps()
    form_id, row = session()
    open_row(row)
    email = email_of(body({"email"})["email"])
    state = email_state(row, email)
    if state["verified"]:
        return jsonify(state)
    if not d.email.configured():
        raise CadastroError("A confirmação por e-mail ainda não está disponível.", 503)
    if state["retry_after"] > 0:
        return jsonify(state)
    if not d.store.allow("email:" + client_hash(), 10, 3600):
        raise CadastroError("Limite de códigos atingido. Aguarde uma hora antes de solicitar outro.", 429)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = time.time()
    email_hash = tokens.digest(d.secret, "email", email)
    code_hash = tokens.digest(d.secret, "codigo:" + form_id, code)
    claim = d.store.claim_email_code(form_id, email_hash, code_hash, now=now, ttl=OTP_TTL, wait=OTP_WAIT)
    if claim == 'limited':
        raise CadastroError("Limite de códigos atingido. Aguarde uma hora antes de solicitar outro.", 429)
    if claim == 'submitted':
        raise CadastroError("Seu cadastro já foi recebido.", 409)
    if claim != 'claimed':
        fresh = email_state(d.store.session(form_id), email)
        if claim == 'waiting':
            fresh['retry_after'] = max(1, fresh['retry_after'])
        return jsonify(fresh)
    message_id = f"<cadastro-publico-{form_id}-{int(now)}@amplifyugc.co>"
    try:
        result = d.email.send_code(email, code, message_id)
    except Exception:
        # O provedor pode ter aceitado: guardar a incerteza, nunca reenviar aqui.
        result = 'incerto'
    d.store.finish_email_code(form_id, code_hash, result)
    return jsonify(email_state(d.store.session(form_id), email))


@bp.post("/email/confirmar")
def email_confirm():
    d = deps()
    form_id, row = session()
    value = body({"email", "code"})
    email = email_of(value["email"])
    code = value["code"]
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        raise CadastroError("Digite os 6 números do código recebido.")
    state = email_state(row, email)
    if state["verified"]:
        return jsonify(state)
    if state["status"] not in ("enviado", "incerto"):
        return jsonify({**state, "status": state["status"] if state["status"] != "nao_solicitado" else "expirado"})
    outcome = d.store.confirm_email_code(
        form_id, tokens.digest(d.secret, 'email', email), tokens.digest(d.secret, 'codigo:' + form_id, code),
        hashlib.sha256(email.encode()).hexdigest(), now_iso(), now=time.time(), maximum=OTP_MAX_ATTEMPTS)
    fresh = email_state(d.store.session(form_id), email)
    return jsonify(fresh if fresh['verified'] else {**fresh, 'status': outcome})


# ---------------------------------------------------------------- validação inicial (1ª etapa)

def require_identity_ready(row, handle, email):
    if row["agency_handle"] != handle or not row["agency_json"]:
        raise CadastroError("Confirme primeiro seu @ do TikTok no início do cadastro.", 409)
    if row["email_hash"] != tokens.digest(deps().secret, "email", email) or not row["email_verified_at"]:
        raise CadastroError("Confirme seu e-mail com o código recebido antes de continuar.", 409)


def identity_answer(result):
    status = result.get("status") if isinstance(result, dict) else None
    if status in ("nova", "existente"):
        return
    if status == "ja_cadastrado":
        raise CadastroError("Seu cadastro já foi recebido. Para alterações, fale com o atendimento da Amplify.", 409)
    if status == "conferencia":
        raise CadastroError(CONFERENCIA.get(result.get("reason"), "Precisamos conferir seus dados antes de continuar. "
                                            "Fale com o atendimento da Amplify."), 409)
    raise CadastroError("Não foi possível validar seus dados agora.", 503)


@bp.post("/validacao-inicial")
def validate_initial():
    d = deps()
    form_id, row = session()
    open_row(row)
    value = body({"nome", "email", "whatsapp", "tiktok"})
    try:
        clean = check_partial({k: value[k] for k in ("nome", "email", "whatsapp", "tiktok")}, datetime.now(timezone.utc), None)
        if set(clean) != {"nome", "email", "whatsapp", "tiktok"}:
            raise FormError("campo_obrigatorio")
    except (FormError, AttributeError):
        raise CadastroError("Confira seus dados antes de continuar.") from None
    require_identity_ready(row, clean["tiktok"], clean["email"])
    try:
        result = d.v5.rpc("consultar_cadastro_publico_v5", {"p_tiktok": clean["tiktok"], "p_whatsapp": clean["whatsapp"],
                                                             "p_email": clean["email"]})
    except V5Error:
        raise CadastroError("Não foi possível validar seus dados agora.", 503) from None
    identity_answer(result)
    d.store.update(form_id, initial_hash=tokens.digest(d.secret, "inicial", clean["tiktok"] + "|" + clean["whatsapp"] + "|" + clean["email"]))
    return jsonify({"status": "aprovada"})


# ---------------------------------------------------------------- anexos

def receipt_for(form_id, field, key):
    return {"receipt": tokens.sign(deps().secret, "anexo", {"f": form_id, "c": field, "o": key})}


def attachment_key(form_id, field, value):
    d = deps()
    try:
        if not isinstance(value, dict) or set(value) != {"receipt"}:
            raise ValueError()
        claims = tokens.verify(d.secret, "anexo", value["receipt"], ttl=SESSION_TTL)
        if claims["f"] != form_id or claims["c"] != field or not d.store.has_attachment(form_id, field, claims["o"]):
            raise ValueError()
        return claims["o"]
    except (tokens.TokenInvalido, KeyError, ValueError):
        raise FormError("anexo_invalido", field) from None


def sanitize_image(data):
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not 0 < len(data) <= MAX_IMAGE:
        raise CadastroError("Escolha uma imagem de até 5 MB.", 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["JPEG", "PNG", "WEBP"]) as img:
                # Bounded JPEG draft downsamples before loading the pixel buffer.
                source_pixels = img.width * img.height
                if getattr(img, "n_frames", 1) != 1:
                    raise ValueError()
                if source_pixels > 20_000_000:
                    if (img.format != "JPEG" or source_pixels > 40_000_000
                            or img.info.get("progressive") or img.info.get("progression")):
                        raise CadastroError("Esta imagem tem resolução muito alta. Envie uma cópia menor ou uma captura de tela legível, em JPG, PNG ou WebP de até 5 MB. JPG comum aceita até 40 megapixels; PNG, WebP e JPG progressivo, até 20 megapixels.")
                    scale = 2400 / max(img.width, img.height)
                    img.draft("RGB", (max(1, int(img.width * scale)), max(1, int(img.height * scale))))
                    if img.width * img.height > 20_000_000:
                        raise CadastroError("Não foi possível reduzir esta imagem com segurança. Envie uma cópia com resolução menor ou uma captura de tela legível de até 5 MB.")
                img.load()
                clean = ImageOps.exif_transpose(img).convert("RGB")
                clean.thumbnail((2400, 2400))
                clean.info.clear()
                output = io.BytesIO()
                clean.save(output, format="JPEG", quality=90, exif=b"", icc_profile=None)
                if output.tell() > MAX_IMAGE:
                    raise ValueError()
                return output.getvalue()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise CadastroError("Imagem inválida. Use JPG, PNG ou WebP sem animação.") from None


def read_gmv_later(key, data):
    d = deps()
    reader, store = d.gmv_reader, d.store

    def run():
        store.save_gmv_read(key, reader.read(data))
    thread = threading.Thread(target=run, name="leitura-print-gmv", daemon=True)
    thread.start()
    d.gmv_threads[key] = thread


@bp.post("/anexos")
def upload():
    d = deps()
    form_id, row = session()
    open_row(row)
    field = request.args.get("campo")
    if field not in FILES or set(request.args) != {"campo"}:
        raise CadastroError("Campo de imagem inválido.")
    data = sanitize_image(request.get_data())
    key = f"publico/{form_id}/{field}/{hashlib.sha256(data).hexdigest()}.jpg"
    if not d.store.add_attachment(form_id, field, key):
        raise CadastroError("Limite de trocas de imagem atingido. Fale com o atendimento.", 409)
    d.v5.upload(key, data)
    if field == "print_gmv" and d.store.gmv_read(key) is None:
        read_gmv_later(key, data)
    return jsonify(receipt_for(form_id, field, key))


@bp.post("/imagem")
def image():
    d = deps()
    form_id, _row = session()
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) != {"receipt", "field"} or value["field"] not in FILES:
        raise CadastroError("Imagem inválida.")
    try:
        key = attachment_key(form_id, value["field"], {"receipt": value["receipt"]})
    except FormError:
        raise CadastroError("Selecione novamente a imagem deste cadastro.") from None
    return send_file(io.BytesIO(d.v5.download(key)), mimetype="image/jpeg", max_age=0)


# ---------------------------------------------------------------- respostas e envio final

@bp.route("/respostas", methods=["PUT", "POST"])
def save():
    form_id, row = session()
    final = request.method == "POST"
    if row["submitted_json"]:
        return jsonify({"outcome": json.loads(row["submitted_json"])["outcome"], "submitted": True, "revision": 0})
    envelope = check_envelope(request.get_json(silent=True), final=final)
    answers = envelope["answers"]
    received = datetime.now(timezone.utc)
    clean = check_partial(answers, received, lambda field, value: attachment_key(form_id, field, value))
    if "tiktok" in clean and clean["tiktok"] != row["agency_handle"]:
        # Sessão temporária perdida ou @ trocado depois da checagem: confere de novo, ao vivo.
        approve_agency(form_id, clean["tiktok"])
        row = deps().store.session(form_id)
    if not final:
        return jsonify({"revision": 0, "step": envelope["step"], "submitted": False})
    return jsonify(submit(form_id, row, answers, received))


def gmv_reading(key):
    d = deps()
    thread = d.gmv_threads.get(key)
    if thread is not None:
        thread.join(timeout=20)
    reading = d.store.gmv_read(key)
    if reading is None:
        reading = d.gmv_reader.read(d.v5.download(key))
        d.store.save_gmv_read(key, reading)
    return reading


def submit(form_id, row, answers, received):
    d = deps()
    keys = {field: attachment_key(form_id, field, answers.get(field)) for field in FILES}
    attachments = {field: {"reference": keys[field], "source": "upload_validado",
                           "receipt_sha256": hashlib.sha256(answers[field]["receipt"].encode()).hexdigest()}
                   for field in FILES}
    payload = build_payload(answers, attachments, received)
    identity = payload["identity"]
    require_identity_ready(row, identity["tiktok"], identity["email"])
    if row["initial_hash"] != tokens.digest(d.secret, "inicial", identity["tiktok"] + "|" + identity["whatsapp"] + "|" + identity["email"]):
        raise CadastroError("Confira seus dados de acesso na primeira etapa antes de enviar.", 409)
    relationship = json.loads(row["agency_json"])
    if time.time() - row["agency_at"] > AGENCY_REFRESH:
        # Conferência antiga: consulta o TikTok de novo antes de gravar.
        result = run_agency(identity["tiktok"])
        if result.get("status") != "linked" or not proof(result):
            d.store.update(form_id, agency_handle=None, agency_json=None, agency_at=None)
            raise CadastroError("Não conseguimos confirmar seu vínculo com a Amplify agora. Volte à primeira etapa "
                                "e toque em Verificar.", 409)
        relationship = proof(result)
        d.store.update(form_id, agency_json=json.dumps(relationship), agency_at=time.time())
    # Produção (patch vinculo-clock, 20/11): horário depois da reconferência do @, para não ficar antes da prova.
    received_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    reading = gmv_reading(keys["print_gmv"])
    context = {
        "event_id": event_id(form_id), "form_instance_id": form_id, "received_at": received_at,
        "source": {"kind": "formulario_publico", "reference": "formulario-publico:" + form_id},
        "attachments": attachments,
        "email_confirmation": {"at": row["email_verified_at"], "source": "email_token_validado",
                               "reference": "formulario-publico:" + form_id + ":email", "email_sha256": row["email_sha256"]},
        "relationship": relationship,
        "gmv_print": {k: reading[k] for k in ("situacao", "valor", "moeda", "periodo_inicio", "periodo_fim", "leitor", "lido_em", "motivo")},
    }
    try:
        result = d.v5.rpc("registrar_cadastro_publico_v5", {"p_payload": payload, "p_context": context})
    except V5Error as error:
        raise submit_error(error.code) from None
    receipt = {k: result.get(k) for k in ("creator_id", "event_id")}
    gmv_lido = reading["valor"] if reading.get("situacao") == "lido" else None
    started = d.entrega.iniciar(context["event_id"], on_done=lambda value: delivery_done(d, form_id, receipt, value),
                                gmv_lido=gmv_lido) if d.entrega else None
    # O HTML original acompanha 'entrega_em_andamento' e mostra o botão do Circle quando liberado.
    outcome = {"outcome": {"status": "entrega_em_andamento" if started else "cadastro_recebido"}}
    d.store.update(form_id, submitted_json=json.dumps({**outcome, "receipt": receipt}))
    return {**outcome, "submitted": True, "revision": 0}


def delivery_done(d, form_id, receipt, value):
    if value.get("status") == "acessos_liberados":
        outcome = {"status": "acessos_liberados", "access": {"circle_confirmed": True, "category": value["category"],
                                                              "email": value["email"], "email_sent": True}}
    elif value.get("status") == "revisao_manual":
        outcome = {"status": "conferencia_entrega"}
    else:
        outcome = {"status": "cadastro_recebido"}
    d.store.update(form_id, submitted_json=json.dumps({"outcome": outcome, "receipt": receipt}))


def submit_error(code):
    if code.startswith("cadastro_publico_conferencia:"):
        return CadastroError(CONFERENCIA.get(code.split(":", 1)[1], "Precisamos conferir seus dados antes de concluir. "
                                             "Fale com o atendimento da Amplify."), 409)
    if code == "cadastro_publico_ja_cadastrado":
        return CadastroError("Seu cadastro já foi recebido. Para alterações, fale com o atendimento da Amplify.", 409)
    if code.startswith("cadastro_publico_vinculo"):
        return CadastroError("Não conseguimos confirmar seu vínculo com a Amplify. Volte à primeira etapa e toque em Verificar.", 409)
    if code.startswith("cadastro_publico_email"):
        return CadastroError("Confirme seu e-mail com o código recebido na primeira etapa antes de enviar o cadastro.", 409)
    if code.startswith("cadastro_publico_"):
        print(f"[cadastro-publico-v5] recusado pelo banco: {code[:120]}")
        return CadastroError("Confira as respostas e tente enviar novamente.", 400)
    # Só a mensagem principal do banco (sem DETAIL, que pode conter valores).
    print(f"[cadastro-publico-v5] falha ao gravar: {code[:120]}")
    return CadastroError("Não foi possível salvar agora. Tente novamente.", 503)
