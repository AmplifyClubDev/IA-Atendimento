"""Pure AI-guided rehearsal: plans are proposals, never business authority.

The caller reserves/deduplicates provider operations and persists the returned
state/outbox. This module performs no provider, filesystem or database I/O.
"""

from copy import deepcopy
import re

import engine
from contracts import allow_inbound, inbound_key


PHASES = ("intro", "origin", "tiktok", "shop", "agency", "consent", "await_acceptance", "form")
INTENTS = {"converse", "question", "clarify", "start", "continue", "pause", "restart", "accept_simulated"}
FIELDS = {
    "intro": "interesse_agenciamento", "origin": "origem_declarada", "tiktok": "tiktok_declarado",
    "shop": "shop_ativo_declarado", "agency": "possui_agencia_declarada",
    "consent": "consentimento_ensaio", "await_acceptance": "aceite_no_ensaio",
}
PROMPTS = {
    "intro": "Posso te apresentar a Amplify e tirar suas dúvidas sobre a parceria, os benefícios e a comissão. O que você gostaria de conhecer?",
    "origin": "Como você conheceu a Amplify? Se preferir não informar, pode me dizer.",
    "tiktok": "Qual é o seu @ do TikTok?",
    "shop": "Seu TikTok Shop Creator está ativo? Se não souber, pode me dizer.",
    "agency": "Você tem vínculo com outra agência atualmente? Se não souber, pode me dizer.",
    "consent": ("Neste ensaio, a conferência do perfil e o convite serão simulados, sem alterar sua conta no TikTok. "
                "Você autoriza essas simulações para continuar o teste?"),
    "await_acceptance": ("A conferência do perfil e o convite retornaram OK SIMULADO; nenhum convite real foi enviado. "
                         "Para testar o aceite, você confirma 'aceitei no ensaio'?"),
    "form": "O próximo passo é o formulário. Seu cadastro só será consolidado após a conclusão validada; mensagem de texto não confirma o recebimento.",
}
_TRUE = {"sim", "sim quero", "quero sim", "pode", "pode sim", "autorizo", "autorizo sim", "confirmo"}
_FALSE = {"nao", "nao quero", "nao autorizo", "prefiro nao", "nao tenho", "nao esta ativo"}
_UNKNOWN = {"nao sei", "nao tenho certeza", "nao sei informar"}
_START = {"quero me agenciar", "quero ser agenciado", "quero ser agenciada", "quero iniciar meu agenciamento",
          "quero iniciar o agenciamento", "tenho interesse em me agenciar", "gostaria de me agenciar"}
_CONSENT = {"autorizo a simulacao", "autorizo as simulacoes", "autorizo simulacoes", "quero continuar o ensaio", "pode fazer a simulacao"}
_ACCEPT = {"aceitei no ensaio", "ja aceitei no ensaio", "confirmo o aceite no ensaio", "aceitei na simulacao"}
_PAUSE = {"quero parar", "parar atendimento", "pausar atendimento", "pausar", "quero pausar", "encerrar atendimento", "nao quero continuar"}
_RESTART = {"recomecar", "comecar de novo", "reiniciar atendimento", "quero recomecar"}
_CHAT_RESET = {"resetar", "/resetar", "reset", "reiniciar chat"}
_RESET_GREETING = "Oi! Eu sou a Bia, agente de IA da Amplify. 👋\n\n" + PROMPTS["intro"]
_TOPIC_ENTRY = {"conhecer amplify", "conhecer a amplify", "tirar duvidas", "outra duvida"}
_TOPICS = ["Como funciona", "Benefícios", "Comissão", "Lives", "Cadastro"]
_TOPIC_TEXT = {engine._normal(value) for value in _TOPICS}
_CONTINUE = {"continuar processo", "continuar atendimento", "continuar"}
_MAIN_OPTIONS = ["Conhecer a Amplify", "Quero me agenciar", "Tirar dúvidas"]
_OPTIONS = {
    "consent": ["Autorizo simulações", "Não autorizo"],
    "await_acceptance": ["Aceitei no ensaio"],
}
_UNSAFE_REPLY = re.compile(r"https?://|convite (?:real )?enviado|v[ií]nculo (?:real )?confirmado|"
                           r"acesso (?:liberado|enviado)|cadastro (?:conclu[ií]do|aprovado)|"
                           r"(?:enviei|enviamos|liberei|criamos) (?:o |seu |um )?(?:convite|acesso|v[ií]nculo)", re.I)
