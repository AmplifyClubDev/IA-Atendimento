"""Deterministic declared qualification. No provider calls or inferred eligibility."""
from decimal import Decimal, InvalidOperation
import re
import unicodedata
import engine
import tutorial_videos

THRESHOLD_CENTS = 5_000_000
QUESTIONS = {
    'agency': ('Você já está agenciado? Se estiver, é pela Amplify ou por outra agência?', ['Já sou Amplify', 'Outra agência', 'Não sou agenciado']),
    'agency_kind': ('Seu vínculo atual é com a Amplify ou com outra agência?', ['Já sou Amplify', 'Outra agência']),
    'existing_profile': ('Se você já é agenciado pela Amplify, não precisa se desvincular nem receber outro convite. Qual é seu @ do TikTok para seguir com o cadastro?', []),
    'unlink': ('Para se agenciar com a Amplify, você precisa primeiro se desvincular da outra agência no TikTok Shop. Confira as condições do seu vínculo atual.\n\nQuando concluir, me avise por aqui.', ['Já me desvinculei']),
    'shop': ('Seu TikTok Shop Creator já está ativado?', ['Sim', 'Não', 'Não sei']),
    'activate': ('Para seguir com o agenciamento, ative o TikTok Shop Creator na sua conta. Quando estiver ativo, me avise para eu conferir o perfil.', ['Já está ativo']),
    'gmv': ('Qual foi seu GMV (total vendido no TikTok Shop) nos últimos 30 dias, em reais? Pode informar um valor aproximado, por exemplo: 50 mil.', []),
    'gmv_zero_confirmation': ('Só para confirmar: você ainda não fez nenhuma venda no TikTok Shop nos últimos 30 dias?', ['Sim, nenhuma venda', 'Já tive vendas']),
    'choice': ('Você pode seguir o agenciamento por aqui com a Bia ou falar com um especialista da Amplify. Como prefere continuar?', ['Seguir com a Bia', 'Especialista']),
    'specialist': ('Sua preferência por um especialista da Amplify ficou registrada. O agenciamento automático está pausado. Se mudar de ideia, pode escolher continuar com a Bia.', ['Seguir com a Bia']),
}
QUESTIONS['activate'] = (tutorial_videos.activation_help(QUESTIONS['activate'][0]), QUESTIONS['activate'][1])


def parse_gmv(text):
    """BRL cents. Reject ranges, comparisons, foreign currency and ambiguous prose."""
    value = ''.join(c for c in unicodedata.normalize('NFD', text.lower().strip()) if not unicodedata.combining(c))
    # Explicit no-sales declarations, not guesses from being new or wanting to learn.
    if re.fullmatch(r'(?:ainda nao vendi|nao vendi nada|nunca vendi|nao fiz nenhuma venda|nenhuma venda|zero)(?:[.!]?(?: quero aprender)?)?[.!]?', value):
        return 0
    # Explicit first-person no-sales statements with a narrow consumer prefix.
    # Do not infer zero from being new, purchases, questions or mixed amounts.
    if re.fullmatch(
            r'(?:(?:eu )?compro (?:as )?coisas (?:pra|para) mim(?: mesmo| mesma)?[,.;] ?)?'
            r'(?:eu )?(?:ainda nao vendi(?: nada)?|nunca vendi(?: nada)?|nao fiz nenhuma venda)'
            r'(?: (?:pelo|no) tiktok shop)?[.!]?', value):
        return 0
    value = re.sub(r'^(?:fiz|vendi|meu gmv foi|meu gmv e|foi|cerca de|aproximadamente)\s+', '', value)
    match = re.fullmatch(r'(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?|\d+\.\d{1,2})\s*(k|mil|milhao|milhoes)?(?:\s*(?:reais|brl))?', value)
    if not match:
        return None
    number, unit = match.groups()
    if ',' in number:
        number = number.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', number):
        number = number.replace('.', '')
    try:
        amount = Decimal(number) * {'k':1000,'mil':1000,'milhao':1_000_000,'milhoes':1_000_000,None:1}[unit] * 100
        if amount != amount.to_integral_value() or not 0 <= amount <= 100_000_000_000:
            return None
        return int(amount)
    except (InvalidOperation, ValueError):
        return None


def stage(cycle):
    record = cycle.get('bia_validation') or {}
    return record.get('stage')


def permitted(cycle):
    record = cycle.get('bia_validation')
    return not record or record.get('stage') == 'complete'


def eligible_to_begin(cycle):
    return (cycle.get('facts', {}).get('interesse_agenciamento') is True
            and not cycle.get('form_entry_request')
            and cycle.get('phase') in {'intro','origin','tiktok','shop','agency','checking'}
            and not cycle.get('real_operations', {}).get('invite'))


def begin(cycle, at):
    if cycle.get('bia_validation') or not eligible_to_begin(cycle):
        return None
    cycle['bia_validation'] = {'version':1, 'stage':'agency', 'opened_at':engine._stamp(at)}
    cycle['phase'] = 'validation'
    return QUESTIONS['agency']


