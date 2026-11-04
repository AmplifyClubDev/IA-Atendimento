"""Robô de leitura do print de GMV enviado no formulário (campo `print_gmv`).

A IA só transcreve o que aparece na imagem (texto do GMV, moeda, datas); o número
é calculado aqui, por regra fixa. Qualquer dúvida vira `indisponivel` com um motivo:
leitura incerta nunca vira zero e nunca vira GMV verificado.
"""
from __future__ import annotations

from offline_policy import effects_allowed, require_effects, REASON

import base64
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

RESPONSES_URL = "https://api.openai.com/v1/responses"
MAX_RESPONSE = 256 * 1024
PROMPT = (
    "Você recebe um print enviado por uma creator no cadastro da Amplify. Ele deveria mostrar o GMV "
    "(valor bruto vendido) do TikTok Shop num período. Transcreva SOMENTE o que está visível; não calcule, "
    "não estime e não complete o que não aparece.\n"
    "- e_print_tiktok_shop: a imagem é uma tela de desempenho/vendas do TikTok Shop?\n"
    "- gmv_encontrado: há um valor rotulado como GMV (ou 'Valor bruto da mercadoria')?\n"
    "- gmv_texto: o valor do GMV exatamente como escrito (ex.: 'R$ 12.345,67', 'R$ 1,2 mil', '12,3K'). "
    "Se houver vários, use o GMV total do período em destaque.\n"
    # Regras aprendidas no leitor treinado em 15/10 (gmv-formulario-teste, parser.cjs).
    "- Ignore valores de meta, objetivo, nível, 'aumente/alcance', comissão, ticket, reembolso, GPM, "
    "'por cliente', 'por pedido', itens vendidos e médias: nada disso é o GMV.\n"
    "- Se houver dois ou mais valores diferentes que possam ser o GMV e não der para saber qual é, "
    "responda gmv_encontrado=false (não escolha o maior).\n"
    "- moeda: código ISO (BRL quando aparecer R$), ou null se não aparecer.\n"
    "- periodo_texto e as datas de início/fim: só preencha dia/mês/ano que estejam escritos. "
    "Ano ausente = null.\n"
    "- confianca: 'alta' só se o valor estiver nítido e sem ambiguidade."
)
_INT = {"type": ["integer", "null"]}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["e_print_tiktok_shop", "gmv_encontrado", "gmv_texto", "moeda", "periodo_texto",
                 "inicio_dia", "inicio_mes", "inicio_ano", "fim_dia", "fim_mes", "fim_ano", "confianca"],
    "properties": {
        "e_print_tiktok_shop": {"type": "boolean"}, "gmv_encontrado": {"type": "boolean"},
        "gmv_texto": {"type": ["string", "null"]}, "moeda": {"type": ["string", "null"]},
        "periodo_texto": {"type": ["string", "null"]},
        "inicio_dia": _INT, "inicio_mes": _INT, "inicio_ano": _INT,
        "fim_dia": _INT, "fim_mes": _INT, "fim_ano": _INT,
        "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
    },
}
_MULTIPLIERS = (("milhões", 6), ("milhoes", 6), ("milhão", 6), ("milhao", 6), ("mil", 3), ("mi", 6),
                ("k", 3), ("m", 6))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_brl(text):
    """'R$ 12.345,67' -> 12345.67; '1,2 mil' -> 1200; ambíguo -> None."""
    if not isinstance(text, str) or len(text) > 60:
        return None
    value = text.strip().lower().replace("r$", "").replace("brl", "").replace(" ", " ").strip()
    exponent = 0
    for word, power in _MULTIPLIERS:
        if re.search(r"\d\s*" + word + r"\.?$", value):
            value, exponent = re.sub(r"\s*" + word + r"\.?$", "", value), power
            break
    value = value.replace(" ", "")
    if not re.fullmatch(r"\d[\d.,]*", value):
        return None
    if "." in value and "," in value:
        if value.rfind(",") < value.rfind("."):
            return None  # formato americano (1,234.56) não é esperado no TikTok Shop BR
        value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        if value.count(",") > 1:
            return None
        value = value.replace(",", ".")
    elif "." in value and not exponent:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", value):
            value = value.replace(".", "")
        elif value.count(".") > 1:
            return None
    try:
        number = Decimal(value).scaleb(exponent).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None
    return number if 0 <= number <= Decimal("1000000000") else None


