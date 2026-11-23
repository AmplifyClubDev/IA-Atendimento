"""Coleta de hora em hora dos agenciados do TikTok Partner Center (auditoria 21/11/2026).

Só leitura na ponte de Agenciamento (GET /relations, status=1, lista inteira). O banco guarda a
foto pela função public.registrar_coleta_agenciados_v5, que ignora coletas com menos de 45 minutos
e só marca saídas com lista completa. Uma falha aqui nunca afeta o atendimento.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time

INTERVAL_SECONDS = 3600
FIRST_DELAY_SECONDS = 120
MAX_ITEMS = 20000
# Lista inteira com detalhes: ~3 KB por agenciado (1.542 em 23/11 passam de 2 MB).
MAX_RESPOSTA_BYTES = 16 * 1024 * 1024


class ColetaInvalida(ValueError):
    pass


# Fase A2 (23/11/2026): detalhes da parceria (?detalhes=1 na ponte) -> campos da ficha no banco.
# A ponte devolve o registro do TikTok achatado ("creator_tier.level": 2). Só passa valores simples e
# conhecidos; o banco valida de novo. Sem detalhes (ponte antiga), não manda nada a mais.
_CAMPOS = {
    'creator_id': 'creator_info.id',
    'start_second': 'effective_start_date_second',
    'expire_time_second': 'expire_time_second',
    'nivel': 'creator_tier.level',
    'nivel_nome': 'creator_tier.name',
    'nivel_proximo': 'creator_tier_progress.target_tier.level',
    'gmv_nivel': 'creator_tier_progress.current_gmv',
    'gmv_meta': 'creator_tier_progress.target_gmv',
    'progresso_pct': 'creator_tier_progress.progress_percent',
    'seguidores': 'creator_info.fans_cnt',
    'comissao_pct': 'commission_relation.commission_proportion',
    'desvinculos_recusados': 'partner_reject_unlink_times',
}


def _detalhes(det):
    if not isinstance(det, dict):
        return {}
    saida = {}
    for campo, chave in _CAMPOS.items():
        valor = det.get(chave)
        if isinstance(valor, bool) or valor is None:
            continue
        if isinstance(valor, (int, float, str)) and len(str(valor)) <= 80:
            saida[campo] = str(valor)
    categorias = [det[f'creator_info.categories.{i}.name'] for i in range(10)
                  if isinstance(det.get(f'creator_info.categories.{i}.name'), str)]
    if categorias:
        saida['categorias'] = [c[:80] for c in categorias]
    return saida


def _validar(code, data):
    items, pages, query = data.get('items'), data.get('pages'), data.get('query')
    if not (code == 200 and data.get('ok') is True and data.get('status') == 'relations_listed'):
        raise ColetaInvalida('ponte_nao_listou')
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ColetaInvalida('itens_invalidos')
    if not (isinstance(pages, list) and pages and all(isinstance(p, dict) and p.get('ok') is True for p in pages)):
        raise ColetaInvalida('paginas_invalidas')
    if not (isinstance(query, dict) and str(query.get('status')) == '1' and query.get('creators') in ([], None)):
        raise ColetaInvalida('consulta_inesperada')
    completa = data.get('completo') is True and pages[-1].get('hasMore') is False
    total = data.get('totalNum')
    total = total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None
    itens = []
    for item in items:
        if not isinstance(item, dict) or item.get('status') != 'vinculado':
            raise ColetaInvalida('item_invalido')
        relation = str(item.get('relation_id') or '')
        if not relation or len(relation) > 64:
            continue
        itens.append({
            'relation_id': relation,
            'arroba': item.get('arroba') if isinstance(item.get('arroba'), str) else None,
            'creator_name': item.get('creator_name') if isinstance(item.get('creator_name'), str) else None,
            'create_time_second': str(item.get('create_time_second') or ''),
            'effective_end_date_second': str(item.get('effective_end_date_second') or ''),
            **_detalhes(item.get('detalhes')),
        })
    return {'total': total, 'completa': completa, 'itens': itens}


def coletar(client, gateway, *, now=None):
    """Uma coleta. Devolve o recibo da função do banco; levanta exceção se a ponte ou o banco falharem."""
    client._ready('agency')
    code, data = client._call('agency', 'GET', '/relations', params={
        'status': '1', 'page_size': '100', 'page_limit': '100', 'fresh': '1', 'detalhes': '1'},
        max_bytes=MAX_RESPOSTA_BYTES)
    lista = _validar(code, data)
    observado = (now or datetime.now(timezone.utc)).isoformat()
    payload = {'observado_em': observado, 'fonte': 'ponte_agenciamento:bia', **lista}
    return gateway._rpc('registrar_coleta_agenciados_v5', {'p': payload})


class Agendador:
    def __init__(self, client, gateway, *, interval=INTERVAL_SECONDS, first_delay=FIRST_DELAY_SECONDS,
                 sleep=time.sleep):
        self.client, self.gateway = client, gateway
        self.interval, self.first_delay, self.sleep = interval, first_delay, sleep
        self.thread = None

    def rodada(self):
        try:
            recibo = coletar(self.client, self.gateway)
            resumo = {k: recibo.get(k) for k in ('status', 'recebidos', 'entraram', 'sairam', 'saidas_aplicadas')
                      } if isinstance(recibo, dict) else {'status': 'recibo_invalido'}
        except Exception as error:
            resumo = {'status': 'falhou', 'erro': type(error).__name__,
                      'motivo': str(error)[:80] if isinstance(error, ColetaInvalida) else ''}
        print('[bia] agenciados_coleta ' + json.dumps(resumo, sort_keys=True), flush=True)
        return resumo

    def iniciar(self):
        def loop():
            self.sleep(self.first_delay)
            while True:
                self.rodada()
                self.sleep(self.interval)
        self.thread = threading.Thread(target=loop, name='agenciados-coleta', daemon=True)
        self.thread.start()
        return True


def instalar(app, settings):
    """Liga a coleta só em produção real (TikTok real + worker real) e se não foi desligada."""
    if (settings.get('agency_sync_enabled') is not True or settings.get('tiktok_mode') != 'real'
            or settings.get('real_worker_enabled') is not True):
        return False
    from playwright_client import PlaywrightClient
    agendador = Agendador(PlaywrightClient(settings), app.extensions['v5_data_gateway'])
    app.extensions['v5_agenciados_coleta'] = agendador
    return agendador.iniciar()
