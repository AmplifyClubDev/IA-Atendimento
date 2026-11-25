"""Vigia das pontes do TikTok: avisa por e-mail quando alguma pede login de novo.

Em 31/10 a sessão do Partner Center caiu às 04:47 (Brasília) e só foi refeita às 12:42:
quase 11 h sem ninguém saber. A sessão é encerrada pelo próprio TikTok; o que dá para
controlar é o tempo de reação. Só lê /bridge/ready (nunca consulta creators nem convida).
Um vigia por ponte (agenciamento, pré-validação, convites); o botão do e-mail leva à página
/operacao do Cadastro, que abre o login já com a chave.
"""
from __future__ import annotations

import threading
import time

from pontes import ler_precisa_login, ler_status

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


# 25/11/2026: a ponte se reativa sozinha. Só pede o botão quando ela diz que o TikTok quer login de verdade
# (/health -> precisa_login) ou quando não volta em 45 min. Se voltar sozinha, só informa.
LIMITE_SEM_VOLTAR = 45 * 60


def _duracao(segundos):
    minutos = max(1, int(segundos / 60))
    return f"{minutos // 60} h {minutos % 60} min" if minutos >= 60 else f"{minutos} min"


class VigiaPonte:
    """Por queda: "renovou sozinha" (só informa) ou "precisa de login" (com botão) e depois "de volta"."""

    def __init__(self, token, alertar, *, nome, base="", painel="", ler=None, ler_precisa=None, confirmacoes=2,
                 limite_sem_voltar=LIMITE_SEM_VOLTAR):
        self.token, self.alertar, self.nome, self.painel = token, alertar, nome, painel
        self.ler = ler or (lambda token: {"status": ler_status(base, token, timeout=20)})
        self.ler_precisa = ler_precisa or ((lambda: ler_precisa_login(base, timeout=10)) if base else (lambda: None))
        self.confirmacoes, self.limite_sem_voltar = confirmacoes, limite_sem_voltar
        self.falhas, self.caida_desde, self.botao_enviado = 0, None, False

    def _voltou(self, agora):
        fora = _duracao(agora - self.caida_desde)
        if self.botao_enviado:
            self.alertar(f"✅ Ponte do TikTok ({self.nome}) de volta — atendimento normalizado",
                         f"O login foi refeito e a ponte {self.nome} voltou a responder às {_hora(agora)}.\n\n"
                         f"Ficou sem login por {fora}. O atendimento dessa etapa já voltou a andar.",
                         titulo="Tudo certo de novo", selo="PONTE NO AR", cor="#1f9d55")
        elif self.falhas >= self.confirmacoes:
            self.alertar(f"🔄 Ponte do TikTok ({self.nome}) renovou sozinha — nada a fazer",
                         f"A ponte {self.nome} perdeu a conexão às {_hora(self.caida_desde)} e voltou sozinha às "
                         f"{_hora(agora)}, sem precisar de login. Ficou fora por {fora}.",
                         titulo="Renovou sozinha", selo="SÓ PARA SABER", cor="#1f6fd9")

    def checar(self, agora=None):
        agora = agora or time.time()
        leitura = self.ler(self.token) or {}
        status = leitura.get("status")
        if status == "ready":
            if self.caida_desde is not None:
                self._voltou(agora)
            self.falhas, self.caida_desde, self.botao_enviado = 0, None, False
            return "ok"
        if status not in LOGIN:
            return "instavel"  # oscilação/ocupada: não alarma
        self.falhas += 1
        if self.caida_desde is None:
            self.caida_desde = agora
        if self.falhas < self.confirmacoes:
            return "caida"
        if self.botao_enviado:
            return "caida"
        precisa = leitura["precisa_login"] if "precisa_login" in leitura else self.ler_precisa()
        sem_voltar = agora - self.caida_desde >= self.limite_sem_voltar
        if precisa is not True and not sem_voltar:
            return "renovando"  # a ponte está tentando sozinha: não chama ninguém
        self.botao_enviado = True
        if precisa is True:
            assunto = f"🔴 Ponte do TikTok ({self.nome}) pediu login — faça o login para liberar os leads"
            motivo = (f"O TikTok encerrou a sessão da ponte {self.nome} às {_hora(self.caida_desde)} e a reconexão "
                      "automática não resolveu: o TikTok está pedindo login (e-mail e senha).")
        else:
            assunto = f"🔴 Ponte do TikTok ({self.nome}) não voltou sozinha — confira o painel"
            motivo = (f"A ponte {self.nome} caiu às {_hora(self.caida_desde)} e tenta voltar sozinha há "
                      f"{_duracao(agora - self.caida_desde)}, sem sucesso. Abra o painel para ver o que o TikTok está pedindo.")
        self.alertar(assunto, motivo + "\n\n"
                     + IMPACTO.get(self.nome, "Enquanto o login não for refeito, os leads ficam parados nessa etapa."),
                     titulo=f"A ponte {self.nome} precisa de você", selo="AÇÃO NECESSÁRIA", cor="#d93a3a",
                     passos=["Clique no botão abaixo: a tela de login do TikTok abre direto.",
                             "Faça o login no TikTok Shop Partner Center. Se houver opção “manter conectado”, marque.",
                             "Pronto: a ponte se ativa sozinha em até 1 minuto e você recebe outro aviso quando ela voltar."],
                     botao=("Abrir painel de login", self.painel))
        return "alertado"

    def iniciar(self, intervalo=300):
        def loop():
            while True:
                try:
                    self.checar()
                except Exception as error:
                    print(f"[cadastro-publico-v5] vigia da ponte {self.nome} indisponivel: {type(error).__name__}")
                time.sleep(intervalo)
        threading.Thread(target=loop, name="vigia-ponte-" + self.nome, daemon=True).start()
