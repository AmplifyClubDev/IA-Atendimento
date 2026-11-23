"""Auditoria 21/11/2026: coleta de hora em hora dos agenciados do Partner Center."""
from datetime import datetime, timezone
import unittest

import agenciados_sync
from config import load_settings

NOW = datetime(2026, 11, 21, 12, 5, tzinfo=timezone.utc)


def resposta(itens=2, completo=True, has_more=False, total=None, **extra):
    data = {'ok': True, 'status': 'relations_listed', 'completo': completo,
            'totalNum': itens if total is None else total,
            'query': {'status': '1', 'pageSize': 100, 'pageLimit': 100, 'creators': []},
            'pages': [{'ok': True, 'hasMore': has_more, 'count': itens}],
            'items': [{'arroba': f'pessoa{i}', 'creator_name': f'Pessoa {i}', 'status': 'vinculado',
                       'relation_id': str(1000 + i), 'create_time_second': 1795200000 + i,
                       'effective_end_date_second': 1826736000} for i in range(itens)]}
    data.update(extra)
    return data


def resposta_status(status, itens):
    """Lista de outro status (4 = desvinculação, 2 = convite pendente) no formato da ponte."""
    data = resposta(itens=0)
    data['query'] = dict(data['query'], status=status)
    data['items'] = itens
    data['totalNum'] = len(itens)
    data['pages'] = [{'ok': True, 'hasMore': False, 'count': len(itens)}]
    return data


class Cliente:
    def __init__(self, code=200, data=None, pronta=True, outros=None):
        self.code, self.data, self.pronta, self.chamadas = code, data or resposta(), pronta, []
        self.outros = outros or {}

    def _ready(self, role):
        self.chamadas.append(('ready', role))
        if not self.pronta:
            raise RuntimeError('session_not_ready')

    def _call(self, role, method, path, params=None, **kw):
        self.chamadas.append((role, method, path, params))
        self.kw = kw
        status = (params or {}).get('status')
        if status != '1':
            outro = self.outros.get(status, resposta_status(status, []))
            if isinstance(outro, Exception):
                raise outro
            return 200, outro
        return self.code, self.data


class Banco:
    def __init__(self, recibo=None):
        self.recibo = recibo or {'status': 'registrada', 'recebidos': 2, 'entraram': 2, 'sairam': 0,
                                 'saidas_aplicadas': True}
        self.chamadas = []

    def _rpc(self, name, body):
        self.chamadas.append((name, body))
        return self.recibo


class ColetaTests(unittest.TestCase):
    def test_le_a_lista_inteira_so_leitura_e_grava_no_banco(self):
        cliente, banco = Cliente(), Banco()
        recibo = agenciados_sync.coletar(cliente, banco, now=NOW)
        self.assertEqual(recibo['status'], 'registrada')
        self.assertEqual(cliente.chamadas[0], ('ready', 'agency'))
        role, method, path, params = cliente.chamadas[1]
        self.assertEqual((role, method, path), ('agency', 'GET', '/relations'))
        self.assertEqual(params['status'], '1')
        self.assertNotIn('creators', params)  # lista inteira, não um @
        nome, body = banco.chamadas[0]
        self.assertEqual(nome, 'registrar_coleta_agenciados_v5')
        p = body['p']
        self.assertEqual((p['total'], p['completa'], len(p['itens'])), (2, True, 2))
        self.assertEqual(p['observado_em'], NOW.isoformat())
        self.assertEqual(p['itens'][0]['relation_id'], '1000')
        self.assertEqual(p['itens'][0]['create_time_second'], '1795200000')

    def test_lista_com_mais_paginas_vai_como_incompleta(self):
        banco = Banco()
        agenciados_sync.coletar(Cliente(data=resposta(has_more=True)), banco, now=NOW)
        self.assertFalse(banco.chamadas[0][1]['p']['completa'])

    def test_resposta_ruim_da_ponte_nao_grava_nada(self):
        ruins = [Cliente(code=503), Cliente(data=resposta(ok=False)), Cliente(data=resposta(status='login_required')),
                 Cliente(data=resposta(query={'status': '1', 'creators': ['outra']})),
                 Cliente(data=resposta(pages=[])), Cliente(pronta=False)]
        for cliente in ruins:
            banco = Banco()
            with self.subTest(chamadas=len(cliente.chamadas)):
                with self.assertRaises(Exception):
                    agenciados_sync.coletar(cliente, banco, now=NOW)
                self.assertEqual(banco.chamadas, [])

    def test_item_que_nao_esta_vinculado_invalida_a_coleta(self):
        data = resposta()
        data['items'][0]['status'] = 'solicitada'
        with self.assertRaises(agenciados_sync.ColetaInvalida):
            agenciados_sync.coletar(Cliente(data=data), Banco(), now=NOW)

    def test_rodada_nunca_levanta_e_registra_o_resultado(self):
        agendador = agenciados_sync.Agendador(Cliente(code=500), Banco(), sleep=lambda s: None)
        self.assertEqual(agendador.rodada()['status'], 'falhou')
        agendador = agenciados_sync.Agendador(Cliente(), Banco(), sleep=lambda s: None)
        self.assertEqual(agendador.rodada()['status'], 'registrada')


