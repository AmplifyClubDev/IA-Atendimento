"""Vigia dos atendimentos da Bia: e-mail à equipe só quando a MÁQUINA erra.

A cada 10 min, só leitura (nunca responde nem mexe no atendimento):
- lead sem resposta: conversa aberta da caixa da Bia, sem responsável humano, cuja última mensagem
  é do lead há mais de 30 min (e menos de 24 h). A Bia responde todo lead em segundos e reprocessa
  quem ficou sem resposta a cada minuto; 30 min sem resposta é erro da máquina;
- Bia fora do ar: sem resposta do /ready em 2 leituras seguidas (e um aviso quando volta).
Não avisa lead esperando a si mesmo (convite pendente, Shop sem status, conversa parada): isso é
trabalho da retomada, não erro. O que já foi avisado fica gravado em disco: reiniciar o serviço
não repete o e-mail.
"""
from __future__ import annotations

import json
import threading
import time
from urllib.request import ProxyHandler, Request, build_opener

MINUTOS, JANELA = 30, 24 * 3600
BIA_READY = "https://atendimento-v5-ensaio-production.up.railway.app/ready"


def _hora(instante):
    return time.strftime("%H:%M de %d/%m", time.gmtime(instante - 3 * 3600))


def _get(url, headers=None, timeout=30):
    with build_opener(ProxyHandler({})).open(Request(url, headers=headers or {}), timeout=timeout) as response:
        return json.loads(response.read(4_000_000))


class Chatwoot:
    def __init__(self, base, conta, token, caixa=3):
        self.base, self.conta, self.token, self.caixa = base.rstrip("/"), conta, token, caixa

    def link(self, conversa):
        return f"{self.base}/app/accounts/{self.conta}/conversations/{conversa}"

    def sem_resposta(self, agora):
        """Conversas abertas cuja última mensagem (não de sistema) é do lead, entre 30 min e 24 h atrás."""
        achadas = []
        for pagina in range(1, 6):
            dados = _get(f"{self.base}/api/v1/accounts/{self.conta}/conversations?inbox_id={self.caixa}&status=open"
                         f"&sort_by=last_activity_at_desc&page={pagina}", {"api_access_token": self.token})
            conversas = (dados.get("data") or {}).get("payload") or []
            for c in conversas:
                if (c.get("meta") or {}).get("assignee"):
                    continue  # conversa com atendente humano não é da Bia
                ultima = c.get("last_non_activity_message") or {}
                quando = ultima.get("created_at") or 0
                if ultima.get("message_type") == 0 and not ultima.get("private") and \
                        agora - JANELA < quando < agora - MINUTOS * 60:
                    achadas.append({"conversa": c["id"], "desde": quando})
            if not conversas or (conversas[-1].get("last_activity_at") or 0) < agora - JANELA:
                break
        return achadas


def _bia_pronta():
    """Fora do ar = a Bia não responde (sem conexão, 502/504, tempo esgotado).

    Um 503 com o corpo do /ready é a Bia respondendo com alguma ponte do TikTok não confirmada:
    isso já tem o alerta das pontes, e a Bia segue recebendo as mensagens (em 02/11 às 18:02 foi assim).
    """
    try:
        dados = _get(BIA_READY, timeout=20)
        return True, ", ".join(dados.get("issues") or [])
    except Exception as error:
        if getattr(error, "code", None) == 503:
            try:
                corpo = json.loads(error.read(65536))
                if isinstance(corpo, dict) and "issues" in corpo:
                    return True, ", ".join(corpo.get("issues") or [])
            except Exception:
                pass
        return False, f"HTTP {error.code}" if getattr(error, "code", None) else type(error).__name__


class VigiaAtendimento:
    def __init__(self, alertar, *, chatwoot, bia=_bia_pronta, confirmacoes=2, arquivo=None):
        self.alertar, self.chatwoot, self.bia, self.arquivo = alertar, chatwoot, bia, arquivo
        self.avisadas, self.confirmacoes, self.falhas_bia, self.bia_fora_desde = set(), confirmacoes, 0, None
        try:
            salvo = json.loads(open(arquivo, encoding="utf-8").read()) if arquivo else {}
            self.avisadas = {int(c) for c in salvo.get("avisadas", [])}
            self.bia_fora_desde = salvo.get("bia_fora_desde")
        except (OSError, ValueError, TypeError):
            pass

    def _gravar(self):
        if not self.arquivo:
            return
        try:
            with open(self.arquivo, "w", encoding="utf-8") as f:
                json.dump({"avisadas": sorted(self.avisadas), "bia_fora_desde": self.bia_fora_desde}, f)
        except OSError:
            pass

    def checar(self, agora=None):
        agora = agora or time.time()
        feitos = []
        pronta, motivo = self.bia()
        if pronta:
            if self.bia_fora_desde is not None:
                self.alertar("✅ Bia de volta — atendimento respondendo",
                             f"A Bia voltou a responder às {_hora(agora)}.",
                             titulo="A Bia voltou", selo="BIA NO AR", cor="#1f9d55")
                feitos.append("bia_voltou")
            self.falhas_bia, self.bia_fora_desde = 0, None
        else:
            self.falhas_bia += 1
            if self.falhas_bia == self.confirmacoes and self.bia_fora_desde is None:
                self.bia_fora_desde = agora
                self.alertar("🔴 Bia fora do ar — leads sem resposta",
                             f"A Bia não está pronta desde {_hora(agora)}.\n\nMotivo informado: {motivo or 'sem resposta'}.\n\n"
                             "Enquanto isso, as mensagens dos leads ficam sem resposta.",
                             titulo="A Bia está fora do ar", selo="AÇÃO NECESSÁRIA", cor="#d93a3a")
                feitos.append("bia_fora")

        itens = {s["conversa"]: s["desde"] for s in self.chatwoot.sem_resposta(agora)}
        novos = {c: d for c, d in itens.items() if c not in self.avisadas}
        self.avisadas &= set(itens)  # respondidos saem; se voltarem a ficar sem resposta, avisa de novo
        if novos:
            linhas = [f"Conversa {c}: mensagem do lead sem resposta desde {_hora(d)} — {self.chatwoot.link(c)}"
                      for c, d in sorted(novos.items())]
            self.alertar(f"🔴 Erro da Bia: {len(novos)} lead(s) sem resposta",
                         f"A Bia não respondeu estes leads há mais de {MINUTOS} min (ela responde em segundos "
                         "e tenta de novo a cada minuto):\n\n" + "\n".join(linhas)
                         + "\n\nPara ver o motivo: /diagnostico/conversa/<conversa> na Bia.",
                         titulo="Leads sem resposta da Bia", selo="ERRO DA MÁQUINA", cor="#d93a3a")
            self.avisadas |= set(novos)
            feitos.append(("sem_resposta", len(novos)))
        self._gravar()
        return feitos

    def iniciar(self, intervalo=600):
        def loop():
            while True:
                try:
                    self.checar()
                except Exception as error:
                    print(f"[cadastro-publico-v5] vigia dos atendimentos indisponivel: {type(error).__name__}")
                time.sleep(intervalo)
        threading.Thread(target=loop, name="vigia-atendimento", daemon=True).start()
