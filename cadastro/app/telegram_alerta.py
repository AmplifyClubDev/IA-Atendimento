"""Aviso das pontes no Telegram (grupo Aquisição HQ, tópico das pontes), 23/11/2026.

Mesmo conteúdo do e-mail do vigia, em texto simples. Usa o bot e o grupo já configurados no Cadastro:
PONTES_TELEGRAM_BOT_TOKEN, PONTES_TELEGRAM_CHAT_ID e PONTES_TELEGRAM_THREAD_ID (tópico).
Nunca levanta exceção: uma falha no Telegram não impede o e-mail.
"""
from __future__ import annotations

import json
import re
from urllib.request import ProxyHandler, Request, build_opener

_http = build_opener(ProxyHandler({}))


def _post(url, corpo, timeout=15):
    pedido = Request(url, data=json.dumps(corpo).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with _http.open(pedido, timeout=timeout) as resposta:
        return json.loads(resposta.read(65536) or b"{}")


class Telegram:
    def __init__(self, token, chat_id, thread_id="", *, post=None):
        self.token, self.chat_id, self.thread_id = token, str(chat_id), str(thread_id or "")
        self.post = post  # None: usa _post na hora do envio

    @classmethod
    def do_ambiente(cls, env):
        token = env.get("PONTES_TELEGRAM_BOT_TOKEN", "").strip()
        chat = env.get("PONTES_TELEGRAM_CHAT_ID", "").strip()
        if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", token) or not re.fullmatch(r"-?\d{5,20}", chat):
            return None
        thread = env.get("PONTES_TELEGRAM_THREAD_ID", "").strip()
        return cls(token, chat, thread if re.fullmatch(r"\d{1,12}", thread) else "")

    @staticmethod
    def texto(assunto, texto, *, passos=(), botao=None, **_visual):
        partes = [assunto, texto]
        if passos:
            partes.append("\n".join(f"{i}. {p}" for i, p in enumerate(passos, 1)))
        if botao and botao[1]:
            partes.append(f"{botao[0]}: {botao[1]}")
        return "\n\n".join(partes)[:4000]

    def enviar(self, assunto, texto, **visual):
        corpo = {"chat_id": self.chat_id, "text": self.texto(assunto, texto, **visual),
                 "disable_web_page_preview": True}
        if self.thread_id:
            corpo["message_thread_id"] = int(self.thread_id)
        try:
            resposta = (self.post or _post)(f"https://api.telegram.org/bot{self.token}/sendMessage", corpo)
            return isinstance(resposta, dict) and resposta.get("ok") is True
        except Exception as error:
            print(f"[cadastro-publico-v5] telegram indisponivel: {type(error).__name__}")
            return False


def juntar(*canais):
    """Um alerta só, entregue em todos os canais configurados; um canal com erro não bloqueia os outros."""
    ativos = [c for c in canais if c]
    if not ativos:
        return None

    def alertar(assunto, texto, **visual):
        for canal in ativos:
            try:
                canal(assunto, texto, **visual)
            except Exception as error:
                print(f"[cadastro-publico-v5] canal de alerta indisponivel: {type(error).__name__}")
    return alertar
