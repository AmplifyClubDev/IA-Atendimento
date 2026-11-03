"""Dublês locais: banco (PostgreSQL local real), Storage em memória, ponte TikTok, SMTP e IA."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

from v5 import V5Error  # noqa: E402


class PgGateway:
    """Chama as funções do banco local como service_role, igual ao PostgREST."""

    def __init__(self, dsn):
        self.dsn, self.objects, self.calls = dsn, {}, []

    def rpc(self, name, params):
        self.calls.append(name)
        args = ", ".join(f"{k} => %({k})s" for k in params)
        values = {k: Jsonb(v) if isinstance(v, (dict, list)) else v for k, v in params.items()}
        with psycopg.connect(self.dsn) as conn:
            conn.execute("SET ROLE service_role")
            try:
                value = conn.execute(f"select public.{name}({args})", values).fetchone()[0]
            except psycopg.Error as error:
                raise V5Error(error.diag.message_primary or "erro") from None
        return value

    def upload(self, key, data):
        self.objects[key] = data

    def download(self, key):
        return self.objects[key]


class FakeBridge:
    """Responde /ready e /relations como a ponte de agenciamento (formato do playwright_client)."""

    def __init__(self, relations):
        self.relations, self.calls = relations, []

    def __call__(self, *, method, url, headers, json_body=None, timeout=30):
        assert url.startswith("https://tiktok-agenciamento-production.up.railway.app/bridge")
        self.calls.append(url)
        if "/ready" in url:
            return 200, {"ok": True, "status": "ready", "contexto": {"aberto": True, "pronto": True},
                         "probe": {"status": "ok", "ageMs": 1000}, "readiness": {"fresh": True}, "riskGuard": {"status": "clear"}}
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(url).query)
        handle, status = query["creators"][0], int(query["status"][0])
        state = self.relations.get(handle)
        items = []
        if (state == "linked" and status == 1) or (state == "pending" and status == 2):
            label = "vinculado" if status == 1 else "solicitada"
            items = [{"arroba": handle, "status": label, "tiktok_status": status, "tiktok_data_status": status,
                      "relation_id": "7300000000000000001"}]
        return 200, {"ok": True, "status": "relations_listed", "completo": True, "items": items,
                     "pages": [{"ok": True, "hasMore": False, "count": len(items)}], "cache": None,
                     "query": {"status": str(status), "creators": [handle]}, "totalNum": len(items)}


class FakeEmail:
    def __init__(self):
        self.sent = []

    def configured(self):
        return True

    def send_code(self, email, code, message_id):
        self.sent.append((email, code))
        return "enviado"

    def last_code(self, email):
        return [code for to, code in self.sent if to == email][-1]


def openai_transport(reading):
    def transport(*, url, headers, body, timeout):
        assert url == "https://api.openai.com/v1/responses" and body["store"] is False
        assert body["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(reading)}]}]}
    return transport


def png(color=(30, 90, 200)):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buffer, format="PNG")
    return buffer.getvalue()


READING_OK = {"e_print_tiktok_shop": True, "gmv_encontrado": True, "gmv_texto": "R$ 12.345,67", "moeda": "BRL",
              "periodo_texto": "02/10 - 29/10", "inicio_dia": 2, "inicio_mes": 10, "inicio_ano": 2026,
              "fim_dia": 29, "fim_mes": 10, "fim_ano": 2026, "confianca": "alta"}
READING_BLUR = {**READING_OK, "gmv_texto": None, "gmv_encontrado": False, "confianca": "baixa"}


def answers(tiktok, whatsapp, email, *, nome="Teste Local"):
    """63 campos válidos, sem condicionais abertas (exceto CNPJ/pets para cobrir condições)."""
    return {
        "nome": nome, "email": email, "whatsapp": whatsapp, "tiktok": tiktok,
        "mini_bio": "Crio conteúdo de beleza.", "canal_origem": "Conheci no TikTok",
        "expectativas": "Campanhas e apoio.", "meta_renda_mensal": "5000", "contexto_adicional": "Nada a acrescentar.",
        "plataformas": ["TikTok", "Instagram"], "instagram": "@teste.insta",
        "experiencia_live_shop": "Básico", "agencia_anterior": "Não", "produtos_excluidos": "Nenhum.",
        "gmv_declarado": "15000.50", "inicio_amplify_informado": "2026-10-01", "cpf": "52998224725",
        "nascimento": "1995-05-20", "genero": "Feminino", "estado_civil": "Solteiro", "camiseta": "M",
        "estado": "Santa Catarina", "cidade": "Joinville", "logradouro": "Rua Teste", "bairro": "Centro", "numero": "100",
        "complemento": "Sem complemento", "cep": "89201000", "pix": "chave-pix-teste", "possui_cnpj": "Sim",
        "cnpj": "11222333000181", "nichos": ["Beleza"], "rotina": "Me dedico 100% ao conteúdo", "tem_filhos": "Não",
        "cabelo": "liso", "calcado": "37", "cor_raca": "Parda", "alimentacao": "Sem restrições (como de tudo)",
        "casa_praia_campo": "Não", "carro": "Não", "moto": "Não", "celular": "iPhone", "computador": "Sim",
        "tripe": "Sim", "microfone": "Não", "academia": "Sim", "tem_pet": "Sim", "pets": "Gato",
        "outro_idioma": "Não", "mais_2000_seguidores": "Sim",
    }
