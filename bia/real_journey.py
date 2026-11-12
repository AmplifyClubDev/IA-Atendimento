"""Pure, evidence-led journey for the single-contact real integration.

This module only proposes durable work. Providers, credentials, claims and
outbound delivery belong to the worker. A lead declaration never proves a
TikTok event. Legacy simulated facts have no authority in this journey.
"""
from copy import deepcopy
import os
import pilot_scope
from datetime import timedelta
import hashlib
import json
import math
import re

import conversao
import engine


# Navigation verified in TikTok Shop's Brazilian guidance; UI labels can change.
# https://seller-br.tiktok.com/university/essay?knowledge_id=8093741534234385&lang=pt-BR
_ACCEPT_INVITE_GUIDE = (
    "No TikTok Shop Creator, abra *Parcerias* ou *Notificações* e procure o convite da *Amplify*. "
    "Confira o percentual, o prazo e as autorizações; aceite somente se estiver de acordo.\n\n"
    "Depois de aceitar, me avise por aqui. Vou consultar o TikTok para confirmar se o vínculo foi efetivado. 😊"
)

PHASES = ("intro", "origin", "tiktok", "shop", "agency", "checking", "consent_real",
          "inviting", "await_acceptance", "checking_acceptance", "form", "blocked")
INTENTS = {"converse", "question", "clarify", "start", "continue", "pause", "restart",
           "consent_real", "check_acceptance"}
FIELDS = {"interesse_agenciamento", "nome_declarado", "origem_declarada", "tiktok_declarado",
          "shop_ativo_declarado", "possui_agencia_declarada", "consentimento_convite", "aceite_declarado"}
PROFILE = {"nome_declarado", "origem_declarada", "origem_canal_declarado", "tiktok_declarado"}
PROMPTS = {
    "intro": conversao.BENEFITS + "\n\nVocê quer se agenciar ou conhecer a proposta primeiro?",
    "origin": "Como você conheceu a Amplify? Se preferir não informar, pode me dizer.",
    "tiktok": "Qual é o seu @ do TikTok? Vou consultar esse perfil para conferir o caminho do agenciamento.",
    "shop": "Seu TikTok Shop Creator está ativo? Se não souber, posso conferir na consulta.",
    "agency": "Você tem vínculo com outra agência atualmente? Se não souber, pode me dizer.",
    "checking": "Estou conferindo seu perfil e o vínculo no TikTok. Assim que a consulta terminar, te oriento sobre o próximo passo. 🔎",
    "consent_real": "A consulta terminou. Falta conferir as condições da parceria antes de autorizar o convite real.",
    "inviting": conversao.INVITING,
    "acesso": conversao.ACCESS_DONE,
    "await_acceptance": _ACCEPT_INVITE_GUIDE,
    "checking_acceptance": "Estou conferindo no TikTok se o seu aceite já apareceu. Te aviso aqui assim que confirmar. 🔎",
    "form": "Agora confira e complete seus dados no formulário. O cadastro só é confirmado após o envio validado.",
    "blocked": "Não consegui confirmar seu perfil automaticamente 😕 Quando quiser que eu confira de novo, é só me mandar uma mensagem aqui.\n\nEnquanto isso, quer tirar alguma dúvida?",
}
_REAL_CONSENT = {"pode mandar", "pode mandar o convite", "pode mandar sim", "sim pode mandar", "manda", "manda sim",
                 "pode me mandar", "pode me mandar o convite", "quero o convite", "quero sim",
                 "autorizo enviar o convite", "autorizo o convite real", "confirmo o convite real",
                 "pode enviar o convite", "sim autorizo enviar o convite", "autorizo convite real",
                 "sim pode enviar", "sim pode mandar o convite", "pode enviar sim",
                 "aceito as condicoes e autorizo enviar o convite"}
_ACCEPTANCE = {"aceitei", "ja aceitei", "aceitei o convite", "ja aceitei o convite", "aceitei no tiktok",
               "ja aceitei no tiktok", "confirmo que aceitei o convite", "verificar aceite", "verificar vinculo"}
_ACCEPT_NEXT_STEP = ("Quando aceitar o convite da *Amplify* no TikTok Shop Creator (em *Parcerias* ou *Notificações*), "
                     "me manda “aceitei” que eu confiro na hora. 😊")
# Depois de um convite, "feito"/"pronto" respondem ao pedido de aceite.
_ACCEPTANCE_CONTEXTUAL = {"feito", "pronto", "prontinho", "ja fiz", "fiz", "consegui", "ja consegui", "ok feito",
                          "pronto feito", "feito ja", "ja feito", "tudo certo", "ja esta", "ja ta"}
# Release 40: conferência do perfil que falhou porque a ponte estava fora (não por perfil inelegível).
BRIDGE_DOWN_REASONS = frozenset({'human_verification_required', 'session_not_ready', 'transport_unconfirmed',
                                 'invalid_response', 'redirect_rejected', 'response_too_large',
                                 'precheck_unconfirmed', 'response_unconfirmed', 'executor_result_unconfirmed'})
BRIDGE_RETRY_LIMIT = 3
BRIDGE_RETRY_GAP = timedelta(minutes=10)
INVITE_FAILED_RETRY_SECONDS = 600
_BRIDGE_WAIT = conversao.BRIDGE_WAIT
_BRIDGE_STILL = conversao.BRIDGE_STILL
_BRIDGE_BACK = conversao.BRIDGE_BACK
# Conversas paradas na ponte em 31/10 (auditoria de 01/11): reconferidas uma vez,
# qualquer que tenha sido o motivo registrado da falha (menos perfil inelegível).
INITIAL_RECHECK = pilot_scope.historical_event_keys('V5_INITIAL_RECHECK_EVENT_KEYS')
# Release 41: o convite também é reenviado sozinho quando a ponte de Convites volta (até 3 vezes, a cada 10 min).
INVITE_BRIDGE_RETRY_LIMIT = 3

INITIAL_INVITE_RECHECK = pilot_scope.historical_event_keys('V5_INITIAL_INVITE_RECHECK_EVENT_KEYS')
_YES = {"sim", "confirmo", "sim confirmo", "autorizo", "autorizo sim", "pode enviar"}
_NO = {"nao", "nao autorizo", "nao quero", "nao confirmo"}
_FAQ_MENU = {'conhecer amplify','conhecer a amplify','menu de duvidas','menu duvidas','tirar duvidas'}
_INTRO_ACTION = 'Se quiser começar, toque em *Quero me agenciar* 😊'
_OPERATIONS = {"lookup", "precheck", "invite", "relationship"}
_STATUS = {
    "precheck": {"eligible", "ineligible", "verification_pending", "failed", "outcome_unknown"},
    "invite": {"sent", "linked", "pending", "ineligible", "pending_verification", "verification_pending", "failed", "outcome_unknown"},
    "relationship": {"linked", "pending", "not_found", "verification_pending", "failed", "outcome_unknown"},
    "lookup": {"observed", "not_found", "verification_pending", "failed", "outcome_unknown"},
}


# Release 43: os códigos das pontes são a chave da automação (ESTADO-DO-ATENDIMENTO.md, seção 5b).
# Cada código leva a uma ação e a uma mensagem; o teste test_codigos43 percorre todos e confere o comportamento.
# "mensagem" é o nome do texto em conversao.py; SILENCIO só quando a leitura é automática e nada mudou (regra da 42).
CLIENT_BLOCKED = ('human_login_required', 'captcha_required', 'mfa_required', 'session_or_partner_context_invalid',
                  'partner_probe_rejected', 'blocked_by_risk_guard')  # a ponte devolve; o cliente vira human_verification_required
BRIDGE_CODE_TABLE = {
    ('relationship', 'linked'): ('mandar o cadastro na hora, sem esperar "aceitei"', 'INVITE_ACCEPTED'),
    ('relationship', 'pending'): ('acompanhar: 15 min, 2 h, 1 vez por dia; passo a passo se o lead diz que não aparece',
                                  'INVITE_IS_THERE'),
    ('relationship', 'not_found'): ('convite dado como feito ou incerto: aviso e reenvio (com a prova da lista); '
                                    'sem convite: pedir a autorização', 'INVITE_NOT_LANDED'),
    ('relationship', 'verification_pending'): ('ler de novo: na leitura automática, no próximo horário; pedida pelo lead, '
                                               'em 5, 15 e 60 min', 'RELATIONSHIP_RETRY'),
    ('relationship', 'failed'): ('igual a verification_pending', 'RELATIONSHIP_RETRY'),
    ('relationship', 'outcome_unknown'): ('igual a verification_pending', 'RELATIONSHIP_RETRY'),
    ('precheck', 'eligible'): ('pedir a autorização do convite', 'consent_full'),
    ('precheck', 'ineligible'): ('encerrar com respeito', 'PROFILE_INELIGIBLE'),
    ('precheck', 'verification_pending'): ('Shop sem status: passo a passo e reconferir no "pronto", no máximo a cada '
                                           '10 min; ponte fora: bridge_wait e reconferência', 'SHOP_UNKNOWN'),
    ('precheck', 'failed'): ('bridge_wait e reconferência', 'BRIDGE_WAIT'),
    ('precheck', 'outcome_unknown'): ('bridge_wait e reconferência', 'BRIDGE_WAIT'),
    ('invite', 'sent'): ('aguardando aceite (o envio já foi conferido na lista)', 'INVITE_SENT'),
    ('invite', 'linked'): ('mandar o cadastro na hora', 'INVITE_ACCEPTED'),
    ('invite', 'pending'): ('acompanhar (o convite já estava no TikTok)', 'INVITE_ALREADY_THERE'),
    ('invite', 'pending_verification'): ('não dizer "enviado"; ler a lista em 5 min e seguir pelo código do vínculo',
                                         'INVITE_CONFIRMING'),
    ('invite', 'outcome_unknown'): ('igual a pending_verification', 'INVITE_CONFIRMING'),
    ('invite', 'verification_pending'): ('ponte fora: invite_wait e reconferência (prova da lista); Shop sem status: '
                                         'passo a passo', 'INVITE_WAIT'),
    ('invite', 'ineligible'): ('encerrar com respeito', 'PROFILE_INELIGIBLE'),
    ('invite', 'failed'): ('1 nova tentativa em 10 min; se falhar de novo, alerta à equipe (atendimento em blocked: '
                           'o vigia do Cadastro avisa em 30 min)', 'INVITE_RETRYING'),
    ('invite', 'failed_again'): ('alerta à equipe', 'INVITE_FAILED_TEAM'),
    **{('*', code): ('bridge_wait (convite: invite_wait) e reconferência quando a ponte voltar',
                     'BRIDGE_WAIT') for code in CLIENT_BLOCKED + tuple(sorted(BRIDGE_DOWN_REASONS))},
}


def _creator(value):
    return value.lower() if isinstance(value, str) and re.fullmatch(r"@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}", value) else None


def _result_creator(value):
    return _creator(value if isinstance(value, str) and value.startswith("@") else "@" + value if isinstance(value, str) else None)


def policy_valid(policy):
    """Only an explicitly approved, versioned policy can authorize an invite."""
    return (isinstance(policy, dict) and policy.get("approved") is True
            and type(policy.get("commission")) in (int, float)
            and math.isfinite(policy["commission"]) and 0 <= policy["commission"] <= 10
            and policy.get("commission_unit") == "percent"
            and policy.get("duration_fixed_months") == 2 and policy.get("duration_label") == "2 meses"
            and isinstance(policy.get("version"), str) and 0 < len(policy["version"]) <= 120)


