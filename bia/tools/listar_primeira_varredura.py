"""Quem recebe mensagem na primeira varredura da release 43. Só lê.

Uso: python -I listar_primeira_varredura.py <cópia do state.sqlite3> [instante ISO]

Trabalha numa cópia temporária do banco: o arquivo indicado não é aberto para escrita.
Cobre as varreduras que mandam mensagem sem o lead escrever:
- reconferência: perfil (ponte de Pré-validação), convite sem prova (ponte de Convites, 41) e, novo na 42,
  a lista de vínculos (ponte de Agenciamento): prova do convite incerto e acompanhamento do convite pendente;
- retomada: lembretes (só das 8h às 21h e só depois de ler a ficha);
- pós-pausa: depende do Chatwoot (mensagens sem resposta); aqui só aparece quem tem evento já registrado.
A varredura começa um lead por minuto, na ordem da lista. O que cada leitura manda depende do que a lista mostrar:
not_found → reenvio único e o texto 1; pending → nada (ou o passo a passo, se era a prova); linked → o texto 2.
Release 43: também o vínculo confirmado cujo aviso não foi entregue (texto 2 de novo) e o envio não confirmado
pela lista (aviso honesto e novo envio). A pós-pausa depende do Chatwoot: a 56938 aparece só pelo estado guardado.
Mostra em destaque 56932 (@viralstoresbr), 56933 (@gabinaresse), 56938, 32922, 56629 e 56931.
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

FOCUS = ('chatwoot:1:56932', 'chatwoot:1:56933', 'chatwoot:1:56938', 'chatwoot:1:32922', 'chatwoot:1:56629',
         'chatwoot:1:56931')
ON_RESULT = {'invite_list_proof': ('not_found: reenvia; o texto 1 sai quando a ponte ou a lista confirmar o convite; '
                                   'pending: passo a passo; linked: texto 2'),
             'invite_tracking': ('linked: texto 2 com o botão Fazer cadastro; pending: nada (ou o texto 1, se o envio '
                                 'esperava a lista); not_found com convite deste atendimento: aviso honesto e novo envio')}


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
        return 'sem a prova de que nada chegou ao TikTok (na 42, a lista de vínculos decide)'
    if cycle.get('invite_retry'):
        return 'tentativa em andamento'
    return 'outra condição (controle humano, consentimento ou limite de tentativas)'


def agency_why_not(state, now):
    """Por que a lista de vínculos não é lida agora para este atendimento (42)."""
    cycle = state.get('cycle') or {}
    operations = cycle.get('real_operations') or {}
    invite, relationship = operations.get('invite') or {}, operations.get('relationship') or {}
    creator = real_journey._creator((cycle.get('facts') or {}).get('tiktok_declarado'))
    try:
        expires = engine._clock(cycle.get('expires_at'))
    except (TypeError, ValueError, OverflowError):
        expires = None
    if cycle.get('status') != 'open':
        return 'atendimento ' + str(cycle.get('status')) + ': sem janela de 24 h, só um modelo aprovado poderia avisar'
    if not expires or now + real_journey.READ_MARGIN >= expires:
        return 'a janela de 24 h fecha às ' + str(cycle.get('expires_at')) + ': depois disso só com modelo aprovado'
    if not (retomada.send_hour(now) and retomada.send_hour(now + real_journey.READ_MARGIN)):
        return 'fora do horário (8h–21h de Brasília): fica para as 8h'
    if state.get('cadastro_situacao') == 'confirmado':
        return 'cadastro confirmado na cópia'
    if cycle.get('relationship_check_in_form') is not True:
        return 'atendimento sem a conferência do vínculo no formulário'
    if state.get('human_control') or cycle.get('qualification_paused') or state.get('opt_out') or cycle.get('opt_out'):
        return 'controle humano, pausa ou saída pedida'
    if real_journey._linked(cycle):
        return 'vínculo já confirmado neste atendimento'
    if creator and real_journey.resend_used(state, creator) and invite.get('status') in real_journey.LIST_PROOF_STATUSES:
        return 'o reenvio único já foi usado'
    if any(e.get('type') == 'tiktok_operation' and e.get('cycle_id') == cycle.get('id')
           and e.get('operation') in {'precheck', 'invite', 'relationship'}
           and e.get('status') in {'pending', 'running'} for e in (state.get('effects') or {}).values()):
        return 'há uma consulta do TikTok em andamento'
    if not (invite or relationship):
        return 'sem convite neste atendimento'
    if invite.get('status') in real_journey.LIST_PROOF_STATUSES:
        mark = cycle.get('invite_list_proof') or {}
        return ('prova da lista: ' + (('resultado ' + mark['result']) if mark.get('result') else
                                      str(mark.get('reads') or 0) + ' de ' + str(real_journey.LIST_PROOF_READ_LIMIT)
                                      + ' leituras; espera 10 min da tentativa e 15 min entre leituras'))
    since = real_journey._tracking_since(state)
    if since:
        mark = cycle.get('invite_tracking') or {}
        last = max([engine._clock(v) for v in (mark.get('last_read_at'),) if v] + [since])
        return 'próxima leitura às ' + (last + real_journey.tracking_interval(now - since)).isoformat()
    return ('convite ' + str(invite.get('status')) + ', fase ' + str(cycle.get('phase'))
            + ', prova da lista: ' + json.dumps(cycle.get('invite_list_proof') or {}, ensure_ascii=False))


def reminder(repo, conv, now):
    state = repo.load_session(conv)
    source = repo.followup_source(conv)
    cycle = state.get('cycle') or {}
    expires = engine._clock(cycle['expires_at']) if cycle.get('expires_at') else None
    if (not source or source.get('cycle_id') != cycle.get('id') or cycle.get('status') != 'open'
            or cycle.get('phase') not in retomada.WAITING or not expires or now >= expires):
        return None
    last = engine._clock(cycle['last_inbound_at']) if cycle.get('last_inbound_at') else None
    last = retomada.reminder_base(state, last) if last else None
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
    if not state:
        return {'conversation': conv, 'situacao': 'não encontrado na cópia'}
    cycle = state.get('cycle') or {}
    operations = cycle.get('real_operations') or {}
    source = real_journey.agency_read_due(state, now)
    return {'conversation': conv, 'creator': (cycle.get('facts') or {}).get('tiktok_declarado'),
            'fase': cycle.get('phase'), 'situacao': cycle.get('status'), 'expira': cycle.get('expires_at'),
            'cadastro_na_copia': state.get('cadastro_situacao'),
            'convite': (operations.get('invite') or {}).get('status'),
            'vinculo_na_ultima_leitura': (operations.get('relationship') or {}).get('status'),
            'leitura_da_lista_agora': source,
            'se_ler': ON_RESULT.get(source) if source else agency_why_not(state, now),
            'reenvio_usado': (state.get('invite_resends') or {}),
            'aviso_do_vinculo': cycle.get('linked_notice'),
            'envio_esperando_a_lista': cycle.get('invite_verify'),
            'leituras_paradas': [e.get('id') for e in (state.get('effects') or {}).values()
                                 if e.get('cycle_id') == cycle.get('id') and real_journey._stale(e, now)],
            'ultimo_convite_na_ponte': last_invite_result(repo, state)}


def last_invite_result(repo, state):
    """O que a ponte de Convites respondeu na última tentativa (status, motivo e as chaves da evidência)."""
    cycle = state.get('cycle') or {}
    attempts = sorted((e for e in (state.get('effects') or {}).values()
                       if e.get('operation') == 'invite' and e.get('cycle_id') == cycle.get('id')),
                      key=lambda e: e.get('created_at') or '')
    if not attempts:
        return None
    job = repo.real_job_for_effect(attempts[-1]['id']) or {}
    result = job.get('result') if isinstance(job.get('result'), dict) else {}
    evidence = result.get('evidence') if isinstance(result.get('evidence'), dict) else {}
    return {'tentativas': len(attempts), 'em': attempts[-1].get('created_at'), 'status': result.get('status'),
            'motivo': result.get('reason'), 'confirmado': result.get('confirmed'),
            'create_accepted': evidence.get('create_accepted'), 'post_attempted': evidence.get('post_attempted'),
            'evidencia': sorted(evidence)}


def main():
    source = Path(sys.argv[1])
    now = engine._clock(sys.argv[2]) if len(sys.argv) > 2 else datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / 'state.sqlite3'
        shutil.copyfile(source, copy)
        repo = Repository(copy)
        chosen = candidates(repo, now)
        for row in chosen:
            row['se_ler'] = ON_RESULT.get(row['reason']) if row['kind'] == 'agency' else None
        picked = {row['conversation'] for row in chosen}
        left_out = []
        for conv in repo.precheck_conversations():
            state = repo.load_session(conv)
            cycle = state.get('cycle') or {}
            if conv in picked or cycle.get('status') != 'open':
                continue
            operations = cycle.get('real_operations') or {}
            if operations.get('invite') or operations.get('relationship'):
                left_out.append({'conversation': conv, 'tipo': 'convite', 'convite': (operations.get('invite') or {}).get('status'),
                                 'lista_de_vinculos': agency_why_not(state, now),
                                 'ponte_de_convites': invite_why_not(state, now) if cycle.get('phase') == 'blocked' else None})
            elif cycle.get('phase') == 'blocked':
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
