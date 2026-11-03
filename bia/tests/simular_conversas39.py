"""Imprime, sem rede, as respostas da Bia nos casos reais da auditoria (release 39)."""
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_release39 import AT, POLICY, invited, say, settle_at  # noqa: E402
import retomada  # noqa: E402


def show(title, turn):
    print('---', title)
    print(turn['reply'] or '(sem mensagem)')
    if turn.get('buttons'):
        print('[botões]', turn['buttons'])
    print()


print('=== gabiosantana1: perguntou onde fica o formulário')
sent = invited('sent')
show('convite enviado', sent)
show('lead: Onde fica o formulário?', say('Onde fica o formulário?', sent['state']))

print('=== lemosalycee: "Feito" depois do convite')
turn = say('Feito', sent['state'])
show('lead: Feito', turn)
first = settle_at(turn['state'], turn['effects'][0], 'pending', AT)
show('ponte: ainda pendente', first)
later = settle_at(first['state'], first['effects'][0], 'linked', AT + timedelta(minutes=5))
show('reconferência de 5 min: vinculada', later)

print('=== ma.ribeiroh: não aceitou; reconferências sem novidade')
state, effect = first['state'], first['effects'][0]
for minutes in (5, 15, 60):
    result = settle_at(state, effect, 'not_found', AT + timedelta(minutes=minutes))
    show(f'reconferência de {minutes} min', result)
    state = result['state']
    effect = (result['effects'] or [None])[0]

print('=== leads parados (8497, 0346, 4153...): retomada')
cold = say('Conhecer a Amplify', {})
for step in (1, 2, 3):
    text, buttons = retomada.message(cold['state'], step, POLICY)
    print(f'--- retomada etapa {step}\n{text}\n[botões] {buttons}\n')

print('=== volta da manutenção (7457, 9413, 6279)')
show('lead escreveu durante a pausa: "Olá! Tenho interesse e queria mais informações."',
     say('Olá! Tenho interesse e queria mais informações.', {},
         resumed={'texts': ['Olá! Tenho interesse e queria mais informações.']}))
