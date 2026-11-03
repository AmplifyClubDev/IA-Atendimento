"""Quem recebe mensagem na primeira varredura da release 41. Só lê.

Uso: python -I listar_primeira_varredura.py <cópia do state.sqlite3> [instante ISO]

Trabalha numa cópia temporária do banco: o arquivo indicado não é aberto para escrita.
Cobre as três varreduras que mandam mensagem sem o lead escrever:
- reconferência: perfil (ponte de Pré-validação) e, novo na 41, convite (ponte de Convites);
- retomada: lembretes (na 41, só das 8h às 21h e só depois de ler a ficha);
- pós-pausa: depende do Chatwoot (mensagens sem resposta); aqui só aparece quem tem evento já registrado,
  porque esses a pós-pausa pula.
Mostra em destaque 56935 (Cristiane) e 56933 (@gabinaresse).
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

import engine  # noqa: E402
import real_journey  # noqa: E402
import retomada  # noqa: E402
from reconferencia import candidates, precheck_reason  # noqa: E402
from repository import Repository  # noqa: E402

FOCUS = ('chatwoot:1:56935', 'chatwoot:1:56933')


def invite_why_not(state, now):
    cycle = state.get('cycle') or {}
    record = (cycle.get('real_operations') or {}).get('invite') or {}
    attempts = [e for e in (state.get('effects') or {}).values() if e.get('operation') == 'invite'
                and e.get('cycle_id') == cycle.get('id')]
    if cycle.get('status') != 'open':
        return 'atendimento ' + str(cycle.get('status'))
    if cycle.get('expires_at') and engine._clock(cycle['expires_at']) <= now:
        return 'passou de 24 h da última mensagem (expira ' + cycle['expires_at'] + ')'
    if record.get('status') not in {'verification_pending', 'failed', 'outcome_unknown'}:
        return 'convite ' + str(record.get('status'))
    if not all(real_journey._invite_no_write(e.get('result_receipt')) for e in attempts):
        return 'sem a prova de que nada chegou ao TikTok: não reenvia (evitaria convite duplicado)'
    if cycle.get('invite_retry'):
        return 'tentativa em andamento'
    return 'outra condição (controle humano, consentimento ou limite de tentativas)'


def reminder(repo, conv, now):
    state = repo.load_session(conv)
    source = repo.followup_source(conv)
    cycle = state.get('cycle') or {}
    expires = engine._clock(cycle['expires_at']) if cycle.get('expires_at') else None
    if (not source or source.get('cycle_id') != cycle.get('id') or cycle.get('status') != 'open'
            or cycle.get('phase') not in retomada.WAITING or not expires or now >= expires):
        return None
    last = engine._clock(cycle['last_inbound_at']) if cycle.get('last_inbound_at') else None
    due = [step for step, after in retomada.steps_for(state) if last and now - last >= after]
    if not due:
        return None
    payload = retomada.message(state, due[-1], None)
    return {'conversation': conv, 'etapa': due[-1], 'fase': cycle.get('phase'),
            'cadastro_na_copia': state.get('cadastro_situacao'),
            'sai_agora': retomada.send_hour(now) and payload is not None,
            'observacao': ('fora do horário (8h–21h): espera as 8h' if not retomada.send_hour(now) else
                           'sem lembrete para esta fase' if payload is None else
                           'a ficha é lida antes do envio; com cadastro confirmado, não sai'),
            'texto': payload[0] if payload else None}


def focus(repo, conv, now):
    state = repo.load_session(conv)
    cycle = state.get('cycle') or {}
    events = []
    with repo._connection() as db:
        for row in db.execute("SELECT event_key,status FROM inbound_events WHERE conversation_key=? "
                              "ORDER BY created_at DESC LIMIT 5", (conv,)):
            outbox = db.execute("SELECT status FROM outbox WHERE outbox_key=?", (row[0] + ':reply',)).fetchone()
            events.append({'evento': row[0], 'status': row[1], 'resposta': outbox[0] if outbox else None})
    return {'conversation': conv, 'fase': cycle.get('phase'), 'situacao': cycle.get('status'),
            'cadastro_na_copia': state.get('cadastro_situacao'), 'expira': cycle.get('expires_at'),
            'convite': ((cycle.get('real_operations') or {}).get('invite') or {}).get('status'),
            'ultimos_eventos': events}


def main():
    source = Path(sys.argv[1])
    now = engine._clock(sys.argv[2]) if len(sys.argv) > 2 else datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / 'state.sqlite3'
        shutil.copyfile(source, copy)
        repo = Repository(copy)
        chosen = candidates(repo, now)
        picked = {row['conversation'] for row in chosen}
        left_out = []
        for conv in repo.precheck_conversations():
            state = repo.load_session(conv)
            cycle = state.get('cycle') or {}
            if conv in picked or cycle.get('phase') != 'blocked':
                continue
            if (cycle.get('real_operations') or {}).get('invite'):
                left_out.append({'conversation': conv, 'tipo': 'convite', 'fica_de_fora_porque': invite_why_not(state, now)})
            else:
                left_out.append({'conversation': conv, 'tipo': 'perfil',
                                 'motivo_da_consulta': precheck_reason(repo, state)})
        reminders = [row for row in (reminder(repo, conv, now) for conv in repo.followup_conversations()) if row]
        report = {'instante': now.isoformat(),
                  'reconferencia_um_por_minuto': chosen,
                  'reconferencia_fora': left_out,
                  'lembretes': reminders,
                  'destaque': [focus(repo, conv, now) for conv in FOCUS]}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