def advance(cycle, text, at):
    """Returns next question or None when declared qualification is complete."""
    record = cycle['bia_validation']; current = record['stage']
    if current == 'complete':
        return None
    value = engine._normal(text).strip()
    yes = value in {'sim','sim tenho','sim esta ativo','esta ativo','ja esta ativo'}
    no = value in {'nao','nao tenho','nao esta ativo','nao sou agenciado','nao sou agenciada'}
    unknown = value in {'nao sei','nao sei informar','nao tenho certeza'}
    next_stage = current
    facts = cycle['facts']
    if current in {'agency','agency_kind'} and value in {'ja sou amplify','sou agenciado pela amplify','ja sou agenciado pela amplify','sou agenciada pela amplify','ja sou agenciada pela amplify'}:
        record['existing_amplify_declared'] = True
        facts['possui_agencia_declarada'] = False  # no declaration of OTHER agency
        next_stage = 'complete' if facts.get('tiktok_declarado') else 'existing_profile'
    elif current in {'agency','agency_kind'} and value in {'outra agencia','sou de outra agencia','sou agenciado por outra agencia'}:
        facts['possui_agencia_declarada'] = True
        next_stage = 'unlink'
    elif current == 'agency' and (yes or no or unknown):
        if yes:
            next_stage = 'agency_kind'
        else:
            facts['possui_agencia_declarada'] = False if no else None
            next_stage = 'shop'
    elif current == 'existing_profile' and re.fullmatch(r'@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}', text.strip()):
        facts['tiktok_declarado'] = text.strip().lower()
        next_stage = 'complete'
    elif current == 'unlink' and value in {'ja me desvinculei','ja desvinculei','desvinculei','nao estou mais agenciado','nao estou mais agenciada'}:
        facts['possui_agencia_declarada'] = False
        next_stage = 'shop'
    elif current == 'shop' and (yes or no or unknown):
        facts['shop_ativo_declarado'] = True if yes else False if no else None
        next_stage = 'activate' if no else 'gmv'
    elif current == 'activate' and value in {'ja esta ativo','ativei','ja ativei','shop ativo'}:
        facts['shop_ativo_declarado'] = True
        next_stage = 'gmv'
    elif current in {'gmv', 'gmv_zero_confirmation'}:
        amount = parse_gmv(text)
        if current == 'gmv_zero_confirmation':
            if value in {'sim', 'sim nenhuma venda', 'sim, nenhuma venda'}:
                amount = 0
            elif value in {'nao', 'ja tive vendas', 'nao ja tive vendas'}:
                record['stage'] = 'gmv'
                record['updated_at'] = engine._stamp(at)
                return ('Entendi. Qual foi o total aproximado vendido nos últimos 30 dias, em reais?', [])
            elif amount is None:
                # Ambiguity cannot answer this specific zero confirmation.
                return QUESTIONS['gmv_zero_confirmation']
        elif amount is None and re.fullmatch(
                r'(?:eu )?(?:ainda nao comecei|nao comecei ainda|so ativei (?:a conta|o shop)|somente ativei (?:a conta|o shop))'
                r'(?:[,.;]? (?:so|somente|apenas) ativei (?:a conta|o shop))?[.!]?', value):
            record['stage'] = 'gmv_zero_confirmation'
            record['updated_at'] = engine._stamp(at)
            return QUESTIONS['gmv_zero_confirmation']
        if amount is not None or unknown:
            facts['gmv_30d_declarado_centavos'] = amount
            facts['gmv_30d_moeda'] = 'BRL'
            record['gmv_source'] = 'lead_declaration'
            record['gmv_at'] = engine._stamp(at)
            next_stage = 'choice' if amount is not None and amount >= THRESHOLD_CENTS else 'complete'
            if next_stage == 'choice':
                record['high_gmv'] = True
                record['alert_requested'] = True
    elif current in {'choice','specialist'}:
        if value in {'seguir com a bia','continuar com a bia','com a bia','maquina','com a maquina'}:
            record['preference'] = 'machine'
            next_stage = 'complete'
        elif current == 'choice' and value in {'falar com especialista','especialista','com especialista','com um especialista'}:
            record['preference'] = 'specialist'
            record['handoff_requested'] = True
            next_stage = 'specialist'
    record['stage'] = next_stage
    record['updated_at'] = engine._stamp(at)
    cycle['phase'] = 'validation'
    if current == 'shop' and unknown:
        # Keep unknown as unknown; this is guidance, not a negative eligibility decision.
        text = ('Se não tiver certeza, confira no app se você tem acesso à Central do criador do TikTok Shop. '
                'O vídeo mostra como ativar, caso ainda não esteja ativo.\n\n' + QUESTIONS['gmv'][0])
        return tutorial_videos.activation_help(text), []
    return None if next_stage == 'complete' else QUESTIONS[next_stage]
