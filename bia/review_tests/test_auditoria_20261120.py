"""Auditoria 20/11/2026: correções da caixa 3 (pedido de especialista, limites e alertas)."""
from copy import deepcopy
import unittest

import test_etiquetas48


class EspecialistaNaoEncerraTests(test_etiquetas48.Etiquetas48Tests):
    """Herda o cenário do lead parado (release 48) e liga o pedido de especialista."""

    def setUp(self):
        super().setUp()
        self.state['cycle']['bia_validation'] = {'stage': 'specialist', 'preference': 'specialist',
                                                 'handoff_requested': True}
        self.repo.state = deepcopy(self.state)

    def test_pedido_de_especialista_parado_nao_ganha_encerrado(self):
        self.parado()
        self.assertNotIn('encerrado', self.adapter.labels)
        self.assertIn('convite', self.adapter.labels)

    def test_depois_de_voltar_para_a_bia_o_encerrado_volta_a_valer(self):
        self.state['cycle']['bia_validation'] = {'stage': 'complete', 'preference': 'machine'}
        self.repo.state = deepcopy(self.state)
        self.parado()
        self.assertIn('encerrado', self.adapter.labels)


# Os testes herdados do cenário base já rodam no arquivo original.
for _name in [n for n in dir(test_etiquetas48.Etiquetas48Tests) if n.startswith('test_')]:
    if not hasattr(EspecialistaNaoEncerraTests, _name) or _name in vars(test_etiquetas48.Etiquetas48Tests):
        setattr(EspecialistaNaoEncerraTests, _name, None)




from datetime import timedelta

import conversao
import conversation
import retomada
from test_relationship_form_chat30 import AT, POLICY, qualified


def _settle_at(state, effect, now, status='verification_pending', reason='shop_unknown'):
    result = dict(operation=effect['operation'], creator=effect['creator'].lstrip('@'), status=status,
                  confirmed=True, observed_at=now.isoformat(), reason=reason,
                  evidence={'source': 'offline', 'complete': True})
    return conversation.resolve_tiktok_result(state, effect['id'], result, now=now, operation_policy=POLICY)


def _say(state, text, now):
    return conversation.handle(state, text, now=now, real_mode=True,
                               operation_policy=POLICY, relationship_check_in_form=True)


class ProntoComLimiteTests(unittest.TestCase):
    """Conversa 50149: o lead mandou "Pronto" mais de 10 vezes e recebeu sempre a mesma mensagem."""

    def stuck(self):
        result = qualified()
        effect = next(item for item in result['effects'] if item['operation'] == 'precheck')
        return _settle_at(result['state'], effect, AT)

    def test_duas_reconferencias_depois_mensagem_clara_e_alerta(self):
        result = self.stuck()
        self.assertEqual(result['reply'], conversao.SHOP_UNKNOWN)
        now = AT
        for rodada in (1, 2):
            now += timedelta(minutes=11)
            result = _say(result['state'], 'pronto', now)
            check = [e for e in result['effects'] if e['operation'] == 'precheck']
            self.assertEqual(len(check), 1, rodada)
            self.assertEqual(result['state']['cycle']['shop_rechecks'], rodada)
            result = _settle_at(result['state'], check[0], now)
        now += timedelta(minutes=11)
        result = _say(result['state'], 'pronto', now)
        self.assertEqual(result['reply'], conversao.SHOP_LIMIT)
        self.assertFalse([e for e in result['effects'] if e['operation'] == 'precheck'])
        self.assertEqual(result['state']['cycle']['team_alert']['reason'], 'shop_unknown_limit')
        self.assertNotIn('equipe', result['reply'].lower())
        self.assertNotIn('time', result['reply'].lower().split())
        alerta = result['state']['cycle']['team_alert']
        for minutos in (1, 30):
            result = _say(result['state'], 'pronto', now + timedelta(minutes=minutos))
            self.assertEqual(result['reply'], conversao.SHOP_LIMIT_STILL)
            self.assertFalse(result['effects'])
        self.assertEqual(result['state']['cycle']['team_alert'], alerta)

    def test_lembrete_nao_pede_pronto_depois_do_limite(self):
        state = self.stuck()['state']
        state['cycle']['team_alert'] = {'at': AT.isoformat(), 'reason': 'shop_unknown_limit'}
        self.assertIsNone(retomada._message(state, 1, {}, now=AT))