_EMOJI_ATOM = r"[\U0001F300-\U0001FAFF\u2600-\u27BF](?:\uFE0F|[\U0001F3FB-\U0001F3FF])?"
_EMOJI = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}|" + _EMOJI_ATOM + r"(?:\u200D" + _EMOJI_ATOM + r")*")


def _reply_text(value, *, allow_multiple_questions=False):
    return (isinstance(value, str) and 0 < len(value.strip()) <= 1800
            and (allow_multiple_questions or value.count("?") <= 1)
            and not _UNSAFE_REPLY.search(value))


def _chat_reset_requested(text, *, real_mode=False):
    # A literal standalone command, never a question or quoted example.
    if "?" in text or any(mark in text for mark in ('"', "“", "”", "'", "‘", "’")):
        return False
    command = text.strip().casefold()
    return (command in _CHAT_RESET or real_mode and not re.search(r"[^\w\s]", command)
            and engine._normal(command) in _RESTART)


def _plan_valid(plan):
    required = {"reply", "intent", "claims", "next_phase", "topic_ids", "provider_status"}
    if (not isinstance(plan, dict) or not required <= plan.keys() or plan["provider_status"] != "completed"
            or not isinstance(plan["intent"], str) or plan["intent"] not in INTENTS
            or not isinstance(plan["next_phase"], str) or plan["next_phase"] not in PHASES
            or not isinstance(plan["reply"], str) or not isinstance(plan["claims"], list)
            or len(plan["claims"]) > 7 or not isinstance(plan["topic_ids"], list)
            or any(not isinstance(value, str) for value in plan["topic_ids"])):
        return False
    seen = set()
    for claim in plan["claims"]:
        if (not isinstance(claim, dict) or set(claim) != {"field", "value", "quote"}
                or not isinstance(claim["field"], str) or claim["field"] not in FIELDS.values() or claim["field"] in seen
                or not isinstance(claim["value"], str) or not isinstance(claim["quote"], str)
                or not 0 < len(claim["quote"]) <= 4000):
            return False
        seen.add(claim["field"])
    return True


def _literal_turn(quote, text):
    return quote in text and "?" not in text


def _explicit_start(text, quote):
    normalized = engine._normal(text)
    if re.search(r"\b(?:disse|falou|diz|perguntou|exemplo|hipotese|hipotetico|talvez)\b|"
                 r"\b(?:se|caso) (?:eu|ele|ela|voce|a pessoa)\b|"
                 r"\b(?:nao|nunca|nem) (?:quero|gostaria|pretendo) (?:me |ser )?agenciar", normalized):
        return False
    # Delimiters separate actual declarations, not a quoted sentence attributed
    # to somebody else. Bare yes/no remains governed by the current question.
    if any(character in text for character in ('"', "“", "”", "'", "‘", "’")):
        return False
    return any(engine._normal(fragment) in _START and (quote in fragment or fragment.strip() in quote)
               for fragment in re.split(r"[,;\n]+", text))


