import pytest
from flask import Flask

import pontes

SEGREDO = "x" * 40
ENV = {"PONTES_LINK_SEGREDO": SEGREDO,
       "V5_TIKTOK_AGENCY_TOKEN": "a" * 40, "PONTE_AGENCIAMENTO_CONSOLE_TOKEN": "console-ag",
       "PONTE_PREVALIDACAO_TOKEN": "p" * 40, "PONTE_PREVALIDACAO_CONSOLE_TOKEN": "console/pv+1",
       "PONTE_CONVITES_TOKEN": "c" * 40, "PONTE_CONVITES_CONSOLE_TOKEN": "console-cv"}
AG, PV, CV = (f"https://tiktok-{n}-production.up.railway.app" for n in ("agenciamento", "pre-validacao", "partner-bridge"))


class PainelFalso:
    # modos: modo do console por ponte; logado: navegador ainda logado (ativar funciona);
    # situacoes: o que Painel.situacao() devolve; reconciliar: pontes com reconciliação pendente.
    modos, chamadas, logado, situacoes, reconciliar = {}, [], set(), {}, set()

    def __init__(self, base, chave, timeout=120):
        self.base = base

    def modo(self):
        return self.modos.get(self.base, "bridge")

    def login(self):
        self.chamadas.append(("login", self.base)); self.modos[self.base] = "login"; return True

    def ativar(self):
        self.chamadas.append(("ativar", self.base))
        if self.base in self.logado:
            self.modos[self.base] = "bridge"; return True
        return False

    def confirmar_pronta(self):
        self.chamadas.append(("confirmar", self.base)); self.reconciliar.discard(self.base)

    def requer_reconciliacao(self):
        return self.base in self.reconciliar

    def situacao(self):
        return dict(self.situacoes.get(self.base, {"erro": None, "aguardar": 0}))


def _zerar(modos=None, logado=None):
    PainelFalso.modos, PainelFalso.chamadas, PainelFalso.logado = modos or {}, [], logado or set()
    PainelFalso.situacoes, PainelFalso.reconciliar = {}, set()


@pytest.fixture
def app(monkeypatch):
    _zerar()
    status = {AG: "ready", PV: "human_login_required", CV: "ready"}
    monkeypatch.setattr(pontes, "ler_status", lambda base, token, timeout=10: status[base])
    monkeypatch.setattr(pontes, "Painel", PainelFalso)
    app = Flask(__name__)
    pontes.registrar(app, env=ENV)
    app.status = status
    return app


def test_link_errado_ou_sem_segredo_nao_existe(app):
    client = app.test_client()
    assert client.get("/pontes/" + "y" * 40).status_code == 404
    assert client.get("/operacao").status_code == 404


def test_painel_so_observa_e_abrir_o_console_e_um_clique_explicito(app):
    client = app.test_client()
    resposta = client.get("/pontes/" + SEGREDO)
    pagina = resposta.get_data(as_text=True)
    # O GET do painel só mostra o estado: não redireciona nem clica em login/ativar.
    assert resposta.status_code == 200
    assert pagina.count("PRECISA DE LOGIN") == 1 and pagina.count("NO AR") == 2
    assert f'href="/pontes/{SEGREDO}/prevalidacao"' in pagina and "Fazer login" in pagina
    assert pagina.count('class="b"') == 1                    # só a ponte caída tem botão
    assert "console%2Fpv" not in pagina and "console/pv+1" not in pagina
    assert PainelFalso.chamadas == []
    # Abrir o console é a ação explícita: leva direto à tela da ponte caída, ainda sem login automático.
    abrir = client.get(f"/pontes/{SEGREDO}/prevalidacao")
    assert abrir.status_code == 303
    assert abrir.headers["Location"] == PV + "/console/#access=console%2Fpv%2B1"
    assert abrir.headers["Cache-Control"] == "no-store" and abrir.headers["Referrer-Policy"] == "no-referrer"
    assert PainelFalso.chamadas == []


def test_duas_caidas_mostra_a_lista_sem_expor_chave(app):
    app.status[CV] = "login_required"
    pagina = app.test_client().get("/pontes/" + SEGREDO).get_data(as_text=True)
    assert pagina.count("PRECISA DE LOGIN") == 2 and pagina.count("class=\"b\"") == 2
    assert "console-cv" not in pagina and "console%2Fpv" not in pagina
    assert "Em Convites, a ativação é manual." in pagina
    assert app.test_client().get(f"/pontes/{SEGREDO}/convites").headers["Location"] == CV + "/console/#access=console-cv"
    assert PainelFalso.chamadas == []


def test_console_em_espera_nao_redireciona_e_informa_o_retry_after(app):
    PainelFalso.situacoes[PV] = {"erro": "rate_limited", "aguardar": 120}
    client = app.test_client()
    pagina = client.get("/pontes/" + SEGREDO).get_data(as_text=True)
    assert "Aguarde 120 s" in pagina and 'class="b"' not in pagina   # bloqueado: sem botão
    resposta = client.get(f"/pontes/{SEGREDO}/prevalidacao")
    assert resposta.status_code == 429 and resposta.headers["Retry-After"] == "120"
    assert "Location" not in resposta.headers and "console/pv" not in resposta.get_data(as_text=True)


