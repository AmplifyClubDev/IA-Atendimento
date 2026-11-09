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
    'profile': ('Que legal! Vamos começar 🚀\n\nMe manda seu *@ de creator no TikTok* para conhecer as próximas etapas. Aqui, não consulto nem agencio seu perfil.',
                {'question': 'Tenho dúvidas'}),
    'member': ('Que bom te ver por aqui de novo! 👋\n\nComo posso te ajudar? Por aqui, não vou consultar seu cadastro.',
               {'question': 'Tenho uma dúvida', 'join': 'Ver o agenciamento'}),
    'conditions': ('Obrigada! ✅\n\nSeu perfil não foi consultado. Posso mostrar as próximas etapas, sem aceite comercial. As condições reais ainda precisam ser confirmadas.',
                   {'continue_test': 'Ver próxima etapa', 'question': 'Tenho uma dúvida'}),
    'invite': ('Veja como seria a etapa de aceite 📨\n\nNenhum convite real foi enviado. Quer ver a confirmação ilustrativa, sem criar vínculo?',
               {'accept_demo': 'Ver confirmação', 'decline': 'Agora não', 'question': 'Tenho uma dúvida'}),
    'confirmed': ('Pronto, você conheceu as etapas! 💙\n\nNão houve aceite comercial nem vínculo real. Seu perfil não foi consultado nem agenciado.',
                  {'question': 'Tenho uma dúvida', 'close': 'Encerrar atendimento'}),
    'paused': ('Tudo bem 😊\n\nPodemos deixar as próximas etapas para depois. Quer retomar a explicação ou encerrar por agora?',
               {'resume': 'Retomar explicação', 'close': 'Encerrar atendimento'}),
    'faq': ('Claro! Me conta sua dúvida por aqui 💬',
            {'back': 'Ver tópicos'}),
    'faq_agency': ('A Amplify é uma agência e comunidade para creators do TikTok Shop ✨ Você pode tirar suas dúvidas antes de decidir se quer se agenciar.',
                   {'join': 'Quero me agenciar', 'question': 'Tenho outra dúvida'}),
    # Verified active V5 card beneficios, contextos-ia-v1:a2e71fb5d6108de76489c25456fda6bc,
    # read on 2026-11-05. Availability is conditional, not a general entitlement.
    'faq_benefits': ('A parceria pode incluir 🌟\n\n- *Treinamentos*\n- *Suporte*\n- *Comunidade no Circle*\n- *Oportunidades de campanhas*\n\nOs benefícios variam conforme sua categoria e cada ação, sujeitos à disponibilidade e às condições da parceria.',
                     {'join': 'Quero me agenciar', 'question': 'Tenho outra dúvida'}),
    'faq_terms': ('As condições reais ainda precisam ser confirmadas 📋 Não tenho detalhes confirmados sobre comissão, prazo ou exclusividade para te passar agora.',
                  {'join': 'Quero me agenciar', 'question': 'Tenho outra dúvida'}),
    'faq_invite': ('Aqui, nenhum convite real é enviado 📨 Você pode conhecer as etapas de aceite, sem agenciar seu perfil nem criar vínculo.',
                   {'join': 'Quero me agenciar', 'question': 'Tenho outra dúvida'}),
    'faq_unknown': ('Não tenho essa informação confirmada 🔎\n\nVocê pode escolher outro tema ou perguntar de outro jeito.',
                    {'question': 'Tenho outra dúvida', 'join': 'Quero me agenciar'}),
    'faq_unavailable': ('Não consegui consultar as informações agora ⚙️\n\nSua etapa está preservada. Você pode tentar a pergunta novamente.',
                        {'retry': 'Tentar novamente', 'back': 'Retomar etapa'}),
    'stopped': ('Tudo bem. Interrompi as mensagens desta conversa no ensaio. 💙\n\nIsso não altera nenhum vínculo com uma agência.', {}),
    'declined': ('Tudo bem 😊 Não vou avançar no agenciamento.\n\nSe quiser, você ainda pode tirar uma dúvida ou encerrar por aqui.',
                 {'question': 'Tenho uma dúvida', 'close': 'Encerrar atendimento'}),
    'human_unavailable': ('Entendi seu pedido de falar com uma pessoa. 💬\n\nNão há atendimento humano disponível neste ensaio, então não fiz uma transferência. Posso continuar a explicação por aqui, se você quiser, ou encerrar.',
                          {'resume': 'Retomar explicação', 'close': 'Encerrar atendimento'}),
    'intent_clarify': ('Só para entender sua intenção 💬\n\nVocê quer conhecer as etapas, deixar para depois ou parar as mensagens desta conversa? Nenhum convite ou aceite será feito com essa escolha.',
                       {'join': 'Conhecer as etapas', 'decline': 'Deixar para depois', 'stop': 'Parar mensagens'}),
    'leave_clarify': ('Você quer encerrar esta conversa ou tirar uma dúvida sobre sair da agência? 💬\n\nNenhum vínculo será alterado por aqui.',
                      {'close': 'Encerrar atendimento', 'leave_help': 'Dúvida sobre saída'}),
    'leave_help': ('Não consigo realizar ou confirmar a saída de uma agência por aqui. 📋\n\nNão tenho o procedimento nem o prazo confirmados. Nenhum vínculo foi alterado. Você pode tirar uma dúvida geral ou encerrar esta conversa.',
                   {'question': 'Tenho uma dúvida', 'close': 'Encerrar atendimento'}),
    'help_account': ('Vamos entender a dificuldade com o convite 🔎\n\nNenhum convite real foi enviado por este ensaio. Se você está verificando um convite fora daqui, confira se está na conta TikTok correta. Você já conferiu? Não envie senha nem código.',
                     {'help_checked': 'Já conferi a conta', 'decline': 'Deixar para depois', 'close': 'Encerrar atendimento'}),
    'help_screen': ('O que aparece na tela ao procurar ou aceitar o convite? 🔎\n\nDescreva só o aviso, sem senha, código, documento ou dados pessoais. Não vou reenviar convite nem alterar vínculo por aqui.',
                    {'decline': 'Deixar para depois', 'close': 'Encerrar atendimento'}),
    'help_unavailable': ('Não consigo confirmar ou corrigir esse problema por aqui. ⚙️\n\nNão há atendimento humano disponível neste ensaio. Não vou repetir os mesmos passos nem reenviar um convite de resultado incerto. Você pode fazer outra pergunta ou encerrar.',
                         {'question': 'Outra pergunta', 'close': 'Encerrar atendimento'}),
    'closed': ('Atendimento encerrado. Obrigada pela conversa! 💙',
               {}),
}
FAQ_STEPS = frozenset(step for step in TEMPLATES if step == 'faq' or step.startswith('faq_'))
KNOWLEDGE_STEPS = FAQ_STEPS | {'about'}
RETURN_STEPS = frozenset({'opening', 'about', 'profile', 'member', 'conditions', 'invite', 'confirmed', 'paused'})
INTERRUPT_STEPS = frozenset({'paused', 'declined', 'human_unavailable', 'intent_clarify',
                             'leave_clarify', 'leave_help', 'help_account', 'help_screen', 'help_unavailable'})