def _claim_value_single(claim, text, phase, fresh, paused, answer_pending=True):
    field, value, quote = claim["field"], claim["value"], claim["quote"]
    if field != FIELDS.get(phase) or not _literal_turn(quote, text):
        return False, None
    normalized = engine._normal(text)
    if field == "tiktok_declarado":
        # A handle may occur in a natural declaration, but not an example,
        # negation, another person's account, or a message with two handles.
        handles = re.findall(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}(?![\w.])", text)
        declaration = re.fullmatch(r"(?:meu (?:perfil|tiktok|usuario|arroba) (?:e |eh )?|(?:eu )?uso |sou (?:o |a )?)?"
                                   + re.escape(engine._normal(value)), normalized)
        if (re.fullmatch(r"@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}", value)
                and len(handles) == 1 and handles[0].lower() == value.lower()
                and value == value.lower() and value in quote.lower() and declaration):
            return True, value
        return False, None
    if field == "origem_declarada":
        origins = {"anuncio": {"anuncio", "vim de um anuncio", "vi um anuncio", "por um anuncio", "por anuncio"},
                   "indicacao": {"indicacao", "vim por indicacao", "por indicacao", "foi uma indicacao"},
                   "outro": {"outro", "outra origem"},
                   "nao_informado": {"prefiro nao informar", "nao quero informar", "nao informar", "pular", "nao sei"}}
        if value == "indicacao" and re.fullmatch(r"(?:vim |conheci a amplify |cheguei )?(?:por |pela |de uma )?indicacao(?: de (?:um |uma )?(?:amigo|amiga|creator|criador|criadora))?", normalized):
            return True, value
        if value == "anuncio" and re.fullmatch(r"(?:vim |cheguei |conheci a amplify )?(?:por |pelo |de |de um |por um )?anuncio(?: no (?:instagram|tiktok|facebook))?", normalized):
            return True, value
        return (True, None if value == "nao_informado" else value) if normalized in origins.get(value, set()) else (False, None)
    if value not in {"true", "false", "unknown"}:
        return False, None
    if field == "interesse_agenciamento":
        # The opening now asks what the person wants to learn; a bare yes is
        # not permission to start qualification, even after a previous turn.
        positive = _explicit_start(text, quote)
        return (True, True) if value == "true" and positive else (False, None)
    if field == "consentimento_ensaio":
        positive = normalized in _CONSENT or (not paused and answer_pending and normalized in _TRUE)
        if value == "true" and positive:
            return True, True
        return (True, False) if value == "false" and normalized in _FALSE else (False, None)
    if field == "aceite_no_ensaio":
        return (True, True) if value == "true" and normalized in _ACCEPT else (False, None)
    positives = set(_TRUE) if answer_pending else set()
    negatives = set(_FALSE) if answer_pending else set()
    if field == "shop_ativo_declarado":
        positives |= {"shop ativo", "meu shop esta ativo", "meu tiktok shop esta ativo", "o tiktok shop esta ativo", "esta ativo", "sim meu shop esta ativo", "sim meu tiktok shop esta ativo", "meu shop esta ativo sim"}
        negatives |= {"shop nao esta ativo", "meu shop nao esta ativo", "meu tiktok shop nao esta ativo", "nao tenho tiktok shop"}
    else:
        positives |= {"tenho agencia", "eu tenho agencia", "tenho outra agencia", "possuo agencia", "possuo outra agencia", "sim tenho agencia", "sim tenho outra agencia"}
        negatives |= {"nao tenho agencia", "eu nao tenho agencia", "nao possuo agencia", "nao tenho outra agencia", "nao nao tenho agencia", "nao tenho nenhuma agencia"}
    choices = {"true": positives, "false": negatives, "unknown": _UNKNOWN}
    return (True, {"true": True, "false": False, "unknown": None}[value]) if normalized in choices[value] else (False, None)


def _claim_value(claim, text, phase, fresh, paused, answer_pending=True):
    field = claim["field"]
    target = next((name for name, value in FIELDS.items() if value == field), None)
    if target not in {"origin", "tiktok", "shop", "agency"}:
        return _claim_value_single(claim, text, phase, fresh, paused, answer_pending)
    if phase == "form" or "?" in text or claim["quote"] not in text:
        return False, None
    # Explicit profile declarations may arrive together, in any qualification
    # order. A bare yes/no only answers the actual, pending field of this turn.
    parts = re.split(r"[,;\n]+|\s+e\s+(?=(?:eu\s+)?(?:n[aã]o|meu|tenho|possuo|o\s+tiktok|shop)\b)", text, flags=re.I)
    for fragment in [text, *parts]:
        fragment = fragment.strip()
        current_answer = phase == target and fragment == text and answer_pending
        valid, value = _claim_value_single(claim, fragment, target, fresh, paused, current_answer)
        if valid:
            return valid, value
    return False, None


def _next_phase(cycle):
    facts = cycle["facts"]
    if facts.get("interesse_agenciamento") is not True:
        return "intro"
    for phase in ("origin", "tiktok", "shop", "agency"):
        if FIELDS[phase] not in facts:
            return phase
    if facts.get("consentimento_ensaio") is not True:
        return "consent"
    return "form" if facts.get("aceite_no_ensaio") is True else "await_acceptance"


