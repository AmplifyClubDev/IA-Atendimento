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
# Release 51: sem prometer quanto tempo a conferência leva (card 'ensaio').
RECEIVED = 'Recebi, {handle}! Já tô conferindo seu perfil 🔎'
RETURNED = ('Oi de novo! Aqui é a Bia, da Amplify. Ainda tenho seu {handle} anotado. '
            'Já tô conferindo seu perfil 🔎')

BRIDGE_WAIT = 'Seu perfil está registrado. Ainda não tenho a confirmação necessária para avançar.'
BRIDGE_STILL = 'Seu perfil está registrado. A validação ainda está pendente.'
BRIDGE_BACK = 'Pronto, conferi! ✅'
SHOP_UNKNOWN = ('O TikTok ainda não trouxe a informação que preciso para confirmar a elegibilidade do seu perfil. '
                'Isso não significa que o seu TikTok Shop Creator esteja inativo. '
                'Se você já usa a Central do criador do TikTok Shop, me manda “pronto” para eu conferir de novo. '
                'Se o @ estiver diferente do que aparece no app, pode me mandar o @ correto.')


def shop_reminder(step):
    """Uma informação ausente não comprova que a conta precisa ser ativada."""
    if step == 1:
        return ('Seu perfil ainda está sem confirmação de elegibilidade pelo TikTok. '
                'Se você já usa o TikTok Shop Creator, me manda “pronto” para uma nova consulta.')
    if step == 2:
        return ('Pode conferir se o @ enviado está igual ao que aparece no seu TikTok? '
                'Se estiver diferente, me manda o @ correto e eu confirmo a alteração antes de consultar. '
                'Se estiver certo, me manda “pronto” para conferir novamente.')
    return ('Seu @ continua anotado por aqui. Quando quiser retomar a consulta, me manda “pronto”. 💙')

BRIDGE_NOTE = 'Seu perfil está registrado. A validação ainda está pendente.'
INVITING = 'Combinado! Sua autorização para o convite está registrada. 😊'
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
INVITE_WAIT = 'Sua autorização está registrada. O envio do convite ainda não está confirmado.'
INVITE_STILL = 'Sua autorização está registrada. O envio do convite ainda não está confirmado.'
INVITE_CHECK = 'Vou conferir agora no TikTok como está o seu convite 🔎'
PRIOR_INVITE_CHECK = 'Você já tem um convite da Amplify de antes. Vou conferir agora no TikTok como ele está 🔎'
INVITE_STEPS = ('Seu convite da *Amplify* está esperando no TikTok. Para aceitar:\n'
                '1. Abra o app do *TikTok Shop Creator* (ou a Central do criador no TikTok).\n'
                '2. Vá em *Parcerias* ou em *Notificações*.\n'
                '3. Toque no convite da *Amplify* e em *Aceitar*.\n\n'
                'Quando aceitar, me manda “aceitei” que eu confiro na hora. 😊')
PRIOR_INVITE_RESENT = 'Sua autorização está registrada. O envio do novo convite ainda não está confirmado.'
SHOP_STEPS = ('Vamos conferir o que aparece no seu app 😊\n'
              '1. No app do TikTok, abra o seu *perfil*.\n'
              '2. Toque no menu (as três linhas no canto de cima) e procure *TikTok Shop* ou '
              '*Central do criador do TikTok Shop*.\n'
              '3. Confira se a Central do criador já está disponível e se o @ está igual ao que você me enviou.\n\n'
              'Se a Central já estiver disponível, me manda “pronto” para eu consultar de novo. '
              'Se não encontrar essa opção, me diga o que aparece na tela.')


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
                   'Se não encontrar, me diga o que aparece na tela.')

