"""Textos de conversão da release 40 (auditoria de 01/11, aprovados com 3 restrições).

Restrições: não citar quantos creators há no Club; nada sobre regras depois do
prazo (só "prazo de 2 meses"); benefícios só os dos cartões de contexto aprovados
(campanhas com marcas, orientação sobre produtos e conteúdos, apoio em lives,
comunidade de creators), sem prometer venda nem renda.
"""

OPENING = 'Oi! Aqui é a Bia, agente de IA da Amplify 💙'
BENEFITS = ('A gente apoia creators do TikTok Shop com campanhas com marcas, orientação sobre produtos e conteúdos, '
            'apoio em lives e uma comunidade de creators.')
ASK_HANDLE = 'Quer ver se seu perfil pode entrar? Me manda seu @ do TikTok 👇'
CTA = 'Quer que eu confira se seu perfil pode entrar? Me manda seu @ do TikTok 👇'
FIRST_BUTTONS = ['Mandar meu @', 'Como funciona?']
HANDLE_HELP = 'Pode mandar! 😊 O @ é o nome que aparece logo abaixo da foto no seu perfil do TikTok, começando com @.'
WANTS_IN = 'Oba! 😊 Me manda seu @ do TikTok que eu já confiro se seu perfil pode entrar.'
NOT_NOW = 'Tudo bem! Quando quiser, é só me mandar seu @ do TikTok por aqui. 😊'
RECEIVED = 'Recebi, {handle}! Já tô conferindo seu perfil 🔎 Leva menos de 1 minuto.'
RETURNED = ('Oi de novo! Aqui é a Bia, da Amplify. Ainda tenho seu {handle} anotado. '
            'Já tô conferindo seu perfil 🔎 Leva menos de 1 minuto.')

BRIDGE_WAIT = ('Anotei seu @! O sistema do TikTok tá um pouco lento agora, mas eu confiro sozinha assim que liberar '
               'e te chamo aqui. Você não precisa fazer nada 😊')
BRIDGE_STILL = ('O sistema do TikTok ainda tá lento, mas seu @ está anotado: eu confiro sozinha assim que liberar '
                'e te chamo aqui. 😊')
BRIDGE_BACK = 'Pronto, conferi! ✅'
SHOP_UNKNOWN = ('Conferi seu @, mas o TikTok não mostrou se o seu TikTok Shop Creator está ativo 😕 '
                'Dá uma olhada no app e, quando estiver ativo, me manda “pronto” que eu confiro de novo.')

CONSENT_BUTTONS = ['Pode mandar', 'Tenho uma dúvida']
CONSENT_QUESTION = 'Posso te mandar o convite no TikTok?'
DOUBT = ('Claro, pode perguntar! 😊 As dúvidas mais comuns:\n'
         '• *E se eu não vender?* Aí você não paga nada: a Amplify só fica com uma parte da comissão quando há venda.\n'
         '• *Preciso fazer live?* Não. Dá para participar com vídeos e conteúdos.\n\n'
         'Qual é a sua dúvida?')


def rate(policy):
    return f"{policy['commission']:g}".replace('.', ',')


def first_reply(policy, valid):
    price = (f'Não tem mensalidade: a Amplify fica com {rate(policy)}% só da comissão que você ganhar.'
             if valid else 'Não tem mensalidade nem taxa fixa para entrar.')
    return OPENING + ' ' + BENEFITS + '\n\n' + price + ' ' + ASK_HANDLE


def consent_full(name, handle, policy):
    return ('Boa notícia' + (', ' + name if name else '') + ': seu perfil pode entrar na Amplify! 🎉\n\n'
            '• o seu conteúdo e as suas vendas continuam sendo seus\n'
            f'• a Amplify fica com {rate(policy)}% só da comissão que você ganhar (se não vender, não paga nada)\n'
            f'• prazo de {policy["duration_label"]}\n\n'
            + CONSENT_QUESTION[:-1] + ' (' + handle + ')?')


def consent_reminder(step, policy):
    """Cada lembrete responde a uma objeção; o bloco das condições nunca se repete."""
    if step == 1:
        return ('Uma dúvida comum: *e se eu não vender?* Aí você não paga nada. A Amplify só fica com '
                f'{rate(policy)}% da comissão quando há venda. 😊 ' + CONSENT_QUESTION)
    if step == 2:
        return ('Outra dúvida comum: *preciso fazer live?* Não. Dá para participar com vídeos e conteúdos, '
                'e o apoio em lives fica disponível se você quiser. ' + CONSENT_QUESTION)
    return 'Vou deixar seu convite separado aqui. Quando quiser seguir, é só tocar em *Pode mandar*. 😊'


def intro_reminder(step):
    """Lembretes de quem ainda não mandou o @: cada um com um ângulo novo."""
    if step == 1:
        return ('Quer contar com campanhas com marcas e orientação sobre produtos no TikTok Shop? 😊 '
                'Me manda seu @ do TikTok que eu confiro se seu perfil pode entrar.'), []
    if step == 2:
        return ('A conferência do seu perfil leva 1 minutinho e você não precisa preencher nada agora. '
                'É só me mandar seu @ do TikTok 👇'), []
    return ('Vou deixar seu atendimento em pausa por aqui. Quando quiser, é só me mandar seu @ do TikTok. 😊'), \
        ['Quero entrar', 'Agora não']


def registration_reminder(step, name, url):
    hello = 'Oi' + (', ' + name if name else '') + '! '
    if step == 1:
        return (hello + 'Seu vínculo com a Amplify já está ativo 🎉 Falta só o cadastro: '
                'seu acesso ao Club sai na hora em que você envia.\n' + url)
    return (hello + 'Passando para lembrar do seu cadastro na Amplify. Leva poucos minutos e o acesso ao Club '
            'sai na hora em que você envia. 😊\n' + url)
