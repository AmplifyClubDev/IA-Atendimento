"""Reconferência do perfil quando a ponte de pré-validação volta (release 40).

Quando a consulta do perfil falha porque a ponte estava fora (login humano,
sessão, transporte), o atendimento fica em ``blocked`` com a marca
``bridge_wait``. Esta varredura, a cada minuto e só com o /bridge/ready da
pré-validação pronto, refaz a consulta de um lead por vez. O resultado segue a
conversa pelo caminho normal (condições do convite etc.), sem pedir o @ de novo.

Atendimentos parados na 39 não têm a marca: o motivo vem do registro do
trabalho de consulta. Perfil inelegível nunca é reconferido.
"""
from datetime import datetime, timedelta, timezone

from followup import clock
from retomada import enabled as _enabled

SCAN_SECONDS = 60


def enabled(settings):
    """Ligada por padrão; V5_RECONFERENCIA_ENABLED=false desliga."""
    return _enabled(settings, 'reconferencia_enabled')


def precheck_reason(repository, state):
    """Motivo da última consulta do perfil, lido do trabalho que a executou."""
    record = ((state.get('cycle') or {}).get('real_operations') or {}).get('precheck') or {}
    job = repository.real_job_for_effect(record['job_id']) if record.get('job_id') else None
    result = (job or {}).get('result') if isinstance(job, dict) else None
    reason = result.get('reason') if isinstance(result, dict) else None
    return reason if isinstance(reason, str) else None


def candidates(repository, now):
    """Quem seria reconferido agora, na ordem da varredura (um por vez).

    As 5 conversas paradas em 31/10 (``INITIAL_RECHECK``) vêm primeiro e entram uma vez
    qualquer que seja o motivo registrado da falha; perfil inelegível nunca entra.
    Release 41: também o convite autorizado que não chegou ao TikTok (``kind='invite'``),
    reenviado quando a ponte de Convites volta.
    """
    from real_journey import INITIAL_INVITE_RECHECK, INITIAL_RECHECK, bridge_retry_due, invite_retry_due
    found = []
    first = INITIAL_RECHECK | INITIAL_INVITE_RECHECK
    for conv in sorted(repository.precheck_conversations(), key=lambda key: (key not in first, key)):
        state = repository.load_session(conv)
        cycle = state.get('cycle') or {}
        if not cycle.get('phase') == 'blocked':
            continue
        if (cycle.get('real_operations') or {}).get('invite'):
            forced = conv in INITIAL_INVITE_RECHECK and not invite_retry_due(state, now)
            if invite_retry_due(state, now, forced=forced):
                found.append({'conversation': conv, 'kind': 'invite', 'reason': (cycle.get('invite_wait') or {}).get('reason'),
                              'forced': forced, 'creator': cycle['facts'].get('tiktok_declarado')})
            continue
        reason = precheck_reason(repository, state)
        forced = conv in INITIAL_RECHECK and not bridge_retry_due(state, now, reason=reason)
        if bridge_retry_due(state, now, reason=reason, forced=forced):
            found.append({'conversation': conv, 'kind': 'precheck', 'reason': reason, 'forced': forced,
                          'creator': cycle['facts'].get('tiktok_declarado')})
    return found


class Reconferencia:
    def __init__(self, repository, settings, bridge_ready, start, *, now=None):
        self.repository, self.settings = repository, settings
        self.bridge_ready, self.start = bridge_ready, start
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.next_scan_at = None
        self.last = {'status': 'not_run'}

    def status(self):
        return {'enabled': enabled(self.settings), **self.last}

    def tick(self):
        now = clock(self.now())
        if not enabled(self.settings) or not now:
            return {'status': 'disabled'}
        if self.next_scan_at and now < self.next_scan_at:
            return {'status': 'cooldown'}
        self.next_scan_at = now + timedelta(seconds=SCAN_SECONDS)
        try:
            rows = candidates(self.repository, now)
            # Cada ponte é lida na hora (GET /bridge/ready), nunca de um resultado guardado, e só se alguém espera por ela.
            ready = {}
            outcome = {'status': 'idle'}
            for row in rows:
                kind = row.get('kind', 'precheck')
                if kind not in ready:
                    ready[kind] = self.bridge_ready(kind) is True
                if not ready[kind]:
                    outcome = {'status': 'bridge_not_ready'}
                    continue
                # One lead per scan: the next one waits for this result.
                result = self.start(row['conversation'], row['reason'], forced=row['forced'], kind=kind)
                outcome = {'status': 'queued' if (result or {}).get('status') == 'queued' else 'skipped',
                           'result': (result or {}).get('status')}
                if outcome['status'] == 'queued':
                    break
        except Exception:
            outcome = {'status': 'unconfirmed'}
        self.last = {**outcome, 'at': now.isoformat()}
        return outcome
