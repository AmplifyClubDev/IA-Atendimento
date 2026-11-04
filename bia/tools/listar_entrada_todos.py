"""Quem a pós-pausa responderia ao ligar V5_GATE_MODE=todos (release 47). Só lê o Chatwoot.

Uso:
    CHATWOOT_BASE_URL=https://... CHATWOOT_API_TOKEN=... python -I listar_entrada_todos.py [instante ISO]

Faz só GET no Chatwoot (lista de conversas abertas da caixa 3 e o histórico de cada candidata), aplica as mesmas
regras da pós-pausa da 47 no modo 'todos' e imprime:
- quem receberia a resposta (lead que escreveu nas últimas 23 h e só recebeu avisos automáticos, como a manutenção);
- quem fica de fora e por quê (etiqueta "Renovacao de contrato", responsável humano, já respondido, janela etc.);
- a contagem e a fila: a pós-pausa responde 1 por minuto, então quem passar de 23 h antes da sua vez sai da janela.

Não lê o estado da Bia: quem já tem atendimento e foi respondido aparece como "já respondida" pelo próprio Chatwoot.
Mostra só os 4 últimos dígitos do telefone. Não grava nem envia nada.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offline_policy import effects_allowed, require_effects
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from urllib.request import ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

import retomada  # noqa: E402
from real_operations import gate_exclusion  # noqa: E402

ACCOUNT, INBOX, TEST_PHONE = os.environ.get('CHATWOOT_ACCOUNT_ID', '1'), os.environ.get('CHATWOOT_INBOX_ID', '3'), '+5547991154859'


class ReadOnlyChatwoot:
    def __init__(self, base_url, token):
        self.base_url, self.token = base_url.rstrip('/'), token
        self.reads = 0

    def http(self, *, method, url, headers, timeout, json_body=None):
        require_effects()
        if method != 'GET':
            raise RuntimeError('somente leitura')
        self.reads += 1
        with build_opener(ProxyHandler({})).open(Request(url, headers=headers), timeout=timeout) as response:
            return json.loads(response.read(8_000_000))


class NoState:
    """Sem o estado da Bia: nenhuma mensagem registrada, nenhum atendimento."""

    def event(self, key):
        return None

    def load_session(self, conv):
        return {}


def main():
    base, token = os.environ.get('CHATWOOT_BASE_URL'), os.environ.get('CHATWOOT_API_TOKEN')
    if not base or not token:
        sys.exit('defina CHATWOOT_BASE_URL e CHATWOOT_API_TOKEN')
    now = datetime.fromisoformat(sys.argv[1].replace('Z', '+00:00')) if len(sys.argv) > 1 else datetime.now(timezone.utc)
    gate = {'enabled': True, 'provider': 'chatwoot', 'account_id': ACCOUNT, 'inbox_id': INBOX, 'phone': TEST_PHONE,
            'mode': 'todos'}
    transport = ReadOnlyChatwoot(base, token)
    scan = retomada.PosPausa(NoState(), {'gate': gate}, transport, None, None, now=lambda: now)
    api = transport.base_url + '/api/v1/accounts/' + ACCOUNT
    listing = scan._listing(api, gate, now) or []
    receive, left_out = [], {}
    for conversation in listing:
        conv = conversation.get('id')
        meta = conversation.get('meta') or {}
        detail = {'labels': conversation.get('labels') or []}
        sender_phone = (meta.get('sender') or {}).get('phone_number')
        reason = gate_exclusion(gate, {'sender_phone': sender_phone}, detail)
        if not reason and meta.get('assignee') is not None:
            reason = 'fora_do_gate:responsavel_humano'
        if not reason:
            event, reason = scan._candidate(conversation, now, api)
            if event:
                created = datetime.fromisoformat(event['created_at'].replace('Z', '+00:00'))
                receive.append({'conversa': conv, 'escreveu_em': event['created_at'], 'final': str(sender_phone)[-4:],
                                'mensagens': len(event['_texts']), 'idade_horas': round((now - created).total_seconds() / 3600, 1)})
                continue
        left_out.setdefault(reason, []).append(conv)
    # A pós-pausa responde 1 por minuto, da conversa com atividade mais recente para a mais antiga.
    for position, row in enumerate(receive):
        row['vez_em_minutos'] = position
        row['sai_da_janela_antes'] = row['idade_horas'] * 60 + position > 23 * 60
    report = {'instante': now.isoformat(), 'conversas_abertas_lidas': len(listing), 'leituras_no_chatwoot': transport.reads,
              'receberiam': len(receive), 'sairiam_da_janela_antes_da_vez': sum(r['sai_da_janela_antes'] for r in receive),
              'fora_por_motivo': {reason: len(convs) for reason, convs in sorted(left_out.items())},
              'lista': receive, 'fora': {reason: convs[:50] for reason, convs in sorted(left_out.items())}}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
