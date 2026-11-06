"""Draft demo copy and transitions. No provider, personal data, URLs or real terms."""
import re
import unicodedata
import uuid

FLOW_VERSION = 'v2'
TEMPLATES = {
    'faq_context': ('', {'join': 'Quero me agenciar', 'question': 'Tenho outra dúvida'}),
    'about': ('O que você quer conhecer? ✨\n\nEscolha um tema ou escreva sua dúvida.',
              {'faq_benefits': 'Conhecer benefícios', 'topic_partnership': 'Parceria e regras', 'topic_more': 'Mais assuntos'}),
    'faq_partnership': ('Vamos falar da parceria 🤝\n\nEscolha um tema ou escreva sua dúvida.',
                        {'faq_terms': 'Regras e saída', 'faq_invite': 'Convite e aceite', 'back': 'Ver tópicos'}),
    'faq_more': ('Qual assunto te interessa? 💬\n\nVocê também pode escrever sua dúvida.',
                 {'topic_lives': 'Lives e conteúdo', 'topic_club': 'Amplify Club', 'back': 'Ver tópicos'}),
    'profile': ('Que legal! Vamos começar 🚀\n\nMe manda seu *@ de creator no TikTok* para seguirmos com seu agenciamento.',
                {'question': 'Tenho dúvidas', 'opening': 'Voltar ao início'}),
    'member': ('Que bom te ver por aqui de novo! 👋\n\nComo posso te ajudar? Neste teste, não vou consultar seu cadastro.',
               {'question': 'Tenho uma dúvida', 'join': 'Ver o agenciamento', 'opening': 'Voltar ao início'}),
    'conditions': ('Recebi seu perfil! ✅\n\nVamos simular as próximas etapas. As condições reais ainda precisam ser confirmadas; este teste não representa aceite comercial.',
                   {'continue_test': 'Seguir no teste', 'question': 'Tenho uma dúvida', 'opening': 'Voltar ao início'}),
    'invite': ('Convite de demonstração preparado 📨\n\nQuer simular o aceite para ver como a confirmação aparece?',
               {'accept_demo': 'Simular aceite', 'decline': 'Agora não', 'question': 'Tenho uma dúvida'}),
    'confirmed': ('Teste concluído! 🎉\n\nO aceite e o vínculo foram simulados. Seu perfil real não foi consultado nem agenciado.',
                  {'opening': 'Recomeçar teste', 'question': 'Tenho uma dúvida', 'close': 'Encerrar teste'}),
    'paused': ('Tudo bem 😊\n\nO convite de teste ficou pausado. Quer retomar ou voltar ao início?',
               {'resume': 'Retomar teste', 'opening': 'Voltar ao início', 'close': 'Encerrar teste'}),
    'faq': ('Claro! Me conta sua dúvida por aqui 💬',
            {'back': 'Ver tópicos'}),
    'faq_agency': ('A Amplify é uma agência e comunidade para creators do TikTok Shop ✨ Você pode tirar suas dúvidas antes de decidir se quer se agenciar.',
                   {'join': 'Quero me agenciar', 'question': 'Tenho outra dúvida'}),
    # Verified active V5 card beneficios, contextos-ia-v1:a2e71fb5d6108de76489c25456fda6bc,
    # read on 2026-11-05. Availability is conditional, not a general entitlement.
    'faq_benefits': ('A parceria pode incluir 🌟\n\n- *Treinamentos*\n- *Suporte*\n- *Comunidade no Circle*\n- *Oportunidades de campanhas*\n\nOs benefícios variam conforme sua categoria e cada ação, sujeitos à disponibilidade e às condições da parceria.',
                     {'join': 'Quero me agenciar', 'question': 'Tenho outra dúvida'}),
    'faq_terms': ('As condições reais ainda precisam ser confirmadas 📋 Não tenho detalhes confirmados sobre comissão, prazo ou exclusividade para te passar neste teste.',
                  {'join': 'Quero me agenciar', 'question': 'Tenho outra dúvida'}),
    'faq_invite': ('Aqui, nenhum convite real é enviado 📨 O aceite e o vínculo são simulados, sem agenciar seu perfil.',
                   {'join': 'Quero me agenciar', 'question': 'Tenho outra dúvida'}),
    'faq_unknown': ('Não tenho essa informação confirmada 🔎\n\nVocê pode escolher outro tema ou perguntar de outro jeito.',
                    {'question': 'Tenho outra dúvida', 'join': 'Quero me agenciar'}),
    'faq_unavailable': ('Não consegui consultar as informações agora ⚙️\n\nSua etapa está preservada. Você pode tentar a pergunta novamente.',
                        {'retry': 'Tentar novamente', 'back': 'Retomar etapa'}),
    'closed': ('Teste encerrado 👋\n\nSe quiser começar de novo, é só tocar abaixo.',
               {'opening': 'Recomeçar teste'}),
}
FAQ_STEPS = frozenset(step for step in TEMPLATES if step == 'faq' or step.startswith('faq_'))
KNOWLEDGE_STEPS = FAQ_STEPS | {'about'}
RETURN_STEPS = frozenset({'opening', 'about', 'profile', 'member', 'conditions', 'invite', 'confirmed', 'paused'})


