"""Approved Bia presentation for REAL journeys. No providers or simulated facts.

Menus only render text. The real journey owns qualification, consent and effects.
Version is pinned to each fresh cycle so deploys never reset in-flight work.
"""
VERSION = 'bia-approved-v1'
OPENING = ('Oi! Que bom ter você por aqui 💙\n\n'
           'Eu sou a Bia, assistente de IA da *Amplify*, uma agência de creators do TikTok Shop.\n\n'
           'Como posso te ajudar hoje? 😊')
CHOICES = ['Quero fazer parte', 'Conhecer a Amplify', 'Já sou Amplify']
MENUS = {
    'conhecer a amplify': ('O que você quer conhecer? ✨\n\nEscolha um tema ou escreva sua dúvida.',
                          ['Conhecer benefícios', 'Parceria e regras', 'Mais assuntos']),
    'parceria e regras': ('Vamos falar da parceria 🤝\n\nEscolha um tema ou escreva sua dúvida.',
                         ['Regras e saída', 'Convite e aceite', 'Ver tópicos']),
    'mais assuntos': ('Qual assunto te interessa? 💬\n\nVocê também pode escrever sua dúvida.',
                     ['Lives e conteúdo', 'Amplify Club', 'Ver tópicos']),
    'tenho uma duvida': ('Claro! Me conta sua dúvida por aqui 💬', ['Ver tópicos']),
}
MENUS['ver topicos'] = MENUS['conhecer a amplify']
MENUS['tenho outra duvida'] = MENUS['tenho uma duvida']
MENUS['tenho duvidas'] = MENUS['tenho uma duvida']
TOPICS = {
    'conhecer beneficios': 'Quais são os benefícios da parceria?',
    'regras e saida': 'Quais são as regras da parceria e como funciona a saída?',
    'convite e aceite': 'Como funciona o convite e o aceite da parceria?',
    'lives e conteudo': 'Preciso fazer lives para participar da parceria?',
    'amplify club': 'O que é o Amplify Club e como funciona o acesso?',
}
