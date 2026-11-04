"""Entrega por cadastro, separada da requisição do formulário.

Nunca repete automaticamente uma tentativa externa de resultado incerto.
O comando operacional exige creator explícito e configuração habilitada.
"""
from __future__ import annotations

from offline_policy import effects_allowed, require_effects, REASON

import html
import json
import os
import re
import smtplib
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode

import requests

GROUPS = {"Start": 85839, "Silver": 85616, "Gold": 85617, "Diamond": 85845}
COMMUNITY = 463176
START_URL = "https://amplify-club.circle.so/c/comece-aqui-d2fee2"
ACCESS_RELEASED_NOTICE = (
    "Oi, {name}! Seu acesso à Amplify foi liberado 💙\n"
    "Enviamos as instruções para o e-mail que você cadastrou: {email}\n"
    "Procure por uma mensagem da Amplify na sua caixa de entrada. Se não encontrar, confira também o spam, promoções ou lixo eletrônico.\n"
    "Seu acesso já está ativo no Circle. Para começar, entre pelo link enviado no e-mail e siga as instruções de boas-vindas."
)


def category(gmv):
    value = Decimal(str(gmv))
    if not value.is_finite() or value < 0:
        raise ValueError("gmv_invalido")
    return "Diamond" if value >= 100000 else "Gold" if value >= 30000 else "Silver" if value >= 5000 else "Start"


def required_groups(tier):
    names = list(GROUPS)
    return {GROUPS[name] for name in names[:names.index(tier)+1]}


def tier_rank(tier):
    return list(GROUPS).index(tier)


class Circle:
    def __init__(self, token):
        if not token:
            raise ValueError("circle_nao_configurado")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + token, "Content-Type": "application/json"})

    def call(self, path, method="GET", body=None, missing=False):
        require_effects()
        response = self.session.request(method, "https://app.circle.so/api/admin/v2" + path, json=body, timeout=30)
        if missing and response.status_code == 404:
            return None
        if not response.ok:
            raise RuntimeError("circle_http_" + str(response.status_code))
        return response.json() if response.content else {}

    def records(self, path):
        result = []
        for page in range(1, 101):
            data = self.call(path + ("&" if "?" in path else "?") + urlencode({"page": page, "per_page": 100}))
            if not isinstance(data.get("records"), list) or type(data.get("has_next_page")) is not bool:
                raise RuntimeError("circle_paginacao_invalida")
            result.extend(data["records"])
            if not data["has_next_page"]:
                return result
        raise RuntimeError("circle_paginacao_incompleta")

    def provision(self, *, email, name, tier, before_write, require_new=False, expected_member_id=None, allow_downgrade=False):
        require_effects()
        import time
        groups = self.records("/access_groups")
        for label, ident in GROUPS.items():
            if not any(g.get("id") == ident and g.get("community_id") == COMMUNITY and g.get("name") == "Creator " + label and g.get("status") == "active" for g in groups):
                raise RuntimeError("circle_mapeamento_divergente")
        tags = self.records("/member_tags")
        tag_ids = {}
        for label in GROUPS:
            found = [t["id"] for t in tags if t.get("name", "").strip() == "Creator " + label]
            if len(found) != 1:
                raise RuntimeError("circle_categoria_ambigua")
            tag_ids[label] = found[0]
        member = self.call("/community_members/search?" + urlencode({"email": email}), missing=True)
        member = member.get('community_member', member) if isinstance(member, dict) else member
        if expected_member_id is not None and (type(expected_member_id) is not int or expected_member_id <= 0
                or member is None or member.get('id') != expected_member_id):
            raise RuntimeError('circle_reconciliacao_identidade_divergente')
        if member is None:
            before_write()
            created = self.call("/community_members", "POST", {"email": email, "name": name, "skip_invitation": False, "member_tag_ids": [tag_ids[tier]]})
            member = created.get("community_member", created)
            created_id = member.get("id")
            if type(created_id) is not int:
                raise RuntimeError("circle_criacao_a_reconciliar")
            for delay in (0, 1, 3, 5):
                if delay:
                    time.sleep(delay)
                # A leitura por ID não depende da atualização do índice de busca por e-mail.
                member = self.call(f"/community_members/{created_id}", missing=True)
                member = member.get('community_member', member) if isinstance(member, dict) else member
                if member is not None:
                    break
            if member is None or member.get("id") != created_id:
                raise RuntimeError("circle_criacao_a_reconciliar")
        if type(member.get("id")) is not int or member.get("community_id") != COMMUNITY or member.get("email", "").lower() != email.lower():
            raise RuntimeError("circle_identidade_divergente")
        member_id = member["id"]
        assigned = {g["id"] for g in self.records(f"/community_members/{member_id}/access_groups") if g.get("status") == "active"}
        wanted = required_groups(tier)
        current_tags = {t["id"] for t in member.get("member_tags", [])}
        managed_groups = set(GROUPS.values())
        requested_rank = tier_rank(tier)
        acceptable_tags = {tag_ids[label] for label in GROUPS if tier_rank(label) >= requested_rank}
        higher_tags = {tag_ids[label] for label in GROUPS if tier_rank(label) > requested_rank}
        preserve_higher = allow_downgrade is not True and bool((assigned & managed_groups) - wanted or current_tags & higher_tags)
        for ident in sorted(wanted - assigned):
            before_write()
            self.call(f"/access_groups/{ident}/community_members", "POST", {"email": email})
        # Remove apenas a hierarquia administrada; outros grupos são preservados.
        if not preserve_higher:
            for ident in sorted((assigned & managed_groups) - wanted):
                before_write()
                self.call(f"/access_groups/{ident}/community_members?" + urlencode({"email": email}), "DELETE")
        if tag_ids[tier] not in current_tags and (not preserve_higher or not (current_tags & acceptable_tags)):
            before_write()
            self.call("/tagged_members", "POST", {"user_email": email, "member_tag_id": tag_ids[tier]})
        if not preserve_higher:
            for ident in (current_tags & set(tag_ids.values())) - {tag_ids[tier]}:
                before_write()
                self.call("/tagged_members?" + urlencode({"user_email": email, "member_tag_id": ident}), "DELETE")
        # Somente leituras podem ser repetidas por atraso de propagação do Circle.
        # Em 30/10 a confirmação passou de 9 s (cadastro da gabiosantana1); espera até ~1 min.
        for delay in (0, 1, 3, 5, 10, 15, 25):
            if delay:
                time.sleep(delay)
            member = self.call(f"/community_members/{member_id}", missing=True)
            if member is None:
                continue
            member = member.get("community_member", member)
            assigned = {g["id"] for g in self.records(f"/community_members/{member_id}/access_groups") if g.get("status") == "active"}
            spaces = self.records("/community_member_spaces?" + urlencode({"community_member_id": member_id}))
            current_tags = {t["id"] for t in member.get("member_tags", [])}
            groups_ok = wanted <= (assigned & managed_groups) if preserve_higher else assigned & managed_groups == wanted
            tags_ok = bool(current_tags & acceptable_tags) if preserve_higher else current_tags & set(tag_ids.values()) == {tag_ids[tier]}
            if (member.get("id") == member_id and member.get("email", "").lower() == email.lower() and member.get("community_id") == COMMUNITY
                and groups_ok
                and tags_ok
                and any(s.get("id") == 2794358 for s in spaces)):
                return member_id
        raise RuntimeError("circle_leitura_ainda_nao_confirmada")


