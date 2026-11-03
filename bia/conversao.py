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

BRIDGE_NOTE = 'Seu @ continua anotado: eu confiro sozinha assim que o sistema do TikTok liberar e te chamo aqui. 😊'
INVITING = 'Combinado! Tô enviando o convite da Amplify para o seu TikTok agora 🔎 Te aviso aqui assim que sair.'
INVITE_WHERE = ('O convite da *Amplify* fica no app do TikTok Shop Creator, em *Parcerias* ou *Notificações*. '
                'Às vezes ele leva alguns minutos para aparecer. Quando aceitar, me manda “aceitei” que eu confiro na hora. 😊')

# Release 41 (conversas de 02/11, aprovadas pelo usuário).
ACCESS_DONE = ('Seu cadastro já está feito e seu acesso ao *Amplify Club* foi liberado 🎉 '
               'Para entrar, use o Circle com o mesmo e-mail do cadastro: o convite de acesso foi para esse e-mail. '
               'Se precisar de algo, é só me chamar por aqui.')
MISSIONS = ('As campanhas e missões ficam no *Amplify Club*, no Circle. Entre com o mesmo e-mail do cadastro: '
            'lá você vê as oportunidades abertas e se candidata às que combinam com seu perfil. 😊')
ACCESS_HINT = 'Seu acesso ao *Amplify Club* já está liberado: entre no Circle com o mesmo e-mail do cadastro. 😊'
SAMPLES = ('Tem sim! 😊 As campanhas com amostras aparecem no *Amplify Club* e você se candidata às que combinam '
           'com seu perfil. A liberação de cada amostra depende da marca e da campanha.')
INVITE_WAIT = ('Sua autorização está anotada! ✅ O sistema do TikTok tá lento para enviar convites agora, '
               'mas eu envio sozinha assim que liberar e te aviso aqui. Você não precisa fazer nada.')
INVITE_STILL = 'Sua autorização continua anotada: eu envio o convite sozinha assim que o sistema do TikTok liberar e te aviso aqui. 😊'
INVITE_CHECK = 'Vou conferir agora no TikTok como está o seu convite 🔎'
PRIOR_INVITE_CHECK = 'Você já tem um convite da Amplify de antes. Vou conferir agora no TikTok como ele está 🔎'
INVITE_STEPS = ('Seu convite da *Amplify* está esperando no TikTok. Para aceitar:\n'
                '1. Abra o app do *TikTok Shop Creator* (ou a Central do criador no TikTok).\n'
                '2. Vá em *Parcerias* ou em *Notificações*.\n'
                '3. Toque no convite da *Amplify* e em *Aceitar*.\n\n'
                'Quando aceitar, me manda “aceitei” que eu confiro na hora. 😊')
PRIOR_INVITE_RESENT = 'Seu convite anterior não está mais no TikTok, então estou enviando um novo agora 🔎 Te aviso aqui assim que sair.'
SHOP_STEPS = ('Te mostro o caminho 😊\n'
              '1. No app do TikTok, abra o seu *perfil*.\n'
              '2. Toque no menu (as três linhas no canto de cima) e procure *TikTok Shop* ou '
              '*Central do criador do TikTok Shop*.\n'
              '3. Siga os passos para ativar a conta de criador do TikTok Shop.\n\n'
              'Quando aparecer como ativo, me manda “pronto” que eu confiro de novo.')


# Release 42 (02/11, textos aprovados pelo usuário). Saem como estão, sem o filtro de um emoji por parágrafo.
def invite_sent_now(name):
    return ('Pronto' + (', ' + name if name else '') + '! Seu convite da Amplify foi enviado agora 🎉 '
            'Abra o TikTok Shop Creator → Parcerias ou Notificações → aceite o convite da Amplify. '
            'Quando aceitar, eu já fico sabendo e te mando o cadastro 😊')


INVITE_ACCEPTED = ('Vi aqui que você aceitou o convite! 🎉 Agora falta só o cadastro, '
                   'e seu acesso ao Club sai na hora em que você envia.')
INVITE_IS_THERE = ('Seu convite está lá, sim! 😊 Para achar:\n'
                   '1. Abra o TikTok Shop Creator (não é o TikTok comum)\n'
                   '2. Toque em Parcerias (ou no sininho de Notificações)\n'
                   '3. Procure o convite da Amplify e toque em Aceitar.\n\n'
                   'Se não achar mesmo, me avisa que eu envio de novo.')

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