class DetalhesTests(unittest.TestCase):
    """Fase A2 (23/11/2026): a coleta pede os detalhes e manda a ficha para o banco."""

    DET = {'creator_info.id': '7440000000000000000', 'effective_start_date_second': '1795200000',
           'expire_time_second': '1795300000', 'creator_tier.level': 2, 'creator_tier.name': 'Level 2',
           'creator_tier_progress.target_tier.level': 3, 'creator_tier_progress.current_gmv': '3030.50',
           'creator_tier_progress.target_gmv': '5000', 'creator_tier_progress.progress_percent': 6,
           'creator_info.fans_cnt': '2170', 'commission_relation.commission_proportion': '10',
           'partner_reject_unlink_times': 0, 'creator_info.categories.0.name': 'Beleza',
           'creator_info.categories.1.name': 'Casa', 'creator_info.verified': True, 'outra.coisa': 'x'}

    def test_pede_detalhes_e_mapeia_a_ficha(self):
        data = resposta(itens=1)
        data['items'][0]['detalhes'] = dict(self.DET)
        cliente, banco = Cliente(data=data), Banco()
        agenciados_sync.coletar(cliente, banco, now=NOW)
        self.assertEqual(cliente.chamadas[1][3]['detalhes'], '1')
        # Lista inteira com detalhes passa de 2 MB (7,5 MB em 23/11): só esta chamada aceita mais.
        self.assertEqual(cliente.kw['max_bytes'], 16 * 1024 * 1024)
        item = banco.chamadas[0][1]['p']['itens'][0]
        self.assertEqual(item['nivel'], '2')
        self.assertEqual(item['nivel_nome'], 'Level 2')
        self.assertEqual(item['gmv_nivel'], '3030.50')
        self.assertEqual(item['gmv_meta'], '5000')
        self.assertEqual(item['seguidores'], '2170')
        self.assertEqual(item['categorias'], ['Beleza', 'Casa'])
        self.assertEqual(item['desvinculos_recusados'], '0')
        self.assertEqual(item['creator_id'], '7440000000000000000')
        self.assertNotIn('outra.coisa', item)
        self.assertNotIn('verified', str(item))

    def test_sem_detalhes_manda_igual_a_antes(self):
        cliente, banco = Cliente(), Banco()
        agenciados_sync.coletar(cliente, banco, now=NOW)
        item = banco.chamadas[0][1]['p']['itens'][0]
        self.assertEqual(set(item), {'relation_id', 'arroba', 'creator_name', 'create_time_second',
                                     'effective_end_date_second', 'estado'})
        self.assertEqual(item['estado'], 'vinculado')

    def test_detalhes_estranhos_sao_ignorados(self):
        self.assertEqual(agenciados_sync._detalhes(None), {})
        self.assertEqual(agenciados_sync._detalhes(['x']), {})
        saida = agenciados_sync._detalhes({'creator_tier.level': True, 'creator_tier.name': 'x' * 200,
                                           'creator_info.fans_cnt': {'a': 1}, 'creator_tier_progress.current_gmv': None})
        self.assertEqual(saida, {})


