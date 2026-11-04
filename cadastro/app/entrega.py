"""Cria o acesso no Circle depois do cadastro, com o código do worker antigo sem alteração
(`legado/cadastro_delivery.py`: Circle.provision, e-mail de boas-vindas por categoria).

Diferença do antigo: o estado vem do AmplifyOS-v5 (preparar/confirmar_entrega_circle_v5)
e a categoria é a do GMV VERIFICADO quando existir; sem ele, a do GMV declarado no formulário
e o valor lido pelo bot no print; sem nenhum, Start. Até 3 tentativas com retomada automática; depois, alerta.
"""
from __future__ import annotations

from offline_policy import effects_allowed, require_effects, REASON

import os
import re
import threading
from decimal import Decimal
from types import SimpleNamespace

from legado.cadastro_delivery import Circle, category, notify_access_released, send_welcome


class CircleComCache(Circle):
    """Circle antigo + cache de 1 h para /access_groups e /member_tags (fixos): cada entrega
    deixa de gastar essas listagens da cota mensal da API."""
    _cache, _lock = {}, threading.Lock()

    def call(self, path, method="GET", body=None, missing=False):
        # Só as boas-vindas da Amplify (decisão de 31/10): o Circle não manda o convite próprio.
        require_effects()
        if method == "POST" and path == "/community_members" and isinstance(body, dict):
            body = {**body, "skip_invitation": True}
        return super().call(path, method, body, missing)

    def records(self, path):
        require_effects()
        if path not in ("/access_groups", "/member_tags"):
            return super().records(path)
        import time
        with self._lock:
            hit = self._cache.get(path)
            if hit and time.monotonic() - hit[0] < 3600:
                return list(hit[1])
        value = super().records(path)
        with self._lock:
            self._cache[path] = (time.monotonic(), list(value))
        return value


def settings_from_env():
    env = os.environ
    from bridge_config import bridge_settings
    return SimpleNamespace(**bridge_settings(env), smtp_usuario=env.get("GMAIL_SENDER") or env.get("SMTP_USUARIO", ""),
                           smtp_senha_app=env.get("SMTP_SENHA_APP", ""),
                           email_transport=env.get("CADASTRO_EMAIL_TRANSPORT", "smtp"),
                           gmail_client_id=env.get("GMAIL_API_CLIENT_ID", ""),
                           gmail_client_secret=env.get("GMAIL_API_CLIENT_SECRET", ""),
                           gmail_refresh_token=env.get("GMAIL_API_REFRESH_TOKEN", ""))


def categoria(job, gmv_lido=None):
    """Tudo automático: GMV verificado quando existir; senão o valor que o bot leu no print;
    print ilegível -> vale o digitado; nada -> Start."""
    gmv_lido = gmv_lido if gmv_lido is not None else job.get("gmv_lido")
    if job.get("gmv_verificado") is not None:
        return category(job["gmv_verificado"])
    if gmv_lido is not None:
        return category(gmv_lido)
    return category(job["gmv_declarado"]) if job.get("gmv_declarado") is not None else "Start"


class Entrega:
    """Até 3 tentativas por cadastro (o banco controla). Uma nova tentativa só refaz o que
    falta: Circle já confirmado não é recriado; e-mail já aceito não é reenviado."""

    def __init__(self, v5, *, circle_token, settings, enabled, circle_factory=CircleComCache, send=send_welcome,
                 notify=None, alert=None):
        self.v5, self.token, self.settings, self.enabled = v5, circle_token, settings, enabled
        self.circle_factory, self.send = circle_factory, send
        self.notify = notify or notify_access_released
        self.alert = alert
        self.threads = {}
        self._lock = threading.Lock()

    def iniciar(self, event_id, on_done=None, gmv_lido=None):
        if not effects_allowed(settings=self.settings):
            return None
        if not self.enabled or not self.token:
            return None

        def run():
            result = self.executar(event_id, gmv_lido=gmv_lido)
            if on_done:
                on_done(result)
        thread = threading.Thread(target=run, name="entrega-circle", daemon=True)
        thread.start()
        self.threads[event_id] = thread
        return thread

    def executar(self, event_id, gmv_lido=None):
        if not effects_allowed(settings=self.settings):
            return {"status": "disabled", "reason": REASON}
        with self._lock:  # uma entrega por vez: poupa a cota da Circle e evita corrida com a retomada
            return self._executar(event_id, gmv_lido)

    def _executar(self, event_id, gmv_lido):
        if not effects_allowed(settings=self.settings):
            return {"status": "disabled", "reason": REASON}
        job = self.v5.rpc("preparar_entrega_circle_v5", {"p_evento": event_id})
        if not job.get("ready"):
            return {"status": job.get("reason")}

        def mark(stage, **extra):
            params = {"p_evento": event_id, "p_etapa": stage, "p_categoria": None, "p_circle_member_id": None,
                      "p_email_message_id": None, "p_motivo": None}
            return self.v5.rpc("confirmar_entrega_circle_v5", {**params, **extra})
        try:
            if job.get("circle_feito"):
                tier = job["categoria_entregue"]
            else:
                tier = categoria(job, gmv_lido)
                member_id = self.circle_factory(self.token).provision(email=job["email"], name=job["name"], tier=tier,
                                                                      before_write=lambda: None)
                mark("circle_confirmado", p_categoria=tier, p_circle_member_id=member_id)
            welcome = {"name": job["name"], "email": job["email"], "onboarding_id": event_id, "revision": 1,
                       "conversation_id": job.get("conversation_id")}
            if not job.get("email_feito"):
                message_id = self.send(self.settings, welcome, tier)
                mark("email_confirmado", p_categoria=tier, p_email_message_id=str(message_id)[:200])
            try:
                # Aviso "acesso liberado" no mesmo chat do WhatsApp (código antigo, idempotente).
                notice = self.notify(welcome)
            except Exception as error:
                notice = {"notice_status": "aviso_chatwoot_pendente", "notice_error_type": type(error).__name__}
            return {"status": "acessos_liberados", "category": tier, "email": job["email"], **notice}
        except Exception as error:
            # Mesmo critério do worker antigo: só códigos fixos, sem conteúdo externo/PII.
            reason = str(error) if type(error) is RuntimeError and re.fullmatch(r"(?:circle|smtp|gmail)_[a-z0-9_]+", str(error)) else type(error).__name__
            print(f"[cadastro-publico-v5] entrega circle falhou (tentativa {job.get('tentativa')}): {reason}")
            try:
                mark("revisao_manual", p_motivo=reason[:80])
            except Exception:
                pass
            if job.get("tentativa", 1) >= 3 and self.alert:
                self.alert(event_id, reason)
            return {"status": "revisao_manual", "reason": reason}

    def retomar_pendentes(self):
        """Refaz entregas que não terminaram (reinício do serviço, Circle lento)."""
        if not effects_allowed(settings=self.settings):
            return [{"status": "disabled", "reason": REASON}]
        if not self.enabled or not self.token:
            return []
        resultados = []
        for item in self.v5.rpc("listar_entregas_pendentes_v5", {}) or []:
            resultados.append(self.executar(item["evento"]))
        return resultados

    def iniciar_retomada(self, intervalo=300):
        if not effects_allowed(settings=self.settings):
            return {"status": "disabled", "reason": REASON}
        def loop():
            import time
            while True:
                time.sleep(intervalo)
                try:
                    self.retomar_pendentes()
                except Exception as error:
                    print(f"[cadastro-publico-v5] retomada indisponivel: {type(error).__name__}")
        threading.Thread(target=loop, name="retomada-entregas", daemon=True).start()