CONTEXT_STEPS = KNOWLEDGE_STEPS | INTERRUPT_STEPS
TERMINAL_STEPS = frozenset({'closed', 'stopped'})
PROTECTIVE_INTENTS = frozenset({'stop', 'pause', 'decline', 'human'})


def safe_context_text(value, limit=900):
    if not isinstance(value, str):
        return ''
    value = re.sub(r'[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|@[A-Za-z0-9_.]+|https?://\S+|\+?\d[\d ()-]{9,}\d', '[dado removido]', value)
    value = re.sub(r'(?i)\b(?:meu nome [ée]|me chamo)\s+[^,.;!?\n]+', '[dado removido]', value)
    value = re.sub(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{8,}\b', '[dado removido]', value)
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    return value[:limit]

TRANSITIONS = {'join': 'profile', 'know': 'about', 'member': 'member', 'question': 'about',
               'opening': 'opening', 'use_profile': 'conditions', 'continue_test': 'invite',
               'accept_demo': 'confirmed', 'decline': 'paused', 'resume': 'invite',
               'close': 'closed', 'faq_agency': 'faq_agency', 'faq_terms': 'faq_terms',
               'faq_invite': 'faq_invite', 'faq_benefits': 'faq_benefits', 'retry': 'faq_unavailable',
               'topic_partnership': 'faq_partnership', 'topic_more': 'faq_more',
               'topic_lives': 'faq_unavailable', 'topic_club': 'faq_unavailable',
               'stop': 'stopped', 'leave_help': 'leave_help', 'help_checked': 'help_screen'}
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
    if not choices:
        return {'content': text, 'message_type': 'outgoing', 'private': False, 'content_type': 'text'}
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


def normalize_intent(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 500:
        return ''
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', text).strip()


def free_intent(text):
    """Conservative, deterministic intent only. Never authorizes an effect.

    Quotes, hypotheticals, questions and negated requests cannot start a flow.
    Clear requests to stop outrank all other intentions. Unknown wording remains
    a question for the grounded path, not an inferred commercial authorization.
    """
    value = normalize_intent(text)
    if not value:
        return None
    if re.search(r'["“”«»]|\b(?:se eu|se alguem|caso eu|hipoteticamente|por exemplo|exemplo de|ele disse|ela disse)\b', value):
        return None
    value = re.sub(r'^(?:(?:oi|ola|bia|por favor)[ ,.!:]+)+', '', value).strip(' .!')
    # Only direct clauses, never an arbitrary substring inside a reported request.
    clauses = re.split(r'[.!;\n]+\s*|,\s*(?:mas\s+)?|\s+(?:mas|e)\s+(?=(?:pare|para|nao|quero))', value)
    stop = r'(?:pare|para|parem|parar|quero parar|pode parar) (?:de (?:me )?(?:mandar|enviar|receber) (?:mais )?mensage(?:m|ns)|(?:com )?(?:as )?mensage(?:m|ns))'
    no_messages = r'nao (?:quero(?: (?:mais )?receber)?|(?:me )?(?:mande|envie)(?: mais)?) (?:mais )?mensage(?:m|ns)'
    if any(re.fullmatch(r'(?:' + stop + '|' + no_messages + r'|nao me contate(?: mais)?|remova meu contato|cancele as mensage(?:m|ns))(?: (?:por favor|aqui|neste ensaio|para mim|pra mim))?[.!? ]*', part.strip()) for part in clauses):
        return 'stop'
    if re.search(r'\b(?:nao (?:quero|preciso|desejo|tenho interesse)|nao me|nao pare|nao e para|nao vou|nao posso|sem interesse)\b', value):
        if re.fullmatch(r'(?:eu )?(?:nao (?:tenho interesse(?: em (?:me agenciar|entrar na agencia|participar))?|quero (?:me agenciar|entrar(?: na agencia)?|participar|continuar))|sem interesse)(?: (?:agora|por enquanto))?(?:,? obrigado|,? obrigada)?', value):
            return 'pause' if re.search(r'\b(?:agora|por enquanto)\b', value) else 'decline'
        return None
    human_pattern = r'(?:eu )?(?:(?:quero|preciso|gostaria de) (?:falar|conversar) com (?:um |uma )?(?:humano|humana|pessoa|atendente)|(?:quero|preciso de) (?:um |uma )?(?:humano|humana|atendente)|(?:me )?(?:transfira|encaminhe)(?: para)? (?:um |uma )?(?:humano|humana|pessoa|atendente))(?: (?:por favor|de verdade|real|agora))?'
    human = any(re.fullmatch(human_pattern, part.strip()) for part in clauses)
    polite_human = re.fullmatch(r'(?:pode|poderia) me (?:passar|transferir|encaminhar) para (?:um |uma )?(?:humano|humana|pessoa|atendente)\??', value)
    if human or polite_human or value in {'atendimento humano', 'falar com atendente', 'falar com humano', 'tem atendimento humano?'}:
        return 'human'
    if '?' in value:
        return None
    leave = re.fullmatch(r'(?:eu )?(?:quero|gostaria de|preciso) (?:sair|me desligar) (?:da agencia|da amplify)|(?:eu )?quero cancelar (?:meu |o )?(?:agenciamento|vinculo|contrato)', value)
    if leave:
        return 'leave'
    if value in {'retomar', 'quero retomar', 'retomar explicacao'}:
        return 'resume'
    if value in {'sair', 'quero sair', 'cancelar', 'quero cancelar', 'parar', 'quero parar'}:
        return 'leave_clarify'
    pause = re.search(r'\b(?:agora nao|nao agora|mais tarde|depois|outra hora|por enquanto nao|pausar|dar um tempo)\b', value)
    interest = re.search(r'\b(?:(?:quero|gostaria de|tenho interesse em) (?:me agenciar|entrar (?:na agencia|na amplify)|participar (?:da agencia|da amplify)|conhecer as etapas)|quero ser agenciado|quero ser agenciada)\b', value)
    if interest:
        if pause or re.search(r'\b(?:mas|antes|se|talvez|depende|ou|ainda|quanto|custa|comissao|gratis)\b', value):
            return 'ambiguous'
        if re.fullmatch(r'(?:eu )?(?:(?:quero|gostaria de|tenho interesse em) (?:me agenciar|entrar (?:na agencia|na amplify)|participar (?:da agencia|da amplify)|conhecer as etapas)|quero ser agenciad[oa])(?: (?:por favor|agora))?', value):
            return 'interest'
        return 'ambiguous'
    if pause and re.fullmatch(r'(?:agora nao|nao agora|(?:vamos |quero |pode )?(?:deixar (?:isso )?(?:para )?(?:depois|mais tarde|outra hora)|pausar)|mais tarde|depois|outra hora|por enquanto nao|(?:quero )?dar um tempo)(?: (?:por favor|agora))?', value):
        return 'pause'
    if re.search(r'\bconvite\b', value) and re.search(r'\b(?:nao aparece|nao apareceu|nao chegou|nao recebi|nao consigo|erro|falha|expirou|expirado|deu errado|problema|dificuldade)\b', value):
        return 'difficulty'
    if value in {'aceito', 'pode mandar', 'pode enviar', 'pode falar', 'quero entrar', 'tenho interesse'}:
        return 'ambiguous'
    return None


def safe_resume(resume_step):
    # A pause before profile collection must never jump straight to invitation.
    return resume_step if resume_step in RETURN_STEPS - {'opening', 'about', 'member', 'paused'} else 'about'


def _intent_decision(intent, step, *, resume_step=None, difficulty_stage=0, text=''):
    target = {'stop': 'stopped', 'pause': 'paused', 'decline': 'declined', 'human': 'human_unavailable',
              'leave': 'leave_help', 'leave_clarify': 'leave_clarify', 'ambiguous': 'intent_clarify'}.get(intent)
    if intent == 'resume':
        target = safe_resume(resume_step)
    if intent == 'interest':
        target = resume_step if resume_step in {'profile', 'conditions', 'invite', 'confirmed'} else 'profile'
    if intent == 'difficulty':
        if difficulty_stage >= 3:
            return {'action': 'difficulty_bounded', 'step': step, 'effects': [], 'no_op': True}
        target = ('help_account' if difficulty_stage == 0 and not re.search(r'ja (?:conferi|verifiquei)', normalize_intent(text))
                  else 'help_screen' if difficulty_stage < 2 else 'help_unavailable')
    if target:
        result = {'action': 'intent_' + intent, 'step': target, 'effects': []}
        if target == step:
            result['no_op'] = True
        if target.startswith('help_'):
            result['difficulty_stage'] = {'help_account': 1, 'help_screen': 2, 'help_unavailable': 3}[target]
        return result
    return None


def decision(step, text, *, correlated, opening_choices, question_answerer=None, resume_step=None,
             last_question=None, current_choices=None, pending_clarification='', difficulty_stage=0):
    choices = current_choices if current_choices is not None else (opening_choices if step == 'opening' else TEMPLATES[step][1])
    action = next((action for action, title in choices.items() if text == title), None) if correlated else None
    if step in TERMINAL_STEPS:
        return None
    intent = free_intent(text) if not action else None
    if intent:
        return _intent_decision(intent, step, resume_step=resume_step, difficulty_stage=difficulty_stage, text=text)
    if action == 'resume':
        return {'action': action, 'step': safe_resume(resume_step), 'effects': []}
    if action == 'help_checked':
        return {'action': action, 'step': 'help_screen', 'effects': [], 'difficulty_stage': 2}
    # A bounded diagnostic gathers no credentials and never retries an invite.
    if not action and step in {'help_account', 'help_screen'}:
        return _intent_decision('difficulty', step, difficulty_stage=max(difficulty_stage, 1 if step == 'help_account' else 2), text=text)
    # Old buttons must not restart the introduction after deployment.
    if action == 'opening' or text in {'Voltar ao início', 'Recomeçar teste'}:
        return None
    if not action and step == 'profile' and isinstance(text, str) and re.fullmatch(r'@[A-Za-z0-9_.]{2,24}', text.strip()):
        return {'action': 'profile_received', 'step': 'conditions', 'effects': [('tiktok', 'eligible')]}
    if step in KNOWLEDGE_STEPS and action == 'back':
        return {'action': action, 'step': 'about', 'effects': []}
    if step in CONTEXT_STEPS and action == 'join':
        target = resume_step if resume_step in RETURN_STEPS else 'profile'
        if target in {'opening', 'about', 'member', 'paused'}:
            target = 'profile'
        return {'action': action, 'step': target, 'effects': []}
    # An acknowledgment is not a request to start or resume collecting data.
    if (not action and step != 'closed' and isinstance(text, str)
            and text.strip().casefold().rstrip('.!') in {'sim', 'ok', 'entendi', 'continuar', 'continue', 'certo', 'obrigado', 'obrigada'}
            and not pending_clarification):
        return {'action': 'acknowledge', 'step': step, 'effects': [], 'no_op': True}
    target = TRANSITIONS[action] if action else question_step(text)
    # Except explicitly recognized safe intents, bare labels require correlation.
    # Free text never authorizes invite/acceptance effects, even if AI errs.
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
