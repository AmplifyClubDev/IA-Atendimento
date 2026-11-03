"""General education keeps its meaning; personal status still needs receipts."""
from copy import deepcopy
import unittest

import receipt_grounding as subject
from test_receipt_grounding28 import NOW, POLICY, base, proven


SUMMARY = ('A Amplify apoia creators no TikTok Shop. Após conferir a conta e receber sua autorização, '
           'o convite é enviado. O formulário verifica o vínculo e recebe o cadastro.')


def plan(*, topic='funcionamento', summary=SUMMARY, **updates):
    value = {'provider_status': 'completed', 'intent': 'question', 'reply': 'Seu convite já foi enviado.',
             'claims': [], 'topic_ids': [topic], 'knowledge_version': 'approved32:fixture',
             'approved_topic_answer': {'id': topic, 'text': summary, 'source': 'approved_context',
                                       'knowledge_version': 'approved32:fixture'}}
    value.update(updates)
    return value


class ContextualMeaning32Tests(unittest.TestCase):
    def test_educational_summary_is_not_downgraded_to_unknown_personal_status(self):
        proposal, state = plan(), base()
        before = deepcopy(state)
        old = subject.ground_reply('Como funciona', SUMMARY, proposal, state, policy=POLICY, now=NOW)
        self.assertNotIn('não tenho confirmação', old)
        answer = subject.approved_educational_reply('Como funciona', proposal)
        self.assertEqual(answer, SUMMARY)
        self.assertNotIn('não tenho confirmação', answer)
        self.assertEqual(state, before)

    def test_general_how_it_works_variants_use_the_same_approved_excerpt(self):
        for text in ('Como funciona?', 'Como funciona a parceria?', 'Como funciona o agenciamento?',
                     'Me explica como funciona a Amplify', 'Quero saber como funciona essa parceria'):
            with self.subTest(text=text):
                self.assertEqual(subject.approved_educational_reply(text, plan()), SUMMARY)

    def test_benefits_can_explain_registration_and_access_without_claiming_delivery(self):
        summary = 'A parceria pode incluir orientação e acesso à comunidade, conforme a categoria e as condições.'
        for text in ('Benefícios', 'Quais são os benefícios?', 'Quais as vantagens da Amplify?'):
            with self.subTest(text=text):
                self.assertEqual(subject.approved_educational_reply(text, plan(topic='beneficios', summary=summary)), summary)

    def test_amplify_description_uses_only_its_approved_topic(self):
        summary = 'A Amplify trabalha com creators do TikTok Shop e orienta a jornada de parceria.'
        for text in ('O que é a Amplify?', 'Conhecer a Amplify', 'O que a Amplify faz?'):
            with self.subTest(text=text):
                self.assertEqual(subject.approved_educational_reply(text, plan(topic='amplify', summary=summary)), summary)

    def test_personal_status_and_acceptance_questions_cannot_take_the_educational_path(self):
        for text in ('Meu convite foi enviado?', 'Como está meu vínculo?', 'Onde aceito o convite?',
                     'Como funciona meu cadastro?', 'Como funciona? Meu convite foi enviado?',
                     'Já sou agenciada pela Amplify e quero meus acessos'):
            with self.subTest(text=text):
                self.assertIsNone(subject.approved_educational_reply(text, plan()))
                answer = subject.ground_reply(text, 'Seu convite já foi enviado.', plan(), base(), policy=POLICY, now=NOW)
                self.assertNotIn('confirmou o envio', answer)
                self.assertNotIn('vínculo com a Amplify foi confirmado', answer)

    def test_unproven_model_success_is_never_used_as_the_educational_excerpt(self):
        proposal = plan(reply='Prontinho, mandei seu convite e confirmei seu vínculo.')
        self.assertEqual(subject.approved_educational_reply('Como funciona', proposal), SUMMARY)
        self.assertNotEqual(subject.approved_educational_reply('Como funciona', proposal), proposal['reply'])

    def test_approved_faq_metadata_is_not_a_receipt_for_personal_or_completed_operations(self):
        for summary in ('Seu convite foi enviado, vínculo confirmado e acesso liberado.',
                        'Você já está agenciada pela Amplify.', 'Eu finalizei o vínculo e liberei os acessos.',
                        'Prontinho, seu convite está na sua conta.', 'Já enviei o convite.',
                        'Convite enviado. Cadastro concluído.', 'Vínculo confirmado. Acesso liberado.',
                        'O vínculo foi confirmado.', 'O convite foi enviado.', 'Os acessos estão liberados.'):
            with self.subTest(summary=summary):
                self.assertIsNone(subject.approved_educational_reply('Como funciona', plan(summary=summary)))

    def test_missing_wrong_or_stale_metadata_cannot_override_the_receipt_gate(self):
        mutations = ({'source': 'model'}, {'id': 'convite_tiktok'}, {'id': 'beneficios'},
                     {'knowledge_version': 'older'}, {'text': ''}, {'text': 'x' * 651})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                proposal = plan()
                proposal['approved_topic_answer'].update(mutation)
                self.assertIsNone(subject.approved_educational_reply('Como funciona', proposal))
        for proposal in ({}, plan(knowledge_version=''), plan(approved_topic_answer=None)):
            self.assertIsNone(subject.approved_educational_reply('Como funciona', proposal))

    def test_links_internal_instructions_and_financial_conditions_are_not_educational_bypasses(self):
        for summary in ('Veja https://example.invalid', 'Use o backend SQL.', 'Consulte a base aprovada.',
                        'A taxa é de 50%.', 'Receba R$100.', 'O prazo é de 8 meses.', 'Me informe seu @?'):
            with self.subTest(summary=summary):
                self.assertIsNone(subject.approved_educational_reply('Como funciona', plan(summary=summary)))

    def test_valid_clarification_question_is_preserved_instead_of_broad_faq(self):
        proposal = plan(intent='clarify', reply='Você quer entender a parceria ou a comissão dos produtos?')
        self.assertIsNone(subject.approved_educational_reply('Como funciona', proposal))

    def test_backend_faq_is_available_even_when_model_is_unavailable(self):
        for status in ('invalid_response', 'incomplete', 'unknown', 'failed'):
            with self.subTest(status=status):
                self.assertEqual(subject.approved_educational_reply('Como funciona', plan(provider_status=status, reply='')), SUMMARY)

    def test_actual_bound_status_receipts_still_control_personal_success(self):
        proposal = plan()
        answer = subject.ground_reply('Como está meu vínculo?', 'Você está agenciada.', proposal,
                                      proven('relationship', 'linked'), policy=POLICY, now=NOW)
        self.assertIn('vínculo com a Amplify foi confirmado', answer)
        self.assertIsNone(subject.approved_educational_reply('Como está meu vínculo?', proposal))

    def test_general_education_does_not_change_or_authorize_business_actions(self):
        proposal = plan()
        before = deepcopy(proposal)
        self.assertEqual(subject.approved_educational_reply('Como funciona', proposal), SUMMARY)
        self.assertEqual(proposal, before)
        self.assertEqual(proposal['claims'], [])


if __name__ == '__main__':
    unittest.main()
