"""Evidência sanitizada das pontes. Nunca armazena payload, URL, cookie ou token."""
import json
import os
import re
import sqlite3
import time
from pathlib import Path


def codigo(valor):
    # Apenas códigos de máquina; mensagens livres podem conter credenciais/URLs.
    return valor if isinstance(valor, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,95}", valor) else None


def resumo(corpo, *, http=None):
    corpo = corpo if isinstance(corpo, dict) else {}
    result = {"status": codigo(corpo.get("status")) or "desconhecido"}
    if codigo(corpo.get("exceptionType")):
        result["exceptionType"] = corpo["exceptionType"]
    if codigo(corpo.get("erro")):
        result["consoleError"] = corpo["erro"]
    if codigo(corpo.get("consoleError")):
        result["consoleError"] = corpo["consoleError"]
    if isinstance(http, int):
        result["http"] = http
    campos = {
        "probe": ("status", "errorCode", "durationMs", "ageMs"),
        "lastContextError": ("code", "at"),
        "riskGuard": ("status", "code", "retryAfterMs"),
        "infrastructure": ("phase", "code"),
        "session": ("state", "authenticated"),
        "process": ("mode", "online", "changing"),
        "contexto": ("status", "aberto", "pronto", "chamadas", "idadeMs"),
        "context": ("open", "ready"),
        "resources": ("memoryBytes", "memoryLimitBytes", "oomKillCount", "browserExitCode"),
    }
    for grupo, chaves in campos.items():
        origem = corpo.get(grupo)
        if not isinstance(origem, dict):
            continue
        valores = {}
        for chave in chaves:
            valor = origem.get(chave)
            if isinstance(valor, (bool, int)) or codigo(valor):
                valores[chave] = valor
        if valores:
            result[grupo] = valores
    diagnostico = corpo.get("diagnostics")
    if isinstance(diagnostico, dict):
        result["diagnostics"] = {}
        for grupo in ("resources", "lastFailure", "lastRecovery"):
            origem = diagnostico.get(grupo)
            if isinstance(origem, dict):
                result["diagnostics"][grupo] = {k: v for k, v in origem.items()
                    if k in {"code", "sourceCode", "errorType", "pageClass", "reason", "result", "child", "signal", "exitCode",
                             "at", "attempt", "httpStatus", "apiCode", "memoryBytes", "memoryLimitBytes",
                             "memoryPeakBytes", "oomKillCount", "oomKillDelta", "expected"}
                    and (isinstance(v, (int, bool)) or codigo(v))}
    return result


def causa(dados):
    codigos = {dados.get("status")}
    failure = (dados.get("diagnostics") or {}).get("lastFailure") or {}
    # Não atribui uma falha antiga ao incidente atual: diagnóstico fica no histórico.
    if isinstance(failure.get("at"), int) and time.time() * 1000 - 600000 <= failure["at"] <= time.time() * 1000 + 60000:
        codigos.add(failure.get("code"))
        pagina = failure.get("pageClass")
        if pagina in {"captcha", "verification"}:
            codigos.add("captcha_required")
        elif pagina == "mfa":
            codigos.add("mfa_required")
        elif pagina == "login":
            codigos.add("login_required")
    for grupo, campo in (("probe", "errorCode"), ("lastContextError", "code"),
                         ("riskGuard", "code"), ("infrastructure", "code")):
        codigos.add((dados.get(grupo) or {}).get(campo))
    # O contador cumulativo de OOM, isoladamente, não prova OOM neste incidente.
    if codigos & {"out_of_memory", "oom_killed", "browser_oom", "memory_limit_exceeded"}:
        return "memoria", "Evento OOM registrado no contêiner. Isso confirma falta de memória no grupo, não identifica sozinho qual processo foi morto."
    if codigos & {"captcha_required", "human_verification_required"}:
        return "captcha", "TikTok exige verificação humana/CAPTCHA."
    if "mfa_required" in codigos:
        return "mfa", "TikTok exige autenticação adicional (MFA)."
    if codigos & {"browser_closed", "browser_disconnected", "browser_crashed", "context_closed"}:
        return "navegador", "Navegador/contexto fechado ou desconectado; motivo do encerramento ainda não comprovado."
    if codigos & {"inacessivel", "network_error", "timeout", "invalid_response", "http_error", "upstream_unavailable"}:
        return "comunicacao", "Falha de comunicação/HTTP ou resposta inválida; não comprova logout."
    if codigos & {"partner_probe_rejected", "session_or_partner_context_invalid"}:
        return "contexto", "Checagem do Partner Center rejeitada ou contexto inválido; não comprova logout."
    if codigos & {"login_required", "human_login_required"}:
        return "login", "A ponte informou necessidade de login; a causa da perda da sessão ainda não foi comprovada."
    if "credencial_invalida" in codigos:
        return "credencial", "A credencial de acesso à ponte foi recusada (HTTP 401/403). Isso não comprova logout do TikTok."
    return "indeterminada", "Causa ainda indeterminada; consultar a evidência técnica do incidente."


def _path():
    return Path(os.environ.get("CADASTRO_STATE_PATH", "/tmp/cadastro.sqlite3")).parent / "pontes-diagnostico.sqlite3"


def registrar(nome, evento, dados, *, agora=None):
    """Uma linha por mudança/tentativa; retenção global de 2 mil eventos/14 dias."""
    instante = time.time() if agora is None else agora
    seguro = resumo(dados, http=dados.get("http"))
    for chave in ("acao", "resultado", "exceptionType"):
        if codigo(dados.get(chave)):
            seguro[chave] = dados[chave]
    registro = {"event": "ponte_diagnostico", "ponte": nome, "evento": evento,
                "at": instante, "evidencia": seguro}
    print(json.dumps(registro, ensure_ascii=False), flush=True)
    try:
        with sqlite3.connect(_path(), timeout=5) as db:
            db.execute("CREATE TABLE IF NOT EXISTS eventos (id INTEGER PRIMARY KEY, at REAL, ponte TEXT, evento TEXT, evidencia TEXT)")
            db.execute("INSERT INTO eventos(at,ponte,evento,evidencia) VALUES(?,?,?,?)",
                       (instante, nome, evento, json.dumps(seguro)))
            db.execute("DELETE FROM eventos WHERE at < ? OR id NOT IN (SELECT id FROM eventos ORDER BY id DESC LIMIT 2000)",
                       (instante - 14 * 86400,))
    except (OSError, sqlite3.Error) as erro:
        # A falha do armazenamento não deve interromper monitoramento/recuperação.
        print(json.dumps({"event": "ponte_diagnostico_storage_error", "type": type(erro).__name__}), flush=True)


def ultima_recuperacao(nome, desde):
    try:
        with sqlite3.connect(_path(), timeout=5) as db:
            row = db.execute("SELECT evidencia FROM eventos WHERE ponte=? AND evento='recuperacao' AND at>=? ORDER BY id DESC LIMIT 1",
                             (nome, desde)).fetchone()
        return json.loads(row[0]) if row else None
    except (OSError, sqlite3.Error, ValueError):
        return None
