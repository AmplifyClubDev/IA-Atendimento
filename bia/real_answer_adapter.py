"""Real-state adapter for the shared answer engine. Never authorizes effects."""
from demo_flow import safe_context_text
from demo_support import clarification_question

ENGINE = 'shared-answer-v1'
UNAVAILABLE = 'Não consegui consultar essa informação agora. Sua etapa está preservada. Você pode tentar a pergunta novamente. 🔎'
UNKNOWN = 'Ainda não tenho essa informação confirmada. 🔎'


def dialogue_from_context(context):
    history = context.get('history') if isinstance(context, dict) else []
    pairs, pending = [], ''
    for item in history[-16:] if isinstance(history, list) else []:
        if not isinstance(item, dict):
            continue
        direction = item.get('direction', item.get('role'))
        text = item.get('text', item.get('content'))
        if direction in {'inbound', 'user'}:
            pending = safe_context_text(text, 300)
        elif direction in {'outbound', 'assistant'} and pending:
            pairs.append({'question': pending, 'answer': safe_context_text(text, 600)})
            pending = ''
    last = pairs[-1] if pairs else {}
    delivered = context.get('delivery_context') if isinstance(context, dict) else None
    accepted = delivered.get('last_accepted_reply') if isinstance(delivered, dict) and delivered.get('source') == 'outbox' else None
    accepted_text = safe_context_text(accepted.get('text'), 600) if isinstance(accepted, dict) else ''
    return {'recent_dialogue': pairs[-6:], 'prior_questions': [p['question'] for p in pairs[-6:]],
            'last_question': last.get('question', ''), 'last_answer': last.get('answer', ''),
            'last_accepted_public_reply': accepted_text,
            'pending_clarification': clarification_question(last.get('answer', ''))}


# A question dropped by the in-process reply fence may be added to the NEXT
# natural FAQ answer. Never feed it back into operational interpretation.
_PENDING_KEY = 'pending_information_questions'
_PENDING_SECONDS = 120
_PENDING_LIMIT = 2


def _informational_question(value):
    import re
    from engine import _normal
    if not isinstance(value, str) or not 1 <= len(value) <= 195 or '?' not in value:
        return ''
    # Limit this recovery to general questions, never controls, PII, access,
    # invitation, consent, a profile lookup or personal status.
    text = safe_context_text(value, 195).strip()
    if '[dado removido]' in text:
        return ''
    plain = _normal(text)
    if not re.search(r'\b(?:como funciona|onde (?:fica|ficam|voces ficam)|de onde (?:voces sao|e a agencia)|'
                     r'qual (?:e |eh )?(?:o endereco|a localizacao)|quais (?:os |as )?(?:beneficios|vantagens)|'
                     r'(?:preciso|posso|tenho que) fazer lives?|tem (?:treinamento|aulas?))\b', plain):
        return ''
    if re.search(r'\b(?:aceit\w*|consent\w*|autoriz\w*|confirm\w*|convites?|cadastro\w*|'
                 r'vincul\w*|perfil|arroba|c[oó]digo|senha|agencia[dr]\w*|agenciamento|'
                 r'(?:meu|minha) acesso|sair|cancel\w*|encerr\w*|parar|reset)\b', plain):
        return ''
    return text


def pending_information_questions(state, event, *, now=None):
    """Return only earlier, recent questions in the same open cycle."""
    from datetime import datetime, timezone
    from engine import _clock
    cycle = state.get('cycle') or {}
    rows = state.get(_PENDING_KEY)
    if (not isinstance(rows, list) or cycle.get('status') != 'open' or not cycle.get('id')):
        return []
    try:
        identifier = int(event['message_id'])
        at = datetime.now(timezone.utc) if now is None else _clock(now)
    except (KeyError, TypeError, ValueError, OverflowError):
        return []
    result = []
    for row in rows[-_PENDING_LIMIT:]:
        if not isinstance(row, dict) or row.get('cycle_id') != cycle['id']:
            continue
        try:
            age = (at - _clock(row['observed_at'])).total_seconds()
            prior = int(row['message_id'])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not 0 <= age <= _PENDING_SECONDS or not 0 < prior < identifier:
            continue
        original = _informational_question(row.get('text'))
        if original:
            result.append({**row, 'text': original})
    return result


def remember_suppressed_question(state, event, *, now=None):
    """Caller must have proven that the reply was superseded before POST."""
    from datetime import datetime, timezone
    from engine import _clock, _stamp
    cycle = state.get('cycle') or {}
    text = _informational_question(event.get('text'))
    if not text or cycle.get('status') != 'open' or not cycle.get('id'):
        return False
    at = datetime.now(timezone.utc) if now is None else _clock(now)
    try:
        identifier = int(event['message_id'])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    if identifier <= 0:
        return False
    existing = pending_information_questions(state, event, now=at)
    formatted = { 'cycle_id': cycle['id'], 'message_id': identifier, 'observed_at': _stamp(at), 'text': text }
    state[_PENDING_KEY] = ([row for row in existing if row['text'] != text] + [formatted])[-_PENDING_LIMIT:]
    return True


