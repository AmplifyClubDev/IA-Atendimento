"""Release 48: etiqueta da etapa + "encerrado" mostram onde o lead parou."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

from retomada import Retomada
from transport import ChatwootProgress, ChatwootTransport
from test_inactivity_stage29 import Adapter, Repo

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Etiquetas48Tests(unittest.TestCase):
    def setUp(self):
        self.gate = {'enabled': True, 'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
                     'phone': '+5547991154859', 'phones': ['+5547991154859'], 'inactivity_close_enabled': True}
        self.event = {'provider': 'chatwoot', 'account_id': '1', 'inbox_id': '3',
                      'conversation_id': '26097', 'contact_id': '3', 'message_id': '777',
                      'message_type': 'incoming', 'private': False, 'sender_type': 'contact',
                      'sender_phone': '+554791154859', 'text': 'meu @ é fulana'}
        self.state = {'session_id': str(uuid4()), 'creator_id': str(uuid4()), 'revision': 7,
                      'processed_inbound': ['chatwoot:1:777'],
                      'chatwoot_progress': {'confirmed_signature': 'x', 'confirmed_labels': ['convite']},
                      'cycle': {'id': str(uuid4()), 'phase': 'await_acceptance', 'status': 'open',
                                'expires_at': (NOW - timedelta(hours=1)).isoformat()}}
        self.repo, self.adapter = Repo(self.state), Adapter()
        self.adapter.labels = ['convite', 'outra-equipe']
        self.progress = ChatwootProgress(self.repo, self.gate, self.adapter)

    def parado(self, now=NOW):
        return self.progress.sync(self.event, self.state, {'kind': 'parado', 'now': now.isoformat()})

    def contact_proof(self, status, revision):
        cycle = self.state['cycle']
        return {'kind': 'contact', 'receipt': {'creator_id': self.state['creator_id'], 'atendimento_id': cycle['id'],
                'event_id': 'chatwoot:1:777', 'revision': revision},
                'snapshot': {'cycle_id': cycle['id'], 'phase': cycle['phase'], 'status': status, 'revision': revision}}

    def test_lead_parado_ganha_encerrado_e_mantem_a_etapa(self):
        self.assertEqual(self.parado()['status'], 'confirmed')
        self.assertEqual(set(self.adapter.labels), {'convite', 'encerrado', 'outra-equipe'})

    def test_segunda_varredura_nao_escreve_de_novo(self):
        self.parado()
        self.state = self.repo.load_session('x')
        self.assertEqual(self.parado()['status'], 'unchanged')
        self.assertEqual(len(self.adapter.writes), 1)

    def test_dentro_da_janela_nao_marca(self):
        self.assertEqual(self.parado(NOW - timedelta(hours=2))['status'], 'ignored')
        self.assertEqual(self.adapter.writes, [])

    def test_sem_etapa_confirmada_antes_nao_marca(self):
        self.state['chatwoot_progress'] = {}
        self.repo.state = deepcopy(self.state)
        self.assertEqual(self.parado()['status'], 'ignored')
        self.assertEqual(self.adapter.writes, [])

    def test_sem_opt_in_do_encerrado_nao_marca(self):
        self.progress = ChatwootProgress(self.repo, {**self.gate, 'inactivity_close_enabled': False}, self.adapter)
        self.assertEqual(self.parado()['status'], 'ignored')
        self.assertEqual(self.adapter.writes, [])

    def test_quando_volta_a_escrever_o_encerrado_sai(self):
        self.parado()
        self.state = self.repo.load_session('x')
        self.state['cycle'].update(phase='form', linked_notice={'at': NOW.isoformat()},
                                  expires_at=(NOW + timedelta(hours=23)).isoformat())
        self.state['revision'] += 1
        self.repo.state = deepcopy(self.state)
        proof = self.contact_proof('open', self.state['revision'])
        self.assertEqual(self.progress.sync(self.event, self.state, proof)['status'], 'confirmed')
        self.assertEqual(set(self.adapter.labels), {'cadastro', 'outra-equipe'})

    def test_atendimento_expirado_tambem_mostra_onde_parou(self):
        self.state['cycle'].update(status='expired', reason='24h_since_last_inbound')
        self.repo.state = deepcopy(self.state)
        self.progress.sync(self.event, self.state, self.contact_proof('expired', 7))
        self.assertEqual(set(self.adapter.labels), {'convite', 'encerrado', 'outra-equipe'})

    def test_chatwoot_recebe_etapa_e_encerrado_no_mesmo_pedido(self):
        requests = []
        adapter = ChatwootTransport('https://chatwoot.t2ffoz.easypanel.host', 'offline-token', self.gate,
                                    http=lambda **request: requests.append(request) or {})
        adapter._read_target = lambda *args, **kwargs: True
        adapter.write_progress(self.event, ['convite', 'encerrado'], 'stage-test:2')
        body = requests[0]['json_body']['labels']
        self.assertEqual(body['add'], ['convite', 'encerrado'])
        self.assertNotIn('encerrado', body['remove'])
        self.assertNotIn('outra-equipe', body['remove'])

    def test_encerrado_sozinho_ou_duas_etapas_sao_recusados(self):
        adapter = ChatwootTransport('https://chatwoot.t2ffoz.easypanel.host', 'offline-token', self.gate,
                                    http=lambda **request: {})
        adapter._read_target = lambda *args, **kwargs: True
        for labels in (['encerrado'], ['convite', 'cadastro'], ['convite', 'cadastro', 'encerrado']):
            self.assertEqual(adapter.write_progress(self.event, labels, 'stage-test:3')['reason'], 'invalid_stage_delta')

    def test_varredura_chama_a_marcacao_para_quem_passou_das_24h(self):
        calls, test = [], self

        class Repository:
            def followup_source(self, conv):
                return {'cycle_id': test.state['cycle']['id'], 'event_key': 'chatwoot:1:777', 'event': test.event}

            def load_session(self, conv):
                return {**deepcopy(test.state), 'cycle': {**test.state['cycle'], 'mode': 'real'}}

        retomada = Retomada(Repository(), {}, None, lambda conv: _Lock(), None, now=lambda: NOW,
                            on_stopped=lambda event, state, now: calls.append((event['conversation_id'], now)))
        self.assertEqual(retomada._conversation('chatwoot:1:26097', NOW)['motivo'], 'fora_da_janela_24h')
        self.assertEqual(calls, [('26097', NOW)])

    def test_controle_humano_nao_ganha_encerrado(self):
        calls, test = [], self
        self.state['human_control'] = True

        class Repository:
            def followup_source(self, conv):
                return {'cycle_id': test.state['cycle']['id'], 'event_key': 'chatwoot:1:777', 'event': test.event}

            def load_session(self, conv):
                return {**deepcopy(test.state), 'cycle': {**test.state['cycle'], 'mode': 'real'}}

        retomada = Retomada(Repository(), {}, None, lambda conv: _Lock(), None, now=lambda: NOW,
                            on_stopped=lambda *args: calls.append(args))
        retomada._conversation('chatwoot:1:26097', NOW)
        self.assertEqual(calls, [])


class EtapaReal48Tests(unittest.TestCase):
    def label(self, phase, **extra):
        from transport import _stage_label
        return _stage_label({'cycle': {'phase': phase, **extra.pop('cycle', {})}, **extra})

    def test_formulario_sem_vinculo_ainda_e_convite(self):
        self.assertEqual(self.label('form'), 'convite')

    def test_formulario_com_vinculo_comprovado_e_cadastro(self):
        self.assertEqual(self.label('form', cycle={'linked_notice': {'at': 'x'}}), 'cadastro')
        self.assertEqual(self.label('form', cycle={'real_operations': {'relationship': {'status': 'linked', 'confirmed': True}}}),
                         'cadastro')
        self.assertEqual(self.label('form', cadastro_situacao='confirmado'), 'cadastro')

    def test_vinculo_nao_confirmado_nao_conta(self):
        self.assertEqual(self.label('form', cycle={'real_operations': {'relationship': {'status': 'linked'}}}), 'convite')

    def test_conferindo_aceite_e_convite_e_acesso_e_cadastro(self):
        self.assertEqual(self.label('checking_acceptance'), 'convite')
        self.assertEqual(self.label('acesso', cycle={'acesso_liberado': True}), 'cadastro')
        self.assertEqual(self.label('checking'), 'validação')


if __name__ == '__main__':
    unittest.main()
