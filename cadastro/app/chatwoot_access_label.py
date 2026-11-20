"""Projeção da entrega confirmada na conversa do Chatwoot, sem mensagens."""
from __future__ import annotations

import os
import re
import time

import requests

ENV_LABEL = "CADASTRO_CHATWOOT_ETIQUETA_ACESSO"


def _id(value):
    ident = str(value or "")
    return ident if re.fullmatch(r"[1-9][0-9]{0,17}", ident) else None


class AccessLabel:
    def __init__(self, env=None, session=None, sleep=time.sleep):
        env = os.environ if env is None else env
        self.label = env.get(ENV_LABEL, "")
        self.base_url = env.get("CHATWOOT_BASE_URL", "").rstrip("/")
        self.account = _id(env.get("CHATWOOT_ACCOUNT_ID"))
        self.inbox = _id(env.get("CADASTRO_CHATWOOT_ETIQUETA_CAIXA", "3"))
        self.token = env.get("CHATWOOT_API_TOKEN", "")
        self.session = session
        self.sleep = sleep

    def _request(self, method, url, **kwargs):
        response = self.session.request(
            method, url, headers={"api_access_token": self.token, "Accept": "application/json"},
            timeout=2, allow_redirects=False, **kwargs,
        )
        if not 200 <= response.status_code < 300:
            raise RuntimeError("chatwoot_etiqueta_http")
        return response

    def _labels(self, conversation):
        body = self._request("GET", conversation + "/labels").json()
        labels = body.get("payload") if isinstance(body, dict) else None
        if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
            raise RuntimeError("chatwoot_etiquetas_inconfirmadas")
        return labels

    def apply(self, job):
        if not self.label:
            return "disabled"
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", self.label):
            return "invalid_label"
        cid = _id(job.get("conversation_id"))
        if not cid:
            return "no_conversation"
        if not (self.base_url.startswith("https://") and self.account and self.inbox and self.token):
            return "not_configured"
        if _id(job.get("account_id")) != self.account:
            return "unverified_conversation"
        source_owned = self.session is None
        if source_owned:
            self.session = requests.Session()
        try:
            account_url = f"{self.base_url}/api/v1/accounts/{self.account}"
            conversation = f"{account_url}/conversations/{cid}"
            detail = self._request("GET", conversation).json()
            if not isinstance(detail, dict) or (
                _id(detail.get("id")), _id(detail.get("account_id")), _id(detail.get("inbox_id"))
            ) != (cid, self.account, self.inbox):
                return "unverified_conversation"
            if self.label in self._labels(conversation):
                return "already_present"
            try:
                # A API /labels substitui a lista. A ação em lote só acrescenta
                # a etiqueta no servidor; não envie nem mesmo uma remoção vazia.
                self._request("POST", account_url + "/bulk_actions", json={
                    "type": "Conversation", "ids": [int(cid)], "labels": {"add": [self.label]},
                })
            except Exception:
                # O ACK pode se perder depois de enfileirar. Reconciliar apenas por leitura.
                pass
            for delay in (0, 0.3, 0.8):
                if delay:
                    self.sleep(delay)
                try:
                    if self.label in self._labels(conversation):
                        return "applied"
                except Exception:
                    continue
            return "pending"
        except Exception:
            return "pending"
        finally:
            if source_owned:
                self.session.close()
                self.session = None


def project_access_label(v5, event_id):
    """Uma falha visual não reabre a entrega nem decide o envio do aviso."""
    if not os.getenv(ENV_LABEL):
        return "disabled"
    try:
        target = v5.rpc("destino_etiqueta_acesso_circle_v5", {"p_evento": event_id})
        status = AccessLabel().apply(target if isinstance(target, dict) else {})
    except Exception:
        status = "pending"
    if status not in {"disabled", "applied", "already_present", "no_conversation"}:
        print(f"[cadastro] etiqueta_chatwoot={status}")
    return status
