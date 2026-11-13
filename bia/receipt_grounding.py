"""Render operational explanations from approved rules and bound receipts.

The four operational subjects are a closed business boundary, not a list of
verbs that supposedly catches every way a model can claim success. Free model
sentences in that boundary are never evidence. This module performs no I/O,
changes no state and creates no permission or action. The journey owns the
single next question, buttons and effects.
"""
from __future__ import annotations

import re


_SUBJECTS = {
    'invite': r'\bconvit\w*\b',
    'relationship': r'\bv[ií]ncul\w*\b|\bagenciad[oa]s?\b',
    'registration': r'\bcadastr\w*\b|\bformul[aá]ri\w*\b',
    'access': r'\bacess\w*\b',
}
_TOPICS = {'convite_tiktok': {'invite'}, 'cadastro_acessos': {'registration', 'access'}}


def _subjects(text):
    return {name for name, pattern in _SUBJECTS.items() if re.search(pattern, text, re.I)}


def _cost_question(text, plan):
    return ('custos' in plan.get('topic_ids', []) or bool(re.search(
        r'comiss[aã]o|comiss[oõ]es|percentual|porcentagem|\btaxa\b|\bcobr\w*\b|\bcusto\b', text, re.I)))


def _policy_text(policy):
    from real_journey import policy_valid
    if not policy_valid(policy):
        return 'As condições precisam estar confirmadas antes de autorizar um convite.'
    rate = f"{policy['commission']:g}".replace('.', ',')
    return (f"A taxa da Amplify é de *{rate}%* sobre as comissões que você recebe como creator, "
            f"com prazo de {policy['duration_label']}; ela não é calculada sobre o total das vendas.")


def approved_cost_reply(text, plan, policy):
    """An explicit cost question survives a missing or rejected model plan.

    Model topic IDs never turn an unrelated message into a financial question.
    A useful clarification about product versus agency commission is retained.
    The backend's approved policy is the only source of numeric conditions.
    """
    if not isinstance(text, str):
        return None
    after_term = bool(re.search(r'(?:depois|apos|após|passad[oa]s?|termin\w*|acabar|fim).*?(?:2|dois)\s+meses|(?:2|dois)\s+meses.*?(?:depois|termin\w*|acabar)', text, re.I))
    if after_term:
        from real_journey import policy_valid
        if not policy_valid(policy):
            return 'As condições precisam estar confirmadas antes de autorizar um convite.'
        return ('O prazo informado para esta parceria é de ' + policy['duration_label'] + '. '
                'Ainda não tenho uma regra confirmada sobre renovação ou condições depois desse período. '
                'Esse ponto precisa ser esclarecido com um especialista da Amplify antes de você aceitar.')
    duration_question = (bool(re.search(r'contrato|parceria|agenciamento', text, re.I))
                         and bool(re.search(r'prazo|dura|tempo|quantos? meses|quanto tempo', text, re.I)))
    if not (_cost_question(text, {}) or duration_question or re.search(
            r'\bmensalidade\b|\bquanto\s+(?:pago|paga|pagar|custa)\b', text, re.I)):
        return None
    plan = plan if isinstance(plan, dict) else {}
    reply = plan.get('reply')
    product = bool(re.search(r'\bproduto\b|\bvendedor\b', text, re.I))
    agency = bool(re.search(r'\bamplify\b|\bag[eê]ncia\b|\bagenciamento\b|\bparceria\b', text, re.I))
    if product and not agency:
        return None
    if (plan.get('provider_status') == 'completed' and plan.get('intent') == 'clarify'
            and isinstance(reply, str) and reply.count('?') == 1 and len(reply) <= 350
            and re.search(r'\bproduto\b|\bvendedor\b|\bplataforma\b', reply, re.I)
            and re.search(r'comiss|taxa|custo', reply, re.I)
            and not re.search(r'\d\s*%|R\$|https?://', reply, re.I)):
        return None
    return _policy_text(policy)


