"""59004 regression: no network, no delivery, no provider side effects."""
import unittest
from copy import deepcopy
import real_journey

NOW = '2026-11-13T03:30:00Z'
QUESTION = 'Quais são as regras da parceria e como funciona a saída?'
CLOSING = 'Se quiser saber mais ou avançar, só avisar 💙'

class FaqSubstance(unittest.TestCase):
    def plan(self, reply):
        return {'provider_status':'completed','intent':'question','reply':reply,'topic_ids':[]}
    def state(self):
        return real_journey.handle_real({}, 'Oi', now=NOW,
            approved_experience_enabled=True)['state']
    def test_grounded_remainder_is_not_an_answer(self):
        state = self.state()
        plan = self.plan('A saída depende das condições do vínculo com a agência. ' + CLOSING)
        self.assertEqual(real_journey._question_reply(QUESTION, plan, state['cycle'],
            state=state, allow_local=False), '')
    def test_approved_fallback_is_tried(self):
        state = self.state()
        plan = self.plan('A saída depende das condições do vínculo com a agência. ' + CLOSING)
        plan.update(knowledge_version='test-v1', approved_topic_answer={
            'source':'approved_context','knowledge_version':'test-v1', 'id':'regras',
            'text':'As condições de saída precisam ser esclarecidas antes do aceite.'})
        answer = real_journey._question_reply(QUESTION, plan, state['cycle'],
            state=state, allow_local=False)
        self.assertEqual(answer, plan['approved_topic_answer']['text'])
    def test_menu_returns_honest_fallback_without_advancing(self):
        state = self.state(); before = deepcopy(state['cycle']['facts'])
        result = real_journey.handle_real(state, 'Regras e saída',
            lambda *_: self.plan('A saída depende das condições do vínculo com a agência. ' + CLOSING),
            now=NOW, approved_experience_enabled=True)
        self.assertIn('Não consegui consultar', result['reply'])
        self.assertFalse(result['effects'])
        self.assertEqual(result['state']['cycle']['facts'], before)
        self.assertEqual(result['state']['cycle']['phase'], 'intro')
    def test_meaningful_answers_survive(self):
        for text in ['As condições precisam ficar claras antes do aceite.',
                     'Não tenho uma regra confirmada sobre saída.',
                     'Você quer saber sobre comissão ou prazo?',
                     'Os benefícios dependem da categoria. ' + CLOSING]:
            self.assertTrue(real_journey._faq_has_answer(text))
    def test_social_only_is_rejected(self):
        for text in ['', '💙', CLOSING, 'Claro! ' + CLOSING, 'Estou por aqui para ajudar.']:
            self.assertFalse(real_journey._faq_has_answer(text), text)
    def test_receipt_guard_still_blocks_fabricated_success(self):
        state = self.state()
        answer = real_journey._question_reply(QUESTION,
            self.plan('Seu vínculo foi confirmado. ' + CLOSING), state['cycle'],
            state=state, allow_local=False)
        self.assertNotIn('foi confirmado', answer)
        self.assertEqual(answer, '')
