"""Mostra as mensagens da release 40 nos casos reais da auditoria de conversão (01/11). Sem rede.

Uso, dentro de src/: python tests/simular_conversas40.py
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]

import real_journey as journey  # noqa: E402
import retomada  # noqa: E402
from test_relationship_form_chat30 import POLICY, eligible, inbound, invited, qualified, settle  # noqa: E402


def show(title, lead, turn):
    print('\n### ' + title)
    if lead:
        print('LEAD: ' + lead)
    print('BIA:  ' + turn[0].replace('\n', '\n      '))
    if turn[1]:
        print('      [' + '] ['.join(turn[1]) + ']')


def say(text, state=None):
    result = inbound(text, state)
    return result, (result['reply'], result['buttons'])


ad = 'Oi, quero saber mais sobre agenciamento de creators'
first, shown = say(ad)
show('1. Primeira resposta (mensagem pronta do anúncio)', ad, shown)
for step in (1, 2, 3):
    show(f'2. Lembrete {step} sem @ (15 min, 2 h, 23h30)', None, retomada.message(first['state'], step, POLICY))
_, shown = say('Conhecer a Amplify')
show('3. "Conhecer a Amplify"', 'Conhecer a Amplify', shown)
_, shown = say('@larvitrine', first['state'])
show('4. Depois do @', '@larvitrine', shown)

stuck = qualified()
effect = next(item for item in stuck['effects'] if item['operation'] == 'precheck')
down = settle(stuck['state'], effect, 'verification_pending', confirmed=False, evidence={}, reason='human_verification_required')
show('6. Ponte fora', None, (down['reply'], down['buttons']))
retry = journey.bridge_retry_effect(down['state'], datetime.now(timezone.utc))
back = settle(down['state'], retry, 'eligible')
show('6. Ponte de volta → 5. Autorização (bloco completo, uma vez)', None, (back['reply'], back['buttons']))
_, shown = say('ok', back['state'])
show('5. Nova mensagem sem decidir (não repete o bloco)', 'ok', shown)
for step in (1, 2, 3):
    show(f'5. Lembrete {step} da autorização (objeções)', None, retomada.message(eligible()['state'], step, POLICY))
_, shown = say('Tenho uma dúvida', eligible()['state'])
show('5. Botão "Tenho uma dúvida"', 'Tenho uma dúvida', shown)

pending = invited()['state']
for question in ('Como funciona', 'Comissão'):
    _, shown = say(question, deepcopy(pending))
    show('7. Dúvida com convite pendente (ma.ribeiroh)', question, shown)

linked = invited()['state']
linked['cycle']['real_operations']['relationship'] = {'status': 'linked', 'confirmed': True}
linked['cycle']['phase'] = 'form'
for step in (1, 2):
    show(f'8. Vínculo sem cadastro, lembrete {step} (2 h, 23h30)', None, retomada.message(linked, step, POLICY))
