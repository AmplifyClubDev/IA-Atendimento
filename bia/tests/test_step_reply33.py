"""Exact canonical explanation deduplication at the current collection step."""
from copy import deepcopy
import unittest

import conversation
import real_journey as journey
from tests.test_audit_response_semantics31 import NOW, POLICY, plan, state_at


REASON = 'Vou consultar esse perfil para conferir o caminho do agenciamento.'


def handle(reply):
    state = state_at('tiktok')
    state['cycle']['facts']['nome_declarado'] = 'Ana'
    return conversation.handle(state, 'Não sei se minha conta está ativa', lambda *_: plan(reply, intent='converse'),
        now=NOW, real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)


class StepReply33Tests(unittest.TestCase):
    def test_real_model_reply_keeps_name_and_reason_once(self):
        raw = 'Sem problemas, Ana! 😊 Vou te ajudar a conferir isso. \n\n' + journey.PROMPTS['tiktok']
        result = handle(raw)
        self.assertIn('Sem problemas, Ana!', result['reply'])
        self.assertIn('Vou te ajudar a conferir isso.', result['reply'])
        self.assertEqual(result['reply'].count(REASON), 1)
        self.assertEqual(result['reply'].count('Qual é o seu @ do TikTok?'), 1)
        self.assertEqual(result['reply'].count('?'), 1)
        self.assertEqual(result['state']['cycle']['phase'], 'tiktok')
        self.assertEqual(result['state']['cycle']['facts']['nome_declarado'], 'Ana')
        self.assertIsNone(result['state']['cycle']['facts']['shop_ativo_declarado'])
        self.assertEqual(result['effects'], [])

    def test_repeated_reason_in_answer_is_still_rendered_once(self):
        result = handle('Tudo bem, Ana. ' + REASON + ' ' + REASON)
        self.assertIn('Tudo bem, Ana.', result['reply'])
        self.assertEqual(result['reply'].count(REASON), 1)
        self.assertEqual(result['reply'].count('?'), 1)

    def test_reason_absent_from_answer_is_added_by_the_canonical_prompt(self):
        result = handle('Sem problemas, Ana! 😊')
        self.assertTrue(result['reply'].startswith('Sem problemas, Ana!'))
        self.assertTrue(result['reply'].endswith(journey.PROMPTS['tiktok']))
        self.assertEqual(result['reply'].count(REASON), 1)

    def test_formatter_preserves_conditions_and_link_exactly(self):
        body = ('Ana, confira as condições de 10% sobre comissões por 2 meses. '
                'Detalhes: https://example.invalid/condicoes#termos. ' + REASON)
        result = journey._step_reply(body, journey.PROMPTS['tiktok'])
        self.assertIn('condições de 10% sobre comissões por 2 meses.', result)
        self.assertIn('https://example.invalid/condicoes#termos.', result)
        self.assertEqual(result.count(REASON), 1)
        self.assertEqual(result.count('?'), 1)

    def test_formatter_does_not_fuzzily_delete_a_different_explanation(self):
        different = 'Vou consultar os requisitos da sua conta antes de qualquer convite.'
        result = journey._step_reply('Tudo bem, Ana. ' + different, journey.PROMPTS['tiktok'])
        self.assertIn(different, result)
        self.assertEqual(result.count(REASON), 1)

    def test_step_rendering_does_not_change_facts_or_operational_receipts(self):
        state = state_at('tiktok')
        before = deepcopy(state)
        proposal = plan('Tudo bem, Ana. ' + REASON)
        answer = journey._question_reply('Não sei se minha conta está ativa', proposal,
                                        state['cycle'], POLICY, state=state, now=NOW)
        self.assertEqual(state, before)
        self.assertEqual(answer.count(REASON), 1)
        self.assertTrue(answer.endswith(journey.PROMPTS['tiktok']))


if __name__ == '__main__':
    unittest.main()
