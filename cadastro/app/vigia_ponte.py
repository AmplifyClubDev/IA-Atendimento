"""Vigia das pontes do TikTok: avisa por e-mail quando alguma pede login de novo.

Em 31/10 a sessão do Partner Center caiu às 04:47 (Brasília) e só foi refeita às 12:42:
quase 11 h sem ninguém saber. A sessão é encerrada pelo próprio TikTok; o que dá para
controlar é o tempo de reação. Só lê /bridge/ready (nunca consulta creators nem convida).
Um vigia por ponte (agenciamento, pré-validação, convites); o botão do e-mail leva à página
/operacao do Cadastro, que abre o login já com a chave.
"""
from __future__ import annotations

from offline_policy import effects_allowed, require_effects, REASON

import threading
import time

from pontes import ler_status

LOGIN = {"human_login_required", "login_required", "session_or_partner_context_invalid",
         "partner_probe_rejected", "captcha_required", "mfa_required"}
IMPACTO = {
    "Agenciamento": "Enquanto o login não for refeito, ninguém passa da 1ª etapa do formulário "
                    "e a Bia não consegue confirmar quem aceitou o convite.",
    "Pré-validação": "Enquanto o login não for refeito, a Bia não consegue conferir o perfil (@) "
                     "dos leads novos, e eles ficam parados antes do convite.",
    "Convites": "Enquanto o login não for refeito, a Bia não consegue enviar convites de agenciamento.",
}


def _hora(instante):
    """Horário de Brasília (UTC-3) para o texto do e-mail."""
    return time.strftime("%H:%M de %d/%m", time.gmtime(instante - 3 * 3600))


class VigiaPonte:
    """Dois avisos por queda no máximo: quando cai (após 2 leituras seguidas) e quando volta."""

    def __init__(self, token, alertar, *, nome, base="", painel="", ler=None, confirmacoes=2):
        self.token, self.alertar, self.nome, self.painel = token, alertar, nome, painel
        self.ler = ler or (lambda token: {"status": ler_status(base, token, timeout=20)})
        self.confirmacoes, self.falhas, self.caida_desde = confirmacoes, 0, None

    def checar(self, agora=None):
        if not effects_allowed():
            return "disabled"
        agora = agora or time.time()
        status = (self.ler(self.token) or {}).get("status")
        if status == "ready":
            if self.caida_desde is not None:
                minutos = int((agora - self.caida_desde) / 60)
                fora = f"{minutos // 60} h {minutos % 60} min" if minutos >= 60 else f"{minutos} min"
                self.alertar(f"✅ Ponte do TikTok ({self.nome}) de volta — atendimento normalizado",
                             f"O login foi refeito e a ponte {self.nome} voltou a responder às {_hora(agora)}.\n\n"
                             f"Ficou sem login por {fora}. O atendimento dessa etapa já voltou a andar.",
                             titulo="Tudo certo de novo", selo="PONTE NO AR", cor="#1f9d55")
            self.falhas, self.caida_desde = 0, None
            return "ok"
        if status not in LOGIN:
            return "instavel"  # oscilação/ocupada: não alarma
        self.falhas += 1
        if self.falhas == self.confirmacoes and self.caida_desde is None:
            self.caida_desde = agora
            self.alertar(f"🔴 Ponte do TikTok ({self.nome}) pediu login — faça o login para liberar os leads",
                         f"O TikTok encerrou a sessão da ponte {self.nome} às {_hora(agora)} e a reconexão "
                         "automática não resolveu: o TikTok está pedindo login.\n\n"
                         + IMPACTO.get(self.nome, "Enquanto o login não for refeito, os leads ficam parados nessa etapa."),
                         titulo=f"A ponte {self.nome} precisa de login", selo="AÇÃO NECESSÁRIA", cor="#d93a3a",
                         passos=["Clique no botão abaixo: a tela de login do TikTok abre direto.",
                                 "Faça o login no TikTok Shop Partner Center. Se houver opção “manter conectado”, marque.",
                                 "Pronto: a ponte se ativa sozinha em até 1 minuto e você recebe outro e-mail quando ela voltar."],
                         botao=("Abrir painel de login", self.painel))
            return "alertado"
        return "caida"

    def iniciar(self, intervalo=300):
        if not effects_allowed():
            return {"status": "disabled", "reason": REASON}
        def loop():
            while True:
                try:
                    self.checar()
                except Exception as error:
                    print(f"[cadastro-publico-v5] vigia da ponte {self.nome} indisponivel: {type(error).__name__}")
                time.sleep(intervalo)
        threading.Thread(target=loop, name="vigia-ponte-" + self.nome, daemon=True).start()