def _day(d, m, y, today):
    if not isinstance(d, int) or not isinstance(m, int):
        return None
    years = [y] if isinstance(y, int) else [today.year, today.year - 1]
    for year in years:
        try:
            value = date(year, m, d)
        except ValueError:
            return None
        if value <= today:
            return value
    return None


def interpret(reading, today):
    """Transforma a transcrição da IA no objeto `gmv_print` que o banco aceita."""
    def unavailable(reason):
        return {"situacao": "indisponivel", "valor": None, "moeda": None, "periodo_inicio": None,
                "periodo_fim": None, "motivo": reason}
    if not isinstance(reading, dict) or set(reading) != set(SCHEMA["required"]):
        return unavailable("leitor_resposta_invalida")
    if reading["e_print_tiktok_shop"] is not True:
        return unavailable("imagem_nao_e_print_gmv")
    if reading["gmv_encontrado"] is not True:
        return unavailable("gmv_nao_encontrado")
    if reading["confianca"] == "baixa":
        return unavailable("leitura_incerta")
    value = parse_brl(reading["gmv_texto"])
    if value is None:
        return unavailable("valor_ilegivel")
    currency = reading["moeda"]
    if "r$" in (reading["gmv_texto"] or "").lower():
        currency = "BRL"
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return unavailable("moeda_nao_identificada")
    start = _day(reading["inicio_dia"], reading["inicio_mes"], reading["inicio_ano"], today)
    end = _day(reading["fim_dia"], reading["fim_mes"], reading["fim_ano"], today)
    if start and end and start > end and not isinstance(reading["inicio_ano"], int):
        start = _day(reading["inicio_dia"], reading["inicio_mes"], end.year - 1, today)
    if not (start and end and start <= end and (end - start).days <= 366):
        start = end = None  # sem período legível: o valor fica no histórico, sem datas inventadas
    return {"situacao": "lido", "valor": format(value, "f"), "moeda": currency,
            "periodo_inicio": start.isoformat() if start else None,
            "periodo_fim": end.isoformat() if end else None, "motivo": None}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def _http(*, url, headers, body, timeout):
    require_effects()
    request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with build_opener(_NoRedirect(), ProxyHandler({})).open(request, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("resposta_grande")
    return json.loads(raw)


class GmvPrintReader:
    def __init__(self, api_key, model, *, transport=None, timeout=40):
        self.api_key, self.model = api_key or "", model or ""
        self.transport = transport or _http
        self.timeout = timeout

    @property
    def leitor(self):
        return "openai:" + (re.sub(r"[^A-Za-z0-9_.-]", "-", self.model)[:100] or "nao-configurado")

    def read(self, jpeg_bytes, *, today=None):
        if not effects_allowed():
            return {**interpret(None, today or datetime.now(timezone.utc).date()), "motivo": REASON, "leitor": self.leitor, "lido_em": _now()}
        today = today or datetime.now(timezone.utc).date()
        base = {"leitor": self.leitor, "lido_em": _now()}
        if not self.api_key or not self.model:
            return {**interpret(None, today), "motivo": "leitor_nao_configurado", **base}
        body = {"model": self.model, "store": False, "max_output_tokens": 400,
                "input": [{"role": "user", "content": [
                    {"type": "input_text", "text": PROMPT},
                    {"type": "input_image", "detail": "high",
                     "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()}]}],
                "text": {"format": {"type": "json_schema", "name": "leitura_print_gmv", "strict": True, "schema": SCHEMA}}}
        try:
            response = self.transport(url=RESPONSES_URL, body=body, timeout=self.timeout,
                                      headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})
            texts = [part.get("text") for item in response.get("output", []) if isinstance(item, dict)
                     for part in item.get("content", []) or [] if isinstance(part, dict) and part.get("type") == "output_text"]
            if len(texts) != 1:
                raise ValueError()
            reading = json.loads(texts[0])
        except Exception:
            # Sem mensagem do provedor nos logs: só o motivo fixo.
            return {**interpret(None, today), "motivo": "leitor_falhou", **base, "lido_em": _now()}
        return {**interpret(reading, today), **base, "lido_em": _now()}
