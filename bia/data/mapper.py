"""Map the 63-field form to V5 without I/O beyond its immutable local map.

The transport resolves private-file receipts and supplies observations. This
module neither calls a provider nor writes to a database. Error messages contain
field names/codes, never submitted values or credentials.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid3


MAP_PATH = Path(__file__).with_name("field-map.json")
BRANCHES = (
    "creators_aquisicao", "creators_perfil", "creators_oportunidades",
    "creators_enderecos", "creators_pagamentos", "creators_circle",
)
_OPAQUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_./-]{0,239}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_EVENT_NAME = "atendimento-v5-ensaio|amplify-cadastro-v2|"


class MappingError(ValueError):
    def __init__(self, field: str, code: str):
        self.field, self.code = field, code
        super().__init__(f"{field}: {code}")


def _fail(field, code):
    raise MappingError(field, code)


def load_mapping() -> dict:
    mapping = json.loads(MAP_PATH.read_text(encoding="utf-8-sig"))
    source = MAP_PATH.with_name("cadastro_contract.json").read_bytes()
    if hashlib.sha256(source).hexdigest() != mapping["source_sha256"]:
        raise RuntimeError("Local form source differs from the reviewed mapping")
    contract = json.loads(source.decode("utf-8-sig"))
    fields = mapping["fields"]
    if len(fields) != 63 or len({f["id"] for f in fields}) != 63:
        raise RuntimeError("Invalid local 63-field mapping")
    if len({(f["table"], f["column"]) for f in fields}) != 63:
        raise RuntimeError("Repeated local mapping destination")
    if [f["id"] for f in fields] != [f["id"] for f in contract["fields"]]:
        raise RuntimeError("Local mapping differs from the 63-field form source")
    return mapping


def _uuid(value, field):
    if not isinstance(value, str):
        _fail(field, "uuid_invalido")
    try:
        parsed = UUID(value)
    except ValueError:
        _fail(field, "uuid_invalido")
    if str(parsed) != value or parsed.int == 0:
        _fail(field, "uuid_invalido")
    return parsed


def submission_id(creator_id: str, form_instance_id: str) -> str:
    """Stable UUID3 for one server-owned form instance; never use as a secret.

    UUID3/MD5 is used for deterministic naming, not authentication or signatures.
    The SQL independently checks this same derivation using built-in md5(bytea).
    """
    creator = _uuid(creator_id, "creator_id")
    form = _uuid(form_instance_id, "form_instance_id")
    return str(uuid3(creator, _EVENT_NAME + str(form)))


def _object(value, field, required, optional=()):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - set(optional):
        _fail(field, "campos_invalidos")
    return value


def _text(value, field, limit=254):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        _fail(field, "texto_invalido")
    return value.strip()


def _opaque(value, field):
    if not isinstance(value, str) or not _OPAQUE.fullmatch(value) or "://" in value or ".." in value:
        _fail(field, "referencia_invalida")
    return value


def _instant(value, field):
    if not isinstance(value, str) or len(value) > 40:
        _fail(field, "data_hora_invalida")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError()
        return instant.astimezone(timezone.utc)
    except ValueError:
        _fail(field, "data_hora_invalida")


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _day(value, field):
    if not isinstance(value, str):
        _fail(field, "data_invalida")
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except ValueError:
        _fail(field, "data_invalida")


def _digits(value, field, size):
    cleaned = re.sub(r"[.\-/\s]", "", _text(value, field))
    if not re.fullmatch(r"\d{" + str(size) + r"}", cleaned, flags=re.ASCII):
        _fail(field, "documento_invalido")
    return cleaned


def _cpf(value, field):
    value = _digits(value, field, 11)
    if len(set(value)) == 1:
        _fail(field, "cpf_invalido")
    for length in (9, 10):
        total = sum(int(value[i]) * (length + 1 - i) for i in range(length))
        digit = total * 10 % 11 % 10
        if digit != int(value[length]):
            _fail(field, "cpf_invalido")
    return value


def _decimal(value, field):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        _fail(field, "numero_invalido")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= Decimal("1000000000") or number.as_tuple().exponent < -2:
            raise ValueError()
        if field == "calcado" and (number > Decimal("999.9") or number != number.quantize(Decimal("0.1"))):
            raise ValueError()
        # Monetary values stay decimal strings through JSON, without float loss.
        return format(number.copy_abs() if number == 0 else number, "f")
    except (InvalidOperation, ValueError):
        _fail(field, "numero_invalido")


def _visible(field, answers, by_id):
    condition = field.get("condition")
    if not condition:
        return True
    parent = by_id[condition["field"]]
    if not _visible(parent, answers, by_id):
        return False
    value = answers.get(parent["id"])
    if "equals" in condition:
        return value == condition["equals"]
    return isinstance(value, list) and condition["includes"] in value


def _context(context, mapping, answers):
    required = {"creator_id", "event_id", "form_instance_id", "received_at", "source", "attachments"}
    optional = {"first_inbound", "origin", "email_confirmation", "gmv_period", "atendimento_id", "execution_mode"}
    _object(context, "context", required, optional)
    creator, form = str(_uuid(context["creator_id"], "creator_id")), str(_uuid(context["form_instance_id"], "form_instance_id"))
    event = str(_uuid(context["event_id"], "event_id"))
    if event != submission_id(creator, form):
        _fail("event_id", "nao_corresponde_ao_formulario")
    received = _instant(context["received_at"], "received_at")
    source = _object(context["source"], "source", {"kind", "reference"})
    real = context.get("execution_mode") == "real"
    if "execution_mode" in context and not real:
        _fail("execution_mode", "modo_invalido")
    if real and "atendimento_id" not in context:
        _fail("atendimento_id", "campo_obrigatorio")
    expected_source = "formulario_whatsapp" if real else "formulario_ensaio"
    if source["kind"] != expected_source:
        _fail("source", "fonte_invalida")
    result = {"creator_id": creator, "event_id": event, "form_instance_id": form,
              "received_at": _iso(received),
              "source": {"kind": expected_source, "reference": _opaque(source["reference"], "source.reference")}}
    if real:
        result["execution_mode"] = "real"
    if "atendimento_id" in context:
        result["atendimento_id"] = str(_uuid(context["atendimento_id"], "atendimento_id"))
    attachments = _object(context["attachments"], "attachments", {"foto_perfil", "print_gmv"})
    result["attachments"] = {}
    for field in ("foto_perfil", "print_gmv"):
        attachment = _object(attachments[field], "attachments." + field, {"reference", "receipt_sha256", "source"})
        receipt = _object(answers.get(field), field, {"receipt"})["receipt"]
        receipt = _text(receipt, field, 2048)
        if attachment["source"] != "upload_validado" or not isinstance(attachment["receipt_sha256"], str) or not _HEX.fullmatch(attachment["receipt_sha256"]):
            _fail(field, "anexo_nao_validado")
        if hashlib.sha256(receipt.encode("utf-8")).hexdigest() != attachment["receipt_sha256"]:
            _fail(field, "recibo_incompativel")
        result["attachments"][field] = {"reference": _opaque(attachment["reference"], field),
                                         "source": "upload_validado", "receipt_sha256": attachment["receipt_sha256"]}
    for key, allowed in (("first_inbound", {"chatwoot_webhook"}),
                         ("origin", {"declaracao_pessoa", "utm_observada", "link_observado"}),
                         ("email_confirmation", {"email_token_validado"})):
        if key not in context:
            continue
        extra = {"value"} if key == "origin" else {"email_sha256"} if key == "email_confirmation" else set()
        observation = _object(context[key], key, {"at", "source", "reference"} | extra)
        observed_at = _instant(observation["at"], key + ".at")
        if observation["source"] not in allowed or observed_at > received:
            _fail(key, "observacao_invalida")
        clean = {"at": _iso(observed_at), "source": observation["source"], "reference": _opaque(observation["reference"], key + ".reference")}
        if key == "origin":
            clean["value"] = _text(observation["value"], key + ".value", 120)
        if key == "email_confirmation":
            email = _text(answers.get("email"), "email").lower()
            if observation["email_sha256"] != hashlib.sha256(email.encode("utf-8")).hexdigest():
                _fail(key, "email_incompativel")
            clean["email_sha256"] = observation["email_sha256"]
        result[key] = clean
    if "gmv_period" in context:
        period = _object(context["gmv_period"], "gmv_period", {"start", "end", "source", "reference"})
        start, end = _day(period["start"], "gmv_period.start"), _day(period["end"], "gmv_period.end")
        if period["source"] != "periodo_declarado" or (end - start).days != 27 or end > received.date():
            _fail("gmv_period", "periodo_invalido")
        result["gmv_period"] = {"start": start.isoformat(), "end": end.isoformat(), "source": "periodo_declarado", "reference": _opaque(period["reference"], "gmv_period.reference")}
    return result, received


def _convert(field, value, context, received):
    key, conversion = field["id"], field["conversion"]
    if field["type"] == "select" and (not isinstance(value, str) or value not in field["options"]):
        _fail(key, "opcao_invalida")
    if conversion == "boolean":
        return value == "Sim"
    if conversion == "multi_select":
        if not isinstance(value, list) or not value or any(not isinstance(item, str) or item not in field["options"] for item in value) or len(set(value)) != len(value):
            _fail(key, "opcoes_invalidas")
        return list(value)
    if conversion == "private_file":
        return context["attachments"][key]["reference"]
    if conversion == "decimal":
        return _decimal(value, key)
    if conversion == "cpf":
        return _cpf(value, key)
    if conversion == "cep":
        return _digits(value, key, 8)
    if conversion == "cnpj":
        cleaned = re.sub(r"[.\-/\s]", "", _text(value, key)).upper()
        if not re.fullmatch(r"[A-Z0-9]{12}\d{2}", cleaned, flags=re.ASCII):
            _fail(key, "cnpj_invalido")
        return cleaned
    text = _text(value, key, 2000 if conversion == "textarea" else 254)
    if conversion == "email":
        text = text.lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
            _fail(key, "email_invalido")
    elif conversion == "phone_number":
        if not re.fullmatch(r"[+()\d\s.-]+", text, flags=re.ASCII):
            _fail(key, "telefone_invalido")
        text = re.sub(r"\D", "", text)
        if len(text) in (10, 11):
            text = "55" + text
        if not re.fullmatch(r"55\d{10,11}", text, flags=re.ASCII):
            _fail(key, "telefone_invalido")
    elif conversion == "tiktok":
        if text.startswith("https://"):
            url = urlsplit(text)
            if url.hostname not in {"www.tiktok.com", "tiktok.com"} or url.query or url.fragment or url.username or url.password:
                _fail(key, "tiktok_invalido")
            text = url.path.strip("/")
        text = text.lstrip("@").lower()
        if not re.fullmatch(r"[a-z0-9._]{2,24}", text):
            _fail(key, "tiktok_invalido")
    elif conversion == "date":
        parsed = _day(text, key)
        if parsed < date(1900, 1, 1) or parsed > received.date():
            _fail(key, "data_invalida")
    elif conversion == "url":
        try:
            url = urlsplit(text)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError()
        except ValueError:
            _fail(key, "url_invalida")
    return text


def map_submission(payload: dict, context: dict) -> dict:
    """Validate a complete final form and return safe arguments for the SQL RPC.

    ``context`` must be assembled by the trusted server, never copied from the
    browser. It contains upload attestations and optional sourced observations.
    No raw receipt, file body, prompt, message history or service key is returned.
    """
    mapping = load_mapping()
    _object(payload, "payload", {"version", "revision", "step", "answers", "consent"})
    if payload["version"] != mapping["form_version"] or type(payload["revision"]) is not int or payload["revision"] < 0 or type(payload["step"]) is not int or not 0 <= payload["step"] < 6:
        _fail("payload", "versao_ou_revisao_invalida")
    consent = _object(payload["consent"], "consent", {"accepted", "version"})
    if consent["accepted"] is not True or consent["version"] != mapping["consent_version"]:
        _fail("consent", "consentimento_obrigatorio")
    fields = mapping["fields"]
    by_id = {field["id"]: field for field in fields}
    answers = _object(payload["answers"], "answers", set(), set(by_id))
    clean_context, received = _context(context, mapping, answers)
    identity, branches, gmv = {}, {branch: {} for branch in BRANCHES}, {}
    for field in fields:
        key = field["id"]
        if not _visible(field, answers, by_id):
            if key in answers and answers[key] not in (None, "", []):
                _fail(key, "campo_fora_da_condicao")
            converted = None
        else:
            if key not in answers or answers[key] is None or answers[key] == "" or answers[key] == []:
                _fail(key, "campo_obrigatorio")
            converted = _convert(field, answers[key], clean_context, received)
        target = identity if field["table"] == "creators" else gmv if field["table"] == "creators_gmv" else branches[field["table"]]
        target[field["column"]] = converted
    normalized = {"mapping_version": mapping["version"], "form_version": mapping["form_version"],
                  "identity": identity, "branches": branches, "gmv": gmv,
                  "consent": {"accepted": True, "version": mapping["consent_version"]}}
    return {"payload": normalized, "context": clean_context,
            "coverage": {"mapped": 63, "total": 63, "fields": [field["id"] for field in fields]}}