import lead_alerts
import test_lead_alerts


class AlertaLeadParadoTests(test_lead_alerts.AlertTests):
    """Antes: cycle['team_alert'] era gravado e nada lia (330 leads em blocked sem aviso)."""

    def setUp(self):
        super().setUp()
        # Lead comum: sem GMV alto e sem fluxo prioritário.
        self.state = {'cycle': {'id': 'cycle-b', 'facts': {'nome_declarado': 'Bea', 'tiktok_declarado': '@bea'},
                                'team_alert': {'at': '2026-11-20T10:00:00+00:00', 'reason': 'shop_unknown_limit'}}}

    def team(self):
        return lead_alerts.dispatch_team(self.settings, self.repo, self.event, self.state, http=self.http)

    def test_motivo_conhecido_manda_um_alerta_so(self):
        self.assertEqual(self.team()['status'], 'accepted')
        self.assertEqual(self.state['cycle']['team_alert']['status'], 'accepted')
        text = self.posts()[0]['payload']['text']
        self.assertIn('Lead parado precisa do time', text)
        self.assertIn('2 reconferências', text)
        self.assertIn('https://chat.example/app/accounts/1/conversations/7', text)
        self.team(); self.team()
        self.assertEqual(len(self.posts()), 1)

    def test_cada_motivo_tem_seu_alerta(self):
        self.team()
        self.state['cycle']['team_alert'] = {'reason': 'invite_failed_twice'}
        self.team()
        self.assertEqual(len(self.posts()), 2)
        self.assertIn('convite no TikTok falhou duas vezes', self.posts()[-1]['payload']['text'])

    def test_sem_motivo_ou_motivo_desconhecido_nao_envia(self):
        for alert in (None, {'reason': 'outro'}, 'texto'):
            self.state['cycle']['team_alert'] = alert
            self.assertEqual(self.team()['status'], 'not_requested')
        self.assertFalse(self.calls)

    def test_opt_out_e_slack_sem_config_nao_enviam(self):
        self.state['cycle']['opt_out'] = True
        self.assertEqual(self.team()['reason'], 'opt_out')
        self.state['cycle'].pop('opt_out'); self.settings['slack_bot_token'] = ''
        self.assertEqual(self.team()['reason'], 'slack_not_configured')
        self.assertFalse(self.posts())


# Os testes herdados de AlertTests já rodam em test_lead_alerts.
for _name in [n for n in vars(test_lead_alerts.AlertTests) if n.startswith('test_')]:
    setattr(AlertaLeadParadoTests, _name, None)


import real_journey


class FrasesTests(unittest.TestCase):
    """Conversas 50149 e 53534: frase repetida na mesma resposta e textos frios."""

    def test_paragrafo_repetido_sai_uma_vez_so(self):
        texto = 'Oi!\n\n' + conversao.SHOP_UNKNOWN + '\n\n' + conversao.SHOP_UNKNOWN
        self.assertEqual(conversao.without_repeated_paragraphs(texto), 'Oi!\n\n' + conversao.SHOP_UNKNOWN)
        self.assertEqual(conversao.without_repeated_paragraphs('A\n\n  a  \n\nB'), 'A\n\nB')
        for intacto in ('', None, 'Uma linha', 'Linha 1\nLinha 1'):
            self.assertEqual(conversao.without_repeated_paragraphs(intacto), intacto)

    def test_trava_reconhece_os_avisos_atuais(self):
        self.assertTrue(real_journey._already_says('Combinado!\n\n' + conversao.INVITE_WAIT,
                                                   conversao.INVITE_STILL, conversao.INVITE_WAIT))
        self.assertFalse(real_journey._already_says('Combinado!', conversao.INVITE_STILL))

    def test_avisos_de_espera_sao_diferentes_e_humanos(self):
        self.assertNotEqual(conversao.INVITE_WAIT, conversao.INVITE_STILL)
        frias = ('validação necessária', 'não está confirmado', 'confirmação necessária', 'está registrad')
        for texto in (conversao.BRIDGE_WAIT, conversao.BRIDGE_STILL, conversao.BRIDGE_NOTE, conversao.INVITE_WAIT,
                      conversao.INVITE_STILL, conversao.PRIOR_INVITE_RESENT, conversao.INVITE_FAILED_TEAM):
            with self.subTest(texto=texto):
                self.assertFalse([f for f in frias if f in texto])
                palavras = texto.lower().replace('!', ' ').replace('.', ' ').split()
                self.assertFalse({'time', 'equipe', 'humano'} & set(palavras))  # release 51


