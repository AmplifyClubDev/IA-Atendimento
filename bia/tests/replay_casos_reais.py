"""Reproduz, sem rede, as conversas reais das duas auditorias sobre o código desta pasta.

Uso, dentro de src/: python tests/replay_casos_reais.py
"""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]

import conversation  # noqa: E402
import real_journey as journey  # noqa: E402
import retomada  # noqa: E402
from test_relationship_form_chat30 import AT, POLICY  # noqa: E402

URL = journey.PUBLIC_FORM_URL


def say(text, state, at=AT):
    return conversation.handle(state, text, now=at, real_mode=True, operation_policy=POLICY,
                               relationship_check_in_form=True)


def settle(state, effect, status, at=AT, **updates):
    result = dict(operation=effect['operation'], creator=effect['creator'].lstrip('@'), status=status,
                  confirmed=True, observed_at=at.isoformat(), evidence={'source': 'offline', 'complete': True})
    result.update(updates)
    return conversation.resolve_tiktok_result(state, effect['id'], result, now=at, operation_policy=POLICY)


def effect(result, operation):
    return next(item for item in result['effects'] if item['operation'] == operation)


def show(lead, result):
    print('  LEAD: ' + lead if lead else '  (sistema)')
    print('  BIA:  ' + (result['reply'] or '—').replace('\n', '\n        ') +
          ('   [' + '] ['.join(result['buttons']) + ']' if result.get('buttons') else ''))
    print('        fase=' + result['state']['cycle'].get('phase', '?') +
          ' efeitos=' + ','.join(item['operation'] for item in result.get('effects', [])))


def run(lead, state, at=AT):
    result = say(lead, state, at)
    show(lead, result)
    return result


def to_eligible(handle='@teste'):
    r = run('Oi, quero saber mais sobre agenciamento de creators', {})
    r = run(handle, r['state'])
    back = settle(r['state'], effect(r, 'precheck'), 'eligible')
    show(None, back)
    return back


def to_invited(handle='@teste'):
    r = to_eligible(handle)
    r = run('Pode mandar', r['state'])
    back = settle(r['state'], effect(r, 'invite'), 'sent')
    show(None, back)
    return back


print('\n## gabiosantana1')
r = to_invited('@gabiosantana1')
for text in ('Onde fica o formulário?', 'Não apareceu o formulário', 'Não apareceu o convite', 'aceitei', 'aceitei'):
    r = run(text, r['state'])

print('\n## lemosalycee')
r = to_invited('@lemosalycee')
r = run('Feito', r['state'])
check = next(item for item in r['effects'] if item['operation'] == 'relationship')
show(None, settle(r['state'], check, 'linked'))

print('\n## ma.ribeiroh')
r = to_invited('@ma.ribeiroh')
for text in ('Conhecer a Amplify', 'Como funciona', 'Benefícios', 'Comissão'):
    r = run(text, r['state'])

print('\n## priscila.matias44')
r = run('Oi, quero saber mais sobre agenciamento de creators', {})
for text in ('Priscila Matias', '@Priscila Matias', '@priscila.matias44'):
    r = run(text, r['state'])
down = settle(r['state'], effect(r, 'precheck'), 'verification_pending', confirmed=False, evidence={},
              reason='human_verification_required')
show(None, down)
for text in ('Recebe pra isso?', 'Quero saber sobre os benefícios'):
    down = run(text, down['state'])

print('\n## Sarah (bloco repetido)')
r = to_eligible('@sarahellen.off')
for text in ('ok', 'hm', 'vou ver'):
    r = run(text, r['state'])
for step in (1, 2, 3):
    print('  lembrete %d: %s' % (step, retomada.message(r['state'], step, POLICY)))

print('\n## 8497 / 0346 / 4153 (informação sem próximo passo)')
for text in ('Como funciona?', 'Quais os benefícios?', 'Conhecer a Amplify'):
    first = run('Oi, quero saber mais sobre agenciamento de creators', {})
    run(text, first['state'])

print('\n## 4 que nunca mandaram o @')
first = run('Oi, quero saber mais sobre agenciamento de creators', {})
for step in (1, 2, 3):
    print('  lembrete %d: %s' % (step, retomada.message(first['state'], step, POLICY)))
