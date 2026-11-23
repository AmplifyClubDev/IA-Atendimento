"""Coleta de hora em hora dos agenciados do TikTok Partner Center (auditoria 21/11/2026).

Só leitura na ponte de Agenciamento (GET /relations, lista inteira). Fase A3 (23/11/2026): lê os vinculados
(status 1), os em desvinculação (status 4, ainda vinculados até o TikTok concluir) e os convites pendentes
(status 2), com o pedido de renovação de cada um e as contagens oficiais do Partner Center. O banco guarda a
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


# Pedido de renovação (extend_relation) -> colunas renovacao_* no banco.
_RENOVACAO = {
    'renovacao_status': 'extend_relation.status',
    'renovacao_pedido_second': 'extend_relation.create_time_second',
    'renovacao_expira_second': 'extend_relation.expire_time_second',
    'renovacao_novo_fim_second': 'extend_relation.effective_end_date_second',
    'renovacao_restantes': 'extend_relation.remaining_extend_request_count',
}
_ESTADOS = {'1': 'vinculado', '4': 'desvinculando'}


def _simples(det, chave):
    valor = det.get(chave)
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)) or len(str(valor)) > 80:
        return None
    return str(valor)


def _renovacao(det):
    if not isinstance(det, dict):
        return {}
    saida = {}
    for campo, chave in _RENOVACAO.items():
        valor = _simples(det, chave)
        if valor is not None:
            saida[campo] = valor
    return saida


def _validar(code, data, status='1'):
    items, pages, query = data.get('items'), data.get('pages'), data.get('query')
    if not (code == 200 and data.get('ok') is True and data.get('status') == 'relations_listed'):
        raise ColetaInvalida('ponte_nao_listou')
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ColetaInvalida('itens_invalidos')
    if not (isinstance(pages, list) and pages and all(isinstance(p, dict) and p.get('ok') is True for p in pages)):
        raise ColetaInvalida('paginas_invalidas')
    if not (isinstance(query, dict) and str(query.get('status')) == status and query.get('creators') in ([], None)):
        raise ColetaInvalida('consulta_inesperada')
    completa = data.get('completo') is True and pages[-1].get('hasMore') is False
    total = data.get('totalNum')
    total = total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None
    itens = []
    for item in items:
        if not isinstance(item, dict):
            raise ColetaInvalida('item_invalido')
        tiktok = item.get('tiktok_status')
        if tiktok is not None and str(tiktok) != status:
            raise ColetaInvalida('item_invalido')
        if status in _ESTADOS and item.get('status') != 'vinculado':
            raise ColetaInvalida('item_invalido')
        relation = str(item.get('relation_id') or '')
        if not relation or len(relation) > 64:
            continue
        base = {
            'relation_id': relation,
            'arroba': item.get('arroba') if isinstance(item.get('arroba'), str) else None,
            'creator_name': item.get('creator_name') if isinstance(item.get('creator_name'), str) else None,
            'create_time_second': str(item.get('create_time_second') or ''),
            'effective_end_date_second': str(item.get('effective_end_date_second') or ''),
        }
        if status not in _ESTADOS:  # convite pendente: só o básico
            base['expire_time_second'] = str(item.get('expire_time_second') or '')
            itens.append(base)
            continue
        det = item.get('detalhes') if isinstance(item.get('detalhes'), dict) else {}
        base.update(_detalhes(det))
        base.update(_renovacao(det))
        base['estado'] = _ESTADOS[status]
        if det:
            base['com_detalhes'] = '1'
        if status == '4':
            # No status 4, as datas do registro são do pedido de saída; as do vínculo ficam em data_relation.
            base['desvinculo_pedido_second'] = base['create_time_second']
            base['desvinculo_conclui_second'] = str(item.get('expire_time_second') or '')
            base['create_time_second'] = _simples(det, 'data_relation.create_time_second') or ''
            base.pop('expire_time_second', None)
            vinculo_expira = _simples(det, 'data_relation.expire_time_second')
            if vinculo_expira:
                base['expire_time_second'] = vinculo_expira
        itens.append(base)
    return {'total': total, 'completa': completa, 'itens': itens, 'contagens': data.get('statusCount')}


def _listar(client, status):
    code, data = client._call('agency', 'GET', '/relations', params={
        'status': status, 'page_size': '100', 'page_limit': '100', 'fresh': '1', 'detalhes': '1'},
        max_bytes=MAX_RESPOSTA_BYTES)
    return _validar(code, data if isinstance(data, dict) else {}, status)


def coletar(client, gateway, *, now=None):
    """Uma coleta. Devolve o recibo da função do banco; levanta exceção se a ponte ou o banco falharem.

    Vinculados (1) e em desvinculação (4) são obrigatórios: sem os dois, o banco marcaria saídas falsas.
    Convites pendentes (2) são opcionais: se falharem, a coleta segue sem eles."""
    client._ready('agency')
    vinculados = _listar(client, '1')
    saindo = _listar(client, '4')
    try:
        pendentes = _listar(client, '2')
    except Exception:
        pendentes = None
    totais = (vinculados['total'], saindo['total'])
    payload = {
        'observado_em': (now or datetime.now(timezone.utc)).isoformat(),
        'fonte': 'ponte_agenciamento:bia',
        'total': None if None in totais else sum(totais),
        'completa': vinculados['completa'] and saindo['completa'],
        'itens': vinculados['itens'] + saindo['itens'],
    }
    if pendentes is not None:
        payload['pendentes'] = {k: pendentes[k] for k in ('total', 'completa', 'itens')}
    if isinstance(vinculados.get('contagens'), dict):
        payload['contagens'] = vinculados['contagens']
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
            resumo = {k: recibo.get(k) for k in ('status', 'recebidos', 'entraram', 'sairam', 'saidas_aplicadas',
                                                       'desvinculando', 'pendentes')
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