def _light_format(text):
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", text):
        matches = 0
        def keep_one(match):
            nonlocal matches
            matches += 1
            return match.group() if matches == 1 else ""
        paragraphs.append(_EMOJI.sub(keep_one, paragraph).strip())
    return "\n\n".join(paragraphs)


def _options(cycle, mode="phase"):
    if mode == "main":
        return list(_MAIN_OPTIONS)
    if mode == "opening":
        return ["Conhecer a Amplify", "Quero me agenciar"]
    if mode == "topics":
        return list(_TOPICS)
    if mode == "doubt":
        return []
    if mode == "paused":
        return list(_OPTIONS["consent"])
    return list(_OPTIONS.get(cycle.get("phase"), []))


def _model_data_request(sentence):
    """Detect a request speech act, including one written without a '?'.

    This is used only to separate proposed collection from useful explanations;
    it never rewrites commercial conditions or deterministic consent/form text.
    """
    normal = engine._normal(sentence)
    return bool("?" in sentence or re.search(
        r"\b(?:me (?:conte|conta|diga|diz|informe|envie|mande|passe|fale|confirme)"
        r"|(?:preciso|precisamos|vou precisar|vamos precisar|gostaria de|queria) "
        r"(?:entender|saber|conhecer|confirmar|verificar|receber|que voce|de\b|do seu|da sua)"
        r"|(?:pode|poderia|consegue|conseguiria) (?:me )?(?:dizer|contar|informar|enviar|mandar|passar|confirmar|compartilhar)"
        r"|(?:voce|vc) (?:precisa|deve|vai precisar) (?:me )?(?:informar|enviar|mandar|dizer|contar|compartilhar|confirmar|responder|preencher)"
        r"|(?:informe|envie|mande|compartilhe|confirme|escreva|preencha|responda|escolha|clique|acesse|abra|aceite|autorize)\b)",
        normal))


def _answer_without_requests(text):
    # Filter complete request sentences, never cut the response at its first
    # question mark: explanations after a request must survive as well.
    return " ".join(sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
                    if sentence.strip() and not _model_data_request(sentence))


def _before_interest_reply(text):
    # Keep the useful answer, but do not ask for onboarding data before opt-in.
    kept = []
    filtered = False
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        normalized = engine._normal(sentence)
        qualification = (_model_data_request(sentence) and (
            "@" in sentence
            or re.search(r"\b(?:seu|teu|sua|tua)\b.*\b(?:perfil|tiktok|arroba|nome|email|e mail|telefone|whatsapp|numero)\b", normalized)
            or re.search(r"\bvoce se chama\b", normalized)
            or re.search(r"\b(?:seu|teu)\b.*\bshop\b.*\bativ", normalized)
            or re.search(r"\b(?:voce|vc)\b.*\b(?:tem|possui|vinculo)\b.*\bagencia\b", normalized)
            or re.search(r"\b(?:como|onde)\b.*\b(?:conheceu|descobriu|chegou|encontrou)\b.*\bamplify\b", normalized)
            or re.search(r"\b(?:quer|gostaria|interesse)\b.*\b(?:agenciar|agenciamento|agenciado|agenciada)\b", normalized)))
        if sentence.strip() and not qualification:
            kept.append(sentence.strip())
        elif qualification:
            filtered = True
    return "\n\n".join(kept) if filtered else text


