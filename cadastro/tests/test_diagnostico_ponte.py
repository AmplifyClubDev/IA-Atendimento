import io
import json
import sqlite3
from urllib.error import HTTPError

import pytest
import diagnostico_ponte as dp
import pontes
from vigia_ponte import VigiaPonte


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("CADASTRO_STATE_PATH", str(tmp_path / "cadastro.sqlite3"))


@pytest.mark.parametrize("estado,categoria", [
    ("login_required", "login"), ("captcha_required", "captcha"),
    ("human_verification_required", "captcha"), ("mfa_required", "mfa"),
    ("partner_probe_rejected", "contexto"), ("browser_disconnected", "navegador"),
    ("inacessivel", "comunicacao"), ("oom_killed", "memoria"),
])
def test_causas_distintas_e_alerta_sem_logout_inventado(estado, categoria):
    enviados = []
    v = VigiaPonte("secret", lambda *a, **k: enviados.append((a, k)), nome="Pré-validação",
                   ler=lambda _: {"status": estado}, ler_precisa=lambda: None, limite_sem_voltar=0)
    assert v.checar(100) == "caida"
    assert v.checar(400) == "alertado"
    assert v.checar(700) == "caida"
    assert len(enviados) == 1
    assert dp.causa({"status": estado})[0] == categoria
    texto = enviados[0][0][1]
    assert "TikTok encerrou" not in texto
    assert "Sem resultado de recuperação" in texto
    v.ler = lambda _: {"status": "ready"}
    assert v.checar(1000) == "ok"
    assert "O login foi refeito" not in enviados[1][0][1]


def test_ocupada_interrompe_confirmacoes():
    estados = iter(["login_required", "busy", "login_required", "login_required"])
    v = VigiaPonte("s", lambda *a, **k: None, nome="Teste", ler=lambda _: {"status": next(estados)}, limite_sem_voltar=0)
    assert [v.checar(i * 300) for i in range(4)] == ["caida", "instavel", "caida", "alertado"]


def test_memoria_alta_e_oom_antigo_nao_provam_causa():
    d = {"status": "partner_probe_rejected", "resources": {"memoryBytes": 3999999999, "oomKillCount": 2}}
    assert dp.causa(d)[0] == "contexto"


def test_nao_grava_segredos_e_retencao(capsys):
    secreto = "https://host/#access=segredo"
    for instante in (1, 15 * 86400):
        dp.registrar("Pré-validação", "estado", {"status": "captcha_required", "token": secreto,
                     "probe": {"errorCode": secreto}, "lastContextError": {"message": secreto}}, agora=instante)
    assert secreto not in capsys.readouterr().out
    with sqlite3.connect(dp._path()) as db:
        linhas = db.execute("SELECT evidencia FROM eventos").fetchall()
    assert len(linhas) == 1 and secreto not in str(linhas)


def test_preserva_diagnostico_do_http_erro(monkeypatch):
    class Opener:
        def open(self, req, timeout):
            raise HTTPError(req.full_url, 503, "x", {}, io.BytesIO(json.dumps({
                "status": "partner_probe_rejected", "probe": {"errorCode": "captcha_required"},
                "cookie": "segredo"}).encode()))
    monkeypatch.setattr(pontes, "build_opener", lambda *a: Opener())
    d = pontes.ler_diagnostico("https://example.org", "secret")
    assert d["http"] == 503 and dp.causa(d)[0] == "captcha"
    assert "segredo" not in str(d)


def test_registra_excecao_recuperacao_sem_mensagem_sensivel(monkeypatch):
    def falha(*args):
        raise TimeoutError("token-super-secreto")
    a = pontes.Painel(pontes.PREVALIDACAO_BASE, "secret")
    monkeypatch.setattr(a, "_abrir", falha)
    with pytest.raises(TimeoutError):
        a.login()
    d = dp.ultima_recuperacao("Pré-validação", 0)
    assert d["resultado"] == "erro" and d["exceptionType"] == "TimeoutError"
    assert "token-super-secreto" not in str(d)


def test_falha_antiga_nao_vira_causa_atual(monkeypatch):
    monkeypatch.setattr(dp.time, "time", lambda: 2000)
    d = {"status": "partner_probe_rejected", "diagnostics": {"lastFailure": {"code": "oom_killed", "at": 100}}}
    assert dp.causa(d)[0] == "contexto"
    d["diagnostics"]["lastFailure"]["at"] = 2000000
    assert dp.causa(d)[0] == "memoria"


def test_login_generico_do_supervisor_nao_esconde_crash(monkeypatch):
    monkeypatch.setattr(dp.time, "time", lambda: 2000)
    d = {"status": "login_required", "diagnostics": {"lastFailure": {"code": "browser_crashed", "at": 2000000}}}
    assert dp.causa(d)[0] == "navegador"
