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
import time

from followup import clock
from retomada import enabled as _enabled
from demo_router import production_blocked, excluded_conversations

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


def candidates(repository, now, policy=None):
    """Quem seria reconferido agora, na ordem da varredura (um por vez).

    As 5 conversas paradas em 31/10 (``INITIAL_RECHECK``) vêm primeiro e entram uma vez
    qualquer que seja o motivo registrado da falha; perfil inelegível nunca entra.
    Release 41: também o convite autorizado que não chegou ao TikTok (``kind='invite'``),
    reenviado quando a ponte de Convites volta.
    Release 42: a leitura da lista de vínculos (``kind='agency'``): a prova de que um convite incerto
    não chegou ao TikTok e o acompanhamento do convite pendente.
    """
    from real_journey import (INITIAL_INVITE_RECHECK, INITIAL_RECHECK, agency_read_due, auto_invite_due,
                              bridge_retry_due, invite_retry_due)
    found = []
    first = INITIAL_RECHECK | INITIAL_INVITE_RECHECK
    for conv in sorted(repository.precheck_conversations(), key=lambda key: (key not in first, key)):
        state = repository.load_session(conv)
        cycle = state.get('cycle') or {}
        source = agency_read_due(state, now)
        if source:
            found.append({'conversation': conv, 'kind': 'agency', 'reason': source, 'forced': False,
                          'creator': cycle['facts'].get('tiktok_declarado')})
            continue
        if cycle.get('phase') == 'consent_real' and auto_invite_due(state, now, policy):
            # Release 52: perfil aprovado parado no "Pode mandar": o convite sai sozinho.
            found.append({'conversation': conv, 'kind': 'consent', 'reason': 'auto_invite', 'forced': False,
                          'creator': cycle['facts'].get('tiktok_declarado')})
            continue
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
    def __init__(self, repository, settings, bridge_ready, start, *, now=None, policy=None):
        self.repository, self.settings = repository, settings
        self.policy = policy or (lambda: None)
        self.bridge_ready, self.start = bridge_ready, start
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.next_scan_at = None
        self.last = {'status': 'not_run'}
        self._progress = None
        self.monotonic = time.monotonic

    def status(self):
        return {'enabled': enabled(self.settings), **self.last}

    def tick(self):
        now = clock(self.now())
        if not enabled(self.settings) or not now:
            return {'status': 'disabled'}
        if self.next_scan_at and now < self.next_scan_at:
            return {'status': 'cooldown'}
        from retomada import DECISOES, send_error
        started = self.monotonic()
        try:
            if self._progress is None:
                self._progress = {'rows': iter(candidates(self.repository, now, self.policy())),
                                  'looked': set(), 'outcome': {'status': 'idle'}}
                DECISOES.start('reconferencia')
            rows = self._progress['rows']
            # Cada ponte é lida na hora (GET /bridge/ready), nunca de um resultado guardado, e só se alguém espera por ela.
            ready = {}
            outcome = self._progress['outcome']
            looked = self._progress['looked']
            processed = 0
            while True:
                if processed >= 25 or (processed and self.monotonic() - started >= 10):
                    self._progress['outcome'] = outcome
                    self.last = {'status': 'scanning', 'at': now.isoformat(),
                                 'puladas_por_motivo': DECISOES.finish('reconferencia')}
                    return dict(self.last)
                try:
                    row = next(rows)
                except StopIteration:
                    break
                processed += 1
                if production_blocked(self.settings, conversation_key=row['conversation']):
                    continue
                conv = row['conversation'].rsplit(':', 1)[-1]
                looked.add(row['conversation'])
                kind = row.get('kind', 'precheck')
                if outcome.get('status') == 'queued':
                    DECISOES.record('reconferencia', conv, 'outro_lead_nesta_varredura', now, tipo=kind)
                    continue
                if kind not in ready:
                    ready[kind] = self.bridge_ready(kind) is True
                if not ready[kind]:
                    outcome = {'status': 'bridge_not_ready'}
                    DECISOES.record('reconferencia', conv, 'ponte_fora', now, tipo=kind)
                    continue
                # One lead per scan: the next one waits for this result.
                result = self.start(row['conversation'], row['reason'], forced=row['forced'], kind=kind) or {}
                status, why = result.get('status'), result.get('reason')
                reason = ('consulta_na_fila' if status == 'queued' else 'controle_humano' if status == 'blocked'
                          else 'cadastro_confirmado' if why == 'registered' else 'ficha_ilegivel' if why == 'registration_unreadable'
                          else 'origem_nao_confirmada' if why == 'precheck_source_unverified'
                          else 'sem_pendencia' if status == 'idle' else send_error(why or status))
                DECISOES.record('reconferencia', conv, reason, now, tipo=kind)
                outcome = {'status': 'queued' if status == 'queued' else 'skipped', 'result': status}
            for conv in self.repository.precheck_conversations():
                if conv not in looked:
                    DECISOES.record('reconferencia', conv.rsplit(':', 1)[-1], 'sem_pendencia', now)
        except Exception:
            outcome = {'status': 'unconfirmed'}
        self._progress = None
        self.next_scan_at = clock(self.now()) + timedelta(seconds=SCAN_SECONDS)
        outcome['puladas_por_motivo'] = DECISOES.finish('reconferencia')
        self.last = {**outcome, 'at': now.isoformat()}
        return outcome
