"""Pure name declaration and same-cycle question helper contracts."""
import unittest

from nome_contextual import extract_name, first_name, name_question


class NomeContextual28Tests(unittest.TestCase):
    def test_explicit_name_and_preference_do_not_require_agency_interest(self):
        for text, expected in (
            ('Meu nome é Ana Maria', 'Ana Maria'),
            ('Me chamo João da Silva.', 'João da Silva'),
            ('Me chamo Nome Novo', 'Nome Novo'),
            ('Sou a Ana', 'Ana'), ('Eu sou Vitor', 'Vitor'),
            ('Pode me chamar de Aninha', 'Aninha'),
            ('Prefiro que me chame de Ana', 'Ana'),
        ):
            with self.subTest(text=text):
                self.assertEqual(extract_name(text), expected)

    def test_bare_name_requires_the_callers_explicit_requested_flag(self):
        self.assertIsNone(extract_name('Ana'))
        self.assertIsNone(extract_name('Ana', requested='true'))
        self.assertEqual(extract_name('Ana', requested=True), 'Ana')
        self.assertEqual(extract_name('  Ana   Maria  ', requested=True), 'Ana Maria')

    def test_full_name_accents_apostrophes_hyphens_and_first_name(self):
        name = extract_name("Me chamo Ana-Maria D’Ávila")
        self.assertEqual(name, "Ana-Maria D'Ávila")
        self.assertEqual(first_name(name), 'Ana-Maria')
        self.assertEqual(first_name('João da Silva'), 'João')
        self.assertEqual(first_name('Nome Novo'), 'Nome')
        self.assertIsNone(first_name('Resetar'))

    def test_commands_greetings_and_journey_answers_are_not_bare_names(self):
        for text in ('Resetar', '/resetar', 'Recomeçar', 'Oi', 'Bom dia', 'Sim', 'Não',
                     'Já falei', 'Quero me agenciar', 'Anúncio', 'Indicação',
                     'Vi um vídeo no Instagram', 'Prefiro não informar', 'Tenho agência'):
            with self.subTest(text=text):
                self.assertIsNone(extract_name(text, requested=True))
        self.assertIsNone(extract_name('Nome', requested=True))
        self.assertIsNone(extract_name('Meu nome', requested=True))
        self.assertIsNone(extract_name('Nome de', requested=True))

    def test_question_third_party_example_and_embedded_requests_are_not_names(self):
        for text in ('Ana?', '"Ana"', 'Minha amiga se chama Ana', 'Se eu me chamo Ana',
                     'Exemplo Ana', 'Meu nome é Ana e quero me agenciar', 'Sou creator'):
            with self.subTest(text=text):
                self.assertIsNone(extract_name(text, requested=True))

    def test_contact_data_numbers_and_length_boundaries_are_refused(self):
        for text in ('ana@example.invalid', '@ana', '+5547999999999', 'Ana2',
                     'https://example.invalid/Ana', 'Ana\nMaria', 'A', 'A' * 81):
            with self.subTest(text=text):
                self.assertIsNone(extract_name(text, requested=True))
        self.assertEqual(extract_name('Li', requested=True), 'Li')

    def test_one_direct_name_question_or_request_is_recognized(self):
        for text in ('Como posso te chamar?', 'Qual é o seu nome?',
                     'Oi! Sou a Bia, agente de IA da Amplify. 👋\n\nComo posso te chamar?',
                     'Antes de começarmos, pode me dizer seu nome?',
                     'Me diga o seu nome.', 'Por qual nome posso te chamar?'):
            with self.subTest(text=text):
                self.assertTrue(name_question(text))

    def test_unrelated_quoted_or_multiple_collection_question_is_not_name_request(self):
        for text in ('Como você conheceu a Amplify?', 'Meu nome é Bia.',
                     'Qual seu nome? E seu @?', 'Me diga seu nome e telefone.',
                     'Qual seu nome e origem?', 'Seu nome aparece no formulário.',
                     'Não me diga seu nome.', 'Não preciso saber seu nome.',
                     'Você escreveu "qual seu nome?"'):
            with self.subTest(text=text):
                self.assertFalse(name_question(text))


if __name__ == '__main__':
    unittest.main()