def test_reconciliacao_pendente_mostra_conectar_e_ainda_abre_o_console(app):
    PainelFalso.situacoes[PV] = {"erro": "requires_reconciliation", "aguardar": 1}
    client = app.test_client()
    pagina = client.get("/pontes/" + SEGREDO).get_data(as_text=True)
    assert "Conectar" in pagina and "Conclua a verificação" in pagina
    assert client.get(f"/pontes/{SEGREDO}/prevalidacao").status_code == 303


def test_ativador_fecha_sozinho_quando_o_login_termina_e_ignora_convites():
    lista = pontes.pontes(ENV)
    _zerar(modos={PV: "login", CV: "login"})
    ativador = pontes.Ativador(lista, painel=PainelFalso, ler=lambda base, token: "ready")
    assert ativador.rodada() == []                 # ainda digitando: recusa e a janela continua
    PainelFalso.logado.add(PV)
    assert ativador.rodada() == [("ativada", "Pré-validação")]  # login feito: ativa sozinha
    assert ativador.rodada() == []                 # já no ar: não mexe mais
    assert ("ativar", CV) not in PainelFalso.chamadas


def test_ponte_que_cai_e_reaberta_e_ativada_sozinha_se_o_navegador_segue_logado():
    status = {AG: "ready", PV: "ready", CV: "ready"}
    _zerar(logado={PV})
    ativador = pontes.Ativador(pontes.pontes(ENV), painel=PainelFalso, ler=lambda base, token: status[base])
    assert ativador.rodada() == []                              # no ar: só confirma a prontidão
    assert PainelFalso.chamadas == [("confirmar", PV)]
    PainelFalso.chamadas.clear()
    status[PV] = "partner_probe_rejected"
    assert ativador.rodada() == []                              # 1ª leitura ruim: espera confirmar
    assert ativador.rodada() == [("reaberta", "Pré-validação")]  # 2ª: reabre o Partner Center
    assert ativador.rodada() == [("ativada", "Pré-validação")]   # navegador ainda logado: volta sozinha
    assert PainelFalso.chamadas == [("login", PV), ("ativar", PV)]


def test_prevalidacao_com_reconciliacao_pendente_nao_reabre_login_ate_ficar_pronta():
    status = {AG: "ready", PV: "partner_probe_rejected", CV: "ready"}
    _zerar()
    PainelFalso.reconciliar.add(PV)
    ativador = pontes.Ativador(pontes.pontes(ENV), painel=PainelFalso, ler=lambda base, token: status[base])
    for _ in range(4):
        assert ativador.rodada() == []                          # pendente: nunca inicia outro login
    assert PainelFalso.chamadas == []
    status[PV] = "ready"
    assert ativador.rodada() == []                              # readiness confirmada limpa a pendência
    assert PainelFalso.chamadas == [("confirmar", PV)] and PV not in PainelFalso.reconciliar
    status[PV] = "partner_probe_rejected"
    assert ativador.rodada() == [] and ativador.rodada() == [("reaberta", "Pré-validação")]


def test_oscilacao_de_uma_leitura_nao_reabre():
    status = {AG: "ready", PV: "ready", CV: "ready"}
    _zerar()
    ativador = pontes.Ativador(pontes.pontes(ENV), painel=PainelFalso, ler=lambda base, token: status[base])
    for leitura in ("human_login_required", "ready", "busy", "human_login_required", "ready"):
        status[PV] = leitura
        assert ativador.rodada() == []
    assert [c for c in PainelFalso.chamadas if c[0] != "confirmar"] == []


def test_link_do_email():
    assert pontes.link(ENV) == "https://amplify-cadastro.up.railway.app/pontes/" + SEGREDO
    assert pontes.link({}) == ""


def test_bia_respondendo_com_ponte_lenta_nao_e_fora_do_ar(monkeypatch):
    import io
    from urllib.error import HTTPError
    import vigia_atendimento as va

    def resposta(corpo, code):
        def _get(url, headers=None, timeout=30):
            raise HTTPError(url, code, "x", {}, io.BytesIO(corpo))
        return _get
    monkeypatch.setattr(va, "_get", resposta(b'{"ready": false, "issues": ["real_tiktok_sessions_unverified"]}', 503))
    assert va._bia_pronta() == (True, "real_tiktok_sessions_unverified")
    monkeypatch.setattr(va, "_get", resposta(b"<html>Application failed to respond</html>", 502))
    assert va._bia_pronta() == (False, "HTTP 502")


def test_convites_caida_nunca_e_reiniciada_sozinha():
    status = {AG: "ready", PV: "ready", CV: "human_login_required"}
    _zerar(logado={CV})                                         # mesmo com o navegador logado
    relogio = iter(range(1000, 100000, 1000))                   # passa muito mais de 30 min
    ativador = pontes.Ativador(pontes.pontes(ENV), painel=PainelFalso, ler=lambda base, token: status[base],
                               relogio=lambda: next(relogio), dormir=lambda s: None)
    for _ in range(6):
        assert ativador.rodada() == []                          # ativação de Convites é manual
    assert [c for c in PainelFalso.chamadas if c[1] == CV] == []


def test_convites_em_modo_de_login_nunca_e_mexida():
    status = {AG: "ready", PV: "ready", CV: "login_required"}
    _zerar(modos={CV: "login"})
    ativador = pontes.Ativador(pontes.pontes(ENV), painel=PainelFalso, ler=lambda base, token: status[base],
                               dormir=lambda s: None)
    for _ in range(4):
        assert ativador.rodada() == []
    assert [c for c in PainelFalso.chamadas if c[1] == CV] == []
