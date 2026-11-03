"""Lista quem a reconferência da release 40 consultaria na primeira varredura. Só lê.

Uso: python -I listar_reconferencia.py <cópia do state.sqlite3> [instante ISO]

Trabalha numa cópia temporária do banco: o arquivo indicado não é aberto para escrita.
Mostra também quem está parado na conferência do perfil, mas fica de fora, e o motivo.
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
from reconferencia import candidates, precheck_reason  # noqa: E402
from repository import Repository  # noqa: E402


def why_not(state, reason, now):
    cycle = state.get('cycle') or {}
    record = (cycle.get('real_operations') or {}).get('precheck') or {}
    wait = cycle.get('bridge_wait') or {}
    if cycle.get('status') != 'open':
        return 'atendimento ' + str(cycle.get('status'))
    if cycle.get('expires_at') and engine._clock(cycle['expires_at']) <= now:
        return 'passou de 24 h da última mensagem (expira ' + cycle['expires_at'] + ')'
    if (wait.get('reason') or reason) not in real_journey.BRIDGE_DOWN_REASONS:
        return 'motivo não é ponte fora: ' + str(wait.get('reason') or reason)
    if (cycle.get('real_operations') or {}).get('invite') or cycle.get('invite_retry'):
        return 'já tem convite'
    if state.get('human_control') or cycle.get('qualification_paused'):
        return 'controle humano ou pausa'
    if int(wait.get('retries') or 0) >= real_journey.BRIDGE_RETRY_LIMIT:
        return 'já reconferido ' + str(wait.get('retries')) + ' vezes'
    return 'consulta do perfil ' + str(record.get('status')) + ' (outra condição)'


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
            reason = precheck_reason(repo, state)
            left_out.append({'conversation': conv, 'creator': (cycle.get('facts') or {}).get('tiktok_declarado'),
                             'motivo_da_consulta': reason, 'fica_de_fora_porque': why_not(state, reason, now)})
    print(json.dumps({'instante': now.isoformat(), 'ordem_da_varredura': chosen, 'fora': left_out},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
