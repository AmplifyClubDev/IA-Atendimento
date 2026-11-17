"""Explicit chat declarations only; no provider metrics or inferred quantities."""
from decimal import Decimal
import re
import unicodedata
import engine


def collect(event, before, cycle):
    text = event.get('text', '')
    if (not isinstance(text, str) or event.get('private') is True
            or str(event.get('account_id')) != '1' or str(event.get('inbox_id')) != '3'
            or not cycle.get('id')):
        return []
    message = str(event.get('message_id', ''))
    if not re.fullmatch(r'[1-9][0-9]{0,19}', message) or not event.get('created_at'):
        return []
    stamp = engine._stamp(engine._clock(event['created_at']))
    common = {'mensagem_id': message, 'declarado_em': stamp, 'evidencia': text[:4000]}
    rows = []
    old, current = before.get('bia_validation') or {}, cycle.get('bia_validation') or {}
    amount = (cycle.get('facts') or {}).get('gmv_30d_declarado_centavos')
    if (before.get('id') == cycle.get('id') and old.get('stage') in {'gmv', 'gmv_zero_confirmation'}
            and current.get('gmv_at') and current.get('gmv_at') != old.get('gmv_at')
            and type(amount) is int and 0 <= amount <= 100_000_000_000):
        rows.append({**common, 'campo': 'gmv', 'valor': amount, 'moeda': 'BRL', 'periodo_dias': 30})
    # Full-message grammar deliberately rejects comparisons, questions and ranges.
    value = ''.join(c for c in unicodedata.normalize('NFD', text.lower().strip())
                    if not unicodedata.combining(c))
    match = re.fullmatch(r'(?:(?:eu )?(?:tenho|estou com|to com) )?(\d{1,3}(?:\.\d{3})+|\d+(?:[,.]\d+)?)\s*(k|mil|milhao|milhoes)? seguidores[.!]?', value)
    if match:
        number, unit = match.groups()
        number = number.replace('.', '') if re.fullmatch(r'\d{1,3}(?:\.\d{3})+', number) else number.replace(',', '.')
        quantity = Decimal(number) * {None: 1, 'k': 1000, 'mil': 1000, 'milhao': 1_000_000, 'milhoes': 1_000_000}[unit]
        if quantity == quantity.to_integral_value() and 0 <= quantity <= 1_000_000_000:
            rows.append({**common, 'campo': 'seguidores', 'valor': int(quantity), 'moeda': None, 'periodo_dias': None})
    return rows
