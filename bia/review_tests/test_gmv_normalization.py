import unittest
from gmv_normalization import normalize_gmv


class Normalization(unittest.TestCase):
    def test_approved_examples(self):
        cases = {
            'Não vendi nada ainds': (0, 'sem_vendas'),
            'Nunca fiz venda dentro do meu TikTok shop. Mas é ativo': (0, 'sem_vendas'),
            'Só ativei': (0, 'inicio_atividade'),
            'Estou começando': (0, 'inicio_atividade'),
            'Não sei': (0, 'nao_sabe'),
            'ñ sei dizer': (0, 'nao_sabe'),
            'Comecei agora 400 e pouquinho': (40000, 'aproximado'),
            'Em torno de uns 800.00 reais': (80000, 'aproximado'),
            'entre 15 a 20 mil': (1500000, 'limite_inferior_faixa'),
            'Entre 15.000 a 20.000 mil': (1500000, 'limite_inferior_faixa'),
            'Entre 15 mil e 20 mil': (1500000, 'limite_inferior_faixa'),
            '50-60k': (5000000, 'limite_inferior_faixa'),
            'R$ 90.000,00': (9000000, 'valor_explicito'),
        }
        for text, expected in cases.items():
            with self.subTest(text=text): self.assertEqual(normalize_gmv(text), expected)

    def test_rest_is_not_converted(self):
        for text in ['Não vendo nada quase', '20.000.00', 'Acho que fiz 1 venda',
                'Gmv 950 em um dia', 'Período: 01/11 a 16/11 : R$ 1.344,55',
                'Mês de novembro até agora 46.300,27', 'Não', 'O', 'Ok',
                'Estou começando, já vendi 5 produtos, estou a um mês,',
                'Em torno de 800 USD', '400 de comissão', 'Entre 20 e 15 mil']:
            with self.subTest(text=text): self.assertIsNone(normalize_gmv(text))


if __name__ == '__main__':
    unittest.main()
