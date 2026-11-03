"""Exact public FAQ paragraph through the planner and normal in-memory turn."""
from copy import deepcopy
import unittest

import conversation
import conversao
import guided_ai
import receipt_grounding
from context_ia import PATTERNS
from tests.test_audit_ai_contract31 import wire
from tests.test_real_journey import NOW, POLICY, GATE


# Exact first paragraph read back from the approved funcionamento card. The
# procedural second person describes steps; it is not a result for this lead.
PUBLIC_PARAGRAPH = ('Primeiro, você tira suas dúvidas e informa seu perfil. Verificamos se ele pode receber o convite da Amplify '
                    'e apresentamos as condições. Com sua autorização, enviamos o convite. Você aceita no TikTok e abre o formulário, '
                    'que confirma o vínculo antes de liberar o cadastro. Depois do cadastro validado, seguimos com os acessos. 😊')
MODEL_REPLY = ('A Amplify é uma agência e comunidade para creators do TikTok Shop. O agenciamento começa com a apresentação '
               'das condições, verificação do seu perfil e, se você quiser, o envio de um convite para parceria. 😊\n\n'
               'Posso te explicar a jornada passo a passo ou há algum ponto específico que você quer entender primeiro?')


class EducationalProcedure33Tests(unittest.TestCase):
    def test_exact_database_paragraph_survives_planner_and_normalized_turn_without_personal_status(self):
        knowledge = {'source': 'database', 'personality': 'Responda brevemente.', 'limits': 'Não invente resultados.',
                     'knowledge_version': 'approved33:exact-public-paragraph', 'topics': [
                         {'id': 'funcionamento', 'title': 'Como funciona', 'patterns': PATTERNS['funcionamento'],
                          'answer': PUBLIC_PARAGRAPH + '\n\nA jornada interna não deve ser copiada para a resposta.'}]}
        settings = {'ai_enabled': True, 'context_db_enabled': True, '_context_snapshot': knowledge,
                    'openai_api_key': 'offline-fictional33', 'ai_model': 'gpt-4.1'}
        calls, plans = [], []

        def transport(**kwargs):
            calls.append(kwargs)
            self.assertEqual(kwargs['url'], guided_ai.RESPONSES_URL)
            return wire(MODEL_REPLY, topic_ids=['funcionamento'])

        def planner(text, context):
            proposal = guided_ai.plan_turn(text, context, settings, transport=transport)
            plans.append(deepcopy(proposal))
            return proposal

        initial = conversation.handle({}, 'oi', now=NOW, real_mode=True,
                                      operation_policy=POLICY, relationship_check_in_form=True)['state']
        event = {'provider': 'chatwoot', 'event': 'message_created', 'account_id': '1', 'inbox_id': '3',
                 'conversation_id': '26097', 'contact_id': '3', 'message_id': '99300001',
                 'sender_phone': GATE['phone'], 'sender_type': 'contact', 'message_type': 'incoming',
                 'private': False, 'text': 'Como funciona', 'created_at': NOW.isoformat(),
                 'source_ref': 'chatwoot:1:99300001'}
        result = conversation.handle_event(initial, event, GATE, planner, now=NOW, real_mode=True,
                                           operation_policy=POLICY, relationship_check_in_form=True)

        self.assertEqual(len(calls), 1)
        self.assertEqual(plans[0]['provider_status'], 'completed')
        self.assertEqual(plans[0]['approved_topic_answer']['id'], 'funcionamento')
        self.assertEqual(plans[0]['approved_topic_answer']['text'], PUBLIC_PARAGRAPH)
        self.assertIn(PUBLIC_PARAGRAPH, result['reply'])
        self.assertNotIn('Ainda não tenho confirmação', result['reply'])
        self.assertNotIn('jornada interna', result['reply'])
        self.assertIn(conversao.CTA, result['reply'])
        self.assertEqual(result['buttons'], conversao.FIRST_BUTTONS)
        self.assertEqual(result['state']['cycle']['phase'], 'intro')
        self.assertEqual(result['state']['cycle']['facts'], {})
        self.assertEqual(result['effects'], [])
        self.assertLessEqual(result['reply'].count('?'), 1)

    def test_second_person_completed_or_current_status_is_still_not_an_educational_receipt(self):
        for text in ('Você está agenciada pela Amplify.', 'Você é agenciada pela Amplify.',
                     'Você foi agenciada pela Amplify.', 'Você tem acesso liberado.',
                     'Você recebeu seu convite.', 'Você recebeu o convite.', 'Você concluiu o cadastro.',
                     'Você finalizou o cadastro.', 'Você já está agenciada.',
                     'Seu convite foi enviado.', 'O vínculo foi confirmado.'):
            with self.subTest(text=text):
                proposal = {'provider_status': 'completed', 'intent': 'question', 'reply': 'Explicação.',
                            'knowledge_version': 'approved33', 'approved_topic_answer': {
                                'id': 'funcionamento', 'text': text, 'source': 'approved_context',
                                'knowledge_version': 'approved33'}}
                self.assertIsNone(receipt_grounding.approved_educational_reply('Como funciona', proposal))

    def test_procedural_second_person_does_not_answer_a_personal_status_question(self):
        proposal = {'provider_status': 'completed', 'intent': 'question', 'reply': MODEL_REPLY,
                    'knowledge_version': 'approved33', 'approved_topic_answer': {
                        'id': 'funcionamento', 'text': PUBLIC_PARAGRAPH, 'source': 'approved_context',
                        'knowledge_version': 'approved33'}}
        for text in ('Como está meu vínculo?', 'Meu convite foi enviado?', 'Onde aceito o convite?'):
            with self.subTest(text=text):
                self.assertIsNone(receipt_grounding.approved_educational_reply(text, proposal))


if __name__ == '__main__':
    unittest.main()