def _next_step_text(text, phase, cycle, intent, option_mode):
    """Complete an informative turn once; never advance state or send a nudge."""
    if (not text or cycle.get("qualification_paused")
            or intent not in {"question", "converse", "start", "continue", "accept_simulated"}
            or option_mode in {"main", "topics", "paused"}):
        return text
    # A generic closing question is the old wait-for-lead pattern. Replace only
    # its exact trailing sentence; keep real clarification and the useful answer.
    endings = list(re.finditer(r"[^.!?\n]*\?", text))
    if len(endings) == 1 and not text[endings[0].end():].strip():
        question = engine._normal(endings[0].group())
        generic = {
            "quer continuar", "voce quer continuar", "quer seguir", "quer seguir agora",
            "voce prefere tirar mais alguma duvida ou continuamos", "quer tirar mais alguma duvida",
            "tem mais alguma duvida", "ficou alguma duvida", "posso esclarecer mais ou seguir",
            "posso ajudar em mais algo", "posso te ajudar em mais algo", "posso ajudar em mais alguma coisa",
            "posso te ajudar em mais alguma coisa", "posso ajudar com algo mais",
        }
        if question in generic:
            text = text[:endings[0].start()].rstrip()
    if "?" in text:
        return text
    if phase == "intro":
        next_step = "O que você busca desenvolver hoje como creator?"
    elif phase == "form":
        # The backend still owns the real link and form-validation receipt.
        if re.search(r"\bformul[aá]rio\b", text, re.I):
            return text
        next_step = ("Agora confira e complete seus dados no formulário enviado aqui."
                     if cycle.get("form_url") else
                     "O formulário será enviado aqui pelo sistema; nele, confira e complete seus dados.")
    else:
        next_step = PROMPTS[phase]
    return (text + "\n\n" if text else "") + next_step


def _qualification_question_pending(text, phase):
    """Bare yes/no may answer only an actual, recognizable field question."""
    questions = re.findall(r"[^.!?\n]*\?", text)
    if len(questions) != 1:
        return False
    question = engine._normal(questions[0])
    if phase == "shop":
        return bool(re.fullmatch(r"(?:hoje |atualmente )?(?:e )?(?:o )?(?:seu|teu) (?:tiktok )?shop(?: creator)?"
                                 r"(?: ja)?(?: esta| ta)? (?:ativo|ativado|habilitado|liberado)(?: hoje|atualmente)?", question))
    if phase == "agency":
        return bool(re.fullmatch(r"(?:hoje |atualmente )?(?:e )?(?:voce|vc)(?: ja| atualmente)? "
                                 r"(?:(?:tem|possui)(?: algum| um)?(?: vinculo com)?(?: uma| outra| alguma)? agencia"
                                 r"|e vinculad[oa] a(?: alguma| outra| uma)? agencia)(?: atualmente| hoje)?", question))
    if phase == "consent":
        return question == "voce autoriza essas simulacoes para continuar o teste"
    # Other pending fields require explicit declarations, never bare yes/no.
    return False


def _opening_text(text):
    """Compose identification once, keeping the proposed answer intact.

    Inspect only the opening paragraph to avoid mistaking a later mention of
    AI for a self-introduction. This never strips greetings or business text.
    """
    opening, separator, remaining = text.partition("\n\n")
    normal = engine._normal(re.sub(r"[*_~`]", "", opening))
    named = re.search(r"\b(?:eu sou|sou|me chamo|aqui e|aqui quem fala e) (?:a )?bia\b", normal)
    disclosed = re.search(r"\bia\b|\binteligencia artificial\b", normal)
    if named:
        if disclosed:
            return text
        # A name-only greeting still needs explicit AI disclosure. Add it
        # without replacing or shortening any sentence supplied by the model.
        return opening + "\nSou uma agente de IA da Amplify." + (separator + remaining if separator else "")
    return "Oi! Eu sou a Bia, agente de IA da Amplify. 👋\n\n" + text


def _finish(state, phase, at, *, intro=False, reply="", notice="", effects=None, status="fallback", option_mode="phase", lead_intent=""):
    if phase == "intro" and state["cycle"]["facts"].get("interesse_agenciamento") is not True:
        reply = _before_interest_reply(reply)
        state["cycle"]["qualification_question_pending"] = False
    text = reply.strip() or ("Posso te explicar a Amplify. Escolha um assunto abaixo ou escreva sua dúvida com suas palavras."
                             if option_mode == "topics" else PROMPTS[phase])
    text = _next_step_text(text, phase, state["cycle"], lead_intent, option_mode)
    if not state["cycle"].get("qualification_paused"):
        state["cycle"]["qualification_question_pending"] = _qualification_question_pending(text, phase)
    if notice:
        text = notice + "\n\n" + text
    if intro:
        text = _opening_text(text)
    if intro and phase == "intro" and option_mode == "phase":
        option_mode = "opening"
    result = engine._finish_reply(state, _light_format(text), _options(state["cycle"], option_mode), at, effects)
    result["planner_status"] = status
    return result