def _policy_fingerprint(policy):
    return hashlib.sha256(json.dumps({key: policy[key] for key in
        ("version", "commission", "commission_unit", "duration_fixed_months", "duration_label")}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _consent_prompt(cycle, policy):
    if not policy_valid(policy):
        cycle.pop("invite_offer", None)
        return ("Seu perfil passou pela consulta. Antes de enviar um convite real, as condições da parceria "
                "precisam estar confirmadas pela Amplify. Vou aguardar essa confirmação para te apresentar tudo com clareza.")
    policy_hash = _policy_fingerprint(policy)
    cycle["invite_offer"] = {"policy_hash": policy_hash, "policy_version": policy["version"],
                              "creator": cycle["facts"].get("tiktok_declarado")}
    if cycle.get("consent_shown") == policy_hash + ":" + str(cycle["facts"].get("tiktok_declarado")):
        return "Posso te mandar o convite no TikTok? 😊"
    cycle["consent_shown"] = policy_hash + ":" + str(cycle["facts"].get("tiktok_declarado"))
    return conversao.consent_full(_first_name(cycle), cycle["facts"]["tiktok_declarado"], policy)


# Release 52 (03/11, pedido do usuário): "a máquina não está enviando convites de forma automática".
# Perfil aprovado → o convite sai sem esperar o "Pode mandar"; o lead vê as condições e aceita no TikTok.
# Quem recusou ("não"), pediu para parar ou está com uma pessoa nunca recebe convite automático.
AUTO_INVITE = os.environ.get('V5_AUTO_INVITE', '').strip().lower() == 'true'


def _auto_invite_allowed(state, policy):
    cycle = state.get('cycle') or {}
    facts = cycle.get('facts') or {}
    offer = cycle.get('invite_offer') or {}
    return (AUTO_INVITE and not policy.get('require_explicit_consent') and policy_valid(policy) and facts.get('consentimento_convite') is not False
            and not state.get('opt_out') and not cycle.get('opt_out') and not state.get('human_control')
            and not cycle.get('qualification_paused') and not cycle.get('pending_profile_changes')
            and bool(facts.get('tiktok_declarado')) and offer.get('creator') == facts.get('tiktok_declarado')
            and offer.get('policy_hash') == _policy_fingerprint(policy))


def _grant_auto_consent(cycle, at):
    cycle['facts']['consentimento_convite'] = True
    cycle['invite_consent'] = {**cycle['invite_offer'], 'cycle_id': cycle['id'], 'at': engine._stamp(at),
                               'source': 'auto_after_eligible'}


def _auto_invite(state, at, policy, *, prefix=''):
    """Logo depois da pré-validação aprovada: condições + convite, numa mensagem só."""
    if not _auto_invite_allowed(state, policy):
        return None
    cycle = state['cycle']
    before = deepcopy(cycle)
    _grant_auto_consent(cycle, at)
    job = _effect(state, 'invite', at, policy=policy)
    if not job:
        state['cycle'] = before
        return None
    cycle['phase'] = 'inviting'
    name, handle = _first_name(cycle), cycle['facts']['tiktok_declarado']
    result = _finish(state, at, reply=prefix + conversao.auto_invite(name, handle, policy), effects=[job], buttons=[])
    result['applied_claims'] = ['consentimento_convite']
    return result


def auto_invite_due(state, now, policy):
    """Quem já estava parado esperando o "Pode mandar" (antes da 52): a reconferência envia sozinha."""
    cycle = state.get('cycle') or {}
    try:
        at, expires = engine._clock(now), engine._clock(cycle.get('expires_at'))
    except (TypeError, ValueError, AttributeError, OverflowError):
        return False
    if (cycle.get('mode') != 'real' or cycle.get('status') != 'open' or cycle.get('phase') != 'consent_real'
            or not expires or at >= expires or (cycle.get('real_operations') or {}).get('invite')
            or not _auto_invite_allowed(state, policy)):
        return False
    return not any(effect.get('type') == 'tiktok_operation' and effect.get('status') in {'pending', 'running'}
                   and effect.get('operation') in {'precheck', 'invite', 'relationship'}
                   and effect.get('cycle_id') == cycle.get('id') for effect in (state.get('effects') or {}).values())


def auto_invite_effect(state, now, policy):
    """O convite (ou, com a validação vencida, a nova validação que leva ao convite em silêncio)."""
    if not auto_invite_due(state, now, policy):
        return None
    at, cycle = engine._clock(now), state['cycle']
    before = deepcopy(cycle)
    _grant_auto_consent(cycle, at)
    # A prior-cycle write must be reconciled before refreshing eligibility.
    # Otherwise every expired precheck returns to consent_real indefinitely.
    if _prior_invite_requires_reconciliation(state, _creator(cycle['facts'].get('tiktok_declarado'))):
        check = _acceptance_check(state, at, 0, origin=engine._stamp(at))
        if check:
            cycle['prior_invite_check'] = {'at': engine._stamp(at), 'effect_id': check['id']}
            cycle['phase'] = 'checking_acceptance'
            state['revision'] += 1
            return check
        state['cycle'] = before
        return None
    if precheck_proven(state, now=at):
        job = _effect(state, 'invite', at, policy=policy)
        if job:
            cycle['phase'] = 'inviting'
            state['revision'] += 1
            return job
    else:
        check = _effect(state, 'precheck', at)
        if check:
            cycle['consent_refresh'] = {'at': engine._stamp(at), 'precheck_effect_id': check['id']}
            cycle['phase'] = 'checking'
            state['revision'] += 1
            return check
    state['cycle'] = before
    return None


NAME_QUESTION = 'Antes de seguir, como posso te chamar? 😊'


def _first_name(cycle):
    from nome_contextual import first_name
    value = (cycle.get('facts') or {}).get('nome_declarado')
    return first_name(value) if isinstance(value, str) and value.strip() else None


def _linked(cycle):
    return any(isinstance(record, dict) and record.get('status') == 'linked'
               for record in (cycle.get('real_operations') or {}).values())


def _form_prompt(cycle):
    name = _first_name(cycle)
    if _linked(cycle):
        return ('Tudo certo com seu agenciamento' + (', ' + name if name else '') + '! 🎉\n\n'
                'Agora é só fazer seu cadastro por aqui:\n' + PUBLIC_FORM_URL + '\n\n'
                'Leva poucos minutos e, no final, você já recebe seu acesso à comunidade.')
    return ((name + ', assim' if name else 'Assim') + ' que aceitar o convite no app do TikTok, é só fazer seu cadastro por aqui:\n'
            + PUBLIC_FORM_URL + '\n\nNo formulário, informe seu @. Ele confere o agenciamento antes de liberar o cadastro.')


def _form_link_recent(state, url, last=3):
    """O botão do cadastro já foi numa das últimas respostas: não repete a cada dúvida."""
    sent = [h for h in (state.get('history') or []) if h.get('direction') == 'outbound']
    return any(url in str(h.get('text') or '') for h in sent[-last:])


def _phase_prompt(cycle, phase=None):
    phase = phase or cycle['phase']
    if phase == 'form':
        return _form_prompt(cycle)
    if phase == 'blocked' and isinstance(cycle.get('bridge_wait'), dict):
        return _BRIDGE_STILL
    if phase == 'blocked' and isinstance(cycle.get('invite_wait'), dict):
        return conversao.INVITE_STILL
    if phase == 'blocked' and _first_name(cycle):
        return _first_name(cycle) + ', ' + PROMPTS['blocked'][0].lower() + PROMPTS['blocked'][1:]
    if cycle.get('relationship_check_in_form') is True:
        if phase == 'checking':
            return 'Estou conferindo seu perfil e a elegibilidade no TikTok Shop. Assim que a consulta terminar, te oriento sobre o próximo passo. 🔎'
        if phase == 'await_acceptance':
            return _ACCEPT_NEXT_STEP
        if phase == 'checking_acceptance':
            return PROMPTS['checking_acceptance']
    return PROMPTS[phase]


def _finish(state, at, *, reply=None, effects=None, status="real", intro=False, buttons=None, force_form_button=False,
            exact=False):
    import conversation
    from nome_contextual import name_question
    cycle = state["cycle"]
    if (not reply and cycle.get('relationship_check_in_form') is True
            and cycle.get('phase') in {'await_acceptance', 'checking_acceptance'}):
        handed_off = _form_after_invite(state, at)
        if handed_off is not None:
            return handed_off
    text = reply or _phase_prompt(cycle)
    if (cycle.get('phase') == 'origin' and not cycle.get('name_asked') and text.endswith(PROMPTS['origin'])
            and not (cycle.get('facts') or {}).get('nome_declarado')):
        cycle['name_asked'] = True
        prefix = text[:-len(PROMPTS['origin'])]
        text = prefix + ('' if prefix.strip() else 'Que bom que você quer fazer parte! 😊\n\n') + NAME_QUESTION
    if intro:
        text = conversation._opening_text(text)
    cycle['name_question_pending']=name_question(text)
    if buttons is None:
        buttons = (["Conhecer a Amplify", "Quero me agenciar"] if cycle["phase"] == "intro" and intro
                   else ["Anúncio", "Indicação", "Outra origem"] if cycle["phase"] == "origin" and text.endswith(PROMPTS["origin"])
                   else list(conversao.CONSENT_BUTTONS) if cycle["phase"] == "consent_real" and cycle.get("invite_offer")
                   else ["Verificar aceite"] if cycle["phase"] == "await_acceptance" else [])
    if cycle.get('experience_version') == 'bia-approved-v1':
        text = text.replace(_INTRO_ACTION, 'Se quiser começar, toque em *Quero fazer parte* 😊')
        buttons = ['Quero fazer parte' if label == 'Quero me agenciar' else label for label in buttons]
    text, buttons = _form_button_once(cycle, text, buttons, force=force_form_button)
    if cycle.get('phase') in {'intro', 'origin', 'tiktok'} and not _creator(cycle['facts'].get('tiktok_declarado')):
        cycle['arroba_pedido'] = text in {_HANDLE_UNKNOWN, conversao.HANDLE_HELP} or bool(re.search(
            r'(?:qual.{0,15}@|(?:me manda|me envie|me manda seu|me informe).{0,20}@)', text, re.I))
    # Release 42: os textos aprovados saem como estão (o filtro tiraria o 2º emoji do parágrafo).
    transition = engine._finish_reply(state, text if exact or cycle.get('experience_version') == 'bia-approved-v1' else conversation._light_format(text), buttons, at, effects)
    transition["planner_status"] = status
    return transition


def _effect(state, operation, at, *, policy=None, retry=False, list_proof=False):
    cycle, creator = state["cycle"], _creator(state["cycle"]["facts"].get("tiktok_declarado"))
    from lead_validation import permitted as validation_permitted
    if not validation_permitted(cycle):
        return None
    if not creator or operation not in _OPERATIONS:
        return None
    for effect in state["effects"].values():
        if (effect.get("type") == "tiktok_operation" and effect.get("cycle_id") == cycle["id"]
                and effect.get("creator") == creator and effect.get("operation") == operation
                and effect.get("status") in {"pending", "running", "outcome_unknown"}):
            # A completed absence read reconciles an interrupted invitation.
            # Preserve its original receipt; only a new bounded, evidenced job may write.
            if (operation == 'invite' and effect.get('status') == 'outcome_unknown'
                    and list_proof and _list_proof(state, at)):
                continue
            return None
    resend = False
    if operation == "invite":
        if _prior_invite_requires_reconciliation(state, creator):
            return None
        # Release 42: no máximo 1 reenvio por lead, contando o convite de um atendimento anterior.
        resend = list_proof or _prior_invite_requires_reconciliation(state, creator, honor_cleared=False)
        if resend and resend_used(state, creator, unlanded=list_proof == 'unlanded'):
            return None
        consent = cycle.get("invite_consent") or {}
        offer = cycle.get("invite_offer") or {}
        if (not policy_valid(policy) or not precheck_proven(state, now=at)
                or consent.get("creator") != creator or consent.get("cycle_id") != cycle["id"]
                or consent.get("policy_hash") != _policy_fingerprint(policy)
                or consent.get("policy_hash") != offer.get("policy_hash")):
            return None
        # An invitation may be attempted once per creator/cycle. The single
        # exception is ``retry``: a second attempt after a receipt proving that
        # TikTok never received a create request (see _invite_retry_possible).
        # Release 41: the invite bridge recheck passes the number of earlier
        # attempts; each of them must carry that same no-write proof.
        previous = [e for e in state["effects"].values() if e.get("type") == "tiktok_operation"
                    and e.get("cycle_id") == cycle["id"] and e.get("creator") == creator and e.get("operation") == "invite"]
        counted = type(retry) is int
        allowed = retry if counted else 1 if retry else 0
        if list_proof:
            # Release 42: a lista de vínculos, lida depois da última tentativa, mostra que nada chegou ao TikTok.
            if not _list_proof(state, at):
                return None
        elif len(previous) > allowed or (counted and (len(previous) > 1 + INVITE_BRIDGE_RETRY_LIMIT or not all(
                _invite_no_write(e.get("result_receipt")) for e in previous))):
            return None
    sequence = 1 + sum(e.get("type") == "tiktok_operation" and e.get("cycle_id") == cycle["id"]
                       for e in state["effects"].values())
    identifier = "tiktok:" + hashlib.sha256(f"{cycle['id']}:{creator}:{operation}:{sequence}".encode()).hexdigest()
    effect = {"id": identifier, "type": "tiktok_operation", "operation": operation,
              "creator": creator, "cycle_id": cycle["id"], "revision": state["revision"] + 1,
              "status": "pending", "created_at": engine._stamp(at), "confirmed": operation == "invite",
              "payload": {"operation": operation, "creator": creator, "cycle_id": cycle["id"]}}
    if operation == "invite":
        effect.update(commission=policy["commission"], commission_unit=policy["commission_unit"],
                      duration_fixed_months=policy["duration_fixed_months"], duration_label=policy["duration_label"],
                      policy_version=policy["version"], policy_hash=_policy_fingerprint(policy),
                      consent=deepcopy(cycle["invite_consent"]))
        effect["payload"].update(confirmed=True, commission=policy["commission"],
                                 duration_fixed_months=policy["duration_fixed_months"])
        if retry or list_proof:
            # Each attempt gets its own worker row (an invite row is never resubmitted).
            effect["payload"]["retry"] = len(previous) if counted or list_proof else 1
        if list_proof:
            effect["payload"]["list_proof"] = True
        if resend:
            state.setdefault("invite_resends", {})[creator] = {
                "at": engine._stamp(at), "cycle_id": cycle["id"], "effect_id": identifier,
                "reason": "list_proof_unlanded" if list_proof == 'unlanded' else "list_proof" if list_proof
                else "prior_invite_not_found", "count": resend_count(state, creator) + 1}
    state["effects"][identifier] = effect
    return deepcopy(effect)


INVITE_RETRY_DELAY_SECONDS = 180


def _invite_no_write(record):
    """True only when the receipt proves TikTok never received a create request."""
    evidence = record.get("evidence") if isinstance(record, dict) else None
    if not isinstance(evidence, dict) or evidence.get("create_accepted") is True:
        return False
    if evidence.get("post_attempted") is False:
        return True
    receipt = evidence.get("receipt") if isinstance(evidence.get("receipt"), dict) else {}
    # The UI bridge routes every create request through its guard, so an
    # unobserved request is proof that nothing reached the provider.
    return (receipt.get("method") == "ui" and receipt.get("provider_request_observed") is False
            and receipt.get("provider_post_attempted") is False and receipt.get("create_post_blocked") is not True)


def _invite_attempts(state):
    cycle = state["cycle"]
    creator = _creator(cycle["facts"].get("tiktok_declarado"))
    return [e for e in state["effects"].values() if e.get("type") == "tiktok_operation" and e.get("operation") == "invite"
            and e.get("cycle_id") == cycle["id"] and e.get("creator") == creator]


def _invite_retry_possible(state):
    """One automatic retry, only for a consented invite that never reached TikTok."""
    cycle = state["cycle"]
    record = (cycle.get("real_operations") or {}).get("invite") or {}
    attempts = _invite_attempts(state)
    consent = cycle.get("invite_consent") or {}
    return (record.get("status") in {"outcome_unknown", "verification_pending", "failed"} and _invite_no_write(record)
            and len(attempts) == 1 and attempts[0].get("id") == record.get("job_id")
            and consent.get("cycle_id") == cycle["id"] and cycle["facts"].get("consentimento_convite") is True
            and not cycle.get("invite_retry") and not state.get("human_control"))


def _schedule_invite_retry(state, at, *, delay):
    """Refresh the precheck first; its eligible result queues the single retry."""
    cycle = state["cycle"]
    check = _effect(state, "precheck", at)
    if not check:
        return None
    if delay:
        not_before = engine._stamp(at + timedelta(seconds=delay))
        state["effects"][check["id"]]["payload"]["not_before"] = not_before
        check["payload"]["not_before"] = not_before
    cycle["invite_retry"] = {"at": engine._stamp(at), "precheck_effect_id": check["id"],
                             "previous_invite_job_id": ((cycle.get("real_operations") or {}).get("invite") or {}).get("job_id")}
    cycle["phase"] = "checking"
    return check


def _prior_invite_requires_reconciliation(state, creator, *, honor_cleared=True):
    """A conversation reset never authorizes repeating a real write for an @."""
    current_cycle = state["cycle"]["id"]
    cleared = state["cycle"].get("prior_invite_cleared") or {}
    relationship = (state["cycle"].get("real_operations") or {}).get("relationship") or {}
    if (honor_cleared and cleared.get("creator") == creator and relationship.get("status") == "not_found"
            and relationship.get("confirmed") is True and relationship.get("job_id") == cleared.get("effect_id")
            and relationship.get("cycle_id") == current_cycle):
        return False
    archived = {cycle.get("id"): cycle for cycle in state.get("closed_cycles", []) if isinstance(cycle, dict)}
    for effect in state.get("effects", {}).values():
        if (effect.get("type") != "tiktok_operation" or effect.get("operation") != "invite"
                or effect.get("creator") != creator or effect.get("cycle_id") == current_cycle):
            continue
        old_cycle = archived.get(effect.get("cycle_id")) or {}
        record = effect.get("result_receipt") or (old_cycle.get("real_operations") or {}).get("invite") or {}
        bound = (isinstance(record, dict) and record.get("job_id") == effect.get("id")
                 and record.get("creator") == creator and record.get("cycle_id") == effect.get("cycle_id"))
        evidence = record.get("evidence") if bound else None
        # A legacy done/superseded effect without its receipt is not proof that
        # no POST happened. Only an explicit negative write receipt releases it.
        no_write = (bound and record.get("status") in {"ineligible", "failed"}
                    and isinstance(evidence, dict) and evidence.get("post_attempted") is False
                    and evidence.get("create_accepted") is not True)
        if not no_write:
            return True
    return False


def _cancel_for_profile_change(state, cycle):
    # The current profile projection may be discarded, but the real invitation
    # receipt belongs permanently to its effect/@, including after a reset.
    receipt = (cycle.get("real_operations") or {}).get("invite") or {}
    prior = state["effects"].get(receipt.get("job_id")) if isinstance(receipt, dict) else None
    if (isinstance(prior, dict) and prior.get("operation") == "invite"
            and prior.get("cycle_id") == receipt.get("cycle_id") == cycle.get("id")
            and prior.get("creator") == receipt.get("creator")):
        prior["result_receipt"] = deepcopy(receipt)
    for effect in state["effects"].values():
        if effect.get("cycle_id") == cycle["id"] and effect.get("status") in {"pending", "running"}:
            effect["status"] = "superseded"
    for name in ("invite_offer", "invite_consent", "real_operations", "form_url", "form_effect_id"):
        cycle.pop(name, None)
    cycle["facts"].pop("consentimento_convite", None)
    cycle["facts"].pop("aceite_declarado", None)


def _qualification_phase(cycle):
    direct = cycle.get('form_entry_request') or {}
    if direct.get('reason') in {'existing_amplify', 'registration_access'}:
        return 'form' if _creator(cycle.get('facts', {}).get('tiktok_declarado')) else 'tiktok'
    if cycle["facts"].get("interesse_agenciamento") is not True:
        return "intro"
    # Shop status and agency linkage are checked by the real providers. A lead
    # does not have to know either answer before the read-only checks can run.
    if "tiktok_declarado" not in cycle["facts"]:
        return "tiktok"
    return "checking"


def _shop_unknown(text, *, contextual=False):
    if "?" in text or any(mark in text for mark in ('"', "“", "”", "'", "‘", "’")):
        return False
    normal = engine._normal(text)
    if contextual and normal in {"nao sei", "nao tenho certeza", "nao sei informar"}:
        return True
    subject = r"(?:(?:o |meu )?(?:tiktok shop(?: creator)?|shop)|(?:a |minha )?(?:conta|loja))"
    explicit = re.fullmatch(r"(?:eu )?nao (?:sei|sabia|tenho certeza) se " + subject + r" (?:esta|estava|ta) ativ[oa]", normal)
    contextual_answer = contextual and re.fullmatch(r"(?:eu )?nao (?:sei|sabia|tenho certeza) se (?:(?:ela|ele) )?(?:esta|estava|ta)(?: ativ[oa])?", normal)
    return bool(explicit or contextual_answer)


def _initial_checks(state, at):
    cycle = state["cycle"]
    if (cycle.get("phase") not in {"intro", "origin", "tiktok", "shop", "agency", "checking"}
            or _qualification_phase(cycle) != "checking"
            or not _creator(cycle["facts"].get("tiktok_declarado"))):
        return []
    cycle["phase"] = "checking"
    receipts = cycle.get("real_operations") or {}
    operations = ('lookup', 'precheck') if cycle.get('relationship_check_in_form') is True else ('lookup', 'precheck', 'relationship')
    return [job for operation in operations
            if operation not in receipts for job in [_effect(state, operation, at)] if job]


def form_entry_allowed(state, effect=None, *, now=None):
    """An invitation permits opening the form, never confirms its linkage."""
    cycle = state.get('cycle') or {}
    creator = _creator((cycle.get('facts') or {}).get('tiktok_declarado'))
    direct = cycle.get('form_entry_request') or {}
    if direct.get('reason') in {'existing_amplify', 'registration_access'}:
        event, proof = direct.get('event') or {}, state.get('contact_sync_proof') or {}
        source = direct.get('source_key')
        try:
            at = engine._clock(now)
            valid_time = at < engine._clock(cycle['expires_at'])
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
        valid = (cycle.get('mode') == 'real' and cycle.get('status') == 'open'
            and cycle.get('relationship_check_in_form') is True and creator and valid_time
            and direct.get('cycle_id') == cycle.get('id') and direct.get('creator') == creator
            and source == event.get('source_ref') == 'chatwoot:' + str(event.get('account_id')) + ':' + str(event.get('message_id'))
            and source in state.get('processed_inbound', [])
            and proof.get('creator_id') == state.get('creator_id') and proof.get('atendimento_id') == cycle.get('id')
            and proof.get('revision') == state.get('revision') and proof.get('event_id') in state.get('processed_inbound', []))
        if effect is not None:
            payload = effect.get('payload') or {}
            valid = (valid and effect.get('type') == 'generate_form_link' and effect.get('cycle_id') == cycle['id']
                and payload.get('relationship_check_in_form') is True and payload.get('verification_mode') == 'real'
                and payload.get('form_entry_reason') == direct['reason'] and payload.get('form_entry_source_key') == source
                and _creator((payload.get('facts') or {}).get('tiktok_declarado')) == creator)
        return bool(valid)
    record = (cycle.get('real_operations') or {}).get('invite') or {}
    invite = (state.get('effects') or {}).get(record.get('job_id')) or {}
    try:
        at = engine._clock(now)
        age = (at-engine._clock(record['observed_at'])).total_seconds()
        valid_time = isinstance(record['observed_at'], str) and 0 <= age <= 24*3600 and at < engine._clock(cycle['expires_at'])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if (cycle.get('mode') != 'real' or cycle.get('status') != 'open'
            or cycle.get('relationship_check_in_form') is not True or not creator or not valid_time
            or record.get('status') not in {'sent', 'pending', 'pending_verification', 'linked'}
            or record.get('cycle_id') != cycle.get('id') or record.get('creator') != creator
            or invite.get('type') != 'tiktok_operation' or invite.get('operation') != 'invite'
            or invite.get('cycle_id') != cycle['id'] or invite.get('creator') != creator
            or invite.get('status') != 'done'
            or invite.get('confirmed') is not True or not invite.get('consent')
            or invite.get('consent') != cycle.get('invite_consent')):
        return False
    if (record.get('confirmed') is not True
            and not (record.get('status') == 'pending_verification'
                     and (record.get('evidence') or {}).get('create_accepted') is True)):
        return False
    if effect is not None:
        payload = effect.get('payload') or {}
        return (effect.get('type') == 'generate_form_link' and effect.get('cycle_id') == cycle['id']
                and payload.get('verification_mode') == 'real'
                and payload.get('relationship_check_in_form') is True
                and payload.get('invite_job_id') == record['job_id']
                and _creator((payload.get('facts') or {}).get('tiktok_declarado')) == creator)
    return True


def _direct_form_reason(text):
    normal = engine._normal(text)
    if re.search(r'\b(?:nao sou|exemplo|supondo|se eu|meu amigo|minha amiga|ele e|ela e)\b', normal):
        return None
    if '?' not in text and re.search(r'\b(?:ja )?sou agenciad[oa] (?:pela|da|na) amplify\b', normal):
        return 'existing_amplify'
    if (normal in {'meu cadastro', 'meus acessos', 'quero meu cadastro', 'quero meus acessos', 'quero cadastro', 'quero acesso'}
            or re.search(r'\b(?:quero|preciso|gostaria de)\b.{0,35}\b(?:preencher|fazer|acessar|atualizar)\b.{0,20}\bcadastro\b', normal)
            or re.search(r'\b(?:quero|preciso)\b.{0,20}\b(?:meus|dos meus) acessos\b', normal)):
        return 'registration_access'
    return None


_NOT_INTERESTED = re.compile(
    r'(?:(?:oi|ola|bom dia|boa tarde|boa noite|obrigad[ao]|valeu|ah|entao) )*(?:eu )?'
    r'(?:nao tenho (?:mais )?interesse|nao tenho interesse (?:nao|nenhum)|sem interesse|nao me interessa(?: nao)?|'
    r'nao (?:estou|to|tou) interessad[ao]|nao quero(?: mais)?(?: participar| me agenciar| ser agenciad[ao]| nada| nao)?'

    r'|(?:pode |quero )?cancela(?:r)?(?: tudo)?|(?:pode )?pare|para de (?:me )?mandar(?: mensage(?:m|ns))?'
    r'|nao (?:me )?mand[ae] mais(?: mensage(?:m|ns))?|(?:quero )?sair|me tira (?:dai|daqui|dessa lista))'
    r'(?: (?:obrigad[ao]|valeu|nao|por enquanto|agora))*')


def not_interested(text):
    """Recusa explícita e curta ("Não tenho interesse"); pergunta ou frase longa segue a conversa."""
    if not isinstance(text, str) or '?' in text or len(text) > 80:
        return False
    return bool(_NOT_INTERESTED.fullmatch(engine._normal(text)))


def _pause_requested(text):
    """An explicit personal decision to defer is a pause, not another field."""
    import conversation
    normal = engine._normal(text)
    if '?' in text or any(mark in text for mark in ('"', "'", '“', '”')):
        return False
    if normal in conversation._PAUSE | {'encerrar agora'}:
        return True
    if not re.match(r'^(?:eu )?(?:prefiro|quero|preciso|vou) (?:pensar|refletir|avaliar|esperar)\b', normal):
        return False
    return bool(re.search(r'\b(?:depois|mais tarde|outro dia|outro momento|voltar|volto|retornar|retorno)\b', normal))


def _other_agency_declaration(text):
    """A personal declaration pauses sales; it never proves a provider link."""
    normal = engine._normal(text)
    if ('?' in text or any(mark in text for mark in ('"', "'", '“', '”'))
            or re.search(r'\b(?:nao|nunca|talvez|se|caso|exemplo|hipotese)\b', normal)
            or re.search(r'\b(?:quero|gostaria|pretendo|vou)\b.{0,45}\b(?:mudar|trocar|sair|amplify)\b', normal)):
        return False
    return bool(re.fullmatch(
        r'(?:eu )?(?:hoje |agora |ja )?(?:entrei (?:para|em)|estou (?:em|com)|tenho|'
        r'estou agenciad[oa] (?:com|por)) (?:uma |outra |a |a minha )?agencia(?: hoje| agora)?', normal))


def _declared_profile_change(text, cycle):
    """Read a correction before a blocked-state retry can reuse the old @."""
    current = _creator((cycle.get('facts') or {}).get('tiktok_declarado'))
    if not current or '?' in text:
        return None
    explicit = _extract_claims(text, 'tiktok', None).get('tiktok_declarado')
    linked = profile_link_handle(text)
    # Bare corrections need handle-shaped punctuation/digits; ordinary words
    # such as "pronto" remain requests about the current profile.
    bare = _bare_handle(text) if re.search(r'[._\d]', text) else None
    proposed = (linked or explicit) if '@' in text or linked else bare
    return proposed if proposed and proposed != current else None


def _refresh_direct_request(state, event, at, *, reason=None):
    from contracts import allow_inbound, inbound_key
    scope = pilot_scope.load_scope()
    if not pilot_scope.scope_ready(scope):
        return False
    gate = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3', 'phone': scope['phone']}
    if (not isinstance(event, dict) or not allow_inbound(gate, event)
            or str(event.get('conversation_id')) != scope['conversation_id'] or str(event.get('contact_id')) != scope['contact_id']
            or event.get('source_ref') != inbound_key(event) or not isinstance(event.get('created_at'), str)):
        return False
    try:
        if engine._clock(event['created_at']) > at:
            return False
    except (ValueError, TypeError, OverflowError):
        return False
    cycle = state['cycle']
    previous = cycle.get('form_entry_request') or {}
    selected = reason or previous.get('reason')
    if selected not in {'existing_amplify', 'registration_access'}:
        return False
    cycle['form_entry_request'] = {'reason': selected, 'cycle_id': cycle['id'],
        'creator': _creator(cycle.get('facts', {}).get('tiktok_declarado')),
        'source_key': inbound_key(event), 'event': deepcopy(event)}
    return True


def _direct_form(state, at):
    cycle = state['cycle']
    request = cycle.get('form_entry_request') or {}
    if not _creator(cycle.get('facts', {}).get('tiktok_declarado')):
        cycle['phase'] = 'tiktok'
        return _finish(state, at, reply='Qual é seu *@ do TikTok*? Vou usá-lo para abrir seu formulário.', buttons=[])
    cycle['phase'] = 'form'
    cycle['form_url'] = PUBLIC_FORM_URL
    reply = ('Faça seu cadastro por aqui: 😊\n' + PUBLIC_FORM_URL +
             '\n\nNo formulário, informe seu @ do TikTok. Ele confere seu agenciamento antes de liberar o cadastro.')
    return _finish(state, at, reply=reply, effects=[], buttons=[])


# One public form for everyone; it checks the agency link from the @ itself.
PUBLIC_FORM_URL = "https://amplify-cadastro.up.railway.app/cadastro"


def form_relationship_proven(state, *, now=None, maximum_age_seconds=24*3600):
    cycle = state.get('cycle') or {}
    record = (cycle.get('real_operations') or {}).get('relationship') or {}
    effect = (state.get('effects') or {}).get(record.get('job_id')) or {}
    return (cycle.get('relationship_check_in_form') is True
            and (effect.get('payload') or {}).get('source') == 'form'
            and relationship_proven(state, now=now, maximum_age_seconds=maximum_age_seconds))


def _form_after_invite(state, at):
    cycle = state['cycle']
    if not form_entry_allowed(state, now=at):
        return None
    cycle['phase'] = 'form'
    cycle['form_url'] = PUBLIC_FORM_URL
    status = cycle['real_operations']['invite']['status']
    notice = (conversao.INVITE_SENT if status == 'sent' else
              conversao.INVITE_ALREADY_THERE if status == 'pending' else
              'Recebemos seu pedido de convite. 😊' if status == 'pending_verification' else
              'Seu perfil já tem um registro com a Amplify. 😊')
    reply = (notice + '\n\nAceite o convite no app do TikTok e depois faça seu cadastro por aqui:\n' + PUBLIC_FORM_URL +
             '\n\nNo formulário, informe seu @. Ele confere o agenciamento antes de liberar o cadastro.')
    return _finish(state, at, reply=reply, effects=[], buttons=[])


# Conduta da release 39 (auditoria dos 10 atendimentos, 31/10/2026): o aceite
# declarado dispara a leitura do vínculo, o formulário sempre vem com o botão e
# o botão sai uma vez por etapa. Nenhum caminho aqui envia ou repete convite.
ACCEPTANCE_RECHECK_MINUTES = (5, 15, 60)
_LINK_POINTER = 'no botão *Fazer cadastro* que te mandei acima.'


def _invite_known(cycle):
    record = (cycle.get('real_operations') or {}).get('invite') or {}
    return (record.get('status') in {'sent', 'pending', 'pending_verification', 'linked'}
            and record.get('cycle_id') == cycle.get('id'))


def acceptance_declared(text, cycle):
    """"Aceitei" sempre; "feito"/"pronto" só depois de um convite."""
    if not isinstance(text, str) or '?' in text:
        return False
    normal = engine._normal(text)
    if not normal or re.search(r'\b(?:nao|nem)\b', normal):
        return False
    if normal in _ACCEPTANCE or re.fullmatch(
            r'(?:ok |sim |pronto |prontinho |oi )?(?:ja )?(?:aceitei|acabei de aceitar)(?: o convite)?'
            r'(?: (?:no|la no|do) tiktok| la| agora| sim| ja)?', normal):
        return True
    return normal in _ACCEPTANCE_CONTEXTUAL and (_invite_known(cycle) or cycle.get('phase') in {'await_acceptance', 'checking_acceptance'})


def form_link_requested(text):
    """Pergunta pelo formulário/link: a resposta sempre reenvia o botão."""
    if not isinstance(text, str):
        return False
    normal = engine._normal(text)
    return bool(re.search(r'\b(?:formulario|link|cadastro|botao)\b', normal) and re.search(
        r'\b(?:onde|cade|qual|manda|mande|envia|envie|reenvia|reenvie|passa|passe)\b|'
        r'\bnao (?:apareceu|aparece|chegou|veio|recebi|achei|encontrei|encontro|acho|abriu|abre)\b', normal))


def invite_missing(text):
    """"Não apareceu o convite", "onde fica o convite?", "não achei o convite"."""
    if not isinstance(text, str):
        return False
    normal = engine._normal(text)
    if normal in {'reenviar', 'reenvia', 'reenvie', 'pode reenviar', 'nao tem nada', 'ate agora nada'}:
        return True
    if re.search(r'\bnao (?:aparece|apareceu|tem|ha) nada\b.{0,30}\baceitar\b|\bnada (?:para|pra) (?:eu )?aceitar\b', normal):
        return True
    return bool(re.search(r'\bconvite\b', normal) and re.search(
        r'\b(?:onde|cade|como (?:acho|encontro|aceito))\b|'
        r'\bnao (?:apareceu|aparece|chegou|veio|recebi|achei|encontrei|encontro|acho)\b', normal))


def _form_stage(cycle):
    if _linked(cycle):
        return 'linked'
    if _invite_known(cycle):
        return 'invite'
    return 'direct' if cycle.get('phase') == 'form' else None


def _form_button_once(cycle, text, buttons, *, force=False):
    """Botão "Fazer cadastro" uma vez por etapa; pedido explícito sempre reenvia."""
    if cycle.get('relationship_check_in_form') is not True or not isinstance(text, str):
        return text, buttons
    stage = _form_stage(cycle)
    if PUBLIC_FORM_URL in text:
        if stage and cycle.get('form_button_stage') == stage and not force:
            text = re.sub(r'por aqui:?\s*(?:😊\s*)?\n?' + re.escape(PUBLIC_FORM_URL), _LINK_POINTER, text)
            return text.replace(PUBLIC_FORM_URL, _LINK_POINTER.rstrip('.')), buttons
        cycle['form_button_stage'] = stage or 'direct'
        return text, []
    if (stage and re.search(r'\bformul[aá]rio\b', text, re.I)
            and (cycle.get('form_button_stage') != stage or force)):
        cycle['form_button_stage'] = stage
        cycle['form_url'] = PUBLIC_FORM_URL
        return text + '\n\nFaça seu cadastro por aqui:\n' + PUBLIC_FORM_URL, []
    return text, buttons


def _acceptance_check(state, at, step, *, origin):
    """Uma leitura do vínculo pedida pelo aceite: imediata ou em 5/15/60 min."""
    job = _effect(state, 'relationship', at)
    if not job:
        return None
    payload = {'source': 'chat_acceptance', 'check': step}
    if step:
        due = engine._clock(origin) + timedelta(minutes=ACCEPTANCE_RECHECK_MINUTES[step - 1])
        payload['not_before'] = engine._stamp(max(due, at))
    state['effects'][job['id']]['payload'].update(payload)
    job['payload'].update(payload)
    state['cycle']['acceptance_check'] = {'at': origin, 'step': step, 'effect_id': job['id']}
    return job


def _linked_in_cycle(state, at):
    return (_operation_proven(state, 'relationship', 'linked', now=at, maximum_age_seconds=24 * 3600)
            or _operation_proven(state, 'invite', 'linked', now=at, maximum_age_seconds=24 * 3600))


def _linked_reply(state):
    cycle = state['cycle']
    cycle['phase'] = 'form'
    cycle['form_url'] = PUBLIC_FORM_URL
    _mark_linked_notice(cycle, engine._clock(None))
    if state.get('cadastro_situacao') == 'confirmado':
        return 'Confirmei no TikTok: seu vínculo com a Amplify está ativo! 🎉\n\nSeu cadastro já consta concluído, então não precisa preencher de novo.'
    name = _first_name(cycle)
    return ('Confirmei no TikTok: seu vínculo com a Amplify está ativo' + (', ' + name if name else '') + '! 🎉\n\n'
            'Agora é só fazer seu cadastro por aqui:\n' + PUBLIC_FORM_URL + '\n\n'
            'Leva poucos minutos e, no final, você já recebe seu acesso à comunidade.')


def _acceptance_turn(state, at):
    cycle = state['cycle']
    cycle['facts']['aceite_declarado'] = True
    if _linked_in_cycle(state, at):
        result = _finish(state, at, reply=_linked_reply(state), buttons=[])
        result['applied_claims'] = ['aceite_declarado']
        return result
    for effect in state['effects'].values():
        payload = effect.get('payload') or {}
        if (effect.get('cycle_id') == cycle['id'] and effect.get('operation') == 'relationship'
                and effect.get('status') == 'pending' and payload.get('source') == 'chat_acceptance'
                and payload.get('check')):
            # Um novo "aceitei" antecipa a reconferência agendada.
            effect['status'] = 'superseded'
    job = _acceptance_check(state, at, 0, origin=engine._stamp(at))
    cycle['phase'] = 'checking_acceptance'
    reply = 'Oba! Vou conferir agora no TikTok se o seu aceite já apareceu. 🔎' if job else PROMPTS['checking_acceptance']
    result = _finish(state, at, reply=reply, effects=[job] if job else [], buttons=[])
    result['applied_claims'] = ['aceite_declarado']
    return result


def _settle_acceptance_check(state, at, effect, status, policy=None):
    """Resultado da leitura pedida pelo aceite: avisa no vínculo, agenda a próxima."""
    cycle = state['cycle']
    effect['status'] = 'done'
    step = (effect.get('payload') or {}).get('check', 0)
    origin = (cycle.get('acceptance_check') or {}).get('at') or engine._stamp(at)
    missing = cycle.get('invite_missing') or {}
    if status == 'not_found' and _invite_unlanded(cycle):
        recovered = _recover_absent_invite(state, at, effect, policy)
        if recovered is not None:
            return recovered
        # An incomplete/too-early read cannot release the write fence or justify an acceptance claim.
        status = 'verification_pending'
    if missing.get('effect_id') == effect['id'] and status in {'pending', 'not_found'}:
        cycle.pop('acceptance_check', None)
        missing['effect_id'] = None
        if status == 'pending':
            # Release 42, item 3. Cancelar e reenviar (48 h sem aceite) não existe na ponte: repete o passo a passo.
            cycle['phase'] = 'await_acceptance'
            if not _tracking_since(state):
                _start_tracking(cycle, at)
            return _finish(state, at, reply=conversao.INVITE_IS_THERE, buttons=['Já aceitei'], exact=True)
        cycle['invite_list_proof'] = {'result': 'not_found', 'effect_id': effect['id'], 'source': 'invite_missing'}
        resent = _list_proof_resend(state, at, policy)
        if resent is not None:
            return resent
        cycle.pop('invite_list_proof', None)
    prior = cycle.get('prior_invite_check') or {}
    if prior.get('effect_id') == effect['id']:
        cycle.pop('prior_invite_check', None)
        if status == 'pending':
            cycle['phase'] = 'await_acceptance'
            return _finish(state, at, reply=conversao.INVITE_STEPS, buttons=['Já aceitei'])
        if status == 'not_found':
            cycle['prior_invite_cleared'] = {'creator': effect['creator'], 'effect_id': effect['id'], 'at': engine._stamp(at)}
            job = _effect(state, 'invite', at, policy=policy)
            if not job and not precheck_proven(state, now=at):
                check = _effect(state, 'precheck', at)
                if check:
                    cycle['consent_refresh'] = {'at': engine._stamp(at), 'precheck_effect_id': check['id']}
                    cycle['phase'] = 'checking'
                    return _finish(state, at, reply=conversao.PRIOR_INVITE_RESENT, effects=[check], buttons=[])
            if job:
                cycle['phase'] = 'inviting'
                return _finish(state, at, reply=conversao.PRIOR_INVITE_RESENT, effects=[job], buttons=[])
    if status == 'linked':
        cycle.pop('acceptance_check', None)
        return _finish(state, at, reply=_linked_reply(state), buttons=[])
    cycle['phase'] = 'await_acceptance'
    last = step >= len(ACCEPTANCE_RECHECK_MINUTES)
    following = None if last else _acceptance_check(state, at, step + 1, origin=origin)
    effects = [following] if following else []
    if last or not following:
        cycle.pop('acceptance_check', None)
        return _finish(state, at, buttons=['Já aceitei'], reply=(
            'Ainda não consegui ver o seu aceite no TikTok. 😕\n\n'
            'Confere se o convite da *Amplify* aparece em *Parcerias* ou *Notificações* do TikTok Shop Creator. '
            'Quando aceitar, me manda “aceitei” que eu confiro na hora.'))
    if step == 0:
        found = status in {'pending', 'not_found'}
        reply = (('Ainda não aparece o seu aceite no TikTok. Às vezes leva alguns minutos para atualizar.' if found else
                  conversao.RELATIONSHIP_RETRY)
                 + ' Vou conferir de novo sozinha daqui a 5, 15 e 60 minutos e te aviso aqui assim que confirmar. 😊'
                 + ('\n\nSe ainda não aceitou: abra o TikTok Shop Creator, em *Parcerias* ou *Notificações*, '
                    'e aceite o convite da *Amplify*.' if found else ''))
        return _finish(state, at, reply=reply, effects=effects, buttons=[])
    # Reconferências intermediárias sem novidade não geram mensagem.
    state['revision'] += 1
    return engine._result(state, effects=effects, operation_settled=True)


def _origin_declaration(text, *, contextual=False, proposed=None):
    """Classify an actual source declaration, never an arbitrary phrase list.

    A channel is not proof of paid advertising. Ads/referrals need their own
    explicit evidence; an organic source is recorded as other plus its channel.
    """
    if "?" in text or any(mark in text for mark in ('"', "“", "”", "'", "‘", "’")):
        return None
    normalized = engine._normal(text)
    buttons = {'anuncio':'anuncio','indicacao':'indicacao','outra origem':'outro','outro':'outro'}
    if normalized in buttons and (contextual or proposed):
        return {'origem_declarada':buttons[normalized]}
    if normalized in {'prefiro nao informar','nao quero informar','nao informar','pular','nao sei'} and (contextual or proposed):
        return {'origem_declarada':None}
    # Preserve a usable organic source when only its paid/organic nature is
    # uncertain. Never let the word anuncio inside that uncertainty imply ads.
    ads = r'(?:anuncio|ads|publicidade|patrocinad[oa])'
    clean = re.sub(r'\b(?:nao sei|nao lembro|nao tenho certeza|talvez)\b[^,;.!?]{0,55}\b'+ads+r'\b', '', normalized)
    clean = re.sub(r'\bnao (?:foi|era|e) (?:um |uma )?'+ads+r'\b','',clean)
    if (re.search(r'\b(?:nao|nunca|nem|ninguem|nenhum|nenhuma|sem|exemplo|hipotese|hipotetico|hipoteticamente|suponha|supondo|suponhamos|imagine|imaginando|digamos|perguntou|perguntaram)\b', clean)
            or re.search(r'^(?:se|caso)\b|\b(?:se|caso) (?:eu|ele|ela|voce|a pessoa|alguem)\b',clean)):
        return None
    third_person = re.search(r'\b(?:ele|ela|eles|elas|meu amigo|minha amiga|um amigo|uma amiga|meu colega|minha colega)\b',clean)
    # Hearing somebody report their discovery is not the lead's discovery.
    # Direct referral ("um amigo me indicou") remains an actual personal source.
    if third_person and re.search(r'\b(?:falou|disse|contou|comentou|relatou|afirmou)\b.{0,35}\bque\b',clean):
        return None
    personal = bool(re.search(r'\b(?:vi|vim|conheci|descobri|encontrei|achei|assisti|cheguei|recebi|soube|acompanho)\b',clean)
                    or re.search(r'\bme (?:indicou|indicaram|mostrou|mandou|enviou|falaram|falou|apareceu)\b',clean)
                    or re.search(r'\b(?:para mim|no meu|na minha)\b',clean))
    if clean!=normalized and not personal:
        return None
    if third_person and not personal:
        return None
    if not personal and not contextual:
        return None
    channel_match = re.search(r'\b(instagram|tiktok|facebook|youtube|google|whatsapp|podcast)\b',clean)
    channel = channel_match[1] if channel_match else None
    explicit_ad = bool(re.search(r'\b'+ads+r'\b',clean))
    referral = bool(re.search(r'\b(?:indicacao|indicou|indicaram)\b',clean))
    if proposed:
        value,quote=proposed
        if not quote or quote not in text or value not in {'anuncio','indicacao','outro','nao_informado'}:
            return None
        if value=='anuncio' and not explicit_ad or value=='indicacao' and not referral:
            return None
    if explicit_ad:
        value='anuncio'
    elif referral:
        value='indicacao'
    elif channel:
        value='outro'
    elif proposed and personal and proposed[0]=='outro':
        value='outro'
    else:
        return None
    result={'origem_declarada':value}
    if channel:
        result['origem_canal_declarado']=channel
    return result


def _origin_source(record):
    """Keep the original quote/time; never relabel a later 'já falei' as source."""
    return {'quote':record['text'], 'at':record.get('source_created_at') or record['at'],
            'reference':record.get('source_ref'),
            'source':'chatwoot_webhook' if record.get('source_created_at') and record.get('source_ref') else 'stored_cycle_history'}


def _recover_origin(state):
    cycle=state['cycle']
    records=[record for record in state['history'][:-1] if isinstance(record,dict)
             and record.get('direction')=='inbound' and record.get('cycle_id')==cycle['id']]
    for record in reversed(records[-4:]):
        declaration=_origin_declaration(record.get('text',''),contextual=True)
        if declaration:
            return declaration,_origin_source(record)
    return None,None


# Words a lead may answer at the @ question that are never a TikTok handle.
_NOT_HANDLE = {"oi", "ola", "ok", "okay", "sim", "nao", "talvez", "menu", "duvida", "ajuda", "pular", "voltar",
               "encerrar", "resetar", "reset", "anuncio", "indicacao", "outro", "obrigado", "obrigada", "bom", "boa",
               "tiktok", "instagram", "perfil", "arroba", "usuario", "nenhum", "nenhuma", "naotenho", "seguir"}
_HANDLE_UNKNOWN = ("Não consegui identificar o seu @ do TikTok. 🙂\n\n"
                   "No TikTok, abra seu perfil: o @ é o nome que aparece logo abaixo da foto e começa com @. "
                   "Me envie exatamente como aparece lá, por exemplo: @<perfil>")


def profile_link_handle(text):
    """O @ de um link de perfil do TikTok (tiktok.com/@<perfil>, com ou sem www/m e parâmetros)."""
    if not isinstance(text, str):
        return None
    match = re.search(r'(?:https?://)?(?:www\.|m\.)?tiktok\.com/@([A-Za-z0-9_][A-Za-z0-9_.]{1,23})', text)
    if not match:
        return None
    handle = match.group(1).rstrip('.').lower()
    return '@' + handle if len(handle) >= 2 and re.search(r'[a-z]', handle) else None


def _bare_handle(text):
    """At the pending @ question, accept one handle typed with or without "@".

    Underscores and periods are part of TikTok handles and are kept. A sentence,
    two words, a question or a known answer word is never taken as a profile.
    """
    if not isinstance(text, str) or "?" in text:
        return None
    match = re.fullmatch(r"@?([A-Za-z0-9_][A-Za-z0-9_.]{1,23})", text.strip())
    if not match or match.group(1).endswith("."):
        return None
    handle = match.group(1).lower()
    if engine._normal(handle) in _NOT_HANDLE or not re.search(r"[a-z]", handle):
        return None
    return "@" + handle


def _extract_claims(text, phase, plan, *, requested_name=False):
    """AI quotes are validated against this inbound; deterministic fallback too."""
    import conversation
    from nome_contextual import extract_name
    proposed = plan.get("claims", []) if isinstance(plan, dict) else []
    if not isinstance(proposed, list):
        proposed = []
    fallback = []
    normal = engine._normal(text)
    if conversation._explicit_start(text, text):
        fallback.append({"field": "interesse_agenciamento", "value": "true", "quote": text})
    if "?" not in text:
        if _shop_unknown(text, contextual=phase == "shop"):
            fallback.append({"field": "shop_ativo_declarado", "value": "unknown", "quote": text})
        name = extract_name(text,requested=requested_name)
        if name:
            fallback.append({"field": "nome_declarado", "value": name, "quote": text})
        for match in re.finditer(r"(?<![\w@])@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}(?![\w.])", text):
            fallback.append({"field": "tiktok_declarado", "value": match.group().lower(), "quote": text})
        origins = {"anuncio": "anuncio", "indicacao": "indicacao", "outro": "outro",
                   "prefiro nao informar": "nao_informado", "pular": "nao_informado"}
        if phase == "origin" and normal in origins:
            fallback.append({"field": "origem_declarada", "value": origins[normal], "quote": text})
        if phase in {"shop", "agency"}:
            value = "true" if normal in conversation._TRUE else "false" if normal in conversation._FALSE else "unknown" if normal in conversation._UNKNOWN else None
            if value:
                fallback.append({"field": conversation.FIELDS[phase], "value": value, "quote": text})
    result = {}
    for claim in [*proposed, *fallback]:
        if (not isinstance(claim, dict) or set(claim) != {"field", "value", "quote"}
                or claim.get("field") not in FIELDS or not isinstance(claim.get("quote"), str)
                or not isinstance(claim.get("value"), str) or not claim["quote"] or claim["quote"] not in text):
            continue
        if claim["field"] == "nome_declarado":
            name=extract_name(text,requested=requested_name)
            if name and name==claim['value']:
                result[claim["field"]] = name
            continue
        if claim["field"] == "origem_declarada":
            origin=_origin_declaration(text,contextual=phase=='origin',proposed=(claim['value'],claim['quote']))
            expected=None if claim['value']=='nao_informado' else claim['value']
            if origin and origin.get('origem_declarada')==expected:
                result.update(origin)
            continue
        if (claim["field"] == "shop_ativo_declarado" and claim["value"] == "unknown"
                and _shop_unknown(text, contextual=phase == "shop")):
            result[claim["field"]] = None
            continue
        valid, value = conversation._claim_value(claim, text, phase, False, False, True)
        if valid:
            result[claim["field"]] = value
    origin = _origin_declaration(text,contextual=phase=='origin') if phase != "form" else None
    if origin:
        result.update(origin)
    if phase == "tiktok" and "tiktok_declarado" not in result:
        handle = _bare_handle(text)
        if handle:
            result["tiktok_declarado"] = handle
    return result


def _approved_topic_answer(plan):
    """Read a server-owned answer from this turn's approved context snapshot."""
    if not isinstance(plan, dict):
        return None
    answer = plan.get('approved_topic_answer')
    if (not isinstance(answer, dict) or answer.get('source') != 'approved_context'
            or answer.get('knowledge_version') != plan.get('knowledge_version')
            or not isinstance(answer.get('knowledge_version'), str)
            or not isinstance(answer.get('id'), str)
            or not isinstance(answer.get('text'), str)):
        return None
    return answer['text'].strip()


def _known_faq_unavailable(text):
    normal = engine._normal(text)
    if normal in {'como funciona', 'como funciona a parceria', 'como funciona o agenciamento'}:
        return 'Não consegui consultar os detalhes aprovados da parceria agora. Prefiro confirmar essa informação para te orientar com precisão.'
    if normal in {'beneficios', 'quais os beneficios', 'quais sao os beneficios', 'quais as vantagens'}:
        return 'Não consegui confirmar os benefícios disponíveis agora. Eles dependem da categoria e das condições da parceria.'
    return None


def _step_reply(answer, prompt):
    """Keep the answer, then state the current question/explanation once."""
    for sentence in re.split(r'(?<=[.!?])\s+', prompt):
        if sentence and not sentence.endswith('?'):
            # Exact canonical sentences only. Conditions, links, names and
            # paraphrases are not shortened or inferred by this formatter.
            answer = answer.replace(sentence, '').strip()
    return (answer + '\n\n' if answer else '') + prompt


def _question_reply(text, plan, cycle, policy=None, *, state=None, now=None, allow_local=True):
    import conversation
    from receipt_grounding import approved_cost_reply, approved_educational_reply, ground_reply
    proposal = plan if isinstance(plan, dict) else {}
    cost_reply = approved_cost_reply(text, proposal, policy)
    educational_reply = approved_educational_reply(text, proposal)
    candidates = []
    if re.search(r'\bamostra', engine._normal(text)):

        candidates.append((conversao.SAMPLES, True, True))
    if cost_reply is not None:
        # Financial facts are rendered from the approved policy, not from an
        # inferred positive/negative mention of GMV in free model language.
        candidates.append((cost_reply, True, True))
    elif educational_reply is not None:
        # A generic explanation is not the status of this person's invitation.
        # Only the approved current FAQ can bypass operational paraphrasing.
        candidates.append((educational_reply, True, True))
    elif (proposal.get('provider_status') == 'completed'
            and proposal.get('intent') in {'question', 'converse', 'clarify', 'start', 'continue'}):
        candidates.append((proposal.get('reply'), False, False))
    fallback = _approved_topic_answer(proposal)
    if fallback:
        candidates.append((fallback, False, True))
    unavailable = _known_faq_unavailable(text)
    asked = engine._normal(text)
    if re.search(r'\bcampanhas?\b', asked) and not re.search(r'\bamostra', asked):

        text, asked = 'Benefícios', 'beneficios'
    local = (_local_topic_answer(text) if allow_local and (unavailable or asked in conversation._TOPIC_TEXT or '?' in text
             or re.search(r'\b(?:beneficio|beneficios|comissao|como funciona|lives?|custa|taxa)\b', asked)) else None)
    if local:
        # Release 41: o botão "Como funciona?" da primeira resposta nunca volta como "não consegui consultar".
        candidates.append((local, True, True))
    if unavailable:
        candidates.append((unavailable, True, True))
    reply, backend_answer, faq_action = '', False, False
    for candidate, canonical, from_context in candidates:
        if not isinstance(candidate, str) or not 0 < len(candidate.strip()) <= 1800:
            continue
        candidate = candidate.strip()
        proposed_rates = re.findall(r'(\d+(?:[.,]\d+)?)\s*%', candidate)
        if not canonical and proposed_rates and (not policy_valid(policy)
                or any(float(rate.replace(',', '.')) != policy['commission'] for rate in proposed_rates)
                or re.search(r'\bgmv\b|faturamento|vendas totais', candidate, re.I)):
            # A status paraphrase must not hide an invented financial value
            # before we try the answer from the approved context snapshot.
            continue
        grounded = canonical
        if state is not None and not canonical:
            safe = ground_reply(text, candidate, proposal, state, policy=policy, now=now)
            grounded = safe != candidate
            candidate = safe
        if (not isinstance(candidate, str) or not 0 < len(candidate.strip()) <= 1800
                or candidate.count('?') > 1
                or not grounded and not conversation._reply_text(candidate, allow_multiple_questions=False)
                or re.search(r'simulad|ensaio|\d+\s*dias', candidate, re.I)):
            continue
        rates = re.findall(r'(\d+(?:[.,]\d+)?)\s*%', candidate)
        if not canonical and rates and (not policy_valid(policy)
                or any(float(rate.replace(',', '.')) != policy['commission'] for rate in rates)
                or re.search(r'\bgmv\b|faturamento|vendas totais', candidate, re.I)):
            continue
        normalized = engine._normal(candidate)
        if not grounded and (re.search(r'\b(?:convite|vinculo|cadastro|acesso)\b.{0,35}\b(?:confirmad|concluid|enviad|liberad|aprovad)', normalized)
                or re.search(r'\bvoce\b.{0,20}\b(?:esta|foi)\b.{0,15}\bagenciad', normalized)):
            continue
        reply, backend_answer = candidate, from_context
        faq_action = (from_context and (not canonical or candidate == educational_reply)
                      and (proposal.get('approved_topic_answer') or {}).get('id') in {'funcionamento', 'beneficios'})
        break
    if not reply:
        return ''
    clarification = (proposal.get('intent') == 'clarify' and reply.count('?') == 1
                     and conversation._before_interest_reply(reply) == reply
                     and re.search(r'\bou\b', engine._normal(reply))
                     and re.search(r'\b(?:comissao|produto|comunidade|campanhas?|beneficios?|parceria|prazo|condicoes)\b',
                                   engine._normal(reply)))
    if clarification:
        # A bounded FAQ disambiguation is a question about the answer, not a
        # substitute onboarding step. It changes neither facts nor providers.
        return reply
    if cycle["phase"] == "intro":
        if faq_action or (backend_answer and local) or cost_reply is not None and policy_valid(policy):
            return reply + '\n\n' + _INTRO_ACTION
        return conversation._before_interest_reply(reply)
    if cycle["phase"] in {"origin", "tiktok", "shop", "agency"}:
        # The backend owns ONE information request, including imperative asks
        # with no question mark. Keep the answer, replace proposed collection
        # with the single current field (also for a clarification proposal).
        phase = _qualification_phase(cycle)
        reply = conversation._answer_without_requests(reply)
        return _step_reply(reply, _phase_prompt(cycle, phase))
    if cycle["phase"] in {"checking", "inviting", "checking_acceptance", "blocked"}:
        # While a provider owns the next step, do not restart qualification or
        # ask the lead to repeat an answer already waiting on that provider.
        reply = conversation._answer_without_requests(reply)
        if bridge_waiting(cycle) and re.search(r'\b(time|equipe|pessoal)\b', reply, re.I):
            # Ninguém confere à mão: quem destrava é a volta da consulta.
            return _BRIDGE_STILL
        if invite_waiting(cycle) and 'anotada' not in reply:
            return reply + '\n\n' + conversao.INVITE_STILL
        if bridge_waiting(cycle) and 'anotado' not in reply:
            # Release 41: a dúvida é respondida e o lead sabe que a conferência segue sozinha (priscila, 30/10).
            return reply + '\n\n' + conversao.BRIDGE_NOTE
        return reply
    if (backend_answer and cycle['phase'] == 'consent_real' and policy_valid(policy)
            and (cycle.get('invite_offer') or {}).get('policy_hash') == _policy_fingerprint(policy)):
        return reply + '\n\n' + conversao.CONSENT_QUESTION
    if backend_answer and cycle['phase'] == 'form' and cycle.get('form_url') and not _form_link_recent(state, cycle['form_url']):
        return reply + '\n\nFaça seu cadastro por aqui:\n' + cycle['form_url']
    if proposal.get("intent") == "clarify":
        # Non-collection clarification must retain its meaning.
        return reply
    return reply if backend_answer or proposal.get("intent") == "question" else ""


def _turn_guidance(state, at):
    """Bounded context from this cycle/profile; no raw provider/form payloads."""
    cycle, facts = state["cycle"], state["cycle"]["facts"]
    phase = cycle["phase"]
    field = {"origin": "origem_declarada", "tiktok": "tiktok_declarado"}.get(phase)
    kind = ("ask_field" if field else "understand_interest" if phase == "intro" else
            "request_real_consent" if phase == "consent_real" else
            "complete_form" if phase == "form" else
            "accept_invite" if phase == "await_acceptance" and not facts.get("aceite_declarado") else
            "wait_for_provider")
    changes = cycle.get("pending_profile_changes") or {}
    if changes:
        kind = "confirm_profile_change"
        field = None
    elif cycle.get('name_question_pending') is True and not facts.get('nome_declarado'):
        kind,field='ask_field','nome_declarado'
    operations, pending = [], []
    creator = _creator(facts.get("tiktok_declarado"))
    for operation, record in (cycle.get("real_operations") or {}).items():
        if (operation not in _OPERATIONS or not isinstance(record, dict)
                or record.get("cycle_id") != cycle["id"] or record.get("creator") != creator
                or record.get("status") not in _STATUS[operation]):
            continue
        operations.append({"operation": operation, "status": record["status"],
                           "proven": _operation_proven(state, operation, record["status"], now=at),
                           "source": "provider_result"})
    for effect in state["effects"].values():
        if (effect.get("type") == "tiktok_operation" and effect.get("cycle_id") == cycle["id"]
                and effect.get("creator") == creator and effect.get("operation") in _OPERATIONS
                and effect.get("status") in {"pending", "running", "outcome_unknown"}):
            pending.append({"operation": effect["operation"], "status": effect["status"]})
    question="Confirma atualizar esses dados?" if changes else "Como posso te chamar?" if field=='nome_declarado' else _phase_prompt(cycle, phase) if field else ""
    return {"next_action": {"kind": kind, "field": field,"question":question},
            "current_question":question or _phase_prompt(cycle, phase),
            "known_fields": sorted(facts), "operations": operations, "pending_operations": pending,
            "pending_profile_changes": {key: value for key, value in changes.items() if key in PROFILE},
            "consent_pending": phase == "consent_real" and bool(cycle.get("invite_offer")),
            "has_form_link": bool(cycle.get("form_url"))}


def close_inactive_cycle(session, *, expected_cycle_id, source_key, warning_key, closure_key,
                         warning_accepted_at, now=None):
    """Close only the unchanged real cycle after its accepted warning window.

    The caller owns the accepted outbox receipts and source/recipient checks.
    This local transition creates no provider work, permission or inbound turn.
    """
    state, at = engine._state(session), engine._clock(now)
    cycle = state.get('cycle') or {}
    try:
        if not isinstance(warning_accepted_at, str):
            raise ValueError('missing_warning_time')
        accepted = engine._clock(warning_accepted_at)
        last_inbound = engine._clock(cycle['last_inbound_at'])
        expires = engine._clock(cycle['expires_at'])
    except (ValueError, TypeError, KeyError, OverflowError):
        return engine._result(state, ignored=True, reason='inactivity_time_invalid')
    if (cycle.get('id') != expected_cycle_id or cycle.get('mode') != 'real'
            or cycle.get('status') != 'open' or at < accepted + timedelta(seconds=300)
            or cycle.get('phase') not in {'intro', 'origin', 'tiktok', 'shop', 'agency',
                                         'consent_real', 'await_acceptance', 'form'}
            or last_inbound >= accepted or at >= expires
            or not source_key or not warning_key or not closure_key
            or state.get('human_control') or cycle.get('qualification_paused')
            or cycle.get('pending_profile_changes') or cycle.get('opt_out') or state.get('opt_out')
            or state.get('cadastro_situacao') == 'confirmado'
            or any(effect.get('cycle_id') == expected_cycle_id
                   and effect.get('status') in {'pending', 'running', 'outcome_unknown'}
                   for effect in state['effects'].values() if isinstance(effect, dict))):
        return engine._result(state, ignored=True, reason='inactivity_state_changed')
    cycle.update(status='closed', reason='inactivity_timeout', closed_at=engine._stamp(at),
                 inactivity_closed_at=engine._stamp(at),
                 inactivity_closure={'source_key': source_key, 'warning_key': warning_key,
                                     'closure_key': closure_key,
                                     'warning_accepted_at': engine._stamp(accepted)})
    state['revision'] += 1
    return engine._result(state, inactivity_closed=True)


_RESUME_OPENING = 'Oi! Eu sou a Bia, agente de IA da Amplify. 👋'
_RESUME_SORRY = 'Desculpa a demora para te responder! 🙏'
_RESUME_SPECIFIC = re.compile(r'\b(?:como funciona|beneficio\w*|vantage\w*|comiss\w*|taxa|quanto|recebe|ganh\w*|'
                              r'lives?|cadastro|formulario|convite|aceitei|duvida\w*)\b')


_AD_MESSAGE = re.compile(r'\bquero saber mais sobre (?:o )?agenciamento\b')
_INTRO_ENDINGS = (PROMPTS['intro'], 'O que você busca desenvolver hoje como creator?', 'O que você quer saber primeiro?',
                  _INTRO_ACTION)
_INTRO_BUTTONS = ([], ['Conhecer a Amplify', 'Quero me agenciar'], ['Quero me agenciar'])


def _carried_handle(state):
    """@ de um atendimento que venceu esperando a conferência do perfil (sem resultado), há até 7 dias."""
    closed = state.get('closed_cycles') or []
    previous = closed[-1] if closed and isinstance(closed[-1], dict) else {}
    record = (previous.get('real_operations') or {}).get('precheck') or {}
    handle = _creator((previous.get('facts') or {}).get('tiktok_declarado'))
    try:
        recent = engine._clock(previous.get('closed_at')) >= engine._clock(state['cycle']['opened_at']) - timedelta(days=7)
    except (TypeError, ValueError, AttributeError, OverflowError, KeyError):
        recent = False
    if (previous.get('mode') == 'real' and previous.get('status') == 'expired' and previous.get('phase') == 'blocked'
            and handle and recent and record.get('creator') == handle
            and record.get('status') in {'verification_pending', 'failed', 'outcome_unknown'}
            and not (previous.get('real_operations') or {}).get('invite')):
        return handle
    return None


def _local_topic_answer(text):
    """Resposta do tema aprovado (cartões de contexto) quando o modelo não respondeu."""
    from answers import _matched_topic, _menu_topic, load_knowledge
    try:
        topics = load_knowledge().get('topics') or []
        topic = _menu_topic(text, topics) or _matched_topic(text, topics)
    except Exception:
        return None
    answer = (topic or {}).get('answer')
    if not isinstance(answer, str):
        return None
    return lead_safe(answer.strip()) or None


def _after_access_reply(text, normal):
    """Depois do acesso liberado: responde a dúvida e lembra onde entrar, sem convite, @ ou formulário."""
    if re.search(r'\bamostra', normal):
        return conversao.SAMPLES + '\n\n' + conversao.ACCESS_HINT
    if re.search(r'\b(?:missao|missoes|campanha|campanhas|oportunidade|oportunidades|marca|marcas)\b', normal):
        return conversao.MISSIONS
    asked = '?' in text or normal in conversation_topics()
    answer = _local_topic_answer(text) if asked else None
    if answer and not re.search(r'\b(?:convite|cadastro|formulario|aceit)', normal):
        return answer + '\n\n' + conversao.ACCESS_HINT
    return conversao.ACCESS_DONE


def conversation_topics():
    import conversation
    return conversation._TOPIC_TEXT | conversation._TOPIC_ENTRY


# Frases dos cartões de contexto que orientam a Bia e nunca vão para o lead
# (ma.ribeiroh, 30/10: "não devem ser prometidos às categorias inferiores").
_INTERNAL_SENTENCE = re.compile(r'por si só|não devem? ser prometid|de Diamond em diante|nesta referência'
                                r'|não estão informad'
                                # Release 51: o atendimento é todo automático; nada de equipe ou atendimento humano.
                                r'|\bequipe\b|\bo time\b|\bnosso time\b|atendente|atendimento humano|\bhumanos?\b', re.I)
_ONLY_INTERNAL = 'Sigo com você por aqui 😊'


def lead_safe(text):
    """Tira de uma resposta ao lead as frases de controle interno, mantendo o resto do texto."""
    if not isinstance(text, str) or not _INTERNAL_SENTENCE.search(text):
        return text
    paragraphs = []
    for paragraph in text.split('\n\n'):
        kept = [part for part in re.split(r'(?<=[.!?])\s+', paragraph) if not _INTERNAL_SENTENCE.search(part)]
        if kept:
            paragraphs.append(' '.join(kept))
    return '\n\n'.join(paragraphs) or _ONLY_INTERNAL


# Quem tenta mandar o @ com espaço ou manda o nome completo (priscila, 30/10).
_NAME_LIKE = re.compile(r'@\S+(?:\s+\S+){1,3}|[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][a-zà-ÿ]+){1,3}')
_NOT_NAME_WORDS = re.compile(r'\b(?:quero|como|sim|nao|oi|ola|bom|boa|obrigad\w*|beneficios?|comissao|funciona|amplify'
                             r'|agenciamento|agencia|duvida|entrar|mandar|conhecer|tiktok|shop|live|lives|cadastro)\b')


def _name_instead_of_handle(text, normal):
    return bool(_NAME_LIKE.fullmatch(text.strip()) and not _NOT_NAME_WORDS.search(normal))



_NAME_ASK = re.compile(r'\s*(?:[^.!?\n]*?\b(?:e\s+)?)?(?:como (?:você )?prefere ser chamad[ao]s?|como (?:posso|podemos) '
                       r'(?:te chamar|chamar você)|qual (?:é )?(?:o )?seu nome|por qual nome)[^?]*\?', re.I)


def _sell_intro(result, policy):
    """2. Antes do @, toda resposta vende e termina com o próximo passo (o @)."""
    state, reply = result['state'], result.get('reply') or ''
    cycle = state.get('cycle') or {}
    fixed = result.pop('fixed_greeting', False)
    if (cycle.get('status') != 'open' or cycle.get('phase') != 'intro' or not reply or fixed
            or cycle.get('qualification_paused') or cycle.get('experience_version') == 'bia-approved-v1'
            or (cycle.get('facts') or {}).get('interesse_agenciamento') is not True
            or _creator((cycle.get('facts') or {}).get('tiktok_declarado'))):
        # O "resetar" de teste e a volta de um atendimento encerrado mantêm a saudação fixa.
        return
    reply = _NAME_ASK.sub('', reply).strip()
    opened = reply.startswith(_RESUME_OPENING)
    body = reply[len(_RESUME_OPENING):].strip() if opened else reply.strip()
    if opened and body in {PROMPTS['intro'], _INTRO_ACTION, ''}:
        reply = conversao.first_reply(policy, policy_valid(policy))
    else:
        for ending in _INTRO_ENDINGS:
            if body.endswith(ending):
                body = body[:-len(ending)].rstrip()
        # The script owns the request. A model question must not replace the
        # @ request and leave the next literal handle without its input marker.
        import conversation
        body = conversation._answer_without_requests(body)
        if conversao.CTA not in body and '@ do TikTok' not in body:
            body = (body + '\n\n' if body else '') + conversao.CTA
        reply = (conversao.OPENING + ' ' + body) if opened else body
    cycle['arroba_pedido'] = True
    if result.get('buttons') in _INTRO_BUTTONS:
        result['buttons'] = list(conversao.FIRST_BUTTONS)
    for item in reversed(state.get('history') or []):
        if item.get('direction') == 'outbound':
            item['text'] = reply
            break
    result['reply'] = reply


def handle_real(session, text, assistant_callback=None, *, resumed=None, **options):
    """One lead turn. ``resumed`` marks messages left unanswered by a pause:
    the reply apologizes and picks up what the lead asked, never a bare greeting."""
    result = _handle_real_turn(session, text, assistant_callback, **options)
    _sell_intro(result, options.get('operation_policy'))
    safe = lead_safe(result.get('reply'))
    if safe != result.get('reply'):
        # Release 41: frase de controle interno nunca chega ao lead, venha do modelo ou do cartão.
        for item in reversed(result['state'].get('history') or []):
            if item.get('direction') == 'outbound':
                item['text'] = safe
                break
        result['reply'] = safe
    if not isinstance(resumed, dict) or not result.get('reply'):
        return result
    state, reply = result['state'], result['reply']
    for opening in (conversao.OPENING, _RESUME_OPENING):
        if reply.startswith(opening):
            reply = opening + ' ' + _RESUME_SORRY + reply[len(opening):]
            break
    else:
        reply = _RESUME_SORRY + '\n\n' + reply
    for item in reversed(state.get('history') or []):
        if item.get('direction') == 'outbound':
            item['text'] = reply
            break
    result['reply'] = reply
    result['resumed'] = True
    return result


def _handle_real_turn(session, text, assistant_callback=None, *, now=None, operation_policy=None, source_event=None,
                      inactivity_notice=None, relationship_check_in_form=False, qualification_enabled=False, qualification_new_cycles_only=False, approved_experience_enabled=False):
    import conversation
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 4000:
        raise ValueError("text must contain between 1 and 4000 characters")
    state, at = engine._state(session), engine._clock(now)
    engine._expire(state, at)
    cycle = state.get("cycle")
    inactivity_return = bool(cycle and cycle.get('status') == 'closed'
                             and cycle.get('reason') in {'inactivity_timeout', 'inactivity_user_close'})
    # O "resetar" do número de teste e o atendimento aberto por ele seguem o funil mesmo com a ficha cadastrada.
    registered = (state.get('cadastro_situacao') == 'confirmado'
                  and not conversation._chat_reset_requested(text, real_mode=True)
                  and not (cycle or {}).get('funnel_after_reset'))
    if registered and cycle and cycle.get('status') == 'open' and not cycle.get('acesso_liberado'):
        # Release 41: o formulário encerra no banco o atendimento aberto ("cadastro_confirmado"). Seguir nele faz o

        cycle.update(status='closed', reason='cadastro_confirmado', closed_at=engine._stamp(at))
        for effect in state['effects'].values():
            if effect.get('cycle_id') == cycle['id'] and effect.get('status') == 'pending':
                effect['status'] = 'cancelled'
    fresh = not cycle or cycle["status"] != "open"
    # A legacy cycle is closed before real operation. Simulated consent or a
    # legacy form can never silently become real permission or a relationship.
    if cycle and cycle.get("mode") != "real" and cycle["status"] == "open":
        cycle.update(status="closed", reason="real_mode_started", closed_at=engine._stamp(at))
        for effect in state["effects"].values():
            if effect.get("cycle_id") == cycle["id"] and effect.get("status") == "pending":
                effect["status"] = "cancelled"
        fresh = True
    if fresh:
        cycle = engine._open(state, at)
        cycle.update(mode="real", phase="intro", qualification_rollout=(qualification_enabled or approved_experience_enabled) is True)
        if approved_experience_enabled is True:
            cycle['experience_version'] = 'bia-approved-v1'
    if cycle.get('experience_version') == 'bia-approved-v1':
        qualification_enabled = True
    state["real_mode"] = True
    if relationship_check_in_form is True:
        cycle['relationship_check_in_form'] = True
    last_inbound_before_turn = cycle.get('last_inbound_at')
    cycle["last_inbound_at"], cycle["expires_at"] = engine._stamp(at), engine._stamp(at + timedelta(hours=24))
    engine._history(state, "inbound", text.strip(), at)
    if (isinstance(source_event,dict) and source_event.get('text')==text
            and source_event.get('provider')=='chatwoot' and source_event.get('source_ref')
            and isinstance(source_event.get('created_at'),str)):
        try:
            if engine._clock(source_event['created_at'])<=at:
                state['history'][-1].update(source_ref=source_event['source_ref'],source_created_at=source_event['created_at'])
        except (ValueError,TypeError,OverflowError):
            pass
    normal = engine._normal(text)
    if registered and (fresh or cycle.get('acesso_liberado')):
        # Com o acesso liberado, a Bia segue respondendo: Club, missões e onde entrar. Nunca volta ao funil.
        cycle.update(acesso_liberado=True, phase='acesso')
        return {**_finish(state, at, reply=_after_access_reply(text, normal), buttons=[]), 'fixed_greeting': True}
    if fresh and _AD_MESSAGE.search(normal) and 'origem_declarada' not in cycle['facts']:
        cycle['facts']['origem_declarada'] = 'anuncio'
        cycle.setdefault('claim_provenance', []).append({'field': 'origem_declarada', 'at': engine._stamp(at),
                                                        'source': 'ad_prefilled_message'})
    if inactivity_return:
        # This is a new atendimento, not an answer to a question from the
        # inactive cycle. Old facts/proofs remain archived for audit/fences.
        if cycle.get('experience_version') == 'bia-approved-v1':
            from approved_experience import OPENING, CHOICES
            return {**_finish(state, at, reply=OPENING, buttons=CHOICES, exact=True), 'fixed_greeting': True}
        return {**_finish(state, at, intro=True, reply=conversation._RESET_GREETING), "fixed_greeting": True}
    if normal in {'sim', 'nao'} and isinstance(inactivity_notice, dict):
        # The server projects the LAST accepted Bia turn from durable outbox
        # receipts. A yes/no to the warning cannot answer an older consent or
        # qualification question, even though the cycle kept that same phase.
        source = inactivity_notice.get('source_key')
        expected = 'inactivity-warning:' + hashlib.sha256(
            ('pilot-inactivity-v2:' + cycle['id'] + ':' + str(source)).encode()).hexdigest()
        try:
            timestamp = inactivity_notice.get('accepted_at', inactivity_notice.get('observed_at'))
            accepted = engine._clock(timestamp)
            valid_time = isinstance(timestamp, str) and engine._clock(last_inbound_before_turn) <= accepted <= at
        except (KeyError, ValueError, TypeError, OverflowError):
            valid_time = False
        source_kind = inactivity_notice.get('source')
        if (source_kind in {'accepted_outbox', 'uncertain_outbox'} and valid_time
                and inactivity_notice.get('cycle_id') == cycle['id']
                and state.get('processed_inbound') and source == state['processed_inbound'][-1]
                and inactivity_notice.get('warning_key') == expected):
            if source_kind == 'accepted_outbox':
                normal = 'seguir atendimento' if normal == 'sim' else 'encerrar agora'
            elif cycle['phase'] in {'shop', 'agency', 'consent_real'}:
                normal = 'seguir atendimento'
    if conversation._chat_reset_requested(text, real_mode=True):
        if not fresh:
            cycle.update(status="closed", reason="lead_restart", closed_at=engine._stamp(at))
            for effect in state["effects"].values():
                if effect.get("cycle_id") == cycle["id"] and effect.get("status") in {"pending", "running"}:
                    # An in-flight invitation may have reached TikTok. Keep its
                    # uncertainty as a fence; read-only jobs can be cancelled.
                    effect["status"] = "outcome_unknown" if effect.get("operation") == "invite" else "cancelled"
            cycle = engine._open(state, at)
            cycle.update(mode="real", phase="intro", qualification_rollout=(qualification_enabled or approved_experience_enabled) is True)
            if approved_experience_enabled is True:
                cycle['experience_version'] = 'bia-approved-v1'
            state["history"][-1]["cycle_id"] = cycle["id"]
        cycle['funnel_after_reset'] = True
        if cycle.get('experience_version') == 'bia-approved-v1':
            from approved_experience import OPENING, CHOICES
            return {**_finish(state, at, reply=OPENING, buttons=CHOICES, exact=True), 'fixed_greeting': True}
        return {**_finish(state, at, intro=True, reply=conversation._RESET_GREETING), "fixed_greeting": True}
    if not_interested(text):

        cycle.update(status="closed", reason="lead_not_interested", closed_at=engine._stamp(at))
        for effect in state["effects"].values():
            if effect.get("cycle_id") == cycle["id"] and effect.get("status") in {"pending", "running"}:
                effect["status"] = "outcome_unknown" if effect.get('operation') == 'invite' else "cancelled"
        return {**_finish(state, at, reply=conversao.NOT_INTERESTED, buttons=[]), 'fixed_greeting': True}
    if ("?" not in text and normal in conversation._PAUSE | {'encerrar agora'}) or _pause_requested(text):
        cycle.update(status="closed", reason='inactivity_user_close' if normal == 'encerrar agora' else "lead_pause",
                     closed_at=engine._stamp(at))
        for effect in state["effects"].values():
            if effect.get("cycle_id") == cycle["id"] and effect.get("status") in {"pending", "running"}:
                effect["status"] = "outcome_unknown" if effect.get('operation') == 'invite' else "cancelled"
        return _finish(state, at, reply="Tudo bem. Encerrei este atendimento, preservando o histórico. Quando quiser conversar de novo, pode me chamar.", buttons=[])
    # Adopt presentation only; provider effects stay in the real state machine.
    if cycle.get('experience_version') == 'bia-approved-v1':
        from approved_experience import OPENING, CHOICES, MENUS, TOPICS
        from lead_validation import stage as current_validation_stage
        prejoin = (cycle['phase'] == 'intro' and not cycle['facts'].get('interesse_agenciamento'))
        greeting_text = re.sub(r'[^a-z0-9 ]', ' ', normal)
        greeting_text = ' '.join(greeting_text.split())
        greeting = bool(re.fullmatch(r'(?:(?:oi|ola|bom dia|boa tarde|boa noite)(?: tudo bem)?(?: eu)?(?: quero conhecer voces| queria conversar| vim pelo anuncio| vi o anuncio)?|tudo bem)', greeting_text))
        if prejoin and (greeting or normal == 'menu' or (fresh and _AD_MESSAGE.search(normal))):
            return {**_finish(state, at, reply=OPENING, buttons=CHOICES, exact=True), 'fixed_greeting': True}
        # Navigation never changes a qualification answer or operational phase.
        if normal in MENUS:
            message, buttons = MENUS[normal]
            return {**_finish(state, at, reply=message, buttons=buttons, exact=True), 'fixed_greeting': True}
        if normal in TOPICS:
            question = TOPICS[normal]
            context = {'phase': cycle['phase'], 'facts': deepcopy(cycle['facts']),
                       'history': deepcopy([item for item in state['history'] if item['cycle_id'] == cycle['id']]),
                       'cycle': {key: cycle[key] for key in ('id', 'number', 'status', 'expires_at', 'opened_at') if key in cycle},
                       'real_mode': True, 'simulation_only': False, 'current_question': '',
                       'allowed_claim_fields': [], 'allowed_actions': ['question', 'clarify', 'converse'],
                       'can_confirm_external_events': False}
            if policy_valid(operation_policy):
                context['commercial_policy'] = {key: operation_policy[key] for key in
                    ('commission', 'commission_unit', 'duration_fixed_months', 'duration_label', 'version')}
            try:
                proposal = assistant_callback(question, context) if callable(assistant_callback) else None
            except Exception:
                proposal = None
            answer = _question_reply(question, proposal, cycle, operation_policy, state=state, now=at, allow_local=False)
            answer = answer or 'Não consegui consultar essa informação agora. Sua etapa está preservada. Você pode tentar a pergunta novamente. 🔎'
            pending = current_validation_stage(cycle)
            if pending and pending != 'complete':
                from lead_validation import QUESTIONS
                prompt, buttons = QUESTIONS[pending]
                answer += '\n\n' + prompt
            else:
                buttons = ['Quero fazer parte', 'Ver tópicos'] if prejoin else ['Ver tópicos']
            return {**_finish(state, at, reply=answer, buttons=buttons, exact=True), 'fixed_greeting': True}
        if prejoin and normal == 'ja sou amplify':
            from lead_validation import begin, advance
            cycle['facts']['interesse_agenciamento'] = True
            begin(cycle, at)
            response = advance(cycle, 'Já sou Amplify', at)
            if response is not None:
                return _finish(state, at, reply=response[0], buttons=response[1], exact=True)
            return _direct_form(state, at)

    from lead_validation import stage as validation_stage, advance as validation_advance
    if validation_stage(cycle) not in {None, 'complete'}:
        validation_text = text
        if (cycle.get('experience_version') == 'bia-approved-v1' and validation_stage(cycle) == 'existing_profile'
                and not re.fullmatch(r'[A-ZÀ-Ý][a-zà-ÿ]+', text.strip())):
            validation_text = _bare_handle(text) or text
        response = validation_advance(cycle, validation_text, at)
        if response is not None:
            question, choices = response
            return _finish(state, at, reply=question, buttons=choices, exact=True)
        if cycle['bia_validation'].get('existing_amplify_declared') is True:
            return _direct_form(state, at)
        cycle['phase'] = _qualification_phase(cycle)
        jobs = _initial_checks(state, at)
        return _finish(state, at, effects=jobs, exact=True)

    if (cycle.get('bia_validation') or {}).get('existing_amplify_declared') is True:
        return _direct_form(state, at)

    # Never insert new questions into a cycle that was already in progress
    # when production qualification was activated. Resets open a new cycle.
    if qualification_new_cycles_only is True:
        qualification_enabled = qualification_enabled is True and cycle.get('qualification_rollout') is True

    if qualification_enabled is True:
        if normal == 'quero fazer parte':
            cycle['facts']['interesse_agenciamento'] = True
        from lead_validation import begin as validation_begin
        validation_question = validation_begin(cycle, at)
        if validation_question is not None:
            # Preserve an explicitly supplied profile, never promote bare prose.
            if _creator(text.strip()) and not cycle['facts'].get('tiktok_declarado'):
                cycle['facts']['tiktok_declarado'] = text.strip().lower()
            question, choices = validation_question
            return _finish(state, at, reply=question, buttons=choices, exact=True)

    prequalification = (cycle['phase'] in {'intro', 'origin', 'tiktok'}
                        and not _creator(cycle['facts'].get('tiktok_declarado')))
    soft_decline = (prequalification and '?' not in text
                    and not any(mark in text for mark in ('"', "'", '“', '”'))
                    and re.match(r'^(?:eu )?(?:ainda |agora )?nao (?:quero|pretendo|tenho interesse em) '
                                 r'(?:me |ser )?agenciar\b', normal))
    if soft_decline:
        cycle['qualification_paused'] = True
    if (cycle['phase'] in {'intro', 'origin', 'tiktok'}
            and not _creator(cycle['facts'].get('tiktok_declarado'))
            and _other_agency_declaration(text)):
        cycle['facts']['possui_agencia_declarada'] = True
        cycle['qualification_paused'] = True
        cycle.setdefault('claim_provenance', []).append({
            'field': 'possui_agencia_declarada', 'at': engine._stamp(at),
            'source': 'current_inbound_declaration'})
        return _finish(state, at, reply=(
            'Entendi. Você quer entender como trocar para a Amplify ou prefere pausar por aqui?'),
            buttons=['Quero trocar', 'Pausar'])
    if cycle.get('qualification_paused'):
        if '?' not in text and (normal == 'quero trocar' or conversation._explicit_start(text, text)
                                or re.fullmatch(r'@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}', text.strip())):
            cycle.pop('qualification_paused', None)
            cycle['facts']['interesse_agenciamento'] = True
            cycle['phase'] = _qualification_phase(cycle)
        else:
            # Keep answering doubts during a pause, without another sales CTA.
            context = {'phase': cycle['phase'], 'facts': deepcopy(cycle['facts']),
                       'real_mode': True, 'current_question': '', 'allowed_claim_fields': [],
                       'can_confirm_external_events': False}
            try:
                proposal = assistant_callback(text, deepcopy(context)) if callable(assistant_callback) else None
            except Exception:
                proposal = None
            answer = _question_reply(text, proposal, cycle, operation_policy, state=state, now=at)
            answer = conversation._before_interest_reply((answer or '').replace(_INTRO_ACTION, ''))
            return _finish(state, at, reply=answer or
                           'Tudo bem. A qualificação fica pausada por aqui. Se quiser entender a troca, me avise.', buttons=[])
    carried = _carried_handle(state) if fresh and not cycle['facts'].get('tiktok_declarado') else None
    if carried:
        # Quem esperou a ponte e voltou depois das 24 h não manda o @ de novo.
        cycle['facts'].update(tiktok_declarado=carried, interesse_agenciamento=True)
        cycle.setdefault('claim_provenance', []).append({'field': 'tiktok_declarado', 'at': engine._stamp(at),
                                                        'source': 'previous_cycle_declaration'})
        jobs = _initial_checks(state, at)
        if jobs:
            return _finish(state, at, reply=conversao.RETURNED.format(handle=carried), effects=jobs, buttons=[])
    generic_entry = (normal in {'oi', 'ola', 'bom dia', 'boa tarde', 'boa noite', 'tudo bem', 'oi tudo bem',
                                'oi tudo bem vi o anuncio'}
                     or re.fullmatch(r'(?:oi )?(?:eu )?(?:quero|gostaria de) saber mais sobre (?:o )?'
                                     r'agenciamento(?: de creators)?', normal))
    if (cycle['phase'] == 'intro' and not _creator(cycle['facts'].get('tiktok_declarado'))
            and cycle['facts'].get('interesse_agenciamento') is not True and generic_entry):
        # The entry script offers one clear choice; AI still answers concrete
        # questions, while the native start/profile handlers own progression.
        return _finish(state, at, intro=fresh, reply=PROMPTS['intro'],
                       buttons=['Conhecer a Amplify', 'Quero me agenciar'])
    no_handle = not _creator(cycle['facts'].get('tiktok_declarado'))
    if no_handle and cycle['phase'] in {'intro', 'origin', 'tiktok'} and "?" not in text:
        if normal == 'mandar meu':
            cycle['arroba_pedido'] = True
            return {**_finish(state, at, reply=conversao.HANDLE_HELP, buttons=[]), "fixed_greeting": True}
        if normal == 'quero entrar':
            cycle['facts']['interesse_agenciamento'] = True
            cycle['phase'] = _qualification_phase(cycle)
            cycle['arroba_pedido'] = True
            return _finish(state, at, reply=conversao.WANTS_IN, buttons=[])
        if normal == 'agora nao':
            cycle.update(status='closed', reason='lead_pause', closed_at=engine._stamp(at))
            return _finish(state, at, reply=conversao.NOT_NOW, buttons=[])
        if cycle.get('arroba_pedido') and _name_instead_of_handle(text, normal):
            # Release 41: o nome no lugar do @ recebe a explicação de onde achar o @, não o pedido repetido.
            return {**_finish(state, at, reply=_HANDLE_UNKNOWN, buttons=[]), "fixed_greeting": True}
    if normal == 'seguir atendimento':
        if cycle['phase'] in {'intro', 'origin', 'tiktok', 'shop', 'agency'}:
            cycle['phase'] = _qualification_phase(cycle)
        jobs = _initial_checks(state, at)
        reply = (_consent_prompt(cycle, operation_policy) if cycle['phase'] == 'consent_real'
                 else _phase_prompt(cycle))
        if cycle['phase'] == 'form' and cycle.get('form_url') and cycle['form_url'] not in reply:
            reply += '\n\n' + cycle['form_url']
        return _finish(state, at, reply=reply, effects=jobs)
    if "?" not in text and normal == "menu":
        return {**_finish(state, at, reply="Você pode conhecer a proposta da Amplify ou conversar sobre seu agenciamento. 👇",
                          buttons=["Conhecer a Amplify", "Quero me agenciar"]), "fixed_greeting": True}
    invite_pending = (cycle.get('relationship_check_in_form') is True and cycle['phase'] in {'await_acceptance', 'form'}
                      and (_invite_known(cycle) or _invite_unlanded(cycle) or ((cycle.get('real_operations') or {}).get('relationship') or {}).get('status')
                           == 'pending') and not _linked(cycle))
    if normal in _FAQ_MENU and cycle['phase']!='intro' and not invite_pending:
        return _finish(state,at,reply='Posso te explicar a parceria, os benefícios e a comissão. Qual assunto você gostaria de conhecer?',
                       buttons=['Como funciona','Benefícios','Comissão'])
    direct_reason = _direct_form_reason(text) if cycle.get('relationship_check_in_form') is True else None
    new_direct = bool(direct_reason and _refresh_direct_request(state, source_event, at, reason=direct_reason))
    if new_direct and not _creator(cycle.get('facts', {}).get('tiktok_declarado')) and '@' not in text:
        return _direct_form(state, at)
    correction = (_declared_profile_change(text, cycle) if cycle['phase'] == 'blocked'
                  and not cycle.get('pending_profile_changes') else None)
    if correction:
        cycle['pending_profile_changes'] = {'tiktok_declarado': correction}
        return _finish(state, at, reply=(
            'Você informou uma mudança: @ do TikTok: ' + cycle['facts']['tiktok_declarado']
            + ' → ' + correction + '.\n\nConfirma atualizar esses dados?'),
            buttons=['Confirmo', 'Não confirmo'])
    shop_unknown = cycle['phase'] == 'blocked' and isinstance(cycle.get('shop_unknown'), dict)
    commercial_question = bool(re.search(
        r'\b(?:comissao|taxa|custa|custo|beneficios?|campanhas?|amostras?|parceria)\b', normal))
    contextual_shop_help = re.fullmatch(r'(?:como (?:eu )?(?:faco|fazer)(?: isso)?|onde (?:eu )?(?:vejo|encontro) isso|me ajuda)', normal)
    shop_help = (not commercial_question
                 and (re.search(r'\b(?:shop|central|ativar|ativacao)\b', normal) or contextual_shop_help)
                 and re.search(r'\b(?:como|onde|ativar|passo|passos|nao sei|ajuda)\b', normal))
    shop_recheck = (not commercial_question and (
        normal in {'pronto', 'prontinho', 'ativei', 'ativado', 'ativo', 'feito', 'consegui', 'liberou', 'liberado'}
        or re.search(r'\b(?:conferir|confere|reconferir|reconfere|consultar|consulta|verificar|verifica)\b', normal)))
    if shop_unknown and shop_help:

        return _finish(state, at, reply=conversao.SHOP_STEPS, buttons=[])
    if cycle.get('relationship_check_in_form') is True and form_link_requested(text) and not new_direct:
        if _form_stage(cycle) or cycle['phase'] in {'await_acceptance', 'checking_acceptance'}:
            cycle['form_url'] = PUBLIC_FORM_URL
            if cycle['phase'] in {'await_acceptance', 'checking_acceptance', 'inviting', 'blocked'} and _invite_known(cycle):
                cycle['phase'] = 'form'
            return _finish(state, at, reply=_form_prompt(cycle), buttons=[], force_form_button=True)
        # Antes do convite não há cadastro a fazer: diz isso e segue o passo atual.
        step = (_INTRO_ACTION if cycle['phase'] == 'intro' else
                _consent_prompt(cycle, operation_policy) if cycle['phase'] == 'consent_real' else _phase_prompt(cycle))
        return _finish(state, at, reply='O cadastro é liberado depois que você aceita o convite da Amplify no TikTok. 😊\n\n' + step,
                       buttons=['Quero me agenciar'] if cycle['phase'] == 'intro' else None)
    if invite_pending and invite_missing(text):
        # Release 41: "Não apareceu o convite" é sobre o convite, não sobre o formulário (gabiosantana1, 30/10).

        result = _acceptance_turn(state, at)
        if result.get('effects'):
            # Release 42: o resultado desta leitura responde com o passo a passo (texto 3) ou com o reenvio único.
            previous = cycle.get('invite_missing') or {}
            cycle['invite_missing'] = {'effect_id': result['effects'][0]['id'], 'at': engine._stamp(at),
                                       'count': int(previous.get('count') or 0) + 1}
            result['reply'] = conversao.INVITE_CHECK
            for item in reversed(state.get('history') or []):
                if item.get('direction') == 'outbound':
                    item['text'] = conversao.INVITE_CHECK
                    break
            return result
        return _finish(state, at, reply=conversao.INVITE_WHERE, buttons=['Já aceitei'])
    if (cycle['phase']=='origin' and cycle['facts'].get('interesse_agenciamento') is True
            and 'origem_declarada' not in cycle['facts'] and not cycle.get('pending_profile_changes')
            and re.fullmatch(r'(?:eu )?ja (?:te )?(?:falei|disse|respondi|informei)',normal)):
        origin,source=_recover_origin(state)
        if origin:
            cycle['facts'].update(origin)
            cycle['origin_declaration']=source
            cycle.setdefault('claim_provenance',[]).append({'field':'origem_declarada','at':source['at'],
                'source':source['source'],'quote':source['quote'],'reference':source['reference']})
            cycle['phase']=_qualification_phase(cycle)
            jobs=_initial_checks(state,at)
            reply=('Anotei a origem que você já informou. 😊\n\n'+PROMPTS[cycle['phase']])
            result=_finish(state,at,reply=reply,effects=jobs)
            result.update(applied_claims=list(origin),origin_source=source)
            return result
    pending = cycle.get("pending_profile_changes")
    if pending and "?" not in text and normal in _YES | _NO:
        applied = []
        profile_changed = normal in _YES and "tiktok_declarado" in pending
        if normal in _YES:
            if "tiktok_declarado" in pending:
                _cancel_for_profile_change(state, cycle)
            cycle["facts"].update(pending)
            applied = list(pending)
        cycle.pop("pending_profile_changes", None)
        if profile_changed or cycle["phase"] in {"intro", "origin", "tiktok", "shop", "agency"}:
            cycle["phase"] = _qualification_phase(cycle)
        jobs = []
        if profile_changed and cycle["phase"] == "checking":
            jobs = _initial_checks(state, at)
        if applied and cycle.get('form_entry_request') and _refresh_direct_request(state, source_event, at):
            return _direct_form(state, at)
        response=None if applied else "Tudo bem, mantive os dados anteriores.\n\n" + PROMPTS[cycle["phase"]]
        if 'nome_declarado' in applied:
            from nome_contextual import first_name
            response='Prazer, '+first_name(cycle['facts']['nome_declarado'])+'! 😊\n\n'+PROMPTS[cycle['phase']]
        transition = _finish(state, at, effects=jobs, reply=response)
        transition["applied_claims"] = applied
        return transition
    # Every real invite consent is bound to the terms actually offered in this
    # cycle, account and handle. Simulated yes/consent fields are never read.
    if cycle["phase"] == "consent_real" and normal == "tenho uma duvida":
        return _finish(state, at, reply=conversao.DOUBT, buttons=[])
    if cycle["phase"] == "consent_real" and "?" not in text:
        if normal in _NO:
            cycle["facts"]["consentimento_convite"] = False
            return _finish(state, at, reply="Tudo bem. Não enviarei o convite. Posso esclarecer as condições da parceria por aqui.", buttons=[])
        offer = cycle.get("invite_offer") or {}
        if (normal in _REAL_CONSENT | _YES and policy_valid(operation_policy)
                and offer.get("policy_hash") == _policy_fingerprint(operation_policy)
                and offer.get("creator") == cycle["facts"].get("tiktok_declarado")):
            cycle["facts"]["consentimento_convite"] = True
            cycle["invite_consent"] = {**offer, "cycle_id": cycle["id"], "at": engine._stamp(at),
                                       "source": "current_inbound_explicit_confirmation"}
            job = _effect(state, "invite", at, policy=operation_policy)
            if job:
                cycle["phase"] = "inviting"
                result = _finish(state, at, effects=[job])
                result["applied_claims"] = ["consentimento_convite"]
                return result
            if _prior_invite_requires_reconciliation(state, _creator(cycle["facts"].get("tiktok_declarado"))):

                # pendente → onde aceitar; sumiu → um convite novo, sem pedir a autorização de novo.
                check = _acceptance_check(state, at, 0, origin=engine._stamp(at))
                if check:
                    cycle["prior_invite_check"] = {"at": engine._stamp(at), "effect_id": check["id"]}
                    cycle["phase"] = "checking_acceptance"
                    return _finish(state, at, reply=conversao.PRIOR_INVITE_CHECK, effects=[check], buttons=[])
                cycle["phase"] = "blocked"
                return _finish(state, at, reply="Há uma solicitação anterior para esse perfil que precisa ser conferida. Vou preservar essa verificação sem enviar outro convite.", buttons=[])
            if not precheck_proven(state, now=at):
                cycle["phase"] = "checking"
                fresh_check = _effect(state, "precheck", at)
                if fresh_check:
                    # Release 41: a autorização já foi dada. A validação é refeita em silêncio e o convite sai em

                    cycle["consent_refresh"] = {"at": engine._stamp(at), "precheck_effect_id": fresh_check["id"]}
                    result = _finish(state, at, reply=conversao.INVITING, effects=[fresh_check], buttons=[])
                    result["applied_claims"] = ["consentimento_convite"]
                    return result
                return _finish(state, at, reply="Vou atualizar a validação do perfil antes de enviar qualquer convite real.",
                               effects=[])
        # A changed policy must be presented and reconfirmed, not accepted by a
        # yes answering the earlier offer.
        if normal in _REAL_CONSENT | _YES:
            return _finish(state, at, reply=_consent_prompt(cycle, operation_policy))
    precheck_record = (cycle.get('real_operations') or {}).get('precheck') or {}
    if (cycle["phase"] == "blocked" and not bridge_waiting(cycle) and not _invite_known(cycle)
            and not cycle.get('invite_retry') and precheck_record.get('cycle_id') == cycle['id']
            and (not shop_unknown or shop_recheck)
            and precheck_record.get('status') in {'verification_pending', 'failed', 'outcome_unknown'}):
        # Quem ficou sem resultado da conferência pode pedir outra escrevendo de novo (no máximo a cada 10 min).
        try:
            last_check = engine._clock(cycle['lead_recheck_at']) if cycle.get('lead_recheck_at') else None
        except (TypeError, ValueError, OverflowError):
            last_check = None
        if last_check is None and isinstance(cycle.get('shop_unknown'), dict):
            # Release 43: o "pronto" reconfere no máximo a cada 10 min, contados também da consulta que deu Shop sem status.
            try:
                last_check = engine._clock(precheck_record.get('observed_at'))
            except (TypeError, ValueError, OverflowError):
                last_check = None
        if (last_check is not None and at - last_check < BRIDGE_RETRY_GAP and isinstance(cycle.get('shop_unknown'), dict)
                and re.search(r'\b(?:pronto|prontinho|ativei|ativado|ativo|feito|consegui|liberou|liberado)\b', normal)):
            return _finish(state, at, reply=conversao.SHOP_RECHECK_SOON, buttons=[])
        if last_check is None or at - last_check >= BRIDGE_RETRY_GAP:
            for old in state['effects'].values():
                if (old.get('operation') == 'precheck' and old.get('cycle_id') == cycle['id']
                        and old.get('status') == 'outcome_unknown'):
                    old['status'] = 'superseded_by_lead_recheck'
            check = _effect(state, 'precheck', at)
            if check:
                cycle['lead_recheck_at'] = engine._stamp(at)
                cycle['phase'] = 'checking'
                return _finish(state, at, reply='Vou conferir seu perfil de novo agora 🔎',
                               effects=[check], buttons=[])
    if cycle["phase"] == "blocked" and _invite_retry_possible(state):
        # A consented invite that never reached TikTok is retried once when the
        # lead writes again; the bridge rechecks relations first, so an invite
        # sent by other means is found as pending instead of duplicated.
        check = _schedule_invite_retry(state, at, delay=0)
        if check:
            return _finish(state, at, reply="Vou conferir seu convite no TikTok agora. 🔎", effects=[check])
    if (cycle.get('relationship_check_in_form') is True
            and cycle["phase"] in {"await_acceptance", "checking_acceptance", "inviting", "blocked", "form"}
            and acceptance_declared(text, cycle)):
        # O aceite declarado é conferido na hora pela ponte (leitura do vínculo).
        return _acceptance_turn(state, at)
    if (cycle["phase"] in {"await_acceptance", "checking_acceptance", "inviting", "blocked"}
            and "?" not in text and (normal in _ACCEPTANCE or
                re.fullmatch(r"(?:ja )?aceitei(?: o convite)?(?: (?:no|la no) tiktok| la| agora)?", normal))):
        cycle["facts"]["aceite_declarado"] = True
        job = _effect(state, "relationship", at)
        cycle["phase"] = "checking_acceptance"
        result = _finish(state, at, effects=[job] if job else [])
        result["applied_claims"] = ["aceite_declarado"]
        return result
    answered_phase = cycle["phase"]
    if cycle["phase"] in {"intro", "origin", "tiktok", "shop", "agency"}:
        # Facts are authoritative even when a previous release parked the cycle
        # on an already answered field. Waiting/result phases never regress.
        cycle["phase"] = _qualification_phase(cycle)
    context = {"phase": cycle["phase"], "facts": deepcopy(cycle["facts"]),
               "history": deepcopy([item for item in state["history"] if item["cycle_id"] == cycle["id"]]),
               "cycle": {key: cycle[key] for key in ("id", "number", "status", "expires_at", "opened_at") if key in cycle},
               "allowed_actions": sorted(INTENTS), "allowed_claim_fields": sorted(FIELDS),
               "current_question": _phase_prompt(cycle), "simulation_only": False,
               "real_mode": True, "can_confirm_external_events": False,
               "relationship_check_in_form": cycle.get('relationship_check_in_form') is True,
               **_turn_guidance(state, at)}
    if policy_valid(operation_policy):
        context["commercial_policy"] = {key: operation_policy[key] for key in
                                        ("commission", "commission_unit", "duration_fixed_months", "duration_label", "version")}
    callback_context=deepcopy(context)
    try:
        direct_input = cycle.get('form_entry_request') and (new_direct or re.fullmatch(r'@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}', text.strip()))
        literal_handle = re.fullmatch(r'@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}', text.strip())
        scripted_input = literal_handle or normal in conversation._START
        plan = (assistant_callback(text, callback_context)
                if callable(assistant_callback) and not (direct_input or scripted_input) else None)
    except Exception:
        plan = None
    # Interpret the answer against the question that was pending when the lead
    # wrote it, even when existing facts already permit a different next action.
    requested_name=cycle.get('name_question_pending') is True
    delivery=callback_context.get('delivery_context')
    if isinstance(delivery,dict):
        from nome_contextual import name_question
        last=delivery.get('last_accepted_reply')
        requested_name=requested_name and delivery.get('source')=='outbox' and isinstance(last,dict) and name_question(last.get('text'))
    claims = _extract_claims(text, answered_phase, plan,requested_name=requested_name)
    # Release 39: the @ sent in answer to a retomada/resume ask is the lead's own
    # opt-in. A capitalized single word looks like a name, not a handle.
    handle_requested = ((cycle.get('arroba_pedido') is True and answered_phase in {'intro', 'origin'}
                        or answered_phase == 'tiktok' and cycle.get('experience_version') == 'bia-approved-v1')
                        and not _creator(cycle['facts'].get('tiktok_declarado')))
    if handle_requested and 'tiktok_declarado' not in claims and not re.fullmatch(r'[A-ZÀ-Ý][a-zà-ÿ]+', text.strip()):
        bare = _bare_handle(text)
        if bare:
            claims['tiktok_declarado'] = bare
    linked_handle = profile_link_handle(text)
    if linked_handle and 'tiktok_declarado' not in claims and not _creator(cycle['facts'].get('tiktok_declarado')):

        claims['tiktok_declarado'] = linked_handle
        claims['interesse_agenciamento'] = True
    handle_by_request = handle_requested and 'tiktok_declarado' in claims
    if handle_by_request or ('tiktok_declarado' in claims and literal_handle):
        # A literal personal @ is the requested profile declaration, even if
        # a previous AI reply failed to persist the request marker.
        claims['interesse_agenciamento'] = True
    # Only explicit desire to start permits collecting qualifications.
    if cycle["facts"].get("interesse_agenciamento") is not True and claims.get("interesse_agenciamento") is not True:
        permitted = {'nome_declarado', 'tiktok_declarado'} if cycle.get('form_entry_request') else {'nome_declarado'}
        claims = {key:value for key,value in claims.items() if key in permitted}
    changes = {key: value for key, value in claims.items() if key in PROFILE and key in cycle["facts"] and cycle["facts"][key] != value}
    if changes:
        cycle["pending_profile_changes"] = changes
        labels = {"nome_declarado": "nome", "tiktok_declarado": "@ do TikTok", "origem_declarada": "origem",
                  "origem_canal_declarado": "canal de origem"}
        details = "; ".join(f"{labels[key]}: {cycle['facts'][key] or 'não informado'} → {value or 'não informado'}" for key, value in changes.items())
        return _finish(state, at, reply="Você informou uma mudança: " + details + ".\n\nConfirma atualizar esses dados?", buttons=["Confirmo", "Não confirmo"])
    applied = []
    for key, value in claims.items():
        if key in {"consentimento_convite", "aceite_declarado"}:
            continue
        cycle["facts"][key] = value
        applied.append(key)
        cycle.setdefault("claim_provenance", []).append({"field": key, "at": engine._stamp(at), "source": "current_inbound_declaration"})
    jobs = []
    if applied:
        phase = _qualification_phase(cycle)
        if cycle["phase"] in {"intro", "origin", "tiktok", "shop", "agency"}:
            cycle["phase"] = phase
    if qualification_enabled is True:
        from lead_validation import begin as validation_begin
        validation_question = validation_begin(cycle, at)
        if validation_question is not None:
            question, choices = validation_question
            return _finish(state, at, reply=question, buttons=choices, exact=True)
    if cycle.get('form_entry_request') and (new_direct or 'tiktok_declarado' in applied):
        if _refresh_direct_request(state, source_event, at):
            return _direct_form(state, at)
    # Also recover a release20 cycle parked at shop/agency with a known handle;
    # no reset, repeated handle or new declaration is needed to run the checks.
    jobs = _initial_checks(state, at)
    if 'origem_declarada' in applied:
        cycle['origin_declaration']=_origin_source(state['history'][-1])
    if cycle['phase'] == 'consent_real' and not policy_valid(operation_policy):
        cycle.pop('invite_offer', None)
    reply = _question_reply(text, plan, cycle, operation_policy,state=state,now=at)
    if shop_unknown and cycle['phase'] == 'blocked' and not jobs:
        # Answer the FAQ, then retain the unresolved provider step. An unknown
        # Shop result is never an instruction to activate an inactive account.
        reply = _step_reply(conversation._answer_without_requests(reply or ''), conversao.SHOP_UNKNOWN)
    if ("interesse_agenciamento" in applied and cycle["phase"] == "origin"
            and normal in conversation._START):
        # The planner saw the previous phase before this explicit declaration.
        # Do not reuse its speculative qualification request after advancing.
        reply = "Que bom! Vou te orientar por aqui. 😊\n\n" + PROMPTS["origin"]
    if cycle["phase"] == "consent_real" and not reply:
        reply = _consent_prompt(cycle, operation_policy)
    if normal in conversation._TOPIC_ENTRY and not reply:
        reply = ("A Amplify é uma agência para creators do TikTok Shop. A parceria reúne orientação, campanhas e comunidade, "
                 "conforme a categoria e as condições de cada creator. 😊\n\nO que você busca desenvolver hoje como creator?")
    if "origem_declarada" in applied and cycle["phase"] == "tiktok":
        reply = PROMPTS["tiktok"]
    if handle_by_request and 'tiktok_declarado' in applied:
        cycle.pop('arroba_pedido', None)
        if cycle['phase'] == 'origin':
            reply = 'Anotei seu @ ' + cycle['facts']['tiktok_declarado'] + '! ✅\n\n' + PROMPTS['origin']
    if (answered_phase == "tiktok" and cycle["phase"] == "tiktok" and "tiktok_declarado" not in applied
            and "?" not in text and not jobs
            and (not re.search(r"\s", text.strip())
                 or re.search(r"\brecebi\b|vou consultar|consultando|estou verificando|vou verificar (?:o|seu) perfil",
                              (reply or "").replace(PROMPTS["tiktok"], ""), re.I))):
        # The handle was not accepted: never let free model text claim it was
        # received or is being checked while the same question is asked again.
        reply = _HANDLE_UNKNOWN
    if 'nome_declarado' in applied:
        from nome_contextual import first_name
        if cycle['phase']=='intro':
            reply='O que você quer saber primeiro?'
        reply='Prazer, '+first_name(cycle['facts']['nome_declarado'])+'! 😊\n\n'+(reply or PROMPTS[cycle['phase']])
    if jobs and 'tiktok_declarado' in applied:
        cycle.pop('arroba_pedido', None)
        reply, plan = conversao.RECEIVED.format(handle=cycle['facts']['tiktok_declarado']), None
    elif jobs:
        checking = (("Tudo bem, você não precisa saber se está ativo para eu conferir.\n\n"
                  if "shop_ativo_declarado" in applied and cycle["facts"].get("shop_ativo_declarado") is None else "")
                 + _phase_prompt(cycle, 'checking'))
        reply = (reply + "\n\n" + checking if reply and isinstance(plan, dict)
                 and plan.get("intent") == "question" else checking)
    if (cycle.get('relationship_check_in_form') is True and cycle['phase'] in {'await_acceptance', 'form'}
            and _invite_known(cycle) and not _linked(cycle) and not jobs):
        # 6. Com o convite pendente, a dúvida é respondida e a resposta lembra do aceite.
        asked = '?' in text or normal in conversation._TOPIC_TEXT or normal in conversation._TOPIC_ENTRY
        if asked and (not reply or reply == _known_faq_unavailable(text)):
            reply = _local_topic_answer(text) or reply or ''
        if reply and 'aceitei' not in reply:
            # Uma pergunta só: a do aceite substitui a pergunta solta do fim da resposta.
            reply = re.sub(r'\s*(?:\n\n)?[^.!?\n]*\?\s*$', '', reply).rstrip() if reply.rstrip().endswith('?') else reply
            reply = (reply + '\n\n' if reply else '') + _ACCEPT_NEXT_STEP
    buttons=['Como funciona','Benefícios','Comissão'] if (normal in _FAQ_MENU or 'nome_declarado' in applied) and cycle['phase']=='intro' else None
    if cycle['phase'] == 'intro':
        if reply.endswith(_INTRO_ACTION):
            buttons = ['Quero me agenciar']
    transition = _finish(state, at, reply=reply, effects=jobs, intro=fresh,buttons=buttons)
    transition["applied_claims"] = applied
    if 'origem_declarada' in applied:
        transition['origin_source']=cycle['origin_declaration']
    return transition


def relationship_proven(state, *, now=None, maximum_age_seconds=900):
    """Recheck at both form creation and submission; a bare bool is never proof."""
    return _operation_proven(state, "relationship", "linked", now=now, maximum_age_seconds=maximum_age_seconds)


def precheck_proven(state, *, now=None, maximum_age_seconds=900):
    return _operation_proven(state, "precheck", "eligible", now=now, maximum_age_seconds=maximum_age_seconds)


def _operation_proven(state, operation, status, *, now=None, maximum_age_seconds=900):
    cycle = state.get("cycle") or {}
    relationship = (cycle.get("real_operations") or {}).get(operation) or {}
    if (cycle.get("mode") != "real" or relationship.get("status") != status or relationship.get("confirmed") is not True
            or relationship.get("creator") != _creator(cycle.get("facts", {}).get("tiktok_declarado"))
            or relationship.get("cycle_id") != cycle.get("id") or not relationship.get("job_id")
            or not isinstance(relationship.get("evidence"), dict) or not relationship["evidence"]):
        return False
    effect = state.get("effects", {}).get(relationship["job_id"]) or {}
    if (effect.get("type") != "tiktok_operation" or effect.get("operation") != operation
            or effect.get("status") != "done" or effect.get("cycle_id") != cycle.get("id")
            or effect.get("creator") != relationship["creator"]):
        return False
    try:
        age = (engine._clock(now) - engine._clock(relationship.get("observed_at"))).total_seconds()
        return 0 <= age <= maximum_age_seconds
    except (TypeError, ValueError, OverflowError):
        return False


def bridge_waiting(cycle):
    return isinstance(cycle, dict) and cycle.get('phase') == 'blocked' and isinstance(cycle.get('bridge_wait'), dict)


def bridge_retry_due(state, now, *, reason=None, forced=False):
    """Atendimento parado na conferência do perfil porque a ponte estava fora: pode reconferir agora?

    ``reason`` vem do registro do trabalho anterior; atendimentos da 39 não têm a marca ``bridge_wait``.
    """
    cycle = state.get('cycle') or {}
    facts = cycle.get('facts') or {}
    record = (cycle.get('real_operations') or {}).get('precheck') or {}
    wait = cycle.get('bridge_wait') if isinstance(cycle.get('bridge_wait'), dict) else {}
    try:
        at, expires = engine._clock(now), engine._clock(cycle.get('expires_at'))
        last = engine._clock(wait['last_retry_at']) if wait.get('last_retry_at') else None
    except (TypeError, ValueError, AttributeError, OverflowError):
        return False
    creator = _creator(facts.get('tiktok_declarado'))
    if (cycle.get('mode') != 'real' or cycle.get('status') != 'open' or cycle.get('phase') != 'blocked'
            or not expires or at >= expires or not creator
            or state.get('human_control') or cycle.get('qualification_paused') or cycle.get('pending_profile_changes')
            or state.get('opt_out') or cycle.get('opt_out')
            or record.get('status') not in {'verification_pending', 'failed', 'outcome_unknown'}
            or record.get('cycle_id') != cycle.get('id') or record.get('creator') != creator
            or (cycle.get('real_operations') or {}).get('invite') or cycle.get('invite_retry')
            or (not forced and (wait.get('reason') or reason) not in BRIDGE_DOWN_REASONS)
            or int(wait.get('retries') or 0) >= (1 if forced and wait.get('reason') not in BRIDGE_DOWN_REASONS
                                                 else BRIDGE_RETRY_LIMIT)):
        return False
    if any(effect.get('type') == 'tiktok_operation' and effect.get('operation') == 'precheck'
           and effect.get('status') in {'pending', 'running'} for effect in (state.get('effects') or {}).values()):
        return False
    return last is None or at - last >= BRIDGE_RETRY_GAP


def bridge_retry_effect(state, now, *, reason=None, forced=False):
    """Nova consulta do perfil, sem mensagem ao lead; o resultado segue a conversa (convite etc.)."""
    if not bridge_retry_due(state, now, reason=reason, forced=forced):
        return None
    cycle, at = state['cycle'], engine._clock(now)
    for old in state['effects'].values():
        if (old.get('type') == 'tiktok_operation' and old.get('operation') == 'precheck'
                and old.get('cycle_id') == cycle['id'] and old.get('status') == 'outcome_unknown'):
            old['status'] = 'superseded_by_bridge_retry'
    effect = _effect(state, 'precheck', at)
    if not effect:
        return None
    effect['payload']['source'] = 'bridge_retry'
    state['effects'][effect['id']]['payload']['source'] = 'bridge_retry'
    wait = cycle.get('bridge_wait') if isinstance(cycle.get('bridge_wait'), dict) else {
        'since': cycle['real_operations']['precheck'].get('observed_at'), 'reason': reason}
    wait.update(retries=int(wait.get('retries') or 0) + 1, last_retry_at=engine._stamp(at))
    cycle['bridge_wait'] = wait
    state['revision'] += 1
    return effect


def invite_waiting(cycle):
    return isinstance(cycle, dict) and cycle.get('phase') == 'blocked' and isinstance(cycle.get('invite_wait'), dict)


def invite_retry_due(state, now, *, forced=False):
    """Convite autorizado que não chegou ao TikTok porque a ponte de Convites estava fora: pode reenviar agora?

    Só com a prova, em toda tentativa anterior, de que nenhum pedido chegou ao TikTok (nunca duplica um convite).
    """
    cycle = state.get('cycle') or {}
    facts = cycle.get('facts') or {}
    record = (cycle.get('real_operations') or {}).get('invite') or {}
    wait = cycle.get('invite_wait') if isinstance(cycle.get('invite_wait'), dict) else {}
    consent = cycle.get('invite_consent') or {}
    try:
        at, expires = engine._clock(now), engine._clock(cycle.get('expires_at'))
        last = engine._clock(wait['last_retry_at']) if wait.get('last_retry_at') else None
    except (TypeError, ValueError, AttributeError, OverflowError):
        return False
    creator = _creator(facts.get('tiktok_declarado'))
    attempts = [e for e in (state.get('effects') or {}).values() if e.get('type') == 'tiktok_operation'
                and e.get('operation') == 'invite' and e.get('cycle_id') == cycle.get('id') and e.get('creator') == creator]
    if (cycle.get('mode') != 'real' or cycle.get('status') != 'open' or cycle.get('phase') != 'blocked'
            or not expires or at >= expires or not creator
            or state.get('human_control') or cycle.get('qualification_paused') or cycle.get('pending_profile_changes')
            or state.get('opt_out') or cycle.get('opt_out') or cycle.get('invite_retry')
            or facts.get('consentimento_convite') is not True or consent.get('cycle_id') != cycle.get('id')
            or record.get('status') not in {'verification_pending', 'failed', 'outcome_unknown'}
            or record.get('cycle_id') != cycle.get('id') or record.get('creator') != creator
            or not attempts or not all(_invite_no_write(e.get('result_receipt')) for e in attempts)
            or (not forced and wait.get('reason') not in BRIDGE_DOWN_REASONS)
            or int(wait.get('retries') or 0) >= (1 if forced and not wait else INVITE_BRIDGE_RETRY_LIMIT)):
        return False
    if any(effect.get('type') == 'tiktok_operation' and effect.get('cycle_id') == cycle.get('id')
           and effect.get('operation') in {'precheck', 'invite', 'relationship'}
           and effect.get('status') in {'pending', 'running'} for effect in (state.get('effects') or {}).values()):
        return False
    return last is None or at - last >= BRIDGE_RETRY_GAP


def invite_retry_effect(state, now, *, forced=False):
    """Nova validação do perfil e, se continuar elegível, o reenvio do convite, tudo sem mensagem ao lead."""
    if not invite_retry_due(state, now, forced=forced):
        return None
    cycle, at = state['cycle'], engine._clock(now)
    for old in state['effects'].values():
        if (old.get('type') == 'tiktok_operation' and old.get('operation') == 'precheck'
                and old.get('cycle_id') == cycle['id'] and old.get('status') == 'outcome_unknown'):
            old['status'] = 'superseded_by_bridge_retry'
    effect = _effect(state, 'precheck', at)
    if not effect:
        return None
    effect['payload']['source'] = 'invite_bridge_retry'
    state['effects'][effect['id']]['payload']['source'] = 'invite_bridge_retry'
    record = (cycle.get('real_operations') or {}).get('invite') or {}
    wait = cycle.get('invite_wait') if isinstance(cycle.get('invite_wait'), dict) else {
        'since': record.get('observed_at'), 'reason': None}
    wait.update(retries=int(wait.get('retries') or 0) + 1, last_retry_at=engine._stamp(at))
    cycle['invite_wait'] = wait
    cycle['invite_retry'] = {'at': engine._stamp(at), 'precheck_effect_id': effect['id'], 'bridge': True,
                             'previous_invite_job_id': record.get('job_id')}
    state['revision'] += 1
    return effect


# Release 42 (02/11, aprovada pelo usuário): a lista de vínculos da ponte de Agenciamento como prova.
# 1. Convite com resultado incerto e @ ausente numa leitura completa e recente da lista: reenvia uma vez.
# 2. Convite pendente: a Bia lê a lista sozinha (15 min, 2 h, 1 dia) e manda o cadastro quando virar vínculo.
# 3. "Não aparece" com o convite pendente: o passo a passo (texto 3).
# Leituras só das 8h às 21h (Brasília): o resultado vira mensagem, então à noite nada é lido e tudo espera as 8h.
LIST_PROOF_STATUSES = frozenset({'verification_pending', 'outcome_unknown'})
LIST_PROOF_READ_LIMIT = 3
LIST_PROOF_MIN_DELAY = timedelta(minutes=5)  # 43: a lista é lida 5 min depois do envio
LIST_PROOF_MAX_AGE_SECONDS = 1800
AGENCY_READ_GAP = timedelta(minutes=15)
TRACKING_HORIZON = timedelta(days=7)
TRACKED_INVITE = frozenset({'sent', 'pending', 'pending_verification'})
AGENCY_SOURCES = frozenset({'invite_list_proof', 'invite_tracking'})
READ_MARGIN = timedelta(minutes=15)


def tracking_interval(age):
    """Menos de 2 h: a cada 15 min; de 2 a 48 h: a cada 2 h; de 48 h a 7 dias: 1 vez por dia."""
    if age < timedelta(hours=2):
        return timedelta(minutes=15)
    if age < timedelta(hours=48):
        return timedelta(hours=2)
    return timedelta(days=1)


def resend_count(state, creator):
    entry = (state.get('invite_resends') or {}).get(creator)
    return int(entry.get('count') or 1) if isinstance(entry, dict) else (1 if entry else 0)


def resend_used(state, creator, *, unlanded=False):
    """1 reenvio por lead (42). Release 43: um 2º só quando a lista prova que o 1º não chegou ao TikTok."""
    return resend_count(state, creator) >= (INVITE_RESEND_LIMIT if unlanded else 1)


INVITE_RESEND_LIMIT = 2
STALE_OPERATION = timedelta(minutes=30)


def _stale(effect, at):
    """Leitura parada há mais de 30 min (o trabalho dela acabou sem aplicar o resultado). Convite nunca é velho."""
    if effect.get('operation') not in {'precheck', 'relationship'} or effect.get('status') not in {'pending', 'running'}:
        return False
    try:
        start = max(engine._clock(value) for value in (effect.get('created_at'), (effect.get('payload') or {}).get('not_before'))
                    if value)
    except (TypeError, ValueError, OverflowError):
        return False
    return at - start > STALE_OPERATION


def _list_proof(state, at):
    """A leitura que pediu o reenvio: @ ausente, lista completa e recente, lida depois da última tentativa."""
    cycle = state['cycle']
    creator = _creator(cycle['facts'].get('tiktok_declarado'))
    mark = cycle.get('invite_list_proof') or {}
    record = (cycle.get('real_operations') or {}).get('relationship') or {}
    evidence = record.get('evidence') if isinstance(record.get('evidence'), dict) else {}
    if not (mark.get('result') == 'not_found' and mark.get('effect_id') == record.get('job_id')
            and record.get('status') == 'not_found' and record.get('confirmed') is True
            and record.get('cycle_id') == cycle['id'] and record.get('creator') == creator
            and evidence.get('complete') is True and evidence.get('fresh') is True):
        return False
    try:
        observed = engine._clock(record['observed_at'])
        if not 0 <= (engine._clock(at) - observed).total_seconds() <= LIST_PROOF_MAX_AGE_SECONDS:
            return False
        return all(engine._clock(attempt['created_at']) + LIST_PROOF_MIN_DELAY <= observed
                   for attempt in _invite_attempts(state))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _agency_gate(state, at):
    cycle = state.get('cycle') or {}
    try:
        expires = engine._clock(cycle.get('expires_at'))
    except (TypeError, ValueError, OverflowError):
        return False
    from retomada import send_hour
    return bool(cycle.get('mode') == 'real' and cycle.get('status') == 'open'
                and cycle.get('relationship_check_in_form') is True
                and expires and at + READ_MARGIN < expires and send_hour(at) and send_hour(at + READ_MARGIN)
                and _creator((cycle.get('facts') or {}).get('tiktok_declarado'))
                and not (state.get('human_control') or cycle.get('qualification_paused')
                         or cycle.get('pending_profile_changes') or state.get('opt_out') or cycle.get('opt_out')
                         or cycle.get('invite_retry'))
                and state.get('cadastro_situacao') != 'confirmado'
                and not any(effect.get('type') == 'tiktok_operation' and effect.get('cycle_id') == cycle.get('id')
                            and effect.get('operation') in {'precheck', 'invite', 'relationship'}
                            and effect.get('status') in {'pending', 'running'} and not _stale(effect, at)
                            for effect in (state.get('effects') or {}).values()))


def list_proof_due(state, now):
    """Convite com resultado incerto, sem prova de que nada chegou ao TikTok: ler a lista de vínculos?"""
    at = engine._clock(now)
    if not _agency_gate(state, at):
        return False
    cycle = state['cycle']
    creator = _creator(cycle['facts'].get('tiktok_declarado'))
    record = (cycle.get('real_operations') or {}).get('invite') or {}
    consent = cycle.get('invite_consent') or {}
    mark = cycle.get('invite_list_proof') or {}
    attempts = _invite_attempts(state)
    if (cycle.get('phase') not in {'blocked', 'await_acceptance', 'checking_acceptance'}
            or record.get('status') not in LIST_PROOF_STATUSES
            or record.get('cycle_id') != cycle['id'] or record.get('creator') != creator or not attempts
            or cycle['facts'].get('consentimento_convite') is not True or consent.get('cycle_id') != cycle['id']
            or resend_used(state, creator) or mark.get('result')
            or int(mark.get('reads') or 0) >= LIST_PROOF_READ_LIMIT or invite_retry_due(state, at)):
        return False
    try:
        last = max(engine._clock(attempt['created_at']) for attempt in attempts)
        previous = engine._clock(mark['last_read_at']) if mark.get('last_read_at') else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return at - last >= LIST_PROOF_MIN_DELAY and (previous is None or at - previous >= AGENCY_READ_GAP)


def _tracking_since(state):
    cycle = state.get('cycle') or {}
    mark = cycle.get('invite_tracking') or {}

    if mark.get('stopped') and not (mark.get('stopped') == 'not_found' and _invite_unlanded(cycle)):
        return None
    operations = cycle.get('real_operations') or {}
    invite, relationship = operations.get('invite') or {}, operations.get('relationship') or {}
    value = (mark.get('since') if mark.get('since') else
             invite.get('observed_at') if (invite.get('status') in TRACKED_INVITE | {'linked'}
                                           and invite.get('cycle_id') == cycle.get('id')) else
             relationship.get('observed_at') if (relationship.get('status') in {'pending', 'linked'}
                                                 and relationship.get('confirmed') is True
                                                 and relationship.get('cycle_id') == cycle.get('id')) else None)
    try:
        return engine._clock(value) if value else None
    except (TypeError, ValueError, OverflowError):
        return None


def tracking_due(state, now):
    """Convite pendente: a próxima leitura da lista já venceu?"""
    at = engine._clock(now)
    if not _agency_gate(state, at):
        return False
    cycle = state['cycle']
    since = _tracking_since(state)

    if (not since or cycle.get('phase') not in {'await_acceptance', 'checking_acceptance', 'form', 'blocked'}
            or not timedelta(0) <= at - since < TRACKING_HORIZON):
        return False
    if _linked(cycle) and not linked_notice_missing(cycle):
        return False
    mark = cycle.get('invite_tracking') or {}
    try:
        reads = [engine._clock(value) for value in (mark.get('last_read_at'), (cycle.get('acceptance_check') or {}).get('at'))
                 if value]
    except (TypeError, ValueError, OverflowError):
        return False
    return at - max(reads + [since]) >= tracking_interval(at - since)


def linked_notice_missing(cycle):
    """Private incident details omitted from this review baseline."""
    notice = cycle.get('linked_notice')
    if not isinstance(notice, dict):
        return True
    return notice.get('delivered') is False and int(notice.get('attempts') or 0) < 2


def _mark_linked_notice(cycle, at):
    previous = cycle.get('linked_notice') if isinstance(cycle.get('linked_notice'), dict) else {}
    cycle['linked_notice'] = {'at': engine._stamp(at), 'delivered': None, 'attempts': int(previous.get('attempts') or 0) + 1}


def agency_read_due(state, now):
    return 'invite_list_proof' if list_proof_due(state, now) else 'invite_tracking' if tracking_due(state, now) else None


def agency_read_effect(state, now):
    """Uma leitura da lista de vínculos, sem mensagem ao lead; o resultado segue em _settle_agency_read."""
    source = agency_read_due(state, now)
    if not source:
        return None
    cycle, at = state['cycle'], engine._clock(now)
    since = _tracking_since(state)
    for old in state['effects'].values():
        if old.get('type') == 'tiktok_operation' and old.get('cycle_id') == cycle['id'] and _stale(old, at):
            old['status'] = 'superseded_stale'
    effect = _effect(state, 'relationship', at)
    if not effect:
        return None
    for item in (effect, state['effects'][effect['id']]):
        item['payload']['source'] = source
    mark = cycle.get(source) if isinstance(cycle.get(source), dict) else {}
    if source == 'invite_tracking' and mark.get('stopped') == 'linked':
        mark.pop('stopped')
    if source == 'invite_tracking' and not mark.get('since'):
        mark['since'] = engine._stamp(since)
    mark.update(reads=int(mark.get('reads') or 0) + 1, last_read_at=engine._stamp(at), effect_id=effect['id'])
    cycle[source] = mark
    state['revision'] += 1
    return effect


def _start_tracking(cycle, at):
    cycle['invite_tracking'] = {'since': engine._stamp(at), 'reads': 0}


def _accepted_reply(state, at):
    """Texto 2 com o botão Fazer cadastro (o link vira o botão no WhatsApp)."""
    cycle = state['cycle']
    cycle['phase'] = 'form'
    cycle['form_url'] = PUBLIC_FORM_URL
    cycle.pop('acceptance_check', None)
    cycle.pop('invite_verify', None)
    _mark_linked_notice(cycle, at)
    return _finish(state, at, reply=conversao.INVITE_ACCEPTED + '\n\n' + PUBLIC_FORM_URL, buttons=[],
                   force_form_button=True, exact=True)


def _list_proof_resend(state, at, policy, *, reply=None):
    """Reenvio depois da prova pela lista: valida o perfil de novo se preciso, sem mensagem (ou com ``reply``)."""
    cycle = state['cycle']
    unlanded = (cycle.get('invite_list_proof') or {}).get('source') == 'invite_tracking'
    proof = 'unlanded' if unlanded else True

    def done(effect, phase):
        cycle['phase'] = phase
        if reply:
            return _finish(state, at, reply=reply, effects=[effect], buttons=[])
        state['revision'] += 1
        return engine._result(state, effects=[effect], operation_settled=True)
    job = _effect(state, 'invite', at, policy=policy, list_proof=proof)
    if job:
        return done(job, 'inviting')
    creator = _creator(cycle['facts'].get('tiktok_declarado'))
    if not precheck_proven(state, now=at) and not resend_used(state, creator, unlanded=unlanded) and _list_proof(state, at):
        check = _effect(state, 'precheck', at)
        if check:
            for item in (check, state['effects'][check['id']]):
                item['payload']['source'] = 'invite_list_proof'
            return done(check, 'checking')
    return None


def _recover_absent_invite(state, at, effect, policy):
    """Only fresh, complete absence after the last attempt authorizes bounded recovery."""
    cycle = state['cycle']
    previous = cycle.get('invite_list_proof')
    cycle['invite_list_proof'] = {'result': 'not_found', 'effect_id': effect['id'], 'source': 'invite_tracking'}
    if not _list_proof(state, at):
        if previous is None:
            cycle.pop('invite_list_proof', None)
        else:
            cycle['invite_list_proof'] = previous
        return None
    cycle.pop('acceptance_check', None)
    cycle.pop('invite_verify', None)
    for other in state['effects'].values():
        if (other.get('cycle_id') == cycle['id'] and other.get('operation') == 'relationship'
                and other.get('status') == 'pending' and other.get('id') != effect['id']
                and (other.get('payload') or {}).get('source') == 'chat_acceptance'):
            other['status'] = 'superseded'
    told = (cycle.get('invite_unlanded') or {}).get('told')
    cycle['invite_unlanded'] = {'at': engine._stamp(at), 'told': True}
    recovered = _list_proof_resend(state, at, policy, reply=None if told else conversao.INVITE_NOT_LANDED)
    if recovered is not None:
        return recovered
    cycle.pop('invite_list_proof', None)
    cycle['phase'] = 'blocked'
    if not told:
        return _finish(state, at, reply=conversao.INVITE_STILL_MISSING, buttons=[])
    state['revision'] += 1
    return engine._result(state, operation_settled=True)


def _settle_agency_read(state, at, effect, result, policy):
    cycle = state['cycle']
    source = effect['payload']['source']
    status = result['status']
    if status == 'linked':
        if state.get('cadastro_situacao') == 'confirmado':
            state['revision'] += 1
            return engine._result(state, operation_settled=True)
        return _accepted_reply(state, at)
    if source == 'invite_list_proof':
        mark = cycle.setdefault('invite_list_proof', {})
        if status == 'pending':
            # O convite chegou ao TikTok: nunca reenviar. Passo a passo para aceitar e acompanhamento.
            mark.update(result='pending', effect_id=effect['id'])
            cycle['phase'] = 'await_acceptance'
            _start_tracking(cycle, at)
            return _finish(state, at, reply=conversao.INVITE_STEPS, buttons=['Já aceitei'])
        evidence = result.get('evidence') if isinstance(result.get('evidence'), dict) else {}
        if status == 'not_found' and evidence.get('complete') is True and evidence.get('fresh') is True:
            mark.update(result='not_found', effect_id=effect['id'])
            resent = _list_proof_resend(state, at, policy)
            if resent is not None:
                return resent
        cycle['phase'] = 'blocked'
    elif status == 'pending' and cycle.pop('invite_verify', None):

        return _finish(state, at, reply=conversao.invite_sent_now(_first_name(cycle)), buttons=[], exact=True)
    elif status == 'not_found' and _invite_unlanded(cycle):
        recovered = _recover_absent_invite(state, at, effect, policy)
        if recovered is not None:
            return recovered
    elif status == 'not_found':
        # O convite pendente sumiu da lista: para de acompanhar; se o lead avisar, a Bia confere na hora.
        cycle.setdefault('invite_tracking', {})['stopped'] = 'not_found'
    state['revision'] += 1
    return engine._result(state, operation_settled=True)


def _invite_unlanded(cycle):
    record = (cycle.get('real_operations') or {}).get('invite') or {}
    return (record.get('status') in {'sent', 'pending_verification', 'verification_pending', 'outcome_unknown'}
            and record.get('cycle_id') == cycle.get('id'))


def _confirming(state, at, effect):
    """Envio sem a confirmação da lista: "Tô confirmando…" e a leitura da lista em 5 min (tabela 5b)."""
    cycle = state['cycle']
    cycle['phase'] = 'await_acceptance'
    cycle['invite_verify'] = {'at': engine._stamp(at), 'effect_id': effect['id']}
    _start_tracking(cycle, at)
    read = _effect(state, 'relationship', at)
    effects = []
    if read:
        payload = {'source': 'invite_tracking', 'not_before': engine._stamp(at + LIST_PROOF_MIN_DELAY)}
        for item in (read, state['effects'][read['id']]):
            item['payload'].update(payload)
        cycle['invite_tracking'].update(reads=1, last_read_at=payload['not_before'], effect_id=read['id'])
        effects.append(read)
    return _finish(state, at, reply=conversao.INVITE_CONFIRMING, effects=effects, buttons=[], exact=True)


def _close_ineligible(state, at):
    cycle = state['cycle']
    cycle.update(status='closed', reason='profile_ineligible', closed_at=engine._stamp(at), phase='blocked')
    for item in state['effects'].values():
        if item.get('cycle_id') == cycle['id'] and item.get('status') == 'pending':
            item['status'] = 'cancelled'
    return _finish(state, at, reply=conversao.PROFILE_INELIGIBLE, buttons=[], exact=True)


def _settle_invite_code(state, at, effect, status, result, record, policy):
    """Resultado do convite pela tabela 5b; None segue o caminho de antes (sent/pending e as tentativas da 41)."""
    cycle = state['cycle']
    reason = result.get('reason')
    if status == 'linked':
        return _accepted_reply(state, at)
    if status == 'ineligible':
        return _close_ineligible(state, at)
    if status in {'pending_verification', 'outcome_unknown'} and not (_invite_no_write(record) and reason in BRIDGE_DOWN_REASONS):
        return _confirming(state, at, effect)
    if status == 'verification_pending':
        if _invite_no_write(record) and (reason in BRIDGE_DOWN_REASONS or _invite_retry_possible(state)):
            return None  # 41: reenvio da reconferência ou nova tentativa sem duplicar
        if (result.get('evidence') or {}).get('shop_status') == 'unknown':
            cycle['phase'] = 'blocked'
            cycle['shop_unknown'] = {'at': engine._stamp(at)}
            return _finish(state, at, reply=conversao.SHOP_UNKNOWN, buttons=[])
        # Ponte fora antes do envio, sem a prova de que nada chegou: a prova da lista (42) decide o reenvio.
        cycle['phase'] = 'blocked'
        if isinstance(cycle.get('invite_wait'), dict):
            state['revision'] += 1
            return engine._result(state, operation_settled=True)
        cycle['invite_wait'] = {'since': engine._stamp(at), 'reason': reason, 'retries': 0}
        return _finish(state, at, reply=conversao.INVITE_WAIT, buttons=[])
    if status == 'failed':
        if _invite_no_write(record) and reason in BRIDGE_DOWN_REASONS:
            return None
        if len(_invite_attempts(state)) == 1 and not cycle.get('invite_failed_retry'):
            cycle['invite_failed_retry'] = {'at': engine._stamp(at), 'reason': reason}
            check = _schedule_invite_retry(state, at, delay=INVITE_FAILED_RETRY_SECONDS)
            if check:
                return _finish(state, at, reply=conversao.INVITE_RETRYING, effects=[check], buttons=[])
        # 2ª falha: o atendimento fica em blocked e o vigia do Cadastro avisa a equipe em 30 min.
        cycle.update(phase='blocked', block_reason='invite_failed_twice')
        cycle['team_alert'] = {'at': engine._stamp(at), 'reason': 'invite_failed_twice', 'last_reason': reason}
        return _finish(state, at, reply=conversao.INVITE_FAILED_TEAM, buttons=[])
    return None


def _settle_list_proof_invite(state, at, effect, status):
    """Resultado do reenvio único: texto 1 e acompanhamento; falha fica em silêncio (nada de novo reenvio)."""
    cycle = state['cycle']
    if status == 'linked':
        return _accepted_reply(state, at)
    if status in {'pending_verification', 'outcome_unknown'}:
        # Release 43: a ponte aceitou o pedido mas a lista ainda não mostra o convite. Nada de "enviado agora".
        return _confirming(state, at, effect)
    if status == 'ineligible':
        return _close_ineligible(state, at)
    if status in TRACKED_INVITE:
        cycle['phase'] = 'await_acceptance'
        _start_tracking(cycle, at)
        if status == 'pending':
            # A conferência antes do envio já achou um convite pendente: nada foi enviado agora.
            return _finish(state, at, reply=conversao.INVITE_STEPS, buttons=['Já aceitei'])
        return _finish(state, at, reply=conversao.invite_sent_now(_first_name(cycle)), buttons=[], exact=True)
    cycle['phase'] = 'blocked'
    if status == 'failed':
        # Release 43 (tabela 5b): o reenvio também falhou; o atendimento fica em blocked e o vigia avisa a equipe.
        cycle['block_reason'] = 'invite_failed_twice'
        cycle['team_alert'] = {'at': engine._stamp(at), 'reason': 'invite_failed_twice'}
        return _finish(state, at, reply=conversao.INVITE_FAILED_TEAM, buttons=[])
    if not isinstance(cycle.get('invite_wait'), dict):
        # Ponte fora no reenvio: o aviso da tabela, uma vez; a prova da lista segue quando a ponte voltar.
        cycle['invite_wait'] = {'since': engine._stamp(at), 'reason': None, 'retries': 0}
        return _finish(state, at, reply=conversao.INVITE_WAIT, buttons=[])
    state['revision'] += 1
    return engine._result(state, operation_settled=True)


def resolve_tiktok_result(session, effect_id, result, *, now=None, operation_policy=None):
    """Apply a matching durable worker result once, without renewing the window."""
    state, at = engine._state(session), engine._clock(now)
    engine._expire(state, at)
    cycle, effect = state.get("cycle"), state["effects"].get(effect_id)
    if (not cycle or cycle.get("mode") != "real" or cycle["status"] != "open" or not effect
            or effect.get("type") != "tiktok_operation" or effect.get("status") not in {"pending", "running"}
            or effect.get("cycle_id") != cycle["id"] or effect.get("creator") != _creator(cycle["facts"].get("tiktok_declarado"))):
        return engine._result(state, ignored=True, reason="stale_or_completed_operation")
    operation = effect["operation"]
    form_mode = cycle.get('relationship_check_in_form') is True
    source = (effect.get('payload') or {}).get('source')
    if form_mode and operation == 'relationship' and source not in {'form', 'chat_acceptance'} | AGENCY_SOURCES:
        return engine._result(state, ignored=True, reason='relationship_requires_form_source')
    if (not isinstance(result, dict) or result.get("operation") != operation
            or _result_creator(result.get("creator")) != effect["creator"]
            or result.get("status") not in _STATUS[operation]):
        return engine._result(state, ignored=True, reason="operation_result_mismatch")
    try:
        observed = engine._clock(result.get("observed_at"))
        age = (at - observed).total_seconds()
        valid_time = isinstance(result.get("observed_at"), str) and 0 <= age <= 900
    except (TypeError, ValueError, OverflowError):
        valid_time = False
    success = result["status"] in {"eligible", "ineligible", "sent", "linked", "pending", "not_found", "observed"}
    proof = isinstance(result.get("evidence"), dict) and bool(result["evidence"])
    if success and (not valid_time or not proof or (operation != "lookup" and result.get("confirmed") is not True)):
        return engine._result(state, ignored=True, reason="operation_evidence_missing_or_stale")
    status = result["status"]
    invite_observed = bool(cycle.get("real_operations", {}).get("invite"))
    effect.update(status=("pending" if not form_mode and operation == "relationship" and (status == "pending" or (status == "not_found" and invite_observed)) else
                          "outcome_unknown" if status == "outcome_unknown" else "done"),
                  resolved_at=engine._stamp(at))
    record = {key: deepcopy(result[key]) for key in ("status", "operation", "creator", "observed_at", "evidence", "confirmed", "reason") if key in result}
    record.update(job_id=effect_id, cycle_id=cycle["id"], creator=effect["creator"])
    cycle.setdefault("real_operations", {})[operation] = record
    if operation == "invite":
        effect["result_receipt"] = deepcopy(record)
    effects, reply = [], ""
    retry = cycle.get("invite_retry") or {}
    if form_mode and operation == 'relationship' and source in AGENCY_SOURCES:
        return _settle_agency_read(state, at, effect, result, operation_policy)
    if form_mode and operation == 'precheck' and source == 'invite_list_proof':
        if status == 'eligible':
            resent = _list_proof_resend(state, at, operation_policy)
            if resent is not None:
                return resent
        if status in {'verification_pending', 'failed', 'outcome_unknown'} and isinstance(cycle.get('invite_list_proof'), dict):
            # A ponte de Pré-validação falhou no meio: a prova vence e a lista é lida de novo (até 3 leituras).
            cycle['invite_list_proof'].pop('result', None)
        cycle['phase'] = 'blocked'
        state['revision'] += 1
        return engine._result(state, operation_settled=True)
    if form_mode and operation == 'invite' and (effect.get('payload') or {}).get('list_proof'):
        return _settle_list_proof_invite(state, at, effect, status)
    if form_mode and operation == 'invite' and not retry.get('bridge'):
        coded = _settle_invite_code(state, at, effect, status, result, record, operation_policy)
        if coded is not None:
            return coded
    if form_mode and operation == 'precheck' and status == 'ineligible' and source not in {'invite_bridge_retry'}:
        return _close_ineligible(state, at)
    if operation == "precheck" and retry.get("precheck_effect_id") == effect_id and not retry.get("invite_effect_id"):
        retry["precheck_status"] = status
        if status == "eligible":
            for old in _invite_attempts(state):
                if old.get("status") == "outcome_unknown":
                    old["status"] = "superseded_by_retry"
            bridge = retry.get("bridge") is True
            job = _effect(state, "invite", at, policy=operation_policy,
                          retry=len(_invite_attempts(state)) if bridge else True)
            if job:
                retry["invite_effect_id"] = job["id"]
                cycle["phase"] = "inviting"
                if bridge or cycle.get('invite_failed_retry'):
                    # Reenvio da reconferência: o lead já sabe que eu envio sozinha; a próxima mensagem é o resultado.
                    state["revision"] += 1
                    return engine._result(state, effects=[job], operation_settled=True)
                return _finish(state, at, reply="Vou reenviar seu convite agora, conferindo antes para não duplicar. 🔎", effects=[job])
    if (operation == "invite" and status in {"outcome_unknown", "verification_pending", "failed"}
            and _invite_retry_possible(state)):
        check = _schedule_invite_retry(state, at, delay=INVITE_RETRY_DELAY_SECONDS)
        if check:
            return _finish(state, at, effects=[check],
                           reply="O convite ainda não chegou ao TikTok. Vou tentar de novo em alguns minutos, sem duplicar o envio.")
    if (operation == 'invite' and status in {'outcome_unknown', 'verification_pending', 'failed'}
            and result.get('reason') in BRIDGE_DOWN_REASONS and _invite_no_write(record)):

        # A autorização fica anotada e a reconferência envia sozinha quando a ponte voltar.
        cycle['phase'] = 'blocked'
        cycle.pop('invite_retry', None)
        wait = cycle.get('invite_wait')
        if isinstance(wait, dict):
            wait['reason'] = result['reason']
            state['revision'] += 1
            return engine._result(state, operation_settled=True)
        cycle['invite_wait'] = {'since': engine._stamp(at), 'reason': result['reason'], 'retries': 0}
        return _finish(state, at, reply=conversao.INVITE_WAIT, buttons=[])
    if (operation == 'precheck' and source == 'invite_bridge_retry'
            and status in {'verification_pending', 'failed', 'outcome_unknown'}):
        # A nova validação antes do reenvio falhou: segue esperando, sem mensagem.
        cycle['phase'] = 'blocked'
        cycle.pop('invite_retry', None)
        if isinstance(cycle.get('invite_wait'), dict) and result.get('reason') in BRIDGE_DOWN_REASONS:
            cycle['invite_wait']['reason'] = result['reason']
        state['revision'] += 1
        return engine._result(state, operation_settled=True)
    if form_mode and operation == 'relationship' and source == 'chat_acceptance':
        return _settle_acceptance_check(state, at, effect, status, operation_policy)
    if form_mode and operation == 'relationship':
        cycle['phase'] = 'form'
        state['revision'] += 1
        return engine._result(state, operation_settled=True, form_relationship_result=True)
    bridge_retry = operation == 'precheck' and (effect.get('payload') or {}).get('source') == 'bridge_retry'
    if operation == 'precheck' and status in {'eligible', 'ineligible'}:
        cycle.pop('bridge_wait', None)
    if (operation == 'precheck' and status in {'verification_pending', 'failed', 'outcome_unknown'}
            and (result.get('reason') in BRIDGE_DOWN_REASONS or (form_mode and status != 'verification_pending'))
            and not relationship_proven(state, now=at)):
        cycle['phase'] = 'blocked'
        wait = cycle.get('bridge_wait')
        if bridge_retry and isinstance(wait, dict):
            # A ponte caiu de novo durante a reconferência: o lead já sabe que eu aviso. Nada de repetir.
            wait['reason'] = result['reason']
            state['revision'] += 1
            return engine._result(state, operation_settled=True)
        cycle['bridge_wait'] = {'since': engine._stamp(at), 'reason': result['reason'], 'retries': 0}
        return _finish(state, at, reply=_BRIDGE_WAIT, buttons=[])
    # A autorização dada antes da nova validação vale também quando a ponte caiu no meio e a reconferência repetiu a consulta.
    refresh = (cycle.pop('consent_refresh', None) if operation == 'precheck' and status in {'eligible', 'ineligible'}
               else None)
    if (form_mode and operation == 'precheck' and status == 'eligible' and isinstance(refresh, dict)
            and cycle['facts'].get('consentimento_convite') is True):
        job = _effect(state, 'invite', at, policy=operation_policy)
        if job:
            # O lead já ouviu "Tô enviando o convite": o envio segue em silêncio.
            cycle['phase'] = 'inviting'
            state['revision'] += 1
            return engine._result(state, effects=[job], operation_settled=True)
    if form_mode and operation == 'precheck' and status == 'eligible':
        cycle['phase'] = 'consent_real'
        prompt = _consent_prompt(cycle, operation_policy)
        sent = _auto_invite(state, at, operation_policy, prefix=_BRIDGE_BACK + '\n\n' if bridge_retry else '')
        if sent is not None:
            return sent
        return _finish(state, at, reply=(_BRIDGE_BACK + '\n\n' + prompt) if bridge_retry else prompt)
    if form_mode and operation == 'invite' and status in {'sent', 'pending', 'pending_verification', 'linked'}:
        cycle.pop('invite_wait', None)
        handed_off = _form_after_invite(state, at)
        if handed_off is not None:
            return handed_off
        cycle['phase'] = 'blocked'
        return _finish(state, at, reply='Ainda não há confirmação suficiente do envio. _Não vou repetir o convite._', buttons=[])
    if operation == "lookup":
        # Lookup enrichment cannot advance another operation's phase or claim
        # exact GMV without the provider's currency/period evidence.
        state["revision"] += 1
        return engine._result(state, operation_settled=True)
    if operation == "precheck" and relationship_proven(state, now=at):
        # The independent reads can finish in either order. A late profile
        # result cannot undo an already evidenced existing linkage/form.
        state["revision"] += 1
        return engine._result(state, operation_settled=True)
    if status in {"verification_pending", "failed", "outcome_unknown"}:
        cycle["phase"] = "blocked"
        if status == "verification_pending" and result.get("reason") == "shop_unknown":
            cycle["shop_unknown"] = {"at": engine._stamp(at)}
        reply = (conversao.SHOP_UNKNOWN if status == "verification_pending" and result.get("reason") == "shop_unknown" else
                 "A consulta precisa de uma verificação de segurança no TikTok. Vou aguardar essa verificação antes de avançar."
                 if status == "verification_pending" else
                 "O TikTok ainda não confirmou o resultado. Vou manter esta etapa pendente e conferir o que aconteceu antes de tentar qualquer novo envio.")
    elif operation == "precheck":
        if status == "eligible":
            relationship = cycle.get("real_operations", {}).get("relationship") or {}
            if _operation_proven(state, "relationship", "not_found", now=at):
                cycle["phase"] = "consent_real"
                reply = _consent_prompt(cycle, operation_policy)
            elif relationship.get("status") == "pending" and relationship.get("confirmed") is True:
                # The earlier relationship result already told the lead where
                # to accept; no duplicate query or stage regression is needed.
                state["revision"] += 1
                return engine._result(state, operation_settled=True)
            else:
                cycle["phase"] = "checking"
                job = _effect(state, "relationship", at)
                effects = [job] if job else []
                reply = "Seu perfil passou pela validação inicial. Estou conferindo o vínculo atual para te orientar no próximo passo. 🔎"
        elif status == "ineligible":
            cycle["phase"] = "blocked"
            reply = "A consulta identificou uma condição que impede seguir com o convite agora. Vou manter essa pendência registrada para a conferência da Amplify."
        if bridge_retry and reply and status == "eligible":
            reply = _BRIDGE_BACK + "\n\n" + reply
        elif bridge_retry and reply:
            reply = "Conferi seu perfil. " + reply
    elif operation == "invite":
        if status == "ineligible":
            cycle["phase"] = "blocked"
            reply = ("A nova conferência do TikTok identificou que seu perfil não está elegível para o convite neste momento. "
                     "Nenhum convite foi enviado. Confira se o TikTok Shop Creator está ativo; vou manter essa pendência registrada.")
        elif status == "sent":
            cycle["phase"] = "await_acceptance"
            reply = "O TikTok confirmou o envio do convite para " + effect["creator"] + ". 😊\n\n" + PROMPTS["await_acceptance"]
        elif status == "pending_verification":
            cycle["phase"] = "await_acceptance"
            reply = "A solicitação foi recebida, mas o envio ainda precisa de conferência. Vou verificar o vínculo sem repetir o convite."
        elif status == "linked":
            cycle["phase"] = "checking_acceptance"
            job = _effect(state, "relationship", at)
            effects = [job] if job else []
            reply = "A conferência encontrou um vínculo para este perfil. Vou validar esse retorno antes de liberar o cadastro."
        elif status == "pending":
            cycle["phase"] = "await_acceptance"
            reply = "O TikTok já mostra uma solicitação pendente para este perfil; não vou enviar outro convite.\n\n" + _ACCEPT_INVITE_GUIDE
    elif operation == "relationship":
        if status == "linked":
            already_registered = state.get("cadastro_situacao") == "confirmado"
            cycle["phase"] = "blocked" if already_registered else "form"
            if already_registered:
                cycle["block_reason"] = "existing_registration_requires_confirmation"
                reply = ("Seu vínculo com a Amplify foi confirmado no TikTok e seu cadastro já consta concluído. ✅\n\n"
                         "Você não precisa preencher uma nova inscrição. Se precisar alterar algum dado, "
                         "a mudança deverá ser conferida e confirmada antes da atualização.")
            elif not cycle.get("form_effect_id"):
                form = engine._effect(state, cycle, "generate_form_link", {
                    "cycle_id": cycle["id"], "facts": deepcopy(cycle["facts"]), "verification_mode": "real",
                    "relationship_job_id": effect_id, "relationship_observed_at": result["observed_at"],
                })
                cycle["form_effect_id"] = form["id"]
                effects.append(deepcopy(form))
            if not already_registered:
                reply = "O TikTok confirmou seu vínculo com a Amplify. ✅\n\nVou preparar o formulário para você conferir e completar seu cadastro."
        elif status == "pending":
            cycle["phase"] = "await_acceptance"
            reply = ("O vínculo ainda aparece pendente no TikTok. Se você já aceitou, vou continuar conferindo e te aviso aqui.\n\n"
                     "Se ainda faltar aceitar: " + _ACCEPT_INVITE_GUIDE)
        elif status == "not_found":
            sent = (cycle.get("real_operations") or {}).get("invite")
            if sent or cycle.get("facts", {}).get("aceite_declarado"):
                cycle["phase"] = "await_acceptance"
                reply = "Ainda não encontrei um vínculo confirmado para este @. Vou manter o cadastro pendente até o TikTok confirmar o aceite."
            else:
                if precheck_proven(state, now=at):
                    cycle["phase"] = "consent_real"
                    reply = _consent_prompt(cycle, operation_policy)
                elif (cycle.get("real_operations", {}).get("precheck") or {}).get("status") in {
                        "ineligible", "verification_pending", "failed", "outcome_unknown"}:
                    cycle["phase"] = "blocked"
                    reply = "A validação do perfil ainda não permite seguir com o convite. Vou manter essa pendência registrada, sem enviar um convite."
                else:
                    cycle["phase"] = "checking"
                    fresh_check = _effect(state, "precheck", at)
                    effects = [fresh_check] if fresh_check else []
                    reply = "Vou atualizar a validação do perfil antes de apresentar o convite real."
    if not form_mode and operation == "invite" and status in {"sent", "pending", "pending_verification", "outcome_unknown"}:
        # Poll the read-only relationship, never retry the invitation write.
        followup = _effect(state, "relationship", at)
        if followup:
            effects.append(followup)
    return _finish(state, at, reply=reply, effects=effects)
