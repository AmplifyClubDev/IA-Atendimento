from telegram_alerta import Telegram, juntar

TOKEN = "123456789:" + "A" * 35


def test_configuracao_valida_e_invalida():
    assert Telegram.do_ambiente({}) is None
    assert Telegram.do_ambiente({"PONTES_TELEGRAM_BOT_TOKEN": "x", "PONTES_TELEGRAM_CHAT_ID": "-100123"}) is None
    t = Telegram.do_ambiente({"PONTES_TELEGRAM_BOT_TOKEN": TOKEN, "PONTES_TELEGRAM_CHAT_ID": "-1004312404134",
                              "PONTES_TELEGRAM_THREAD_ID": "7464"})
    assert t and t.chat_id == "-1004312404134" and t.thread_id == "7464"
    assert Telegram.do_ambiente({"PONTES_TELEGRAM_BOT_TOKEN": TOKEN, "PONTES_TELEGRAM_CHAT_ID": "-100123",
                                 "PONTES_TELEGRAM_THREAD_ID": "abc"}).thread_id == ""


def test_envia_no_topico_com_passos_e_link():
    enviados = []
    t = Telegram(TOKEN, "-100123", "7464", post=lambda url, corpo: enviados.append((url, corpo)) or {"ok": True})
    assert t.enviar("🔴 Ponte pediu login", "Texto do aviso.", passos=["Abra", "Entre"], botao=("Abrir painel", "https://x/p"),
                    selo="AÇÃO", cor="#d93a3a", titulo="t")
    url, corpo = enviados[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert corpo["chat_id"] == "-100123" and corpo["message_thread_id"] == 7464
    assert corpo["text"] == "🔴 Ponte pediu login\n\nTexto do aviso.\n\n1. Abra\n2. Entre\n\nAbrir painel: https://x/p"
    assert corpo["disable_web_page_preview"] is True


def test_falha_no_telegram_nao_levanta_e_nao_bloqueia_email():
    def quebra(url, corpo):
        raise OSError("rede")
    t = Telegram(TOKEN, "-100123", post=quebra)
    assert t.enviar("a", "b") is False
    emails = []
    alertar = juntar(lambda a, b, **v: emails.append(a), t.enviar)
    alertar("assunto", "texto", selo="X")
    assert emails == ["assunto"]
    ordem = []
    juntar(lambda *a, **v: (_ for _ in ()).throw(RuntimeError()), lambda a, b, **v: ordem.append(a))("x", "y")
    assert ordem == ["x"]
    assert juntar(None, None) is None


def test_vigia_da_ponte_usa_os_dois_canais(monkeypatch):
    import cadastro_server
    env = {"PONTES_TELEGRAM_BOT_TOKEN": TOKEN, "PONTES_TELEGRAM_CHAT_ID": "-100123", "PONTES_TELEGRAM_THREAD_ID": "7464",
           "V5_TIKTOK_AGENCY_TOKEN": "t" * 40, "PONTES_LINK_SEGREDO": "s" * 40}
    vigias = cadastro_server.vigia_da_ponte(env)
    assert [v.nome for v in vigias] == ["Agenciamento"]
    enviados = []
    monkeypatch.setattr("telegram_alerta._post", lambda url, corpo, timeout=15: enviados.append(corpo) or {"ok": True})
    vigias[0].ler = lambda token: {"status": "human_login_required", "precisa_login": True}
    assert [vigias[0].checar(agora=1000 + 300 * i) for i in range(2)] == ["caida", "alertado"]
    assert len(enviados) == 1 and enviados[0]["text"].startswith("🔴 Ponte do TikTok (Agenciamento) pediu login")
    assert "/pontes/" + "s" * 40 in enviados[0]["text"]
