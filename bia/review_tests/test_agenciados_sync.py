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


class Cliente:
    def __init__(self, code=200, data=None, pronta=True):
        self.code, self.data, self.pronta, self.chamadas = code, data or resposta(), pronta, []

    def _ready(self, role):
        self.chamadas.append(('ready', role))
        if not self.pronta:
            raise RuntimeError('session_not_ready')

    def _call(self, role, method, path, params=None, **kw):
        self.chamadas.append((role, method, path, params))
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
