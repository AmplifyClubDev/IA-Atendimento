"""Serviço Cadastro: um único formulário público que grava no AmplifyOS-v5.

`cadastro_pilot.create_app()` (cópia sem alteração do wrapper publicado) envolve esta
fábrica para manter vivo o link /cadastro/ensaio que a Bia envia hoje aos leads.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request, send_file

import pontes
import publico
from agency import AgencyChecker
from emailer import EmailSender
from gmv_print import GmvPrintReader
from entrega import Entrega, settings_from_env
from store import Store
from v5 import RestGateway
from vigia_atendimento import Chatwoot, VigiaAtendimento
from vigia_ponte import VigiaPonte

STATIC = Path(__file__).resolve().parent / "static"
RECOVERY_PNG = "be49aa1c21c7989f47f0f148f668bd0e7824c8065303894f397a44ac6ca68448.png"
LEGACY_PAGES = ("/formulario", "/f", "/onboarding/api/v2/pagina")
LEGACY_API = ("contexto", "respostas", "anexos", "imagem", "convite/contexto", "convite/respostas",
              "convite/anexos", "convite/imagem")


@dataclass
class Deps:
    secret: str
    public_url: str
    store: Store
    v5: object
    agency: object
    email: object
    gmv_reader: object
    enabled: bool = True
    entrega: object = None
    retomada: bool = False
    vigia: object = None
    ativador: object = None
    vigia_atendimento: object = None
    gmv_threads: dict = field(default_factory=dict)


def enviar_alerta(env):
    """E-mail para a equipe (ALERTA_EMAIL); None quando não configurado."""
    destino = env.get("ALERTA_EMAIL", "").strip()
    if not destino:
        return None
    sender = EmailSender(host=env.get("SMTP_HOST", "smtp.gmail.com"), port=env.get("SMTP_PORT", "465"),
                         user=env.get("SMTP_USUARIO", ""), password=env.get("SMTP_SENHA_APP", ""))
    return lambda subject, text, **visual: sender.send_alert(destino, subject, text, **visual)


def alerta_por_email(env):
    """Entrega que esgotou as 3 tentativas."""
    enviar = enviar_alerta(env)
    if enviar is None:
        return None
    return lambda event_id, reason: enviar("Cadastro: acesso não liberado após 3 tentativas",
                                           "O acesso ao Circle de um cadastro do formulário não foi concluído.\n\n"
                                           f"Envio: {event_id}\nMotivo: {reason}\n\n"
                                           "Consulte interno.eventos com referencia = este envio.")


def vigia_da_ponte(env):
    """Um vigia por ponte configurada; o botão do e-mail é o link único das pontes."""
    enviar = enviar_alerta(env)
    if not enviar:
        return []
    painel = pontes.link(env)
    return [VigiaPonte(p["token"], enviar, nome=p["nome"], base=p["base"], painel=painel)
            for p in pontes.pontes(env) if p["token"]]


def vigia_dos_atendimentos(env, v5):
    """Só erro da máquina: lead sem resposta e Bia fora do ar, por e-mail à equipe."""
    enviar = enviar_alerta(env)
    if not enviar or not all(env.get(k) for k in ("CHATWOOT_BASE_URL", "CHATWOOT_ACCOUNT_ID", "CHATWOOT_API_TOKEN")):
        return None
    chatwoot = Chatwoot(env["CHATWOOT_BASE_URL"], env["CHATWOOT_ACCOUNT_ID"], env["CHATWOOT_API_TOKEN"])
    estado = os.path.join(os.path.dirname(env.get("CADASTRO_STATE_PATH", "/tmp/x")) or "/tmp", "vigia-atendimento.json")
    return VigiaAtendimento(enviar, chatwoot=chatwoot, arquivo=estado)


def deps_from_env():
    env = os.environ
    secret = env["ONBOARDING_FORM_SECRET"]
    if len(secret) < 32:
        raise RuntimeError("ONBOARDING_FORM_SECRET curto demais")
    v5 = RestGateway(env["SUPABASE_V5_URL"], env["SUPABASE_V5_SERVICE_KEY"])
    return Deps(
        secret=secret, public_url=env["ONBOARDING_PUBLIC_URL"],
        store=Store(env.get("CADASTRO_STATE_PATH", "/tmp/cadastro-publico-v5.sqlite3")),
        v5=v5,
        entrega=Entrega(v5, circle_token=env.get("CIRCLE_ADMIN_TOKEN", ""), settings=settings_from_env(),
                        enabled=env.get("CADASTRO_ENTREGA_CIRCLE_ATIVA", "false").lower() == "true",
                        alert=alerta_por_email(env)),
        agency=AgencyChecker(env.get("V5_TIKTOK_AGENCY_TOKEN", ""), env=env),
        email=EmailSender(host=env.get("SMTP_HOST", "smtp.gmail.com"), port=env.get("SMTP_PORT", "465"),
                          user=env.get("SMTP_USUARIO", ""), password=env.get("SMTP_SENHA_APP", "")),
        gmv_reader=GmvPrintReader(env.get("OPENAI_API_KEY", ""), env.get("GMV_PRINT_MODEL", "")),
        enabled=env.get("CADASTRO_PUBLICO_V5_ATIVO", "false").lower() == "true",
        retomada=env.get("CADASTRO_RETOMADA_ATIVA", "true").lower() == "true",
        vigia=vigia_da_ponte(env),
        ativador=pontes.Ativador(pontes.pontes(env)),
        vigia_atendimento=vigia_dos_atendimentos(env, v5),
    )


def page_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                                                   "img-src data: blob:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return response


def create_app(deps=None):
    deps = deps or deps_from_env()
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=publico.MAX_IMAGE + 65536)
    app.extensions["cadastro_v5"] = deps

    @app.before_request
    def maintenance():
        if not deps.enabled and request.path.startswith("/onboarding/api/v2/publico/"):
            return jsonify({"erro": "Cadastro em manutenção. Tente novamente em alguns minutos."}), 503

    app.register_blueprint(publico.bp)
    if deps.entrega is not None and getattr(deps, "retomada", False):
        deps.entrega.iniciar_retomada()
    for vigia in deps.vigia or ():
        vigia.iniciar()
    if deps.ativador is not None:
        deps.ativador.iniciar()
    if deps.vigia_atendimento is not None:
        deps.vigia_atendimento.iniciar()
    pontes.registrar(app)

    @app.get("/cadastro")
    @app.get("/cadastro/")
    def page():
        return page_headers(send_file(STATIC / "cadastro.html", mimetype="text/html", max_age=0))

    @app.get("/")
    def index():
        return page_headers(redirect("/cadastro", code=302))

    for path in LEGACY_PAGES:
        # Links pessoais antigos (?t=, ?c=, ?i=) caem no formulário único.
        app.add_url_rule(path, "legado" + path.replace("/", "_"), lambda: page_headers(redirect("/cadastro", code=302)))

    @app.route("/onboarding/api/v2/<path:path>", methods=["GET", "PUT", "POST"])
    def legacy_api(path):
        if path in LEGACY_API:
            return jsonify({"erro": "Este link foi substituído. Abra o cadastro em https://amplify-cadastro.up.railway.app/cadastro."}), 410
        return jsonify({"erro": "Não encontrado."}), 404

    @app.get("/media/recovery/" + RECOVERY_PNG)
    def recovery_header():
        response = Response((STATIC / "media" / ("recovery-header-" + RECOVERY_PNG)).read_bytes(), content_type="image/png")
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "cadastro", "destino": "amplifyos-v5", "formulario_publico": deps.enabled}

    return app