def _restart_chat(state, cycle, at):
    cycle.update(status="closed", reason="lead_restart", closed_at=engine._stamp(at))
    for effect in state["effects"].values():
        if effect["cycle_id"] == cycle["id"] and effect["status"] == "pending":
            effect["status"] = "cancelled"
    cycle = engine._open(state, at)
    cycle["phase"] = "intro"
    state["history"][-1]["cycle_id"] = cycle["id"]
    cycle["qualification_question_pending"] = True
    return _finish(state, "intro", at, intro=True, reply=_RESET_GREETING)


def handle(session, text, assistant_callback=None, *, now=None, real_mode=False, operation_policy=None, source_event=None,
           inactivity_notice=None, relationship_check_in_form=False, resumed=None, qualification_enabled=False, qualification_new_cycles_only=False, approved_experience_enabled=False):
    if real_mode:
        from real_journey import handle_real
        return handle_real(session, text, assistant_callback, now=now, operation_policy=operation_policy,
                           source_event=source_event, inactivity_notice=inactivity_notice, qualification_enabled=qualification_enabled,
                           qualification_new_cycles_only=qualification_new_cycles_only, approved_experience_enabled=approved_experience_enabled,
                           **({'relationship_check_in_form': True} if relationship_check_in_form is True else {}),
                           **({'resumed': resumed} if resumed is not None else {}))
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
        raise ValueError("text must contain between 1 and 4000 characters")
    state, at = engine._state(session), engine._clock(now)
    engine._expire(state, at)
    cycle = state.get("cycle")
    fresh = not cycle or cycle["status"] != "open"
    if fresh:
        cycle = engine._open(state, at)
        cycle["phase"] = "intro"
    elif cycle.get("phase") not in PHASES:
        cycle["phase"] = _next_phase(cycle)
    elif cycle["phase"] == "await_acceptance" and cycle["facts"].get("consentimento_ensaio") is not True:
        # Old menu sessions remain intact but cannot bypass the new consent gate.
        cycle["phase"] = "consent"
    # Preserve an existing valid form context; no new form is inferred from it.
    phase = cycle["phase"]
    cycle["last_inbound_at"], cycle["expires_at"] = engine._stamp(at), engine._stamp(at + engine.timedelta(hours=24))
    engine._history(state, "inbound", text.strip(), at)
    normalized = engine._normal(text)
    # Exact user command only. handle_event has already checked scope and dedupe.
    # Do not strip punctuation or infer a reset from a question/quoted phrase.
    if _chat_reset_requested(text):
        if fresh:
            cycle["qualification_question_pending"] = True
            return _finish(state, "intro", at, intro=True, reply=_RESET_GREETING)
        return _restart_chat(state, cycle, at)
    if "?" not in text and normalized == "menu":
        cycle["qualification_question_pending"] = False
        return _finish(state, phase, at, intro=fresh,
                       reply="Escolha uma opção abaixo ou escreva com suas palavras. 👇", option_mode="main", status="navigation")
    if "?" not in text and normalized in _CONTINUE:
        cycle["qualification_question_pending"] = True
        return _finish(state, phase, at, intro=fresh, status="navigation")
    ui_mode = "topics" if normalized in _TOPIC_ENTRY else "doubt" if normalized in _TOPIC_TEXT else "phase"
    context = {
        "phase": phase, "facts": deepcopy(cycle["facts"]),
        "history": deepcopy([entry for entry in state["history"] if entry["cycle_id"] == cycle["id"]]),
        "cycle": {key: cycle[key] for key in ("id", "number", "status", "expires_at")},
        "allowed_actions": sorted(INTENTS),
        "allowed_claim_fields": ([FIELDS[phase]] if phase in FIELDS else []) +
                                ([FIELDS[name] for name in ("origin", "tiktok", "shop", "agency")
                                  if FIELDS[name] != FIELDS.get(phase)] if phase != "form" else []),
        "current_question": PROMPTS[phase], "simulation_only": True, "can_confirm_external_events": False,
        "ui_mode": ui_mode, "available_topics": list(_TOPICS),
    }
    try:
        plan = assistant_callback(text, deepcopy(context)) if callable(assistant_callback) else None
    except Exception:
        plan = None
    if not _plan_valid(plan):
        cycle["qualification_question_pending"] = True
        return _finish(state, phase, at, intro=fresh, option_mode=ui_mode)
    intent = plan["intent"]
    normalized = engine._normal(text)
    if intent == "pause" and normalized in _PAUSE and "?" not in text:
        cycle.update(status="closed", reason="lead_pause", closed_at=engine._stamp(at))
        for effect in state["effects"].values():
            if effect["cycle_id"] == cycle["id"] and effect["status"] == "pending":
                effect["status"] = "cancelled"
        return engine._finish_reply(state, "Tudo bem. Encerrei este atendimento, preservando o histórico. Quando quiser conversar de novo, pode me chamar.", [], at)
    if intent == "restart" and normalized in _RESTART and "?" not in text:
        return _restart_chat(state, cycle, at)
    applied = []
    if intent in {"start", "continue", "accept_simulated"}:
        for claim in plan["claims"]:
            field = claim["field"]
            expected_intent = "start" if field == "interesse_agenciamento" else "accept_simulated" if field == "aceite_no_ensaio" else "continue"
            profile = field in {FIELDS[name] for name in ("origin", "tiktok", "shop", "agency")}
            if intent == expected_intent or (profile and intent in {"start", "continue"}):
                valid, value = _claim_value(claim, text, phase, fresh, cycle.get("qualification_paused", False),
                                            cycle.get("qualification_question_pending", True))
                if valid:
                    cycle["facts"][claim["field"]] = value
                    applied.append(claim["field"])
    effects = []
    if applied:
        cycle["phase"] = _next_phase(cycle)
        if "consentimento_ensaio" in applied:
            cycle["qualification_paused"] = cycle["facts"]["consentimento_ensaio"] is not True
            if not cycle["qualification_paused"]:
                engine._simulate(cycle, "playwright_precheck", at)
                engine._simulate(cycle, "invitation", at)
        if "aceite_no_ensaio" in applied:
            engine._simulate(cycle, "relationship", at)
            effect = engine._effect(state, cycle, "generate_form_link", {
                "cycle_id": cycle["id"], "facts": deepcopy(cycle["facts"]), "verification_mode": "simulated",
            })
            effects.append(deepcopy(effect))
        for field in applied:
            cycle.setdefault("claim_provenance", []).append({
                "field": field, "at": engine._stamp(at), "source": "current_inbound_declaration",
            })
    authoritative = cycle["phase"]
    plain_question = intent == "question" and not applied
    reply = plan["reply"] if ((plain_question or plan["next_phase"] == authoritative)
                              and _reply_text(plan["reply"], allow_multiple_questions=plain_question)) else ""
    if cycle.get("qualification_paused"):
        paused_reply = reply if plan["intent"] in {"question", "clarify", "converse"} else ""
        return _finish(state, authoritative, at, reply=paused_reply or "Tudo bem. Não farei as simulações. Podemos conversar sobre suas dúvidas sem avançar o processo.",
                       option_mode="topics" if ui_mode == "topics" else "paused", status="applied")
    cycle["qualification_question_pending"] = bool(applied) or not reply or intent not in {"converse", "question", "clarify"}
    if normalized in _TOPIC_ENTRY or normalized in _TOPIC_TEXT:
        cycle["qualification_question_pending"] = False
    if not applied and ui_mode == "phase" and intent == "question" and reply:
        ui_mode = "doubt"
    if normalized in _CONTINUE or applied:
        ui_mode = "phase"
    notice = ""
    if "consentimento_ensaio" in applied and cycle["facts"]["consentimento_ensaio"] is True:
        notice = "A conferência do perfil e o convite retornaram OK SIMULADO; nenhum convite real foi enviado."
    if effects:
        notice = "O vínculo retornou OK SIMULADO neste ensaio; nenhum vínculo real foi criado."
    result = _finish(state, authoritative, at, intro=fresh, reply=reply, notice=notice, effects=effects, status="applied", option_mode=ui_mode, lead_intent=intent)
    result["applied_claims"] = applied
    return result


