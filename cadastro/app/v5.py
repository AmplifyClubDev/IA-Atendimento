"""Acesso ao AmplifyOS-v5 (Supabase divlvdmsqbwplervsqwu): duas RPCs e o bucket privado.

Nenhuma tabela é lida ou escrita diretamente; toda gravação passa pela função
`registrar_cadastro_publico_v5`, numa única transação.
"""
from __future__ import annotations

from offline_policy import effects_allowed, require_effects, REASON

import requests

BUCKET = "cadastro-privado"
MAX_IMAGE = 5 * 1024 * 1024


class V5Error(Exception):
    """`code` é o código da exceção SQL (ex.: cadastro_publico_ja_cadastrado), nunca dados pessoais."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


class RestGateway:
    def __init__(self, url, service_key):
        if not url.startswith("https://") or not service_key:
            raise RuntimeError("configuracao_v5_incompleta")
        self.base = url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"apikey": service_key, "Authorization": "Bearer " + service_key})

    def rpc(self, name, params):
        require_effects()
        response = self.session.post(self.base + "/rest/v1/rpc/" + name, json=params, timeout=30)
        if not response.ok:
            code = ""
            if "application/json" in response.headers.get("Content-Type", ""):
                code = str(response.json().get("message", ""))[:200]
            raise V5Error(code or "v5_indisponivel")
        return response.json()

    def upload(self, key, data):
        # Chave derivada do hash da imagem: repetir após timeout não cria outro objeto.
        require_effects()
        response = self.session.post(self.base + f"/storage/v1/object/{BUCKET}/{key}", data=data,
                                     headers={"Content-Type": "image/jpeg", "x-upsert": "true"}, timeout=30)
        if not response.ok:
            raise V5Error("storage_upload_falhou")

    def download(self, key):
        require_effects()
        response = self.session.get(self.base + f"/storage/v1/object/authenticated/{BUCKET}/{key}", timeout=30)
        if not response.ok or len(response.content) > MAX_IMAGE:
            raise V5Error("storage_download_falhou")
        return response.content