def approved_educational_reply(text, plan):
    """Keep a general FAQ distinct from this person's operational status.

    Only the current turn's approved public FAQ excerpt can take this path;
    model prose and model-selected topic IDs cannot supply its facts. Personal
    status questions and operational instructions retain the receipt gate.
    """
    from engine import _normal
    if not isinstance(text, str) or not isinstance(plan, dict):
        return None
    normal = _normal(text)
    normal = re.sub(r'^(?:por favor |(?:pode |poderia )?me explicar |me explica |'
                    r'me conte |me conta |quero saber |gostaria de saber )', '', normal)
    requests = {
        'funcionamento': r'(?:como funciona(?: a amplify| a parceria| essa parceria| o agenciamento)?|funcionamento)',
        'beneficios': r'(?:(?:quais (?:sao )?(?:os |as )?)?(?:beneficios|vantagens)(?: da amplify| da parceria)?)',
        'amplify': r'(?:conhecer (?:a )?amplify|o que e a amplify|quem e a amplify|o que a amplify faz|sobre a amplify)',
    }
    topic_id = next((key for key, pattern in requests.items() if re.fullmatch(pattern, normal)), None)
    if topic_id is None:
        return None
    # Preserve a useful live clarification instead of answering a different
    # question merely because the context snapshot also has a broad FAQ.
    live_reply = plan.get('reply')
    if (plan.get('provider_status') == 'completed' and plan.get('intent') == 'clarify'
            and isinstance(live_reply, str) and live_reply.count('?') == 1):
        return None
    approved = plan.get('approved_topic_answer')
    version = plan.get('knowledge_version')
    if (not isinstance(approved, dict) or approved.get('id') != topic_id
            or approved.get('source') != 'approved_context'
            or not isinstance(version, str) or not version.strip()
            or approved.get('knowledge_version') != version):
        return None
    summary = approved.get('text')
    if (not isinstance(summary, str) or not 0 < len(summary.strip()) <= 650
            or '?' in summary or re.search(r'https?://|R\$|\d\s*%|\d+\s*(?:dias|meses)\b', summary, re.I)
            or re.search(r'\b(?:backend|sql|schema)\b|contexto interno|base aprovada', summary, re.I)):
        return None
    if _subjects(summary):
        # A public description can mention what happens after authorization.
        # It cannot address this person's milestone or speak as its executor.
        # Even an approved topic is not a receipt for a personal operation.
        public = _normal(summary)
        if (re.search(r'\b(?:seu|sua|seus|suas|teu|tua|meu|minha)\s+(?:convite|vinculo|cadastro|acesso)s?\b', public)
                or re.search(r'\b(?:eu|ja|pronto|prontinho|acabei)\b', public)
                # "Você aceita/abre/informa" can describe a general procedure.
                # A personal state or completed action still needs a receipt.
                or re.search(r'\bvoce\s+(?:e|esta|foi|tem|teve|recebeu|concluiu|finalizou)\b', public)
                or re.search(r'\bnós\b', summary, re.I)
                or re.search(r'\b(?:foi|foram|esta|estao)\s+(?:\w+\s+){0,2}'
                             r'(?:confirmad|concluid|enviad|liberad|aprovad)\w*\b', public)
                or re.search(r'(?:^|[.;])\s*(?:o |os )?(?:convite|v[ií]nculo|cadastro|acesso)s?\s+'
                             r'(?:confirmad|concluid|enviad|liberad|aprovad)\w*\b', summary, re.I)):
            return None
    return summary.strip()




_ACCEPT_GUIDE = ('Para aceitar, abra o TikTok Shop Creator em *Parcerias* ou *Notificações* e procure o convite da *Amplify*. '
                 'Quando aceitar, me manda “aceitei” que eu confiro na hora.')
# The last confirmed fact of this cycle answers. The 15-minute proof window is
# a rule for permissions, not for what the lead was already told.
_FACT_AGE = 24 * 3600