def clear_answered_questions(state, message_ids):
    rows = state.get(_PENDING_KEY)
    if not isinstance(rows, list) or not message_ids:
        return False
    pending = [row for row in rows if not isinstance(row, dict) or row.get('message_id') not in message_ids]
    if pending == rows:
        return False
    if pending:
        state[_PENDING_KEY] = pending
    else:
        state.pop(_PENDING_KEY, None)
    return True


def _merged_information_question(question, context):
    from engine import _normal
    current = safe_context_text(question, 300)
    if current != question or not isinstance(context, dict) or context.get('real_mode') is not True:
        return question, []
    rows = context.get('pending_information_questions')
    if not isinstance(rows, list):
        return question, []
    # Only context from the trusted server projection reaches here. Recheck
    # shape and scope: not a user-supplied instruction or an operational claim.
    parts, sources = [], []
    for row in rows[-_PENDING_LIMIT:]:
        if not isinstance(row, dict) or type(row.get('message_id')) is not int:
            continue
        text = _informational_question(row.get('text'))
        if not text or _normal(text) == _normal(current) or text in parts:
            continue
        if sum(map(len, parts)) + len(text) + len(current) + 4 > 500:
            continue
        parts.append(text)
        sources.append(row['message_id'])
    return ('\n'.join(parts + [current]), sources) if parts else (question, [])


def build_real_planner(settings, planner, *, answerer=None):
    """Keep validated interpretation, replace ALL generative reply/fallback text."""
    from answer_engine import build_answerer
    engine = answerer if answerer is not None else build_answerer(settings, mode='real')
    def plan(question, context, turn_settings):
        try:
            # Even the structured interpretation prompt must never see carried
            # FAQ text: only the current inbound can express facts or consent.
            classifier_context = {key: value for key, value in context.items()
                                  if key != _PENDING_KEY} if isinstance(context, dict) else context
            result = planner(question, classifier_context, turn_settings)
        except Exception:
            result = {'provider_status': 'unknown', 'intent': 'clarify', 'claims': []}
        result = dict(result) if isinstance(result, dict) else {'provider_status': 'unknown', 'intent': 'clarify', 'claims': []}
        # Model output is never permitted to mint a trusted engine marker.
        result.pop('shared_answer', None)
        result.pop('carried_information_sources', None)
        result['reply'] = ''
        result.pop('approved_topic_answer', None)
        result.pop('topic_ids', None)
        try:
            answer_question, carried_sources = _merged_information_question(question, context)
            answer = engine(answer_question, conversation=dialogue_from_context(context)) if callable(engine) else 'faq_unavailable'
        except Exception:
            answer, carried_sources = 'faq_unavailable', []
        valid = (isinstance(answer, dict) and isinstance(answer.get('answer'), str)
                 and isinstance(answer.get('evidence'), list) and bool(answer['evidence'])
                 and isinstance(answer.get('knowledge_version'), str))
        text = answer['answer'] if valid else UNKNOWN if answer == 'faq_unknown' else UNAVAILABLE
        result['reply'] = text
        if valid and carried_sources and not clarification_question(text):
            result['carried_information_sources'] = carried_sources
        result['shared_answer'] = {'engine': ENGINE, 'status': 'supported' if valid else 'unavailable',
                                   'text': text, 'profile_id': getattr(engine, 'profile_id', 'amplify-v1')}
        return result
    plan.shared_engine_available = callable(engine)
    plan.shared_engine_version = ENGINE
    return plan


def shared_reply(proposal, cycle, policy):
    """Validated engine prose, without the legacy canned FAQ substitutions."""
    record = proposal.get('shared_answer') if isinstance(proposal, dict) else None
    if not isinstance(record, dict) or record.get('engine') != ENGINE:
        return None
    text = record.get('text')
    if not isinstance(text, str) or not 0 < len(text) <= 900:
        return UNAVAILABLE
    # No generative claim of a real event can bypass receipt-based backend text.
    import re
    from engine import _normal
    plain = _normal(text)
    if (re.search(r'\b(?:seu|teu|o seu)\s+(?:convite|vinculo|cadastro|acesso|perfil)\b.{0,35}\b(?:confirmad|concluid|enviad|liberad|aprovad)', plain)
            or re.search(r'\bvoce\b.{0,20}\b(?:esta|foi)\b.{0,15}\bagenciad', plain)):
        return UNAVAILABLE
    if clarification_question(text):
        return text
    if '?' in text:
        return UNAVAILABLE
    if cycle.get('phase') in {'origin', 'tiktok', 'shop', 'agency'}:
        from real_journey import _phase_prompt, _qualification_phase, _step_reply
        return _step_reply(text, _phase_prompt(cycle, _qualification_phase(cycle)))
    return text


