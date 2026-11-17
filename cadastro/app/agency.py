"""Checagem AO VIVO do vínculo do @ com a Amplify no TikTok Partner Center.

Usa o mesmo cliente da Bia (`playwright_client.py`, cópia sem alteração), operação
`relationship`, na ponte https://tiktok-agenciamento-production.up.railway.app/bridge.
A ponte abre um Chromium por consulta; por isso há limite de concorrência e a mesma
consulta em andamento é reaproveitada. O navegador desiste do pedido em 45 s, então
a resposta é devolvida em até ~38 s e a consulta continua em segundo plano.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from playwright_client import PlaywrightClient

AGENCY_URL = "https://tiktok-agenciamento-production.up.railway.app/bridge"


class AgencyChecker:
    def __init__(self, token, *, transport=None, max_parallel=2, wait_seconds=38, cache_seconds=6 * 3600):
        self.client = PlaywrightClient({"tiktok_agency_url": AGENCY_URL, "tiktok_agency_token": token or "",
                                        "tiktok_timeout_seconds": 35, "tiktok_status_timeout_seconds": 5},
                                       transport=transport)
        self.pool = ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix="agenciamento")
        self.wait_seconds = wait_seconds
        self._inflight = {}
        # "Vinculado" confirmado fica guardado por 6 h: poupa a ponte (Chromium) quando muitos leads
        # entram ao mesmo tempo. Pendente/não encontrado nunca ficam guardados (a pessoa pode aceitar agora).
        self._linked = {}
        self.cache_seconds = cache_seconds
        self._lock = threading.Lock()

    def configured(self):
        return self.client.configuration("relationship")["configured"]

    def _run(self, handle):
        result = self.client.execute("relationship", handle)
        # Prova no formato que a função do banco confere (7 campos).
        result["job_id"] = "formulario-publico:relationship:" + str(uuid.uuid4())
        return result

    def check(self, handle):
        """Devolve o resultado da ponte ou None se ainda não terminou dentro da espera."""
        with self._lock:
            cached = self._linked.get(handle)
            if cached and time.monotonic() - cached[0] < self.cache_seconds:
                return dict(cached[1])
            future = self._inflight.get(handle)
            if future is None or future.done() and future.exception() is not None:
                future = self.pool.submit(self._run, handle)
                self._inflight[handle] = future
        try:
            result = future.result(timeout=self.wait_seconds)
        except FutureTimeout:
            return None
        except Exception:
            result = {"status": "verification_pending", "reason": "response_unconfirmed"}
        with self._lock:
            if self._inflight.get(handle) is future:
                del self._inflight[handle]
            if result.get("status") == "linked" and proof(result):
                self._linked[handle] = (time.monotonic(), dict(result))
        return result


def proof(result):
    """Só um vínculo ativo, confirmado e completo vira prova para o banco."""
    evidence = result.get("evidence") or {}
    if (result.get("status") != "linked" or result.get("confirmed") is not True
            or evidence.get("status") != "vinculado" or evidence.get("complete") is not True):
        return None
    value = {key: result[key] for key in ("operation", "observed_at", "status", "confirmed", "job_id", "evidence")}
    # Mesmo formato da prova que a Bia grava no atendimento: '@' + perfil.
    return {**value, "creator": "@" + result["creator"].lstrip("@")}
