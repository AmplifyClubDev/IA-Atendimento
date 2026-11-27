"""Painel de recuperação das pontes, com sessões e espera compartilhadas.

O GET do painel só observa; o usuário abre o console explicitamente. O ativador
existente de agenciamento/pré-validação reutiliza a mesma sessão do painel.
Convites não é ativada nem reiniciada por este módulo.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import html
import http.cookiejar
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

from flask import Blueprint, abort, current_app, make_response, redirect
from diagnostico_ponte import registrar as registrar_diagnostico, resumo

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
PREVALIDACAO_BASE = next(base for chave, _, base, *_ in PONTES if chave == "prevalidacao")
LOGIN = {"human_login_required", "login_required", "session_or_partner_context_invalid",
         "partner_probe_rejected", "captcha_required", "mfa_required", "human_verification_required"}


def ler_precisa_login(base, timeout=10):
    """/health público da ponte (25/11/2026): True só quando o TikTok pediu login de verdade.

    None quando não deu para ler (ponte antiga ou fora do ar): o vigia espera o limite de 45 min."""
    request_ = Request(base + "/health", headers={"Accept": "application/json"})
    try:
        response = build_opener(ProxyHandler({}), SemRedirecionamento()).open(request_, timeout=timeout)
        try:
            corpo = json.loads(response.read(65536))
        finally:
            response.close()
    except Exception:
        return None
    valor = corpo.get("precisa_login") if isinstance(corpo, dict) else None
    return valor if isinstance(valor, bool) else None


def ler_diagnostico(base, token, timeout=10):
    """Readiness não confunde HTTP 429/401/503 com necessidade de login."""
    request_ = Request(base + "/bridge/ready", headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
    try:
        response = build_opener(ProxyHandler({}), SemRedirecionamento()).open(request_, timeout=timeout)
    except HTTPError as error:
        response = error
    except Exception as error:
        return {"status": "inacessivel", "exceptionType": type(error).__name__}
    try:
        if response.code == 429:
            return {"status": "rate_limited", "http": 429}
        if response.code in {401, 403}:
            return {"status": "credencial_invalida", "http": response.code}
        corpo = json.loads(response.read(65536))
        return resumo(corpo, http=response.code)
    except Exception:
        return {"status": "inacessivel", "http": response.code}
    finally:
        try:
            response.close()
        except Exception:
            pass


def ler_status(base, token, timeout=10):
    return ler_diagnostico(base, token, timeout)["status"]


class SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # nunca encaminhar Authorization/cookies para outro destino


class _Sessao:
    def __init__(self):
        self.lock = threading.RLock()
        self.credencial = None
        self.opener = None
        self.autenticada = False
        self.aguardar_ate = 0
        self.falhas = 0
        self.erro = None
        self.ativacao_aguardar_ate = 0
        self.ativacao_falhas = 0
        self.ativacao_erro = None


# Um worker/uma réplica do Cadastro: estado compartilhado por todas as threads,
# tanto do ativador quanto das requisições HTTP. Cookies só ficam em memória.
_SESSOES = {}
_SESSOES_LOCK = threading.Lock()


def _sessao(base):
    with _SESSOES_LOCK:
        return _SESSOES.setdefault(base, _Sessao())


def _retry_after(valor):
    try:
        segundos = float(valor)
        if math.isfinite(segundos) and segundos >= 0:
            return segundos
    except (TypeError, ValueError):
        pass
    try:
        return max(0, parsedate_to_datetime(valor).timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return None


class Painel:
    """Uma sessão por ponte; serializa chamadas e nunca repete um POST na falha."""

    def __init__(self, base, chave, timeout=120):
        self.base, self.chave, self.timeout = base.rstrip("/"), chave, timeout
        self._estado = _sessao(self.base)

    def _espera(self):
        return max(0, math.ceil(self._estado.aguardar_ate - time.monotonic()))

    def _espera_ativacao(self):
        estado = self._estado
        if estado.ativacao_erro == "requires_reconciliation":
            return 1  # pausa sem prazo; só readiness autenticada ou ativação bem-sucedida limpa
        return max(0, math.ceil(estado.ativacao_aguardar_ate - time.monotonic()))

    def _limpar_ativacao(self):
        estado = self._estado
        estado.ativacao_falhas, estado.ativacao_erro, estado.ativacao_aguardar_ate = 0, None, 0

    def confirmar_pronta(self):
        if self.base == PREVALIDACAO_BASE and self._estado.lock.acquire(timeout=1):
            try:
                self._limpar_ativacao()
            finally:
                self._estado.lock.release()

    def requer_reconciliacao(self):
        if self.base != PREVALIDACAO_BASE:
            return False
        if not self._estado.lock.acquire(timeout=1):
            return True  # não iniciar outro login enquanto há uma operação em andamento
        try:
            return self._estado.ativacao_erro == "requires_reconciliation"
        finally:
            self._estado.lock.release()

    def situacao(self):
        if not self._estado.lock.acquire(timeout=1):
            return {"erro": "console_busy", "aguardar": 1}
        try:
            espera = self._espera()
            erro = self._estado.ativacao_erro
            if erro == "requires_reconciliation" and not (
                    espera and self._estado.erro in {"rate_limited", "console_unauthorized"}):
                return {"erro": erro, "aguardar": 1}
            espera_ativacao = self._espera_ativacao()
            if not espera and espera_ativacao:
                return {"erro": "activation_backoff", "aguardar": 0, "ativar_em": espera_ativacao}
            return {"erro": self._estado.erro, "aguardar": espera}
        finally:
            self._estado.lock.release()

    def _falhou(self, codigo, headers=None, *, reconcilia=False, ativacao=False):
        estado = self._estado
        if ativacao and (codigo == 409 or codigo >= 500):
            estado.ativacao_falhas += 1
            espera = min(300, 30 * 2 ** min(estado.ativacao_falhas - 1, 4))
            erro = "requires_reconciliation" if reconcilia else "console_unavailable"
            estado.ativacao_erro = erro
            estado.ativacao_aguardar_ate = time.monotonic() + espera
            return codigo, {"erro": erro, "retry_after": espera}
        estado.falhas += 1
        if codigo == 429:
            informado = _retry_after((headers or {}).get("Retry-After"))
            # Sem cabeçalho, espera conservadora crescente; nunca um retry imediato.
            espera = informado if informado is not None else min(1800, 300 * 2 ** min(estado.falhas - 1, 3))
            espera = max(30, espera)
            erro = "rate_limited"
        elif codigo in {401, 403}:
            espera, erro = 300, "console_unauthorized"
            estado.autenticada = False
        else:
            espera = min(300, 30 * 2 ** min(estado.falhas - 1, 4))
            erro = "requires_reconciliation" if reconcilia else "console_unavailable"
        estado.erro = erro
        estado.aguardar_ate = time.monotonic() + espera
        return codigo, {"erro": erro, "retry_after": self._espera()}

    def _pedir(self, path, method, *, autenticar=False):
        ativacao = self.base == PREVALIDACAO_BASE and path == "/console/activate" and method == "POST"
        headers = {"Origin": self.base, "Accept": "application/json"}
        if autenticar:
            headers["Authorization"] = "Bearer " + self.chave
        try:
            response = self._estado.opener.open(
                Request(self.base + path, method=method, headers=headers),
                timeout=20 if autenticar else self.timeout)
        except HTTPError as error:
            response = error
        except Exception as error:
            codigo, corpo = self._falhou(503, ativacao=ativacao)
            return codigo, {**corpo, "exceptionType": type(error).__name__}
        try:
            codigo = response.code
            if codigo not in {200, 204}:
                reconcilia = False
                if codigo == 409 and path == "/console/activate" and method == "POST":
                    raw = response.read(65537)
                    try:
                        corpo_erro = json.loads(raw) if len(raw) <= 65536 else None
                    except (UnicodeError, ValueError):
                        corpo_erro = None
                    if isinstance(corpo_erro, dict):
                        reconcilia = corpo_erro.get("requires_reconciliation") is True or any(
                            corpo_erro.get(k) == "requires_reconciliation" for k in ("code", "error", "status")
                        )
                return self._falhou(codigo, response.headers, reconcilia=reconcilia, ativacao=ativacao)
            raw = response.read(65537)
            if len(raw) > 65536:
                return self._falhou(502, ativacao=ativacao)
            corpo = json.loads(raw or b"{}")
            if not isinstance(corpo, dict):
                return self._falhou(502, ativacao=ativacao)
            return codigo, corpo
        except Exception as error:
            codigo, corpo = self._falhou(502, ativacao=ativacao)
            return codigo, {**corpo, "exceptionType": type(error).__name__}
        finally:
            try:
                response.close()
            except Exception:
                pass

    def _abrir(self, path, method="GET"):
        estado = self._estado
        if not estado.lock.acquire(timeout=1):
            return 503, {"erro": "console_busy", "retry_after": 1}
        try:
            fingerprint = hashlib.sha256(self.chave.encode()).digest()
            if estado.credencial != fingerprint:
                estado.credencial = fingerprint
                estado.opener = build_opener(ProxyHandler({}), SemRedirecionamento(),
                    HTTPCookieProcessor(http.cookiejar.CookieJar()))
                estado.autenticada = False
                # Trocar a chave não apaga a espera imposta pela ponte.
            if self._espera():
                codigo = 429 if estado.erro == "rate_limited" else 503
                return codigo, {"erro": estado.erro, "retry_after": self._espera()}
            if self.base == PREVALIDACAO_BASE and path == "/console/activate" and method == "POST":
                espera = self._espera_ativacao()
                if espera:
                    return 503, {"erro": estado.ativacao_erro, "retry_after": espera}
            if not estado.autenticada:
                codigo, corpo = self._pedir("/console/session", "POST", autenticar=True)
                if codigo not in {200, 204}:
                    return codigo, corpo
                estado.autenticada = True
            codigo, corpo = self._pedir(path, method)
            if codigo in {200, 204}:
                estado.falhas, estado.erro, estado.aguardar_ate = 0, None, 0
                if path == "/console/activate" and method == "POST":
                    self._limpar_ativacao()
            # 401 invalida a sessão, mas só uma chamada futura poderá reautenticar.
            return codigo, corpo
        finally:
            estado.lock.release()

    def modo(self):
        status, corpo = self._abrir("/console/status")
        processo = corpo.get("process")
        return processo.get("mode") if status == 200 and isinstance(processo, dict) else None

    def login(self):
        return self._acao_observada("login")

    def ativar(self):
        return self._acao_observada("activate")

    def _acao_observada(self, acao):
        nome = next((n for _, n, b, *_ in PONTES if b == self.base), "Ponte")
        registrar_diagnostico(nome, "recuperacao", {"acao": acao, "resultado": "iniciada"})
        try:
            status, corpo = self._abrir("/console/" + acao, "POST")
        except Exception as error:
            registrar_diagnostico(nome, "recuperacao", {"acao": acao, "resultado": "erro", "exceptionType": type(error).__name__})
            raise
        resultado = "aceita" if status == 200 else "recusada"
        if status != 200 and corpo.get("retry_after"):
            resultado = "aguardando_ou_recusada"  # pode ser espera local; não afirma que houve nova chamada HTTP.
        registrar_diagnostico(nome, "recuperacao", {**resumo(corpo, http=status), "acao": acao,
                              "resultado": resultado})
        return status == 200


def pontes(env=None):
    env = env if env is not None else os.environ
    return [{"chave": k, "nome": n, "base": b, "token": env.get(t, ""), "console": env.get(c, ""), "ativa_sozinha": a}
            for k, n, b, t, c, a in PONTES]


class Ativador:
    """Recuperação já existente de agenciamento/pré-validação; Convites é manual."""

    def __init__(self, lista, *, painel=Painel, ler=None, intervalo=30, confirmacoes=2, espera_reinicio=1800,
                 relogio=time.time, dormir=time.sleep):
        self.pontes = [(p["nome"], p["base"], p["token"], painel(p["base"], p["console"]), p["ativa_sozinha"])
                       for p in lista if p["console"] and p["token"]]
        self.ler = ler or (lambda base, token: ler_status(base, token))
        self.intervalo, self.confirmacoes, self.falhas = intervalo, confirmacoes, {}
        self.espera_reinicio, self.relogio, self.dormir, self.ultimo_reinicio = espera_reinicio, relogio, dormir, {}

    def rodada(self):
        feitos = []
        for nome, base, token, painel, ativa_sozinha in self.pontes:
            if not ativa_sozinha:
                continue
            try:
                modo = painel.modo()
                if modo == "login":
                    self.falhas[nome] = 0
                    if painel.ativar():
                        feitos.append(("ativada", nome))
                    continue
                if modo != "bridge":
                    continue
                status = self.ler(base, token)
                if base == PREVALIDACAO_BASE:
                    if status == "ready":
                        painel.confirmar_pronta()
                    if painel.requer_reconciliacao():
                        self.falhas[nome] = 0
                        continue
                self.falhas[nome] = self.falhas.get(nome, 0) + 1 if status in LOGIN else 0
                if self.falhas[nome] >= self.confirmacoes and painel.login():
                    self.falhas[nome] = 0
                    feitos.append(("reaberta", nome))
            except Exception as error:
                # Uma ponte com erro nunca impede as próximas de serem verificadas.
                print(f"[cadastro-publico-v5] ponte {nome} indisponivel: {type(error).__name__}")
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
    response.headers["X-Amplify-Pontes-Revision"] = "recovery-20261114-activation-v2"
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
    with ThreadPoolExecutor(len(lista) or 1) as pool:
        status = list(pool.map(lambda p: ler_status(p["base"], p["token"]), lista))
    caidas = [p for p, s in zip(lista, status) if s != "ready"]
    def consultar(item):
        p, s = item
        try:
            cliente = Painel(p["base"], p["console"], timeout=20) if p["console"] else None
            # Apenas leitura; no máximo 20 s de sessão + 20 s de status por ponte.
            if cliente and s in LOGIN:
                cliente.modo()
            return cliente.situacao() if cliente else {"erro": None, "aguardar": 0}
        except Exception:
            return {"erro": "console_unavailable", "aguardar": 30}

    # O pior caso não soma os timeouts de três pontes na mesma requisição.
    with ThreadPoolExecutor(len(lista) or 1) as pool:
        consoles = list(pool.map(consultar, zip(lista, status)))
    linhas = ""
    for p, s, console in zip(lista, status, consoles):
        no_ar = s == "ready"
        bloqueado = bool(console["aguardar"])
        detalhe = ""
        if no_ar:
            texto = "NO AR"
        elif s in LOGIN:
            texto = "PRECISA DE LOGIN"
        elif s in {"busy", "starting", "initializing"}:
            texto = "PONTE OCUPADA"
        elif s == "rate_limited":
            texto = "LIMITE TEMPORÁRIO"
        else:
            texto = "STATUS INDISPONÍVEL"
        if console["erro"] == "rate_limited":
            detalhe = f'Limite temporário do painel (HTTP 429). Aguarde {console["aguardar"]} s.' if bloqueado else "A espera terminou. Atualize para conferir o painel."
        elif console["erro"] == "console_unauthorized":
            detalhe = "O painel recusou a credencial (HTTP 401/403). Confira a configuração."
        elif console["erro"] == "requires_reconciliation":
            detalhe = "Conclua a verificação na página de conexão para retomar esta ponte."
        elif console["erro"] == "activation_backoff":
            detalhe = f'Nova tentativa automática em {console["ativar_em"]} s. Você pode conectar agora.'
        elif console["erro"] == "console_busy":
            detalhe = "Há uma operação em andamento no painel desta ponte. Aguarde."
        elif console["erro"]:
            detalhe = "Não foi possível consultar o painel desta ponte. Uma nova leitura será feita após a espera."
        selo = f'<span class="s {"ok" if no_ar else "no"}">{texto}</span>'
        botao = ""
        if not no_ar and p["console"] and (not bloqueado or console["erro"] == "requires_reconciliation"):
            rotulo = "Conectar" if console["erro"] in {"requires_reconciliation", "activation_backoff"} else ("Fazer login" if s in LOGIN else "Abrir painel")
            botao = f'<a class="b" href="/pontes/{quote(segredo)}/{p["chave"]}" target="_blank" rel="noreferrer">{rotulo}</a>'
        linhas += f'<div class="p"><div><b>{html.escape(p["nome"])}</b><br>{selo}<br><small>{html.escape(detalhe)}</small></div>{botao}</div>'
    topo = ("Todas as pontes estão no ar. ✅" if not caidas else
            "Confira o estado de cada ponte. Para refazer o login, abra o painel da ponte indicada. "
            "Em Convites, a ativação é manual.")
    return _pagina(f"<p>{topo}</p>{linhas}<p><small>Esta página se atualiza sozinha, respeitando a espera de cada ponte.</small></p>", recarregar=bool(caidas))


@bp.get("/pontes/<segredo>/<chave>")
def abrir(segredo, chave):
    _conferir(segredo)
    ponte = next((p for p in pontes(_cfg()["env"]) if p["chave"] == chave and p["console"]), None)
    if ponte is None:
        abort(404)
    situacao = Painel(ponte["base"], ponte["console"]).situacao()
    if situacao["aguardar"] and situacao["erro"] != "requires_reconciliation":
        espera = situacao["aguardar"]
        response = _pagina(f"<p>O painel de {html.escape(ponte['nome'])} está em espera. Aguarde {espera} s e volte à lista de pontes.</p>",
                           429 if situacao["erro"] == "rate_limited" else 503)
        response.headers["Retry-After"] = str(espera)
        return response
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