def safe_context_text(value, limit=900):
    if not isinstance(value, str):
        return ''
    value = re.sub(r'[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|@[A-Za-z0-9_.]+|https?://\S+|\+?\d[\d ()-]{9,}\d', '[dado removido]', value)
    return value[:limit]

TRANSITIONS = {'join': 'profile', 'know': 'about', 'member': 'member', 'question': 'about',
               'opening': 'opening', 'use_profile': 'conditions', 'continue_test': 'invite',
               'accept_demo': 'confirmed', 'decline': 'paused', 'resume': 'invite',
               'close': 'closed', 'faq_agency': 'faq_agency', 'faq_terms': 'faq_terms',
               'faq_invite': 'faq_invite', 'faq_benefits': 'faq_benefits', 'retry': 'faq_unavailable',
               'topic_partnership': 'faq_partnership', 'topic_more': 'faq_more',
               'topic_lives': 'faq_unavailable', 'topic_club': 'faq_unavailable'}
TOPIC_QUESTIONS = {
    'faq_benefits': 'Conhecer benefícios',
    'faq_terms': 'Quais são as regras da parceria e como funciona a saída?',
    'faq_invite': 'Como funciona o convite e o aceite da parceria?',
    'topic_lives': 'Preciso fazer lives para participar da parceria?',
    'topic_club': 'O que é o Amplify Club e como funciona o acesso?',
}


def presented_choices(key, message):
    """Use the exact persisted buttons, including those shown before a deploy."""
    if not isinstance(message, dict) or message.get('content_type') != 'input_select':
        return {}
    attributes = message.get('content_attributes')
    items = attributes.get('items') if isinstance(attributes, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        return {}
    choices = {}
    for item in items:
        if not isinstance(item, dict):
            return {}
        title, value = item.get('title'), item.get('value')
        if (not isinstance(title, str) or not 1 <= len(title) <= 20
                or not isinstance(value, str) or not value.startswith(key + ':')):
            return {}
        action = value[len(key) + 1:]
        if action not in {*TRANSITIONS, 'back'} or action in choices or title in choices.values():
            return {}
        choices[action] = title
    return choices


def key_parts(key):
    match = re.fullmatch(r'bia-demo:v2:([a-f0-9]{32}):([a-z_]{1,24}):([a-f0-9]{16})', key) if isinstance(key, str) else None
    if not match or match[2] not in {'opening', *TEMPLATES}:
        raise ValueError('demo_flow_key_invalid')
    return match[1], match[2], match[3]


def new_key(run, step):
    key = 'bia-demo:v2:' + run + ':' + step + ':' + uuid.uuid4().hex[:16]
    key_parts(key)
    return key


def format_answer(text):
    """Presentation only: retain every sentence and qualifier, never truncate."""
    text = re.sub(r'\*\*([^*]+)\*\*', r'*\1*', text.strip()).replace('\r\n', '\n')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # A common unformatted benefits enumeration: retain the exact item words.
    match = re.match(r'(A parceria pode (?:oferecer|incluir)) ([^\n.!?]+)\.', text)
    if match and ',' in match[2] and '*' not in match[2]:
        items = re.split(r',\s*|\s+e\s+(?=[^,]+$)', match[2])
        if 2 <= len(items) <= 6:
            listing = '\n'.join('- *' + item.strip() + '*' for item in items)
            text = match[1] + ':\n\n' + listing + '\n\n' + text[match.end():].strip()
    # Break prose at sentence boundaries; do not split decimal values or lists.
    blocks = []
    for block in text.split('\n\n'):
        if '\n' not in block and len(block) > 150:
            blocks.extend(re.split(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])', block))
        else:
            blocks.append(block)
    text = '\n\n'.join(block.strip() for block in blocks if block.strip())
    if '*' not in text:
        # Highlight a short existing sentence, without introducing a heading/fact.
        first = text.split('\n\n', 1)[0]
        if len(first) <= 160 and '\n' not in first:
            text = '*' + first + '*' + text[len(first):]
    if not re.search('[\U0001F300-\U0001FAFF\u2600-\u27BF]', text):
        topic = text.casefold()
        emoji = ('🎥' if 'live' in topic else '📚' if 'treinamento' in topic else
                 '🤝' if 'comunidade' in topic or 'circle' in topic else '📋')
        text = emoji + ' ' + text
    if len(text.encode('utf-16-le')) // 2 > 900:
        raise ValueError('demo_answer_too_long')
    return text


def payload(key, opening, opening_choices, answer=None):
    _, step, _ = key_parts(key)
    text, choices = (opening, opening_choices) if step == 'opening' else TEMPLATES[step]
    if step == 'faq_context':
        if not isinstance(answer, str) or not 1 <= len(answer) <= 900:
            raise ValueError('demo_context_answer_required')
        text = format_answer(answer)
    # One presentation rule for scripted copy and generated/context answers.
    text = format_answer(text)
    if len(text.encode('utf-16-le')) // 2 > 1024:
        raise ValueError('demo_interactive_body_too_long')
    return {'content': text, 'message_type': 'outgoing', 'private': False, 'content_type': 'input_select',
            'content_attributes': {'items': [{'title': title, 'value': key + ':' + action}
                                            for action, title in choices.items()]}}


def question_step(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 500:
        return None
    value = ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))
    if re.search(r'comiss|condic|prazo|exclusiv|quanto|custa|paga|ganh', value):
        return 'faq_terms'
    if re.search(r'benefici|vantagen', value):
        return 'faq_benefits'
    if re.search(r'convite|aceite|vinculo', value) and ('?' in value or re.search(r'como|duvida|pergunta', value)):
        return 'faq_invite'
    if '?' in value or re.search(r'\b(como|duvida|pergunta)\b', value):
        return 'faq'
    return None


