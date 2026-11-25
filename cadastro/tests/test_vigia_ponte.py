"""Vigia das pontes: avisos de queda, renovação sozinha e login (25/11/2026)."""


def _vigia(respostas, precisa=None, **kw):
    from vigia_ponte import VigiaPonte
    respostas, alertas = iter(respostas), []
    vigia = VigiaPonte("t" * 40, lambda assunto, texto, **visual: alertas.append((assunto, visual.get("botao"))),
                       nome="Pré-validação", painel="https://cadastro/operacao", ler=lambda token: {"status": next(respostas)},
                       ler_precisa=lambda: precisa, **kw)
    return vigia, alertas


def test_vigia_avisa_quando_a_ponte_pede_login_e_quando_volta():
    vigia, alertas = _vigia(["ready", "human_login_required", "human_login_required", "human_login_required", "busy",
                             "ready", "ready"], precisa=True)
    resultados = [vigia.checar(agora=1000 + 300 * i) for i in range(7)]
    assert resultados == ["ok", "caida", "alertado", "caida", "instavel", "ok", "ok"]
    assert alertas[0][0].startswith("🔴 Ponte do TikTok (Pré-validação) pediu login")
    assert alertas[0][1] == ("Abrir painel de login", "https://cadastro/operacao")
    assert alertas[1][0].startswith("✅ Ponte do TikTok (Pré-validação) de volta") and len(alertas) == 2


def test_vigia_so_informa_quando_a_ponte_renova_sozinha():
    """25/11/2026: a ponte caiu e voltou sozinha: um aviso só, sem botão."""
    vigia, alertas = _vigia(["ready", "login_required", "login_required", "login_required", "ready"], precisa=False)
    resultados = [vigia.checar(agora=1000 + 300 * i) for i in range(5)]
    assert resultados == ["ok", "caida", "renovando", "renovando", "ok"]
    assert len(alertas) == 1 and alertas[0][1] is None
    assert alertas[0][0].startswith("🔄 Ponte do TikTok (Pré-validação) renovou sozinha")


def test_vigia_nao_avisa_oscilacao_de_uma_leitura():
    vigia, alertas = _vigia(["ready", "login_required", "ready"], precisa=False)
    assert [vigia.checar(agora=1000 + 300 * i) for i in range(3)] == ["ok", "caida", "ok"]
    assert alertas == []


def test_vigia_manda_o_botao_se_nao_voltar_em_45_min():
    vigia, alertas = _vigia(["login_required"] * 10 + ["ready"], precisa=None)
    resultados = [vigia.checar(agora=1000 + 300 * i) for i in range(11)]
    assert resultados[:9] == ["caida"] + ["renovando"] * 8
    assert resultados[9:] == ["alertado", "ok"]
    assert alertas[0][0].startswith("🔴 Ponte do TikTok (Pré-validação) não voltou sozinha")
    assert alertas[0][1] == ("Abrir painel de login", "https://cadastro/operacao")
    assert alertas[1][0].startswith("✅ Ponte do TikTok (Pré-validação) de volta") and len(alertas) == 2


def test_le_precisa_login_do_health_publico():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pontes import ler_precisa_login
    corpos = iter([b'{"ok":true,"precisa_login":true}', b'{"ok":true}', b'nao e json'])

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            corpo = next(corpos)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *a):
            pass
    servidor = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}"
    try:
        assert [ler_precisa_login(base, timeout=5) for _ in range(3)] == [True, None, None]
    finally:
        servidor.shutdown()