import contextlib
import io

import server


class LogDeFalhaTests(unittest.TestCase):
    """Conversa 55626: "Tive uma instabilidade" saía sem nenhum log da causa."""

    def test_registra_tipo_e_ponto_do_codigo_sem_dados_do_lead(self):
        try:
            {}['+5511999999999 texto do lead']
        except KeyError as error:
            saida = io.StringIO()
            with contextlib.redirect_stdout(saida):
                server._log_inbound_failure(error)
        linha = saida.getvalue()
        self.assertIn('[bia] inbound_falhou tipo=KeyError onde=test_auditoria_20261120.py:', linha)
        self.assertNotIn('5511999999999', linha)
        self.assertNotIn('texto do lead', linha)


from transport import ChatwootProgress


class _AdapterComResolver(test_etiquetas48.Adapter):
    def __init__(self):
        super().__init__()
        self.resolvidas = []

    def resolve(self, event, key):
        self.resolvidas.append(key)
        return {'status': 'accepted'}


class EncerradoEResolvidoTests(test_etiquetas48.Etiquetas48Tests):
    """15.644 conversas "abertas": o encerrado falhava após o 2º lembrete e nada era resolvido."""

    def setUp(self):
        super().setUp()
        self.adapter = _AdapterComResolver()
        self.adapter.labels = ['convite', 'outra-equipe']
        self.progress = ChatwootProgress(self.repo, self.gate, self.adapter)

    def ligar_resolver(self):
        self.progress = ChatwootProgress(self.repo, {**self.gate, 'resolve_on_close_enabled': True}, self.adapter)

    def test_ciclo_fechado_pelo_2o_lembrete_ganha_encerrado(self):
        self.state['cycle'].update(status='closed', reason='inactivity_timeout',
                                   expires_at=(test_etiquetas48.NOW + test_etiquetas48.timedelta(hours=5)).isoformat())
        self.repo.state = deepcopy(self.state)
        self.assertEqual(self.parado()['status'], 'confirmed')
        self.assertIn('encerrado', self.adapter.labels)

    def test_ciclo_fechado_por_outro_motivo_nao_ganha_encerrado(self):
        self.state['cycle'].update(status='closed', reason='validated_form')
        self.repo.state = deepcopy(self.state)
        self.assertEqual(self.parado()['status'], 'ignored')

    def test_sem_a_chave_nao_resolve(self):
        self.parado()
        self.assertIn('encerrado', self.adapter.labels)
        self.assertEqual(self.adapter.resolvidas, [])

    def test_com_a_chave_resolve_uma_vez_por_ciclo(self):
        self.ligar_resolver()
        self.parado()
        self.assertEqual(len(self.adapter.resolvidas), 1)
        self.state = self.repo.load_session('x')
        self.parado()
        self.assertEqual(len(self.adapter.resolvidas), 1)

    def test_especialista_nunca_e_resolvido(self):
        self.ligar_resolver()
        self.state['cycle']['bia_validation'] = {'stage': 'specialist'}
        self.repo.state = deepcopy(self.state)
        self.parado()
        self.assertEqual(self.adapter.resolvidas, [])


for _name in [n for n in vars(test_etiquetas48.Etiquetas48Tests) if n.startswith('test_')]:
    setattr(EncerradoEResolvidoTests, _name, None)


if __name__ == '__main__':
    unittest.main()
