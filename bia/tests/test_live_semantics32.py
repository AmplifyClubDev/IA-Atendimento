"""Regression of the real-model audit's educational answer and defer decision."""
from copy import deepcopy
import unittest

import conversation
import conversao
import real_journey as journey
from tests.test_audit_response_semantics31 import NOW, POLICY, plan, state_at
from tests.test_relationship_form_chat30 import direct_entry


EDUCATION = ('A parceria oferece orientação no TikTok Shop. Após conferir a conta e sua autorização, '
             'um convite pode ser enviado; a confirmação do vínculo é feita no formulário.')


def turn(text, state=None, proposal=None, **kwargs):
    return conversation.handle(state or state_at('intro'), text,
        lambda *_: proposal or plan('Pode conversar comigo por aqui.'), now=NOW, real_mode=True,
        operation_policy=POLICY, relationship_check_in_form=True, **kwargs)


class LiveSemantics32Tests(unittest.TestCase):
    def test_real_how_it_works_answer_keeps_education_instead_of_personal_status(self):
        proposal = plan('Após conferir seu perfil, um convite é enviado e o vínculo é confirmado no formulário.',
                        approved=('funcionamento', EDUCATION))
        snapshot = deepcopy(proposal)
        result = turn('Como funciona', proposal=proposal)
        self.assertIn(EDUCATION, result['reply'])
        self.assertNotIn('Ainda não tenho confirmação', result['reply'])
        self.assertIn(conversao.CTA, result['reply'])
        self.assertEqual(result['buttons'], conversao.FIRST_BUTTONS)
        self.assertEqual(result['state']['cycle']['phase'], 'intro')
        self.assertEqual(result['state']['cycle']['facts'], {})
        self.assertEqual(result['effects'], [])
        self.assertEqual(proposal, snapshot)

    def test_educational_answer_does_not_approve_personal_invitation_or_access(self):
        proposal = plan('Seu convite foi enviado e seus acessos estão liberados.',
                        approved=('funcionamento', EDUCATION))
        result = turn('Meu convite já foi enviado?', proposal=proposal)
        self.assertNotIn('Seu convite foi enviado', result['reply'])
        self.assertNotIn('acessos estão liberados', result['reply'])
        self.assertNotIn('Se quiser começar', result['reply'])
        self.assertEqual(result['effects'], [])

    def test_useful_thematic_clarification_is_not_overwritten_by_education(self):
        clarification = 'Você quer entender a comunidade ou as campanhas?'
        result = turn('Como funciona', proposal=plan(clarification, intent='clarify',
                                                   approved=('funcionamento', EDUCATION)))
        self.assertEqual(result['reply'], clarification)
        self.assertEqual(result['buttons'], [])

    def test_female_existing_creator_works_with_real_inbound_provenance(self):
        first, after_handle, _ = direct_entry('Já sou agenciada pela Amplify e quero meus acessos')
        self.assertEqual(first['state']['cycle']['phase'], 'tiktok')
        self.assertIn('@ do TikTok', first['reply'])
        self.assertEqual(first['effects'], [])
        self.assertEqual(after_handle['state']['cycle']['phase'], 'form')
        self.assertEqual(after_handle['effects'], [])
        self.assertIn(journey.PUBLIC_FORM_URL, after_handle['reply'])
        self.assertFalse(any(e.get('operation') == 'invite' for e in after_handle['state']['effects'].values()))
        self.assertNotIn('consentimento_convite', after_handle['state']['cycle']['facts'])

    def test_unproven_existing_creator_text_does_not_fabricate_form_identity(self):
        result = turn('Já sou agenciada pela Amplify e quero meus acessos')
        self.assertNotIn('form_entry_request', result['state']['cycle'])
        self.assertEqual(result['effects'], [])
        self.assertFalse(journey.form_entry_allowed(result['state'], now=NOW))
        self.assertIsNone(journey._direct_form_reason('Já tenho agência'))

    def test_real_defer_message_closes_cycle_without_repeating_question(self):
        state = state_at('origin')
        state['cycle']['facts']['nome_declarado'] = 'Ana'
        source_facts = deepcopy(state['cycle']['facts'])
        calls = []
        result = conversation.handle(state, 'Prefiro pensar e voltar depois',
            lambda *_: calls.append(True), now=NOW, real_mode=True,
            operation_policy=POLICY, relationship_check_in_form=True)
        self.assertEqual(calls, [])
        self.assertEqual(result['state']['cycle']['status'], 'closed')
        self.assertEqual(result['state']['cycle']['reason'], 'lead_pause')
        self.assertEqual(result['state']['cycle']['facts'], source_facts)
        self.assertNotIn('Como você conheceu', result['reply'])
        self.assertEqual(result['reply'].count('?'), 0)
        self.assertEqual(result['buttons'], [])
        self.assertEqual(result['effects'], [])

    def test_defer_variations_are_explicit_personal_decisions(self):
        for text in ('Quero refletir e voltar outro dia', 'Vou avaliar melhor e retorno mais tarde',
                     'Eu preciso pensar e conversar depois'):
            with self.subTest(text=text):
                self.assertEqual(turn(text, state_at('origin'))['state']['cycle']['status'], 'closed')

    def test_pause_questions_examples_and_third_party_do_not_close_cycle(self):
        for text in ('Como pausar?', 'Se eu preferir pensar e voltar depois, posso retomar?',
                     'Ela prefere pensar e voltar depois', '"Prefiro pensar e voltar depois"',
                     "'Prefiro pensar e voltar depois'",
                     'Quero avaliar meu perfil'):
            with self.subTest(text=text):
                result = turn(text, state_at('origin'), plan('Você pode tirar dúvidas antes de decidir.'))
                self.assertEqual(result['state']['cycle']['status'], 'open')

    def test_pause_preserves_uncertain_invite_fence_and_cancels_read_only_work(self):
        state = state_at('origin')
        cycle = state['cycle']['id']
        state['effects'].update({
            'invite-old': {'id': 'invite-old', 'type': 'tiktok_operation', 'cycle_id': cycle,
                           'creator': '@teste', 'operation': 'invite', 'status': 'running'},
            'lookup-old': {'id': 'lookup-old', 'type': 'tiktok_operation', 'cycle_id': cycle,
                           'creator': '@teste', 'operation': 'lookup', 'status': 'pending'}})
        result = turn('Prefiro pensar e voltar depois', state)
        self.assertEqual(result['state']['effects']['invite-old']['status'], 'outcome_unknown')
        self.assertEqual(result['state']['effects']['lookup-old']['status'], 'cancelled')
        self.assertEqual(result['effects'], [])

    def test_legacy_simulated_defer_interpretation_is_preserved(self):
        state = conversation.handle({}, 'Quero me agenciar', now=NOW, real_mode=False)['state']
        result = conversation.handle(state, 'Prefiro pensar e voltar depois',
                                     now=NOW, real_mode=False)
        self.assertEqual(result['state']['cycle']['status'], 'open')


if __name__ == '__main__':
    unittest.main()
