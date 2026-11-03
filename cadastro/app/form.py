"""Validação das respostas e montagem do envio para o banco.

Usa o mesmo mapa de 63 campos da Bia (`data/field-map.json`, conferido por hash):
cada pergunta tem um destino fixo na ficha (`interno.creators`) ou no GMV.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from data.mapper import BRANCHES, MappingError, _convert, _visible, load_mapping

MAPPING = load_mapping()
FIELDS = {field["id"]: field for field in MAPPING["fields"]}
VERSION = MAPPING["form_version"]
CONSENT_VERSION = MAPPING["consent_version"]
FILES = ("foto_perfil", "print_gmv")


class FormError(Exception):
    def __init__(self, code, field=None):
        self.code, self.field = code, field
        super().__init__(code)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def event_id(form_id):
    """Mesmo cálculo da função SQL: MD5 de 'amplify-cadastro-publico-v5|<form>' com bits de UUID v3."""
    raw = hashlib.md5(("amplify-cadastro-publico-v5|" + form_id).encode()).digest()
    return str(UUID(bytes=raw, version=3))


def _empty(value):
    return value is None or value == "" or value == [] or isinstance(value, str) and not value.strip()


def check_envelope(body, *, final):
    keys = {"version", "revision", "step", "answers"} | ({"consent"} if final else set())
    if (not isinstance(body, dict) or set(body) != keys or body["version"] != VERSION
            or type(body["revision"]) is not int or body["revision"] < 0
            or type(body["step"]) is not int or not 0 <= body["step"] < 6
            or not isinstance(body["answers"], dict) or set(body["answers"]) - FIELDS.keys()):
        raise FormError("envelope_invalido")
    if final and body["consent"] != {"accepted": True, "version": CONSENT_VERSION}:
        raise FormError("consentimento_obrigatorio")
    return body


def check_partial(answers, received, file_check):
    """Confere cada resposta já preenchida; vazias ficam para o envio final."""
    clean = {}
    for key, value in answers.items():
        if _empty(value):
            continue
        field = FIELDS[key]
        if field["conversion"] == "private_file":
            clean[key] = file_check(key, value)
            continue
        try:
            clean[key] = _convert(field, value, {}, received)
        except MappingError as error:
            raise FormError(error.code, error.field) from None
    return clean


def build_payload(answers, attachments, received):
    """Igual a data.mapper.map_submission, mas com o contexto do formulário público."""
    identity, branches, gmv = {}, {branch: {} for branch in BRANCHES}, {}
    for field in MAPPING["fields"]:
        key = field["id"]
        if not _visible(field, answers, FIELDS):
            if not _empty(answers.get(key)):
                raise FormError("campo_fora_da_condicao", key)
            converted = None
        elif _empty(answers.get(key)):
            raise FormError("campo_obrigatorio", key)
        elif field["conversion"] == "private_file":
            converted = attachments[key]["reference"]
        else:
            try:
                converted = _convert(field, answers[key], {}, received)
            except MappingError as error:
                raise FormError(error.code, error.field) from None
        target = identity if field["table"] == "creators" else gmv if field["table"] == "creators_gmv" else branches[field["table"]]
        target[field["column"]] = converted
    return {"mapping_version": MAPPING["version"], "form_version": VERSION, "identity": identity,
            "branches": branches, "gmv": gmv, "consent": {"accepted": True, "version": CONSENT_VERSION}}
