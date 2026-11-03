"""Isolated headless rehearsal. No database, provider, env or network access.

Callbacks belong to the transport. Only explicit qualification answers change
facts. Simulated Playwright/invitation/relationship results never become proof
of a real invitation, relationship, registration or delivered access.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
import unicodedata
from urllib.parse import urlsplit
from uuid import uuid4

from contracts import allow_inbound, inbound_key


_MENU = (
    "Oi! Eu sou a Bia, agente virtual da Amplify. Nas dúvidas, você conversa com uma IA. "
    "O que você gostaria de fazer?\n\n1. Conhecer a Amplify\n2. Quero me agenciar\n\n"
    "Você também pode escrever sua pergunta com suas palavras."
)
_KNOW = (
    "A Amplify é uma agência para criadores que trabalham com o TikTok Shop. "
    "A parceria inclui campanhas com marcas, orientação e comunidade, conforme as condições "
    "e a categoria de cada creator. Você pode entender a proposta antes de decidir.\n\n"
    "1. Agenciamento\n2. Comissão\n3. Benefícios\n4. Outra dúvida\n\n"
    "Escolha um assunto ou escreva sua pergunta."
)
_MAIN_BUTTONS = ["Conhecer a Amplify", "Quero me agenciar"]
_KNOW_BUTTONS = ["Agenciamento", "Comissão", "Benefícios"]
_DOUBT_BUTTONS = ["Outra dúvida", "Continuar", "Menu"]
_PROMPTS = {
    "menu": (_MENU, _MAIN_BUTTONS),
    "know": (_KNOW, _KNOW_BUTTONS),
    "origin": ("Como você conheceu a Amplify? É opcional.\n\n1. Anúncio\n2. Indicação\n3. Outro\n4. Prefiro não informar",
               ["Anúncio", "Indicação", "Prefiro não informar"]),
    "tiktok": ("Qual é o seu @ do TikTok? Digite como aparece no perfil.", ["Tenho uma dúvida", "Menu"]),
    "shop": ("Seu TikTok Shop Creator está ativo?", ["Sim", "Não", "Não sei"]),
    "agency": ("Você possui vínculo com outra agência atualmente?", ["Sim", "Não", "Não sei"]),
    "await_acceptance": (
        "Neste ensaio, a conferência da conta e o envio do convite retornaram OK SIMULADO. "
        "Nenhum convite real foi enviado. Para testar o próximo passo, escolha 'Aceitei no ensaio'.",
        ["Aceitei no ensaio", "Tenho uma dúvida", "Menu"],
    ),
    "form": ("A próxima etapa é preencher o formulário. O cadastro só será consolidado após a conclusão validada do formulário.",
             ["Tenho uma dúvida", "Menu"]),
}
_INFO = {
    "agency": (
        "O agenciamento é uma parceria entre o creator e a agência no TikTok Shop. "
        "Primeiro você entende as condições; depois a conta e o vínculo atual precisam ser conferidos. "
        "A parceria depende do convite dentro do TikTok. Preencher um cadastro, por si só, não confirma esse vínculo."
    ),
    "commission": (
        "As condições de comissão e contrato precisam ficar claras antes de você aceitar a parceria. "
        "Não vou informar valores ou percentuais sem uma proposta vigente confirmada. "
        "O que você gostaria de entender sobre a comissão?"
    ),
    "benefits": (
        "A Amplify atua com campanhas com marcas, orientação sobre produtos e conteúdos e comunidade de creators. "
        "Os recursos disponíveis, como mentoria e apoio em lives, dependem da categoria e das condições da parceria. "
        "Isso não é garantia de vendas, renda ou recebimento de produtos. Pode perguntar sobre esses pontos."
    ),
}
_ORIGINS = {"1": "anuncio", "anuncio": "anuncio", "2": "indicacao", "indicacao": "indicacao",
            "3": "outro", "outro": "outro", "4": None, "prefiro nao informar": None, "pular": None, "nao sei": None}
_YES_NO = {"1": True, "sim": True, "tenho": True, "tenho agencia": True, "ja tenho agencia": True,
           "2": False, "nao": False, "nao tenho": False, "nao tenho agencia": False,
           "nao sei": None, "3": None}
_QUESTION_COMMANDS = {"tenho uma duvida", "tenho duvida", "tenho duvidas", "outra duvida", "duvida", "duvidas",
                      "posso perguntar", "posso fazer perguntas", "quero fazer uma pergunta"}
_RESUME = {"continuar", "retomar", "seguir", "retomar atendimento"}


def _normal(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(character if character.isalnum() else " " for character in decomposed
                             if unicodedata.category(character) != "Mn").split())


def _clock(value=None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime or ISO timestamp")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.isoformat()


def _state(session: dict) -> dict:
    if not isinstance(session, dict):
        raise TypeError("session must be a dict")
    result = deepcopy(session)
    result.setdefault("schema_version", 1)
    result.setdefault("session_id", str(uuid4()))
    result.setdefault("cycle", None)
    result.setdefault("closed_cycles", [])
    result.setdefault("history", [])
    result.setdefault("observations", {})
    result.setdefault("effects", {})
    result.setdefault("processed_inbound", [])
    result.setdefault("revision", 0)
    return result


def _history(state, direction, text, now, cycle=None):
    state["history"].append({"direction": direction, "text": text, "at": _stamp(now),
                             "cycle_id": (cycle or state.get("cycle") or {}).get("id")})


def _expire(state, now):
    cycle = state.get("cycle")
    if cycle and cycle["status"] == "open" and now >= _clock(cycle["expires_at"]):
        cycle["status"], cycle["reason"] = "expired", "24h_since_last_inbound"
        cycle["closed_at"] = cycle["expires_at"]
        for effect in state["effects"].values():
            if effect["cycle_id"] == cycle["id"] and effect["status"] == "pending":
                effect["status"] = "expired"
        _history(state, "system", "Atendimento encerrado após 24 horas sem nova mensagem da pessoa.",
                 _clock(cycle["expires_at"]), cycle)


def _open(state, now):
    previous = state.get("cycle")
    if previous:
        state["closed_cycles"].append(previous)
    previous_numbers = [entry.get('number', 0) for entry in state['closed_cycles'] if isinstance(entry, dict)]
    number = max([state.get('cycle_number', 0)] + [n for n in previous_numbers if type(n) is int]) + 1
    state['cycle_number'] = number
    cycle = {"id": str(uuid4()), "number": number, "status": "open", "phase": "menu",
             "opened_at": _stamp(now), "last_inbound_at": _stamp(now), "expires_at": _stamp(now + timedelta(hours=24)),
             "facts": {}, "simulations": []}
    state["cycle"] = cycle
    return cycle


def _result(state, reply="", buttons=None, effects=None, **extra):
    return {"state": state, "reply": reply, "buttons": list(buttons or []), "effects": list(effects or []), **extra}


def _finish_reply(state, reply, buttons, now, effects=None):
    state["revision"] += 1
    if reply:
        _history(state, "outbound", reply, now)
    return _result(state, reply, buttons, effects)


def _effect(state, cycle, kind, payload):
    identifier = f"v5:{state['session_id']}:{cycle['number']}:{state['revision'] + 1}:{kind}"
    effect = {"id": identifier, "type": kind, "cycle_id": cycle["id"], "status": "pending", "payload": payload}
    state["effects"][identifier] = effect
    return effect


def _ask(state, cycle, text, now, knowledge_callback, invitation=False):
    cycle["dialogue_mode"] = "duvidas"
    if invitation:
        return _finish_reply(state, "Claro! Pode escrever sua pergunta com suas palavras. Você está conversando com uma IA da Amplify.",
                             _DOUBT_BUTTONS, now)
    prior = state["effects"].get(cycle.get("pending_question_id"))
    if prior and prior["status"] == "pending":
        prior["status"] = "superseded"
    context = {"cycle_id": cycle["id"], "phase": cycle["phase"], "facts": deepcopy(cycle["facts"]),
               "history": deepcopy([message for message in state["history"] if message["cycle_id"] == cycle["id"]]),
               "agent_is_ai": True, "can_change_business_state": False}
    effect = _effect(state, cycle, "answer_question", {"question": text, "context": context})
    cycle["pending_question_id"] = effect["id"]
    if knowledge_callback is None:
        return _finish_reply(state, "Recebi sua pergunta. Vou responder por aqui com a IA da Amplify.",
                             _DOUBT_BUTTONS, now, [deepcopy(effect)])
    try:
        answer = knowledge_callback(text, deepcopy(context))
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 8000:
            raise ValueError("invalid knowledge answer")
    except Exception:
        effect["status"] = "failed"
        return _finish_reply(state, "Não consegui responder sua dúvida agora. Pode reformular a pergunta ou continuar o atendimento. "
                             "Não vou inventar uma informação para você.", _DOUBT_BUTTONS, now)
    effect["status"] = "done"
    return _finish_reply(state, answer.strip() + "\n\nPode perguntar mais. Quando quiser seguir, escreva 'continuar'.",
                         _DOUBT_BUTTONS, now)


def _simulate(cycle, kind, now):
    cycle["simulations"].append({"kind": kind, "status": "ok", "mode": "simulated", "at": _stamp(now)})


def handle(session: dict, text: str, knowledge_callback=None, *, now=None) -> dict:
    """Process one authorized inbound. Transport owns durable dedupe and sending.

    Every new cycle starts with the menu. The optional knowledge callback takes
    (question, context) and returns text; it receives a deep copy and cannot
    change facts. Without it, the only AI instruction is an answer_question effect.
    """
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
        raise ValueError("text must contain between 1 and 4000 characters")
    state, at = _state(session), _clock(now)
    _expire(state, at)
    cycle = state.get("cycle")
    fresh = not cycle or cycle["status"] != "open"
    if fresh:
        cycle = _open(state, at)
    cycle["last_inbound_at"], cycle["expires_at"] = _stamp(at), _stamp(at + timedelta(hours=24))
    _history(state, "inbound", text.strip(), at)
    value = _normal(text)
    literal_command = "?" not in text
    if fresh:
        return _finish_reply(state, _MENU, _MAIN_BUTTONS, at)
    if literal_command and value in {"menu", "voltar", "inicio", "voltar ao menu"}:
        cycle["phase"] = "menu"
        cycle.pop("dialogue_mode", None)
        return _finish_reply(state, _MENU, _MAIN_BUTTONS, at)
    if literal_command and (value in {"conhecer", "conhecer a amplify"}
                            or (cycle["phase"] == "menu" and value == "1" and not cycle.get("dialogue_mode"))):
        cycle["phase"] = "know"
        cycle.pop("dialogue_mode", None)
        return _finish_reply(state, _KNOW, _KNOW_BUTTONS, at)
    if literal_command and (value in {"quero me agenciar", "iniciar agenciamento"}
                            or (cycle["phase"] == "menu" and value == "2" and not cycle.get("dialogue_mode"))):
        cycle["phase"] = "origin"
        cycle.pop("dialogue_mode", None)
        cycle["facts"]["interesse_agenciamento"] = True
        return _finish_reply(state, *_PROMPTS["origin"], at)
    if literal_command and value in _RESUME:
        cycle.pop("dialogue_mode", None)
        return _finish_reply(state, *_PROMPTS[cycle["phase"]], at)
    if literal_command and cycle["phase"] == "await_acceptance" and value in {"ja aceitei", "aceitei", "aceitei no ensaio", "ja aceitei no ensaio"}:
        cycle["phase"] = "form"
        cycle.pop("dialogue_mode", None)
        _simulate(cycle, "relationship", at)
        effect = _effect(state, cycle, "generate_form_link", {"cycle_id": cycle["id"],
                         "facts": deepcopy(cycle["facts"]), "verification_mode": "simulated"})
        return _finish_reply(state, "O vínculo retornou OK SIMULADO neste ensaio. Nenhum vínculo real foi criado. "
                             "Vou preparar o formulário para você preencher.", _PROMPTS["form"][1], at, [deepcopy(effect)])
    if value in _QUESTION_COMMANDS or (cycle["phase"] == "know" and value == "4"):
        return _ask(state, cycle, text, at, knowledge_callback, invitation=True)
    if cycle.get("dialogue_mode") == "duvidas":
        if value in {"1", "2", "3", "4", "sim", "nao", "nao sei"}:
            return _finish_reply(state, "Estamos tirando dúvidas. Escreva sua pergunta ou envie 'continuar' para voltar ao atendimento. "
                                 "Essa mensagem não alterou suas respostas do cadastro.", _DOUBT_BUTTONS, at)
        return _ask(state, cycle, text, at, knowledge_callback)
    if cycle["phase"] == "know":
        topic = {"1": "agency", "agenciamento": "agency", "2": "commission", "comissao": "commission",
                 "3": "benefits", "beneficios": "benefits"}.get(value)
        if topic:
            return _finish_reply(state, _INFO[topic] + "\n\nPode fazer perguntas antes de decidir se quer se agenciar.",
                                 ["Quero me agenciar", "Outra dúvida", "Voltar"], at)
    if "?" in text:
        return _ask(state, cycle, text, at, knowledge_callback)
    if cycle["phase"] == "origin" and value in _ORIGINS:
        cycle["facts"]["origem_declarada"] = _ORIGINS[value]
        cycle["phase"] = "tiktok"
        return _finish_reply(state, *_PROMPTS["tiktok"], at)
    if cycle["phase"] == "tiktok" and re.fullmatch(r"@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}", text.strip()):
        cycle["facts"]["tiktok_declarado"] = text.strip().lower()
        cycle["phase"] = "shop"
        return _finish_reply(state, *_PROMPTS["shop"], at)
    if cycle["phase"] == "shop" and value in _YES_NO:
        cycle["facts"]["shop_ativo_declarado"] = _YES_NO[value]
        cycle["phase"] = "agency"
        return _finish_reply(state, *_PROMPTS["agency"], at)
    if cycle["phase"] == "agency" and value in _YES_NO:
        cycle["facts"]["possui_agencia_declarada"] = _YES_NO[value]
        _simulate(cycle, "playwright_precheck", at)
        _simulate(cycle, "invitation", at)
        cycle["phase"] = "await_acceptance"
        return _finish_reply(state, *_PROMPTS["await_acceptance"], at)
    if cycle["phase"] == "form" and value in {"ja preenchi", "terminei", "formulario enviado"}:
        return _finish_reply(state, "A conclusão do cadastro é confirmada pelo formulário. Sua mensagem fica registrada, "
                             "mas não substitui a validação dos dados enviados.", _PROMPTS["form"][1], at)
    return _ask(state, cycle, text, at, knowledge_callback)


def handle_event(session: dict, event: dict, config: dict, knowledge_callback=None, *, now=None) -> dict:
    """Optional pure gate/dedupe wrapper; production still needs a unique DB key."""
    if not allow_inbound(config, event):
        return _result(deepcopy(session), accepted=False, duplicate=False, reason="outside_pilot")
    key = inbound_key(event)
    if key in session.get("processed_inbound", []):
        return _result(deepcopy(session), accepted=True, duplicate=True)
    at = _clock(now)
    result = handle(session, event["text"], knowledge_callback, now=at)
    # Only authenticated provider metadata can establish these observations.
    # Missing timestamps never become the processing clock or a later message.
    observed = None
    if (event.get("provider") == "chatwoot" and event.get("source_ref") == key
            and isinstance(event.get("created_at"), str) and len(event["created_at"]) <= 40):
        try:
            provider_at = _clock(event["created_at"])
            if provider_at <= at:
                observed = {"at": _stamp(provider_at), "reference": key}
        except (ValueError, TypeError, OverflowError):
            pass
    observations = result["state"]["observations"]
    first_message = not any(session.get(name) for name in ("cycle", "history", "processed_inbound", "closed_cycles"))
    if observed and first_message:
        observations.setdefault("first_inbound", {**observed, "source": "chatwoot_webhook"})
    previous_cycle, cycle = session.get("cycle") or {}, result["state"]["cycle"]
    if (observed and previous_cycle.get("id") == cycle["id"] and previous_cycle.get("phase") == "origin"
            and cycle.get("phase") == "tiktok" and cycle["facts"].get("origem_declarada") in {"anuncio", "indicacao", "outro"}):
        observations.setdefault("origin", {**observed, "source": "declaracao_pessoa",
                                           "value": cycle["facts"]["origem_declarada"]})
    result["state"]["processed_inbound"].append(key)
    result.update(accepted=True, duplicate=False, inbound_key=key)
    return result


def resolve_effect(session: dict, effect_id: str, *, answer: str | None = None, form_url: str | None = None, now=None) -> dict:
    """Apply one callback once without renewing the lead's 24-hour deadline."""
    state, at = _state(session), _clock(now)
    _expire(state, at)
    cycle, effect = state.get("cycle"), state["effects"].get(effect_id)
    if (not cycle or cycle["status"] != "open" or not effect or effect["status"] != "pending"
            or effect["cycle_id"] != cycle["id"]):
        return _result(state, ignored=True, reason="stale_or_completed_effect")
    if effect["type"] == "answer_question":
        if cycle.get("pending_question_id") != effect_id or cycle.get("dialogue_mode") != "duvidas":
            return _result(state, ignored=True, reason="question_context_changed")
        if not isinstance(answer, str) or not 0 < len(answer.strip()) <= 8000:
            raise ValueError("invalid question answer")
        reply = answer.strip() + "\n\nPode perguntar mais. Quando quiser seguir, escreva 'continuar'."
        buttons = _DOUBT_BUTTONS
    elif effect["type"] == "generate_form_link":
        if cycle["phase"] != "form":
            return _result(state, ignored=True, reason="form_context_changed")
        if cycle.get("mode") == "real":
            from real_journey import relationship_proven
            if (effect.get("payload", {}).get("verification_mode") != "real"
                    or not relationship_proven(state, now=at)):
                return _result(state, ignored=True, reason="real_relationship_not_proven")
        if not isinstance(form_url, str) or len(form_url) > 2048 or re.search(r"\s", form_url):
            raise ValueError("invalid form URL")
        parsed = urlsplit(form_url)
        if (not parsed.hostname or parsed.username or parsed.password
                or not (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}))):
            raise ValueError("form URL must use HTTPS")
        cycle["form_url"] = form_url
        reply = "Aqui está seu formulário:\n" + form_url + "\n\nO cadastro só é consolidado depois da conclusão validada. "
        if cycle.get("mode") == "real":
            reply += "Seu vínculo foi conferido no TikTok; agora confira e complete seus dados para concluir o cadastro."
        else:
            reply += "As conferências de conta, convite e vínculo deste ensaio foram simuladas."
        buttons = _PROMPTS["form"][1]
    else:
        raise ValueError("unsupported effect")
    effect["status"], effect["resolved_at"] = "done", _stamp(at)
    return _finish_reply(state, reply, buttons, at)