def decision(step, text, *, correlated, opening_choices, question_answerer=None, resume_step=None,
             last_question=None, current_choices=None):
    choices = current_choices if current_choices is not None else (opening_choices if step == 'opening' else TEMPLATES[step][1])
    action = next((action for action, title in choices.items() if text == title), None) if correlated else None
    if not action and step == 'profile' and isinstance(text, str) and re.fullmatch(r'@[A-Za-z0-9_.]{2,24}', text.strip()):
        return {'action': 'profile_received', 'step': 'conditions', 'effects': [('tiktok', 'eligible')]}
    if step in KNOWLEDGE_STEPS and action == 'back':
        return {'action': action, 'step': 'about', 'effects': []}
    if step in KNOWLEDGE_STEPS and action == 'join':
        target = resume_step if resume_step in RETURN_STEPS else 'profile'
        if target in {'opening', 'about', 'member'}:
            target = 'profile'
        return {'action': action, 'step': target, 'effects': []}
    # An acknowledgment is not a request to start or resume collecting data.
    if step in KNOWLEDGE_STEPS and isinstance(text, str) and text.strip().casefold() in {'sim', 'ok', 'entendi', 'continuar', 'continue'}:
        return {'action': 'back', 'step': 'about', 'effects': []}
    target = TRANSITIONS[action] if action else question_step(text)
    # A bare menu label must not bypass reply correlation. Free questions never
    # execute transitions or authorize simulated acceptance, even if AI errs.
    known_labels = set(opening_choices.values()) | set(choices.values()) | {label for _, menu in TEMPLATES.values() for label in menu.values()}
    if not action and (text in known_labels if isinstance(text, str) else False):
        return None
    if step == 'closed' and not action:
        return None
    grounded, asked_question = None, None
    if (action in {*TOPIC_QUESTIONS, 'retry'} or (not action and isinstance(text, str) and text not in known_labels and step != 'closed')):
        asked_question = safe_context_text(last_question, 500) if action == 'retry' else TOPIC_QUESTIONS.get(action, text)
        if action == 'retry' and not asked_question.strip():
            # No saved question means there is nothing safe to replay.
            return {'action': action, 'step': 'faq', 'effects': []}
        if question_answerer:
            try:
                answer = question_answerer(asked_question)
                if (isinstance(answer, dict) and isinstance(answer.get('answer'), str)
                        and 1 <= len(answer['answer']) <= 900 and answer.get('evidence')
                        and answer.get('knowledge_version')):
                    grounded, target = answer, 'faq_context'
                else:
                    target = answer if isinstance(answer, str) and answer in {'faq_agency', 'faq_terms', 'faq_invite', 'faq_unknown', 'faq_benefits', 'faq_unavailable'} else 'faq_unknown'
            except Exception:
                target = 'faq_unavailable'
        elif step in {'faq', 'member'} and not target:
            target = 'faq_unknown'
    if not target:
        return None
    effects = []
    if action == 'use_profile':effects = [('tiktok', 'eligible')]
    elif action == 'continue_test':effects = [('invite', 'unknown')]
    elif action == 'accept_demo':effects = [('invite', 'accepted'), ('relationship', 'linked')]
    return {'action': action or 'question', 'step': target, 'effects': effects,
            'grounded': grounded, 'question': asked_question}