class PartnerCompletoTests(unittest.TestCase):
    """Fase A3 (23/11/2026): desvinculação (status 4), convites pendentes (2), renovação e contagens."""

    SAINDO = {'arroba': 'saindo', 'creator_name': 'Saindo', 'status': 'vinculado', 'tiktok_status': 4,
              'relation_id': '2001', 'create_time_second': '1795457509', 'expire_time_second': '1796062309',
              'effective_end_date_second': '1796035722',
              'detalhes': {'data_relation.create_time_second': '1790000000',
                           'data_relation.expire_time_second': '1790600000',
                           'expire_time_second': '1796062309', 'creator_tier_progress.current_gmv': '44.8'}}
    PENDENTE = {'arroba': 'convidada', 'creator_name': 'C', 'status': 'solicitada', 'tiktok_status': 2,
                'relation_id': '3001', 'create_time_second': '1795457616', 'expire_time_second': '1796062416',
                'effective_end_date_second': '1800728014', 'detalhes': {'x': 1}}
    CONTAGENS = {'bound': 2, 'pending': 1, 'unbinding': 1, 'all': 10}

    def _coleta(self, outros=None, data=None):
        data = data or resposta(itens=2, statusCount=self.CONTAGENS)
        cliente, banco = Cliente(data=data, outros=outros or {
            '4': resposta_status('4', [dict(self.SAINDO)]), '2': resposta_status('2', [dict(self.PENDENTE)])}), Banco()
        agenciados_sync.coletar(cliente, banco, now=NOW)
        return cliente, banco.chamadas[0][1]['p']

    def test_le_vinculados_desvinculando_e_pendentes(self):
        cliente, p = self._coleta()
        status = [c[3]['status'] for c in cliente.chamadas[1:]]
        self.assertEqual(status, ['1', '4', '2'])
        self.assertTrue(all(c[3]['detalhes'] == '1' and c[2] == '/relations' and c[1] == 'GET'
                            for c in cliente.chamadas[1:]))
        self.assertEqual((p['total'], p['completa'], len(p['itens'])), (3, True, 3))
        self.assertEqual(p['contagens'], self.CONTAGENS)
        self.assertEqual(p['pendentes']['total'], 1)
        self.assertEqual(p['pendentes']['itens'][0], {
            'relation_id': '3001', 'arroba': 'convidada', 'creator_name': 'C', 'create_time_second': '1795457616',
            'effective_end_date_second': '1800728014', 'expire_time_second': '1796062416'})

    def test_desvinculando_usa_as_datas_do_vinculo(self):
        _, p = self._coleta()
        item = p['itens'][-1]
        self.assertEqual(item['estado'], 'desvinculando')
        self.assertEqual(item['desvinculo_pedido_second'], '1795457509')
        self.assertEqual(item['desvinculo_conclui_second'], '1796062309')
        self.assertEqual(item['create_time_second'], '1790000000')  # entrada, não o pedido de saída
        self.assertEqual(item['expire_time_second'], '1790600000')
        self.assertEqual(item['gmv_nivel'], '44.8')

    def test_pedido_de_renovacao(self):
        data = resposta(itens=1)
        data['items'][0]['detalhes'] = {
            'extend_relation.status': 1, 'extend_relation.create_time_second': '1795400000',
            'extend_relation.expire_time_second': '1796000000', 'extend_relation.effective_end_date_second': '1827000000',
            'extend_relation.remaining_extend_request_count': 1, 'extend_relation.id': '8690041642357393170123'}
        _, p = self._coleta(data=data)
        item = p['itens'][0]
        self.assertEqual({k: v for k, v in item.items() if k.startswith('renovacao')}, {
            'renovacao_status': '1', 'renovacao_pedido_second': '1795400000', 'renovacao_expira_second': '1796000000',
            'renovacao_novo_fim_second': '1827000000', 'renovacao_restantes': '1'})
        self.assertEqual(item['com_detalhes'], '1')

    def test_sem_a_lista_de_desvinculacao_nao_grava(self):
        for ruim in (RuntimeError('ponte'), resposta_status('1', []), dict(resposta_status('4', []), ok=False)):
            banco = Banco()
            cliente = Cliente(outros={'4': ruim})
            with self.subTest(ruim=str(ruim)[:30]):
                with self.assertRaises(Exception):
                    agenciados_sync.coletar(cliente, banco, now=NOW)
                self.assertEqual(banco.chamadas, [])

    def test_item_de_outro_status_invalida(self):
        errado = dict(self.SAINDO, tiktok_status=1)
        with self.assertRaises(agenciados_sync.ColetaInvalida):
            self._coleta(outros={'4': resposta_status('4', [errado])})

    def test_pendentes_com_falha_seguem_sem_eles(self):
        _, p = self._coleta(outros={'4': resposta_status('4', []), '2': RuntimeError('ponte')})
        self.assertNotIn('pendentes', p)
        self.assertEqual(len(p['itens']), 2)

    def test_desvinculacao_incompleta_marca_coleta_incompleta(self):
        lista = resposta_status('4', [dict(self.SAINDO)])
        lista['pages'][-1]['hasMore'] = True
        _, p = self._coleta(outros={'4': lista})
        self.assertFalse(p['completa'])