def handle_event(session, event, gate, assistant_callback=None, *, now=None, real_mode=False, operation_policy=None,
                 inactivity_notice=None, relationship_check_in_form=False, resumed=None, qualification_enabled=False, qualification_new_cycles_only=False, approved_experience_enabled=False):
    if not allow_inbound(gate, event):
        return engine._result(deepcopy(session), accepted=False, duplicate=False, reason="outside_pilot")
    key = inbound_key(event)
    if key in session.get("processed_inbound", []):
        return engine._result(deepcopy(session), accepted=True, duplicate=True)
    at = engine._clock(now)
    turn_options = {'inactivity_notice': inactivity_notice} if inactivity_notice is not None else {}
    if approved_experience_enabled is True:
        turn_options['approved_experience_enabled'] = True
    if qualification_enabled is True:
        turn_options['qualification_enabled'] = True
        turn_options['qualification_new_cycles_only'] = qualification_new_cycles_only
    if relationship_check_in_form is True:
        turn_options['relationship_check_in_form'] = True
    if resumed is not None and real_mode:
        turn_options['resumed'] = resumed
    result = handle(session, event["text"], assistant_callback, now=at,
                    real_mode=real_mode, operation_policy=operation_policy,source_event=event,
                    **turn_options)
    observed = None
    if event.get("provider") == "chatwoot" and event.get("source_ref") == key and isinstance(event.get("created_at"), str):
        try:
            provider_at = engine._clock(event["created_at"])
            if provider_at <= at:
                observed = {"at": engine._stamp(provider_at), "reference": key}
        except (ValueError, TypeError, OverflowError):
            pass
    observations = result["state"]["observations"]
    first = not any(session.get(name) for name in ("cycle", "history", "processed_inbound", "closed_cycles"))
    if observed and first:
        observations.setdefault("first_inbound", {**observed, "source": "chatwoot_webhook"})
    origin_source=result.get('origin_source')
    if real_mode and isinstance(origin_source,dict):
        reference=origin_source.get('reference')
        if (reference==key or reference in session.get('processed_inbound',[])) and isinstance(origin_source.get('at'),str):
            observed={'at':origin_source['at'],'reference':reference}
        else:
            observed=None
    # Prefilled ad declarations may return through the fixed greeting before
    # applied_claims is emitted. Persist only a fresh, source-backed declaration,
    # never an old fact carried from another cycle or an inferred channel.
    previous_origin = (session.get("cycle") or {}).get("facts", {}).get("origem_declarada")
    current_cycle = result["state"].get("cycle") or {}
    prefilled_origin = (real_mode and previous_origin is None
                        and current_cycle.get("facts", {}).get("origem_declarada") == "anuncio"
                        and any(item.get("field") == "origem_declarada"
                                and item.get("source") == "ad_prefilled_message"
                                and item.get("at") == engine._stamp(at)
                                for item in current_cycle.get("claim_provenance", [])
                                if isinstance(item, dict)))
    if observed and ("origem_declarada" in result.get("applied_claims", []) or prefilled_origin):
        value = result["state"]["cycle"]["facts"].get("origem_declarada")
        if value in {"anuncio", "indicacao", "outro"}:
            observations.setdefault("origin", {**observed, "source": "ad_prefilled_message" if prefilled_origin else "declaracao_pessoa", "value": value})
    result["state"]["processed_inbound"].append(key)
    result.update(accepted=True, duplicate=False, inbound_key=key)
    return result


def resolve_effect(session, effect_id, **kwargs):
    result = engine.resolve_effect(session, effect_id, **kwargs)
    cycle = result['state'].get('cycle') or {}
    effect = result['state'].get('effects', {}).get(effect_id) or {}
    if (cycle.get('relationship_check_in_form') is True and effect.get('type') == 'generate_form_link'
            and not result.get('ignored') and cycle.get('form_url')):
        result['reply'] = ('*Abra seu formulário:*\n' + cycle['form_url'] +
                           '\n\nNele, informe seu @ para verificar o agenciamento antes de preencher os dados.')
    result["buttons"] = _options(result["state"]["cycle"]) if result.get("reply") else []
    return result


def resolve_tiktok_result(session, effect_id, result, *, now=None, operation_policy=None):
    """Worker-only pure settlement; inbound text and AI cannot call providers."""
    from real_journey import resolve_tiktok_result as settle
    return settle(session, effect_id, result, now=now, operation_policy=operation_policy)