# Release 43 (02/11): nenhum lead fica sem resposta em silêncio. Textos novos, para aprovação do usuário.
NOT_INTERESTED = 'Tudo bem! Se mudar de ideia, é só chamar 💙'
INVITE_NOT_LANDED = 'O convite ainda não aparece no TikTok.'
INVITE_STILL_MISSING = 'O convite ainda não aparece no TikTok.'
INBOUND_FALLBACK = ('Recebi sua mensagem! 🙏 Tive uma instabilidade aqui e não consegui responder agora. '
                    'Pode me mandar de novo, por favor?')
OPERATION_FALLBACK = 'Ainda não tenho a confirmação dessa etapa.'

# Release 43, seção 5b (códigos das pontes): os dois primeiros vêm da tabela do usuário; os outros, para aprovação.
# Textos que já existiam no código, com nome para a tabela dos códigos.
INVITE_SENT = 'Seu convite foi enviado! 🎉'
INVITE_ALREADY_THERE = 'Seu convite já está no TikTok. 😊'
RELATIONSHIP_RETRY = 'Não consegui consultar o TikTok agora.'
INVITE_CONFIRMING = 'O envio do convite ainda não está confirmado.'
INVITE_RETRYING = 'O envio do convite ainda não está confirmado.'
# Release 51: nada de equipe ou atendimento humano no texto ao lead (o alerta da ponte segue por e-mail).
INVITE_FAILED_TEAM = 'Não foi possível concluir o envio do convite agora. Sua autorização está registrada.'
PROFILE_INELIGIBLE = ('Conferi seu perfil e, por enquanto, ele ainda não pode entrar na Amplify 😕 Quando o seu TikTok '
                      'Shop Creator estiver ativo e liberado, é só me chamar aqui que eu confiro de novo 💙')
SHOP_RECHECK_SOON = ('Acabei de conferir há pouquinho 😊 Me manda “pronto” de novo daqui a uns 10 minutos que eu '
                     'confiro outra vez.')

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


def auto_invite(name, handle, policy):
    """Release 52: perfil aprovado, o convite sai na hora; as condições vêm junto e o lead aceita no TikTok."""
    return ('Boa notícia' + (', ' + name if name else '') + ': seu perfil pode entrar na Amplify! 🎉\n\n'
            '• o seu conteúdo e as suas vendas continuam sendo seus\n'
            f'• a Amplify fica com {rate(policy)}% só da comissão que você ganhar (se não vender, não paga nada)\n'
            f'• prazo de {policy["duration_label"]}\n\n'
            'Essas são as condições da parceria para o perfil ' + handle + '.')


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
        return ('A conferência do seu perfil é feita aqui mesmo e você não precisa preencher nada agora. '
                'É só me mandar seu @ do TikTok 👇'), []
    return ('Vou deixar seu atendimento em pausa por aqui. Quando quiser, é só me mandar seu @ do TikTok. 😊'), \
        ['Quero entrar', 'Agora não']


def registration_reminder(step, name, url):
    hello = 'Oi' + (', ' + name if name else '') + '! '
    if step == 1:
        return (hello + 'Seu vínculo com a Amplify já está ativo 🎉 Continue seu cadastro pelo mesmo navegador '
                'para recuperar as respostas salvas. Se já confirmou o e-mail, siga para as próximas etapas.\n' + url)
    return (hello + 'Conseguiu concluir seu cadastro na Amplify? Se parou no código, confira o pedido mais recente '
            'no e-mail e no formulário, inclusive em Spam e Promoções. Se o e-mail já está confirmado, '
            'continue de onde parou pelo mesmo navegador. 😊\n' + url)

# Tutorials supplied and authorized by Amplify; explicit help can be requested again.
import tutorial_videos
INVITE_WHERE = tutorial_videos.invitation_help(INVITE_WHERE)
INVITE_STEPS = tutorial_videos.invitation_help(INVITE_STEPS)
INVITE_IS_THERE = tutorial_videos.invitation_help(INVITE_IS_THERE)
SHOP_STEPS = tutorial_videos.activation_help(SHOP_STEPS)