class ClienteRealTests(unittest.TestCase):
    """23/11: a lista com detalhes (7,5 MB) passava do limite de 2 MB em dois lugares do cliente."""

    def _cliente(self, tamanho):
        import playwright_client
        grande = resposta(itens=1)
        grande['items'][0]['detalhes'] = {'x': 'a' * tamanho}
        vistos = {}

        def transporte(**kw):
            vistos.update(kw)
            return 200, grande
        settings = {'tiktok_agency_url': 'https://tiktok-agenciamento-production.up.railway.app/bridge',
                    'tiktok_agency_token': 't' * 40}
        return playwright_client.PlaywrightClient(settings, transport=transporte), vistos

    def test_coleta_aceita_resposta_grande_e_outras_chamadas_nao(self):
        import playwright_client
        cliente, vistos = self._cliente(3 * 1024 * 1024)
        code, data = cliente._call('agency', 'GET', '/relations', max_bytes=agenciados_sync.MAX_RESPOSTA_BYTES)
        self.assertEqual((code, vistos['max_bytes']), (200, agenciados_sync.MAX_RESPOSTA_BYTES))
        cliente, vistos = self._cliente(3 * 1024 * 1024)
        with self.assertRaises(playwright_client._CallError):
            cliente._call('agency', 'GET', '/relations')
        self.assertNotIn('max_bytes', vistos)


class LigaDesligaTests(unittest.TestCase):
    def test_ligada_por_padrao_e_desligavel(self):
        self.assertTrue(load_settings({})['agency_sync_enabled'])
        self.assertFalse(load_settings({'V5_AGENCY_SYNC_ENABLED': 'false'})['agency_sync_enabled'])

    def test_nao_instala_fora_da_producao_real(self):
        for settings in ({'agency_sync_enabled': True, 'tiktok_mode': 'simulated', 'real_worker_enabled': True},
                         {'agency_sync_enabled': True, 'tiktok_mode': 'real', 'real_worker_enabled': False},
                         {'agency_sync_enabled': False, 'tiktok_mode': 'real', 'real_worker_enabled': True}):
            with self.subTest(settings=settings):
                self.assertFalse(agenciados_sync.instalar(None, settings))


if __name__ == '__main__':
    unittest.main()
