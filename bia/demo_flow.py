"""Draft demo copy and transitions. No provider, personal data, URLs or real terms."""
import re
import unicodedata
import uuid

FLOW_VERSION = 'v2'
TEMPLATES = {
    'about': ('Somos a *Amplify*, uma agência de creators do TikTok Shop 💜\n\nQuer seguir com o seu agenciamento?',
              {'join': 'Quero me agenciar', 'question': 'Tenho uma dúvida', 'opening': 'Voltar ao início'}),
    'profile': ('Vamos nessa! 💜\n\nNeste teste, vamos usar um perfil de exemplo para conhecer as próximas etapas.',
                {'use_profile': 'Usar perfil de teste', 'question': 'Tenho uma dúvida', 'opening': 'Voltar ao início'}),
    'member': ('Que bom te ver por aqui de novo! 💜\n\nComo posso te ajudar? Neste teste, não vou consultar seu cadastro.',
               {'question': 'Tenho uma dúvida', 'join': 'Ver o agenciamento', 'opening': 'Voltar ao início'}),
    'conditions': ('Antes de um convite real, você precisa conhecer e confirmar as condições 💜\n\nAqui vamos simular essa etapa, sem aceitar condições comerciais.',
                   {'continue_test': 'Seguir no teste', 'question': 'Tenho uma dúvida', 'opening': 'Voltar ao início'}),
    'invite': ('Convite de demonstração preparado 💜\n\nQuer simular o aceite para ver como a confirmação aparece?',
               {'accept_demo': 'Simular aceite', 'decline': 'Agora não', 'question': 'Tenho uma dúvida'}),
    'confirmed': ('Teste concluído! 💜\n\nO aceite e o vínculo foram simulados. Seu perfil real não foi consultado nem agenciado.',
                  {'opening': 'Recomeçar teste', 'question': 'Tenho uma dúvida', 'close': 'Encerrar teste'}),
    'paused': ('Tudo bem 😊\n\nO convite de teste ficou pausado. Quer retomar ou voltar ao início?',
               {'resume': 'Retomar teste', 'opening': 'Voltar ao início', 'close': 'Encerrar teste'}),
    'faq': ('Claro! 💜 Sobre o que você quer saber?',
            {'faq_agency': 'Como funciona?', 'faq_terms': 'Quais condições?', 'faq_invite': 'Sobre o convite'}),
    'faq_agency': ('Você pode conhecer a Amplify e tirar suas dúvidas antes de decidir se quer seguir 💜\n\nAqui mostramos as etapas com perfil e vínculo de exemplo.',
                   {'join': 'Quero me agenciar', 'faq_terms': 'Quais condições?', 'opening': 'Voltar ao início'}),
    'faq_terms': ('As condições reais ainda precisam ser confirmadas 💜\n\nNesta demonstração, nenhuma comissão, prazo ou exclusividade é aceita.',
                  {'join': 'Seguir no teste', 'faq_invite': 'Sobre o convite', 'opening': 'Voltar ao início'}),
    'faq_invite': ('Aqui, nenhum convite real é enviado 😊\n\nO botão serve para você experimentar como seria o aceite e a confirmação.',
                   {'join': 'Seguir no teste', 'faq_terms': 'Quais condições?', 'opening': 'Voltar ao início'}),
    'closed': ('Teste encerrado 💜\n\nSe quiser começar de novo, é só tocar abaixo.',
               {'opening': 'Recomeçar teste'}),
}
TRANSITIONS = {'join': 'profile', 'know': 'about', 'member': 'member', 'question': 'faq',
               'opening': 'opening', 'use_profile': 'conditions', 'continue_test': 'invite',
               'accept_demo': 'confirmed', 'decline': 'paused', 'resume': 'invite',
               'close': 'closed', 'faq_agency': 'faq_agency', 'faq_terms': 'faq_terms',
               'faq_invite': 'faq_invite'}


def key_parts(key):
    match = re.fullmatch(r'bia-demo:v2:([a-f0-9]{32}):([a-z_]{1,24}):([a-f0-9]{16})', key) if isinstance(key, str) else None
    if not match or match[2] not in {'opening', *TEMPLATES}:
        raise ValueError('demo_flow_key_invalid')
    return match[1], match[2], match[3]


def new_key(run, step):
    key = 'bia-demo:v2:' + run + ':' + step + ':' + uuid.uuid4().hex[:16]
    key_parts(key)
    return key


def payload(key, opening, opening_choices):
    _, step, _ = key_parts(key)
    text, choices = (opening, opening_choices) if step == 'opening' else TEMPLATES[step]
    return {'content': text, 'message_type': 'outgoing', 'private': False, 'content_type': 'input_select',
            'content_attributes': {'items': [{'title': title, 'value': key + ':' + action}
                                            for action, title in choices.items()]}}


def question_step(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 500:
        return None
    value = ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))
    if re.search(r'comiss|condic|prazo|exclusiv|benefici|quanto|custa|paga|ganh', value):
        return 'faq_terms'
    if re.search(r'convite|aceite|vinculo', value) and ('?' in value or re.search(r'como|duvida|pergunta', value)):
        return 'faq_invite'
    if '?' in value or re.search(r'\b(como|duvida|pergunta)\b', value):
        return 'faq'
    return None


def decision(step, text, *, correlated, opening_choices):
    choices = opening_choices if step == 'opening' else TEMPLATES[step][1]
    action = next((action for action, title in choices.items() if text == title), None) if correlated else None
    target = TRANSITIONS[action] if action else question_step(text)
    if not target:
        return None
    effects = []
    if action == 'use_profile':effects = [('tiktok', 'eligible')]
    elif action == 'continue_test':effects = [('invite', 'unknown')]
    elif action == 'accept_demo':effects = [('invite', 'accepted'), ('relationship', 'linked')]
    return {'action': action or 'question', 'step': target, 'effects': effects}
