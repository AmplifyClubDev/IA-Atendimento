"""Vigia de falhas das pontes: causa/recuperação por evidência, sem presumir logout."""
from __future__ import annotations

import threading
import time

from pontes import ler_precisa_login, ler_diagnostico
from diagnostico_ponte import causa, registrar, resumo, ultima_recuperacao

LOGIN = {"human_login_required", "login_required", "session_or_partner_context_invalid",
         "partner_probe_rejected", "captcha_required", "mfa_required", "human_verification_required"}
FALHAS = LOGIN | {"inacessivel", "network_error", "timeout", "browser_closed", "browser_disconnected",
                  "browser_crashed", "context_closed", "oom_killed", "out_of_memory", "memory_limit_exceeded",
                  "upstream_unavailable", "browser_unavailable", "desktop_unavailable", "degraded", "credencial_invalida"}
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
        self.ler = ler or (lambda token: ler_diagnostico(base, token, timeout=20))
        self.ler_precisa = ler_precisa or ((lambda: ler_precisa_login(base, timeout=10)) if base else (lambda: None))
        self.confirmacoes, self.limite_sem_voltar = confirmacoes, limite_sem_voltar
        self.falhas, self.caida_desde, self.botao_enviado = 0, None, False
        self.ultima_evidencia, self.ultimo_estado = {}, None

    def _evidencia(self):
        d = self.ultima_evidencia
        _, descricao = causa(d)
        texto = f"Diagnóstico: {descricao}\nEstado observado: {d.get('status', 'desconhecido')}."
        code = (d.get("probe") or {}).get("errorCode") or (d.get("lastContextError") or {}).get("code")
        if code:
            texto += f" Código da checagem: {code}."
        diagnostic = d.get("diagnostics") or {}
        failure = diagnostic.get("lastFailure") or {}
        if failure:
            texto += f"\nÚltimo evento técnico: {failure.get('code', 'indeterminado')}"
            for key in ("pageClass", "httpStatus", "apiCode", "child", "exitCode", "signal", "oomKillDelta"):
                if key in failure:
                    texto += f"; {key}={failure[key]}"
            if isinstance(failure.get("at"), int):
                texto += f"; observado às {_hora(failure['at'] / 1000)} (Brasília)"
            texto += ". Evento histórico não comprova sozinho a causa desta falha."
        resources = diagnostic.get("resources") or {}
        used, limit = resources.get("memoryBytes"), resources.get("memoryLimitBytes")
        if isinstance(used, int) and isinstance(limit, int) and limit > 0:
            texto += f"\nMemória do contêiner na leitura: {used / 1e9:.2f}/{limit / 1e9:.2f} GB. Consumo alto, sozinho, não prova OOM."
        else:
            texto += "\nMemória do contêiner: sem medição disponível nesta leitura."
        recovery = diagnostic.get("lastRecovery") or {}
        local = ultima_recuperacao(self.nome, self.caida_desde or 0)
        if recovery:
            texto += f"\nÚltima recuperação interna registrada: {recovery.get('result', 'desconhecido')}"
            if isinstance(recovery.get("at"), int):
                texto += f" às {_hora(recovery['at'] / 1000)} (Brasília)"
            texto += "."
        elif local:
            texto += f"\nÚltima ação do monitor: {local.get('acao')} / {local.get('resultado')}; ação aceita não comprova sessão recuperada."
        else:
            texto += "\nSem resultado de recuperação registrado nesta leitura; não é possível afirmar que ela foi tentada ou falhou."
        return texto

    def _voltou(self, agora):
        fora = _duracao(agora - self.caida_desde)
        if self.botao_enviado:
            self.alertar(f"✅ Ponte do TikTok ({self.nome}) de volta — atendimento normalizado",
                         f"A ponte {self.nome} voltou ao estado pronto às {_hora(agora)}.\n\n"
                         f"Tempo desde a primeira falha observada: {fora}. Isso não comprova novo login.\n" + self._evidencia(),
                         titulo="Tudo certo de novo", selo="PONTE NO AR", cor="#1f9d55")
        elif self.falhas >= self.confirmacoes:
            self.alertar(f"🔄 Ponte do TikTok ({self.nome}) renovou sozinha — nada a fazer",
                         f"A falha foi observada às {_hora(self.caida_desde)}; o estado pronto voltou às "
                         f"{_hora(agora)}. Intervalo observado: {fora}.\n" + self._evidencia(),
                         titulo="Renovou sozinha", selo="SÓ PARA SABER", cor="#1f6fd9")

    def checar(self, agora=None):
        agora = time.time() if agora is None else agora
        leitura = self.ler(self.token) or {}
        dados = resumo(leitura, http=leitura.get("http"))
        status = dados["status"]
        assinatura = (status, (dados.get("probe") or {}).get("errorCode"),
                      (dados.get("lastContextError") or {}).get("code"), dados.get("http"),
                      ((dados.get("diagnostics") or {}).get("lastFailure") or {}).get("at"))
        if assinatura != self.ultimo_estado:
            registrar(self.nome, "estado", dados, agora=agora)
            self.ultimo_estado = assinatura
        if status != "ready":
            self.ultima_evidencia = dados
        if status == "ready":
            if self.caida_desde is not None:
                self._voltou(agora)
            self.falhas, self.caida_desde, self.botao_enviado = 0, None, False
            return "ok"
        precisa = None
        if status not in FALHAS:
            precisa = leitura["precisa_login"] if "precisa_login" in leitura else self.ler_precisa()
            if precisa is not True:
                if not self.botao_enviado:
                    self.falhas, self.caida_desde = 0, None
                return "instavel"
        self.falhas += 1
        if self.caida_desde is None:
            self.caida_desde = agora
        if self.falhas < self.confirmacoes:
            return "caida"
        if self.botao_enviado:
            return "caida"
        if precisa is None:
            precisa = leitura["precisa_login"] if "precisa_login" in leitura else self.ler_precisa()
        sem_voltar = agora - self.caida_desde >= self.limite_sem_voltar
        if precisa is not True and not sem_voltar:
            return "renovando"  # a ponte está tentando sozinha: não chama ninguém
        self.botao_enviado = True
        categoria, _ = causa(dados)
        if precisa is True:
            assunto = (f"🔴 Ponte do TikTok ({self.nome}) pediu login — verificar autenticação" if categoria == "login"
                       else f"🔴 Ponte do TikTok ({self.nome}) com falha — {categoria}")
            motivo = (f"A ponte informou necessidade de intervenção; primeira falha observada às {_hora(self.caida_desde)}. "
                      "Esse sinal pode significar login ou verificação humana; não comprova expiração da sessão.")
        else:
            assunto = f"🔴 Ponte do TikTok ({self.nome}) não voltou sozinha — confira o painel"
            motivo = (f"A ponte {self.nome} apresenta falha desde a leitura das {_hora(self.caida_desde)}; "
                      f"sem estado pronto por {_duracao(agora - self.caida_desde)}. A causa precisa ser avaliada pela evidência abaixo.")
        self.alertar(assunto, motivo + "\n\n" + self._evidencia() + "\n\n"
                     + "Impacto: esta etapa do atendimento pode ficar parada enquanto a ponte não estiver pronta.",
                     titulo=f"A ponte {self.nome} precisa de você", selo="AÇÃO NECESSÁRIA", cor="#d93a3a",
                     passos=["Clique no botão abaixo: a tela de login do TikTok abre direto.",
                             "Confira se há pedido de login ou desafio. Não refaça o login se a falha for de infraestrutura.",
                             "Pronto: a ponte se ativa sozinha em até 1 minuto e você recebe outro aviso quando ela voltar."],
                     botao=("Abrir painel de login" if categoria in {"login", "captcha", "mfa"} else "Abrir diagnóstico da ponte", self.painel))
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
