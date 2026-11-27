"""27/11/2026: "Já sou Amplify" e a etiqueta de renovação são do serviço de renovação (a Bia dos agenciados)."""
import unittest

from real_operations import gate_exclusion

TODOS = {'mode': 'todos', 'phone': '+5547991154859', 'inbox_id': 3}
LISTA = {'phone': '+5547991154859', 'inbox_id': 3}
RENOVACAO = 'fora_do_gate:renovacao_de_contrato'


class JaSouAmplifyGate(unittest.TestCase):
    def test_botao_ja_sou_amplify_fica_com_o_servico(self):
        for texto in ('Já sou Amplify', 'já sou amplify!', '  JA SOU AMPLIFY '):
            self.assertEqual(gate_exclusion(TODOS, {'text': texto, 'sender_phone': '+5511999990000'}, {}), RENOVACAO)

    def test_vale_no_numero_de_teste_e_no_modo_lista(self):
        evento = {'text': 'Já sou Amplify', 'sender_phone': '+5547991154859'}
        self.assertEqual(gate_exclusion(TODOS, evento, {}), RENOVACAO)
        self.assertEqual(gate_exclusion(LISTA, evento, {}), RENOVACAO)
        self.assertEqual(gate_exclusion(TODOS, {'text': 'oi', 'sender_phone': '+5547991154859'},
                                        {'labels': ['Renovacao de contrato']}), RENOVACAO)

    def test_outras_mensagens_seguem_com_a_bia(self):
        self.assertIsNone(gate_exclusion(TODOS, {'text': 'Já sou Amplify e quero saber do GMV'}, {}))
        self.assertIsNone(gate_exclusion(TODOS, {'text': 'Quero ser Amplify'}, {'labels': ['lead']}))
        self.assertIsNone(gate_exclusion(TODOS, {'text': None}, {'labels': None}))


if __name__ == '__main__':
    unittest.main()