def ground_shared_operational_reply(question, answer, state, *, now=None):
    """Do not use the legacy sales/cost/status paraphraser for engine prose.

    General explanations retain the shared engine's semantic/evidence review.
    Personal operational results are rendered exclusively from bound receipts;
    absence of proof never becomes a claim of an active job or future follow-up.
    """
    import re
    from engine import _normal
    from receipt_grounding import _subjects
    from real_journey import _operation_proven
    q, a = _normal(question), _normal(answer)
    asked, mentioned = _subjects(question), _subjects(answer)
    # A transfer, action promise or follow-up cannot be evidenced by FAQ cards.
    if re.search(r'\b(?:transferi|transferimos|encaminhei|encaminhamos|acionei|acionamos)\b|'
                 r'\b(?:vou|vamos|irei)\s+(?:te\s+|voce\s+)?(?:transferir|encaminhar|acionar|enviar|liberar)|'
                 r'\b(?:te aviso|vou avisar|entraremos em contato)\b', a):
        return UNAVAILABLE
    cycle = state.get('cycle', {}) if isinstance(state, dict) else {}
    contextual_status = (not cycle.get('answer_clarification')
        and cycle.get('phase') in {'inviting', 'invite_pending', 'await_acceptance', 'form',
                                  'relationship_pending', 'checking', 'acesso', 'consent_real'}
        and bool(re.fullmatch(r'(?:e ai|deu certo|conseguiu|conseguiram|funcionou|pronto|ja foi|foi)\s*[?!.]*', q)))
    if contextual_status:
        return 'Ainda não tenho confirmação do TikTok. Assim que chegar, te aviso por aqui 😊'
    if not asked and not mentioned:
        return answer
    # Subject words alone are not personal status: requirements, duration and
    # access eligibility are FAQ, including questions that need clarification.
    personal_question = bool(asked and re.search(
        r'\b(?:meu|minha|meus|minhas)\b.{0,45}\b(?:ja|foi|esta|status|situacao|confirmad|enviad|liberad|feito)|'
        r'\b(?:ja|foi|esta|status|situacao)\b.{0,35}\b(?:meu|minha|convite|vinculo|cadastro|acesso)|'
        r'\b(?:voce|voces)\s+(?:ja\s+)?(?:enviou|enviaram|mandou|mandaram|confirmou|liberou)|'
        r'\b(?:sou|estou|fui)\s+(?:ja\s+)?(?:agenciad|vinculad|cadastrad)|'
        r'\b(?:recebi|aceitei|conclui|finalizei)\b|'
        r'\b(?:meu|minha|o convite|o cadastro|o acesso)\b.{0,40}\b(?:saiu|chegou|funcionou|deu certo|pronto)|'
        r'\b(?:deu certo|conseguiu|conseguiram|conseguimos|funcionou|liberaram|enviaram|mandaram)\b.{0,45}\b(?:meu|minha|convite|cadastro|acesso|vinculo)', q))
    personal_claim = bool(re.search(
        r'\b(?:enviei|enviamos|mandei|mandamos|confirmei|confirmamos|liberei|liberamos|'
        r'conclui|concluimos|aprovei|aprovamos)\b|'
        r'\b(?:seu|sua|seus|suas|teu|tua)\s+(?:convite|vinculo|cadastro|acesso|perfil)s?\b.{0,30}\b(?:ja|foi|esta|enviad|confirmad|feito|liberad)|'
        r'\bvoce\s+(?:ja\s+)?(?:esta|foi|tem|teve|recebeu|concluiu|finalizou)\b|'
        r'\b(?:foi|foram|esta|estao|ja)\s+(?:\w+\s+){0,2}(?:confirmad|concluid|enviad|liberad|aprovad)\w*\b|'
        r'(?:^|[.;])\s*(?:o |seu )?(?:convite|vinculo|cadastro|acesso|perfil)s?\s+(?:ja )?(?:confirmad|concluid|enviad|liberad|aprovad)\w*\b', a))
    if not personal_question and not (mentioned and personal_claim):
        return answer
    if not asked:
        return UNAVAILABLE
    if not isinstance(state, dict):
        return 'Ainda não tenho confirmação do TikTok. Assim que chegar, te aviso por aqui 😊'
    proven=lambda operation,status:_operation_proven(state,operation,status,now=now,maximum_age_seconds=24*3600)
    if asked & {'invite','relationship'}:
        if proven('relationship','linked') or proven('invite','linked'):
            return 'Seu vínculo com a Amplify foi confirmado no TikTok. ✅'
        if proven('relationship','pending') or proven('invite','pending'):
            return 'O TikTok confirmou que o convite da Amplify está aguardando o aceite.'
        if proven('invite','sent'):
            return 'O TikTok confirmou o envio do convite da Amplify.'
    return 'Ainda não tenho confirmação do TikTok. Assim que chegar, te aviso por aqui 😊'