def _relationship_status(state, now):
    from real_journey import _operation_proven
    cycle = state.get('cycle') or {}

    def proven(operation, status):
        return _operation_proven(state, operation, status, now=now, maximum_age_seconds=_FACT_AGE)

    if proven('relationship', 'linked') or proven('invite', 'linked'):
        return 'Seu vínculo com a Amplify foi confirmado no TikTok. ✅'
    if proven('relationship', 'pending') or proven('invite', 'pending'):
        return 'Seu convite da Amplify já está no TikTok, esperando o seu aceite. 😊\n\n' + _ACCEPT_GUIDE
    if proven('invite', 'sent'):
        return 'O TikTok confirmou o envio do seu convite. 😊\n\n' + _ACCEPT_GUIDE
    record = (cycle.get('real_operations') or {}).get('invite') or {}
    if record.get('status') == 'pending_verification' and (record.get('evidence') or {}).get('create_accepted') is True:
        return 'Seu convite foi enviado ao TikTok. 😊\n\n' + _ACCEPT_GUIDE
    if (record.get('status') == 'failed'
            and record.get('reason') == 'creator_binding_not_permitted'):
        return ('O TikTok informou que este perfil ainda não tem permissão para se vincular a uma agência. '
                'Esse requisito precisa ser verificado antes de continuar o agenciamento.')
    if record.get('status') == 'failed' and (record.get('evidence') or {}).get('create_accepted') is False:
        return ('A tentativa de envio falhou, então ainda não tenho confirmação do convite. '
                'Não vou pedir que você aceite um convite sem confirmação. O time precisa conferir o motivo antes de um novo envio.')
    if record:
        # Release 38 approved text: say where to look instead of only denying.
        return ('Ainda não tenho confirmação do TikTok de que o seu convite chegou 😕\n\n'
                'Dá uma olhada no app do TikTok Shop Creator, em *Parcerias* ou *Notificações*, e procure o convite da *Amplify*. '
                'Se não estiver lá, me avise que o time confere para você.')
    if not (cycle.get('facts') or {}).get('tiktok_declarado'):
        return 'O convite é enviado depois que eu confiro seu perfil. Me manda seu @ do TikTok que eu já confiro. 😊'
    if cycle.get('phase') == 'consent_real':
        return 'O convite sai assim que você autorizar as condições da parceria.'
    return 'O convite é enviado depois da conferência do seu perfil, que eu já estou fazendo. Te aviso aqui. 🔎'


def _model_sentences(reply):
    """Model sentences that touch no operational subject and carry no link."""
    kept = [part.strip() for part in re.split(r'(?<=[.!?])\s+|\n+', reply)
            if part.strip() and not _subjects(part) and not re.search(r'https?://', part)]
    return ' '.join(kept)


def ground_reply(lead_text, reply, plan, state, *, policy=None, now=None):
    """Return a short backend-owned answer, or the untouched nonoperational text.

    Operational sentences come from the cycle's last confirmed receipts, never
    from model prose, and cannot announce registration/access completion:
    those announcements remain owned by their receipt callbacks. Internal
    control rules are not shown to the lead; every status ends with a step.
    """
    from real_journey import _invite_known, _linked
    if not isinstance(reply, str) or not isinstance(plan, dict):
        return ''
    if not isinstance(state, dict) or not isinstance(state.get('cycle'), dict):
        return '' if _subjects(reply) else reply
    lead_text = lead_text if isinstance(lead_text, str) else ''
    approved_cost = approved_cost_reply(lead_text, plan, policy)
    if approved_cost is not None and not _subjects(lead_text):
        return approved_cost
    asked = _subjects(lead_text)
    subjects = _subjects(reply)
    if plan.get('intent') in {'question', 'clarify'}:
        subjects |= asked
        for topic in plan.get('topic_ids', []) if isinstance(plan.get('topic_ids'), list) else []:
            if isinstance(topic, str):
                subjects |= _TOPICS.get(topic, set())
    if not subjects:
        return reply
    parts = []
    if _cost_question(lead_text, plan):
        parts.append(_policy_text(policy))
    elif not asked:
        # The lead asked about something else: answer that, dropping only the
        # model's operational sentences instead of replacing the whole reply.
        answer = _model_sentences(reply)
        if answer:
            return answer
    cycle = state['cycle']
    if subjects & {'invite', 'relationship'}:
        status = _relationship_status(state, now)
        if (re.search(r'\bonde\b|\bcomo\b', lead_text, re.I) and re.search(r'aceit|convite|parcer', lead_text, re.I)
                and 'Parcerias' not in status and (cycle.get('facts') or {}).get('tiktok_declarado')
                and not (((cycle.get('real_operations') or {}).get('invite') or {}).get('status') == 'failed')):
            parts.append(_ACCEPT_GUIDE)
        parts.append(status)
    if subjects & {'registration', 'access'}:
        if _linked(cycle) or _invite_known(cycle):
            parts.append('O cadastro é feito no formulário: assim que você envia, a gente confere e libera seu acesso à comunidade. 😊')
        else:
            parts.append('O cadastro é liberado depois que você aceita o convite da Amplify no TikTok; '
                         'no final dele, você já recebe seu acesso à comunidade.')
    return '\n\n'.join(dict.fromkeys(parts))