def welcome_message(settings, job, tier):
    templates = json.loads(Path(__file__).with_name("cadastro_assets").joinpath("welcome_templates.json").read_text(encoding="utf-8"))
    template = templates[tier]
    name, email = job["name"], job["email"]
    message = EmailMessage()
    message["From"] = f"Amplify — notificações <{settings.smtp_usuario}>"
    message["To"] = email
    message['Auto-Submitted'] = 'auto-generated'
    message['X-Auto-Response-Suppress'] = 'All'
    message["Subject"] = f"{name.split()[0]}, bem-vindo à Amplify {tier}! {template['emoji']}"
    message["Message-ID"] = f"<cadastro-{job['onboarding_id']}-v{job['revision']}@amplifyugc.co>"
    included = ", ".join(name for name, ident in GROUPS.items() if ident in required_groups(tier))
    message.set_content(f"Olá, {name}! 💙\n\nSeu acesso {tier} está liberado, incluindo {included}.\nPara entrar, use o mesmo e-mail do seu cadastro ({email}) e crie sua senha no primeiro acesso: no Circle, digite esse e-mail, toque em Continuar e siga os passos. Não use 'Continuar com Google' com outro e-mail.\n\nComece aqui: {START_URL}\n\nBia e time Amplify\n\nMensagem automática — não responda a este e-mail. Este endereço é usado apenas para notificações.")
    rendered = template["html"].replace("AMPLIFY_CREATOR_NAME", html.escape(name)).replace("AMPLIFY_CREATOR_EMAIL", html.escape(email))
    rendered = rendered.replace('</body>', '<p style="text-align:center;padding:16px;font-family:Arial,sans-serif;font-size:12px;line-height:1.6;color:#536177">Mensagem automática — não responda a este e-mail. Este endereço é usado apenas para notificações.</p></body>')
    message.add_alternative(rendered, subtype="html")
    return message


def send_welcome(settings, job, tier):
    require_effects(settings=settings)
    message = welcome_message(settings, job, tier)
    if getattr(settings, 'email_transport', 'smtp') == 'gmail_api':
        from .gmail_api import GmailAPI
        return GmailAPI(settings).send(message)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(settings.smtp_usuario, settings.smtp_senha_app)
        refused = smtp.send_message(message)
        if refused:
            raise RuntimeError("smtp_recusou_destinatario")
    return str(message["Message-ID"])


