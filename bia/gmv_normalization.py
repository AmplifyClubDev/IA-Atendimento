"""Bruno-approved storage rules (2026-11-17); not verified TikTok revenue."""
import re
import unicodedata


def normalize_gmv(text):
    from lead_validation import parse_gmv
    t = ''.join(c for c in unicodedata.normalize('NFD', text.lower().strip())
                if not unicodedata.combining(c))
    t = re.sub(r'\s+', ' ', t).strip()
    if '?' in t or re.search(r'\b(?:usd|dolar|eur|comissao|comissoes|seguidores)\b', t):
        return None
    # Never silently convert another period or a sale/product count to 30-day GMV.
    if re.search(r'\b(?:dia|dias|mes|meses|novembro|periodo|produto|produtos|vendinha)\b|\d\s+vendas?\b', t):
        return None
    exact = parse_gmv(text)
    if exact is not None:
        return exact, 'aproximado' if re.match(r'(?:cerca de|aproximadamente)\b', t) else 'valor_explicito'
    if re.fullmatch(r'(?:nao|n) sei(?: dizer| informar)?[.!]*', t):
        return 0, 'nao_sabe'
    # Clear no-sales language; mixed amounts, actual sales or "almost" stay pending.
    if not re.search(r'\d|\b(?:quase|pouco|algumas|primeira venda|vendi [a-z]+ produtos)\b', t):
        no_sales = re.search(r'\b(?:nunca vendi|nunca fiz vendas?|nao vendi|nao vendo|nao faco vendas|nao tenho nenhuma venda|nao fiz vendas?|nao realizei vendas|nao realizei nenhuma venda|nao consegui vender nada|sem faturamento)\b', t)
        if no_sales and not re.search(r'\b(?:ja vendi|fiz uma venda|mas vendi|porem vendi)\b', t):
            return 0, 'sem_vendas'
        if re.fullmatch(r'(?:ainda )?nada(?: ainda)?[.!]*', t):
            return 0, 'sem_vendas'
    start = re.fullmatch(
        r'(?:(?:eu )?(?:ainda )?(?:nao comecei(?: a vender| as vendas)?|nao iniciei|nao inicie vendas|nao iniciei ainda|nao comecei ainda|nao comecei as vendas)|'
        r'(?:eu )?(?:estou|to) (?:comecando|iniciando)(?: agora)?|estou no comeco|comecei agora|'
        r'vou comecar(?: ainda| do zero)?|(?:irei|vou|irie) comecar(?: a vender amanha)?|seria a primeira vez|'
        r'(?:(?:eu )?(?:so|somente) )?ativei(?: agora| hoje| pouco tempo| a conta| o shop)?|'
        r'ainda nao comecei, somente ativei a conta)[.! ,]*', t)
    if start:
        return 0, 'inicio_atividade'
    number = r'(?:\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[,.]\d{1,2})?)'
    unit = r'(?:k|mil|milhao|milhoes)'
    span = re.fullmatch(r'(?:entre )?(r\$\s*)?('+number+r')\s*('+unit+r')?\s*(?:a|e|ate|-)\s*(?:r\$\s*)?('+number+r')\s*('+unit+r')?(?: reais)?[.!]?', t)
    if span:
        _, lo, lu, hi, hu = span.groups()
        # Approved real example: "Entre 15.000 a 20.000 mil" means 15k–20k,
        # not 15–20 million. Both bounds already spell the thousands out.
        redundant = not lu and hu == 'mil' and all(re.fullmatch(r'\d{1,3}(?:\.\d{3})+', n) for n in (lo, hi))
        if redundant:
            hu = None
        low = parse_gmv(lo + (' ' + (lu or hu) if lu or hu else ''))
        high = parse_gmv(hi + (' ' + (hu or lu) if hu or lu else ''))
        if low is not None and high is not None and low <= high:
            return low, 'limite_inferior_faixa'
        return None
    approximate = re.fullmatch(r'(?:(?:comecei agora|em torno de(?: uns)?|cerca de|aproximadamente)\s+)?(r\$\s*'+number+r'\s*(?:'+unit+r')?|'+number+r'\s*(?:'+unit+r')?)(?: reais)?(?: e pouquinho)?[.!]?', t)
    if approximate and re.search(r'comecei agora|em torno de|cerca de|aproximadamente|e pouquinho', t):
        value = parse_gmv(approximate[1].strip())
        if value is not None:
            return value, 'aproximado'
    return None
