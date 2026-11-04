"""Pontes do TikTok: um link só para refazer o login, e a ponte se ativa sozinha depois.

- O link (`/pontes/<PONTES_LINK_SEGREDO>`) mostra as 3 pontes. Ao abrir, toda ponte que pediu
  login já é posta em modo de login (o navegador dela abre o Partner Center); se só uma caiu,
  o link vai direto para a tela de login dela.
- As chaves dos painéis ficam nas variáveis do Railway (referências às próprias pontes) e nunca
  aparecem na página: o redirecionamento leva a chave depois do "#", que não sai do navegador.
- Ativador: enquanto uma ponte está em modo de login, tenta ativar a cada 30 s. Nas pontes de
  agenciamento e pré-validação o "ativar" só confere a sessão já aberta (lista 1 relação) e,
  sem login, recusa sem fechar a janela; então a ponte fecha sozinha quando o login termina.
  A ponte de convites roda uma versão em que ativar fecha a janela: nela o ativador fica desligado.
"""
from __future__ import annotations

from bridge_config import bridge_origin, activation_allowed
import hmac
import html
import http.cookiejar
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

from flask import Blueprint, abort, current_app, make_response, redirect

bp = Blueprint("operacao", __name__)

# chave, nome, endereço, variável do token de leitura, variável da chave do painel, ativa sozinha
PONTES = (
    ("agenciamento", "Agenciamento", "https://tiktok-agenciamento-production.up.railway.app",
     "V5_TIKTOK_AGENCY_TOKEN", "PONTE_AGENCIAMENTO_CONSOLE_TOKEN", True),
    ("prevalidacao", "Pré-validação", "https://tiktok-pre-validacao-production.up.railway.app",
     "PONTE_PREVALIDACAO_TOKEN", "PONTE_PREVALIDACAO_CONSOLE_TOKEN", True),
    ("convites", "Convites", "https://tiktok-partner-bridge-production.up.railway.app",
     "PONTE_CONVITES_TOKEN", "PONTE_CONVITES_CONSOLE_TOKEN", False),
)
LOGIN = {"human_login_required", "login_required", "session_or_partner_context_invalid",
         "partner_probe_rejected", "captcha_required", "mfa_required", "human_verification_required"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ler_status(base, token, timeout=10):
    """status do /bridge/ready; a ponte que pede login responde erro HTTP com o status no corpo."""
    request_ = Request(base + "/bridge/ready", headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    try:
        with build_opener(_NoRedirect(), ProxyHandler({})).open(request_, timeout=timeout) as response:
            return json.loads(response.read(65536)).get("status") or "desconhecido"
    except Exception as error:
        try:
            return json.loads(error.read(65536)).get("status") or "desconhecido"
        except Exception:
            return "inacessivel"


class Painel:
    """Cliente do /console da ponte (o mesmo que os botões do painel usam)."""

    def __init__(self, base, chave, timeout=120):
        self.base, self.chave, self.timeout = base, chave, timeout

    def _abrir(self, path, method="GET"):
        opener = build_opener(_NoRedirect(), ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        origem = {"Origin": self.base}
        opener.open(Request(self.base + "/console/session", method="POST",
                            headers={**origem, "Authorization": "Bearer " + self.chave}), timeout=20).read()
        try:
            with opener.open(Request(self.base + path, method=method, headers=origem), timeout=self.timeout) as response:
                return response.status, json.loads(response.read(65536) or b"{}")
        except Exception as error:
            return getattr(error, "code", 0), {}

    def modo(self):
        status, corpo = self._abrir("/console/status")
        return (corpo.get("process") or {}).get("mode") if status == 200 else None

    def login(self):
        return self._abrir("/console/login", "POST")[0] == 200

    def ativar(self):
        return self._abrir("/console/activate", "POST")[0] == 200


def pontes(env=None):
    env = env if env is not None else os.environ
    roles = {"agenciamento": "agency", "prevalidacao": "precheck", "convites": "invites"}
    result = []
    for k, n, b, t, c, a in PONTES:
        base = bridge_origin(env, roles[k], b)
        if base:
            result.append({"chave": k, "nome": n, "base": base, "token": env.get(t, ""),
                           "console": env.get(c, "") if activation_allowed(env) else "", "ativa_sozinha": a})
    return result


class Ativador:
    """A cada 30 s, cuida sozinho das pontes que reabrem sem fechar a janela (agenciamento e pré-validação).

    - Ponte pedindo login por 2 leituras seguidas: reabre o Partner Center no navegador dela (modo de
      login). Se o TikTok ainda reconhece o navegador, a página abre logada e a próxima rodada ativa;
      só quando o TikTok pede senha de verdade é que a ponte segue fora e o vigia manda o e-mail.
    - Ponte em modo de login: tenta ativar (sem login, recusa e a janela continua aberta).

    A ponte de Convites (versão antiga) não tem o "ativar" que só confere: lá ativar reinicia a ponte.
    Para ela, só com a ponte em modo normal e pedindo login por 2 leituras: reabre e reinicia na hora
    (o mesmo que "Recuperar autenticação" + "Concluí"). Se o navegador seguia logado, ela volta sozinha.
    Nunca mexe nela em modo de login (alguém pode estar digitando) e espera 30 min entre tentativas.
    """

    def __init__(self, lista, *, painel=Painel, ler=None, intervalo=30, confirmacoes=2, espera_reinicio=1800,
                 relogio=time.time, dormir=time.sleep):
        self.pontes = [(p["nome"], p["base"], p["token"], painel(p["base"], p["console"]), p["ativa_sozinha"])
                       for p in lista if p["console"] and p["token"]]
        self.ler = ler or (lambda base, token: ler_status(base, token))
        self.intervalo, self.confirmacoes, self.falhas = intervalo, confirmacoes, {}
        self.espera_reinicio, self.relogio, self.dormir, self.ultimo_reinicio = espera_reinicio, relogio, dormir, {}

    def _reiniciar(self, nome, painel):
        """Ponte antiga: reabrir + ativar seguidos, no máximo 1 vez a cada 30 min."""
        agora = self.relogio()
        if agora - self.ultimo_reinicio.get(nome, -self.espera_reinicio) < self.espera_reinicio:
            return None
        self.ultimo_reinicio[nome] = agora
        if not painel.login():
            return None
        self.dormir(20)  # o navegador abre o Partner Center com o perfil salvo
        ok = painel.ativar()
        print(f"[cadastro-publico-v5] ponte {nome} pediu login; reiniciada sozinha ({'ok' if ok else 'sem sucesso'})")
        return ("reiniciada", nome) if ok else ("reinicio_sem_sucesso", nome)

    def rodada(self):
        feitos = []
        for nome, base, token, painel, ativa_sozinha in self.pontes:
            modo = painel.modo()
            if not ativa_sozinha:
                if modo != "bridge":
                    self.falhas[nome] = 0  # em modo de login fica com quem está fazendo o login
                    continue
                self.falhas[nome] = self.falhas.get(nome, 0) + 1 if self.ler(base, token) in LOGIN else 0
                if self.falhas[nome] >= self.confirmacoes:
                    feito = self._reiniciar(nome, painel)
                    if feito:
                        self.falhas[nome] = 0
                        feitos.append(feito)
                continue
            if modo == "login":
                self.falhas[nome] = 0
                if painel.ativar():
                    feitos.append(("ativada", nome))
                    print(f"[cadastro-publico-v5] ponte {nome} ativada sozinha")
                continue
            if modo != "bridge":
                continue
            self.falhas[nome] = self.falhas.get(nome, 0) + 1 if self.ler(base, token) in LOGIN else 0
            if self.falhas[nome] >= self.confirmacoes and painel.login():
                self.falhas[nome] = 0
                feitos.append(("reaberta", nome))
                print(f"[cadastro-publico-v5] ponte {nome} pediu login; Partner Center reaberto sozinho")
        return feitos

    def iniciar(self):
        def loop():
            while True:
                try:
                    self.rodada()
                except Exception as error:
                    print(f"[cadastro-publico-v5] ativador das pontes indisponivel: {type(error).__name__}")
                time.sleep(self.intervalo)
        threading.Thread(target=loop, name="ativador-pontes", daemon=True).start()


def _cfg():
    return current_app.extensions["operacao"]


def _pagina(corpo, status=200, *, recarregar=False):
    meta = '<meta http-equiv="refresh" content="20">' if recarregar else ""
    response = make_response('''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">''' + meta + '''<title>Pontes do TikTok</title>
<style>body{margin:0;background:#f4f6fc;font-family:Arial,sans-serif;color:#14213b}
.w{max-width:560px;margin:0 auto;padding:24px 16px}.h{background:#2148d4;color:#fff;border-radius:20px 20px 0 0;padding:22px 24px}
.h b{font-size:26px}.h span{display:block;font-size:11px;letter-spacing:3px}.c{background:#fff;border:1px solid #e0e6f0;border-top:0;border-radius:0 0 20px 20px;padding:22px 24px}
.p{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 0;border-bottom:1px solid #eef1f7}.p:last-of-type{border-bottom:0}
.s{display:inline-block;font-size:12px;font-weight:bold;padding:5px 10px;border-radius:999px;color:#fff}.ok{background:#1f9d55}.no{background:#d93a3a}
a.b{display:inline-block;background:#2148d4;color:#fff;border-radius:12px;padding:12px 18px;font-size:15px;font-weight:bold;text-decoration:none}
small{color:#64728a;line-height:1.5}</style></head>
<body><div class="w"><div class="h"><b>amplify</b><span>OPERAÇÃO · PONTES DO TIKTOK</span></div><div class="c">''' + corpo + "</div></div></body></html>", status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    return response


def _conferir(segredo):
    esperado = _cfg()["segredo"]
    if not esperado or len(esperado) < 32 or not hmac.compare_digest(segredo.encode(), esperado.encode()):
        abort(404)


def _destino(ponte):
    return ponte["base"] + "/console/#access=" + quote(ponte["console"], safe="")


@bp.get("/pontes/<segredo>")
def painel(segredo):
    _conferir(segredo)
    lista = [p for p in pontes(_cfg()["env"]) if p["token"]]
    if not lista:
        return _pagina("<p>Pontes desabilitadas ou não configuradas neste ambiente.</p>", status=503)
    with ThreadPoolExecutor(len(lista)) as pool:
        status = list(pool.map(lambda p: ler_status(p["base"], p["token"]), lista))
    caidas = [p for p, s in zip(lista, status) if s != "ready"]
    for ponte in caidas:  # já deixa o navegador da ponte aberto na tela de login do TikTok
        if ponte["console"] and Painel(ponte["base"], ponte["console"], timeout=60).modo() != "login":
            Painel(ponte["base"], ponte["console"], timeout=60).login()
    if len(caidas) == 1 and caidas[0]["console"]:
        response = redirect(_destino(caidas[0]), code=303)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
    linhas = ""
    for p, s in zip(lista, status):
        no_ar = s == "ready"
        selo = '<span class="s ok">NO AR</span>' if no_ar else '<span class="s no">PRECISA DE LOGIN</span>'
        botao = "" if no_ar or not p["console"] else f'<a class="b" href="/pontes/{quote(segredo)}/{p["chave"]}" target="_blank" rel="noreferrer">Fazer login</a>'
        linhas += f'<div class="p"><div><b>{html.escape(p["nome"])}</b><br>{selo}</div>{botao}</div>'
    topo = ("Todas as pontes configuradas estão no ar. ✅" if not caidas else
            "Clique em <b>Fazer login</b> e entre no TikTok na janela que abrir. A ponte se ativa sozinha "
            "quando o login termina (na de Convites, clique em “Concluí a verificação — ativar”).")
    if caidas and not any(p["console"] for p in caidas):
        topo = "Há pontes indisponíveis. Login e ativação estão desabilitados ou não configurados neste ambiente."
    return _pagina(f"<p>{topo}</p>{linhas}<p><small>Esta página se atualiza sozinha.</small></p>", recarregar=bool(caidas))


@bp.get("/pontes/<segredo>/<chave>")
def abrir(segredo, chave):
    _conferir(segredo)
    ponte = next((p for p in pontes(_cfg()["env"]) if p["chave"] == chave and p["console"]), None)
    if ponte is None:
        abort(404)
    response = redirect(_destino(ponte), code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def link(env=None):
    env = env if env is not None else os.environ
    segredo = env.get("PONTES_LINK_SEGREDO", "")
    base = env.get("ONBOARDING_PUBLIC_URL", "https://amplify-cadastro.up.railway.app").rstrip("/")
    return f"{base}/pontes/{segredo}" if len(segredo) >= 32 else ""


def registrar(app, *, env=None):
    env = env if env is not None else os.environ
    app.extensions["operacao"] = {"segredo": env.get("PONTES_LINK_SEGREDO", ""), "env": env}
    app.register_blueprint(bp)
