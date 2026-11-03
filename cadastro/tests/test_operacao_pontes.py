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
    modos, chamadas, logado = {}, [], set()

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


@pytest.fixture
def app(monkeypatch):
    PainelFalso.modos, PainelFalso.chamadas, PainelFalso.logado = {}, [], set()
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


def test_um_clique_poe_em_login_e_vai_direto_para_a_tela_da_ponte_caida(app):
    resposta = app.test_client().get("/pontes/" + SEGREDO)
    assert resposta.status_code == 303
    assert resposta.headers["Location"] == PV + "/console/#access=console%2Fpv%2B1"
    assert PainelFalso.chamadas == [("login", PV)]


def test_duas_caidas_mostra_a_lista_sem_expor_chave(app):
    app.status[CV] = "login_required"
    pagina = app.test_client().get("/pontes/" + SEGREDO).get_data(as_text=True)
    assert pagina.count("PRECISA DE LOGIN") == 2 and pagina.count("class=\"b\"") == 2
    assert "console-cv" not in pagina and "console%2Fpv" not in pagina
    assert app.test_client().get(f"/pontes/{SEGREDO}/convites").headers["Location"] == CV + "/console/#access=console-cv"


def test_ativador_fecha_sozinho_quando_o_login_termina_e_ignora_convites():
    lista = pontes.pontes(ENV)
    PainelFalso.modos, PainelFalso.chamadas, PainelFalso.logado = {PV: "login", CV: "login"}, [], set()
    ativador = pontes.Ativador(lista, painel=PainelFalso, ler=lambda base, token: "ready")
    assert ativador.rodada() == []                 # ainda digitando: recusa e a janela continua
    PainelFalso.logado.add(PV)
    assert ativador.rodada() == [("ativada", "Pré-validação")]  # login feito: ativa sozinha
    assert ativador.rodada() == []                 # já no ar: não mexe mais
    assert ("ativar", CV) not in PainelFalso.chamadas


def test_ponte_que_cai_e_reaberta_e_ativada_sozinha_se_o_navegador_segue_logado():
    status = {AG: "ready", PV: "ready", CV: "ready"}
    PainelFalso.modos, PainelFalso.chamadas, PainelFalso.logado = {}, [], {PV}
    ativador = pontes.Ativador(pontes.pontes(ENV), painel=PainelFalso, ler=lambda base, token: status[base])
    status[PV] = "partner_probe_rejected"
    assert ativador.rodada() == []                              # 1ª leitura ruim: espera confirmar
    assert ativador.rodada() == [("reaberta", "Pré-validação")]  # 2ª: reabre o Partner Center
    assert ativador.rodada() == [("ativada", "Pré-validação")]   # navegador ainda logado: volta sozinha
    assert PainelFalso.chamadas == [("login", PV), ("ativar", PV)]


def test_oscilacao_de_uma_leitura_nao_reabre():
    status = {AG: "ready", PV: "ready", CV: "ready"}
    PainelFalso.modos, PainelFalso.chamadas, PainelFalso.logado = {}, [], set()
    ativador = pontes.Ativador(pontes.pontes(ENV), painel=PainelFalso, ler=lambda base, token: status[base])
    for leitura in ("human_login_required", "ready", "busy", "human_login_required", "ready"):
        status[PV] = leitura
        assert ativador.rodada() == []
    assert PainelFalso.chamadas == []


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


def test_convites_caida_e_reiniciada_sozinha_uma_vez_a_cada_30_min():
    status = {AG: "ready", PV: "ready", CV: "human_login_required"}
    PainelFalso.modos, PainelFalso.chamadas, PainelFalso.logado = {}, [], {CV}
    relogio = iter([1000, 1100, 1200, 1300, 1400, 1500, 4000, 4100])
    ativador = pontes.Ativador(pontes.pontes(ENV), painel=PainelFalso, ler=lambda base, token: status[base],
                               relogio=lambda: next(relogio), dormir=lambda s: None)
    assert ativador.rodada() == []                              # 1ª leitura ruim: espera confirmar
    assert ativador.rodada() == [("reiniciada", "Convites")]    # 2ª: reabre + ativa
    assert PainelFalso.chamadas == [("login", CV), ("ativar", CV)]
    PainelFalso.logado.clear()                                 # agora o TikTok pede senha de verdade
    assert ativador.rodada() == [] and ativador.rodada() == []  # dentro dos 30 min: não insiste
    assert PainelFalso.chamadas.count(("login", CV)) == 1


def test_convites_em_modo_de_login_nunca_e_mexida():
    status = {AG: "ready", PV: "ready", CV: "login_required"}
    PainelFalso.modos, PainelFalso.chamadas, PainelFalso.logado = {CV: "login"}, [], set()
    ativador = pontes.Ativador(pontes.pontes(ENV), painel=PainelFalso, ler=lambda base, token: status[base],
                               dormir=lambda s: None)
    for _ in range(4):
        assert ativador.rodada() == []
    assert PainelFalso.chamadas == []