class ChatwootAccessNotifier:
    def __init__(self):
        self.enabled = os.getenv("CADASTRO_AVISO_ACESSO_CHATWOOT_ATIVO", "false").lower() in ("true", "1", "sim")
        self.base_url = os.getenv("CHATWOOT_BASE_URL", "").rstrip("/")
        self.account_id = os.getenv("CHATWOOT_ACCOUNT_ID", "")
        self.token = os.getenv("CHATWOOT_API_TOKEN", "")
        self.session = requests.Session()
        if self.token:
            self.session.headers.update({
                "api_access_token": self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            })

    def configured(self):
        if not effects_allowed():
            return False
        return bool(self.enabled and self.base_url and self.account_id and self.token)

    def messages_url(self, conversation_id):
        return f"{self.base_url}/api/v1/accounts/{self.account_id}/conversations/{conversation_id}/messages"

    def already_sent(self, conversation_id, key):
        require_effects()
        response = self.session.get(self.messages_url(conversation_id), timeout=30)
        response.raise_for_status()
        body = response.json()
        payload = body.get("payload", body) if isinstance(body, dict) else body
        for message in payload if isinstance(payload, list) else []:
            attributes = message.get("content_attributes") or {}
            if str(attributes.get("amplify_idempotency_key") or "") == key:
                return True
        return False

    def send(self, job):
        if not effects_allowed():
            return {"notice_status": "disabled", "reason": REASON}
        conversation_id = job.get("conversation_id")
        if not self.configured():
            return {"notice_status": "aviso_chatwoot_desativado"}
        if not conversation_id:
            return {"notice_status": "aviso_chatwoot_sem_conversa"}
        key = f"cadastro-acesso-liberado:{job['onboarding_id']}:v{job['revision']}"
        if self.already_sent(conversation_id, key):
            return {"notice_status": "aviso_chatwoot_ja_enviado"}
        content = ACCESS_RELEASED_NOTICE.format(name=job["name"], email=job["email"])
        response = self.session.post(self.messages_url(conversation_id), json={
            "content": content,
            "message_type": "outgoing",
            "private": False,
            "content_attributes": {
                "amplify_actor": "machine",
                "amplify_idempotency_key": key,
            },
        }, timeout=30)
        response.raise_for_status()
        data = response.json()
        if type(data.get("id")) is not int:
            raise RuntimeError("chatwoot_recibo_incerto")
        return {"notice_status": "aviso_chatwoot_enviado", "notice_message_id": data["id"]}


def notify_access_released(job):
    if not effects_allowed():
        return {"notice_status": "disabled", "reason": REASON}
    return ChatwootAccessNotifier().send(job)


def deliver(gateway, circle, settings, creator_id, send=send_welcome, notify=notify_access_released):
    if not effects_allowed(settings=settings):
        return {"status": "disabled", "reason": REASON}
    job = gateway.rpc("cadastro_v2_preparar_entrega", {"p_criador_id": creator_id})
    if not job["ready"]:
        return {"status": job["reason"]}
    base = {"p_criador_id": creator_id, "p_onboarding_id": job["onboarding_id"], "p_tentativa": job["attempt"]}
    def mark(stage, **extra):
        return gateway.rpc("cadastro_v2_confirmar_entrega", {**base, "p_etapa": stage, **extra})
    try:
        tier = category(job["gmv"])
        extra = {"require_new": True} if job.get("require_new_member") else {}
        if job.get('reconciled_circle_member_id') is not None:
            extra['expected_member_id'] = job['reconciled_circle_member_id']
        member_id = circle.provision(email=job["email"], name=job["name"], tier=tier, before_write=lambda: mark("conferir"), **extra)
        mark("circle_confirmado", p_circle_member_id=member_id)
        mark("conferir")
        message_id = send(settings, job, tier)
        mark("email_confirmado", p_email_message_id=message_id)
        try:
            notice = notify(job)
        except Exception as error:
            notice = {"notice_status": "aviso_chatwoot_pendente", "notice_error_type": type(error).__name__}
        return {"status": "email_aceito_provedor", "onboarding_id": job["onboarding_id"], "category": tier, **notice}
    except Exception as error:
        # Nenhum conteúdo/PII de erros externos é gravado no motivo ou nos logs.
        reason = str(error) if type(error) is RuntimeError and re.fullmatch(r'(?:circle|smtp|gmail)_[a-z0-9_]+', str(error)) else type(error).__name__
        try:
            mark("revisao_manual", p_motivo=reason)
        except Exception:
            pass  # Tentativa continua travada: operador reconcilia antes de repetir.
        return {"status": "revisao_manual", "onboarding_id": job["onboarding_id"], "reason": reason}
