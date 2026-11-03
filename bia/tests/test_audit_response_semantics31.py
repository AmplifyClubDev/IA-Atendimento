"""Offline audit of FAQ meaning, approved money terms and current-stage answers."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

import conversao
import conversation
import real_journey as journey


NOW = datetime(2026, 10, 29, 19, 3, tzinfo=timezone.utc)
POLICY = {'approved': True, 'commission': 10, 'commission_unit': 'percent',
          'duration_fixed_months': 2, 'duration_label': '2 meses', 'version': 'approved-policy31'}
VERSION = 'approved-context31'


def plan(reply='', *, intent='question', status='completed', approved=None):
    result = {'reply': reply, 'intent': intent, 'claims': [], 'next_phase': 'intro',
              'topic_ids': [], 'provider_status': status, 'knowledge_version': VERSION}
    if approved:
        result['approved_topic_answer'] = {'id': approved[0], 'text': approved[1],
                                          'source': 'approved_context', 'knowledge_version': VERSION}
    return result


def state_at(phase):
    state = conversation.handle({}, 'oi', now=NOW, real_mode=True,
                                operation_policy=POLICY)['state']
    cycle = state['cycle']
    cycle['phase'] = phase
    cycle['relationship_check_in_form'] = True
    if phase != 'intro':
        cycle['facts']['interesse_agenciamento'] = True
    if phase not in {'intro', 'origin'}:
        cycle['facts']['origem_declarada'] = 'indicacao'
    if phase not in {'intro', 'origin', 'tiktok'}:
        cycle['facts']['tiktok_declarado'] = '@teste'
    if phase == 'consent_real':
        journey._consent_prompt(cycle, POLICY)
    if phase == 'form':
        cycle['form_url'] = 'https://amplify-cadastro.up.railway.app/cadastro/ensaio#s=' + 'a' * 43
    return state


def render(text, proposal, *, phase='intro', policy=POLICY):
    state = state_at(phase)
    before = deepcopy(state)
    before_proposal = deepcopy(proposal)
    reply = journey._question_reply(text, proposal, state['cycle'], policy, state=state, now=NOW)
    assert state == before, 'answer rendering cannot change journey, facts or effects'
    assert proposal == before_proposal, 'a useful fallback must not rewrite the provider receipt'
    return reply


class ResponseSemanticsAudit31Tests(unittest.TestCase):
    def assert_cost(self, reply):
        self.assertIn('10%', reply)
        self.assertIn('comiss', reply.lower())
        self.assertIn('2 meses', reply)
        self.assertNotIn('Posso te apresentar', reply)
        self.assertLessEqual(reply.count('?'), 1)

    def test_actual_commission_menu_rejection_is_repaired_in_full_real_turn(self):
        initial = state_at('intro')
        offered = conversation.handle(initial, 'Conhecer a Amplify',
            lambda *_: plan('A Amplify é uma agência para creators do TikTok Shop.'),
            now=NOW, real_mode=True, operation_policy=POLICY)
        self.assertEqual(offered['buttons'], ['Como funciona', 'Benefícios', 'Comissão'])
        actual = conversation.handle(offered['state'], 'Comissão',
            lambda *_: plan('A taxa é de 10% sobre as comissões recebidas, não sobre o GMV.'),
            now=NOW, real_mode=True, operation_policy=POLICY)
        self.assert_cost(actual['reply'])
        self.assertEqual(actual['state']['cycle']['phase'], 'intro')
        self.assertEqual(actual['effects'], [])
        self.assertEqual(actual['buttons'], conversao.FIRST_BUTTONS)  # release 40: o próximo passo é o @
        self.assertNotIn('interesse_agenciamento', actual['state']['cycle']['facts'])

    def test_commission_menu_works_without_planner(self):
        self.assert_cost(render('Comissão', None))

    def test_financial_answer_survives_all_provider_failure_shapes(self):
        for status in ('failed', 'unknown', 'invalid_response', 'context_unavailable', 'disabled'):
            with self.subTest(status=status):
                self.assert_cost(render('Quanto é a comissão?', plan(status=status)))

    def test_negative_gmv_and_faturamento_explanations_are_not_lost(self):
        for base in ('GMV', 'faturamento', 'vendas totais', 'total das vendas'):
            with self.subTest(base=base):
                self.assert_cost(render('Qual é a comissão?', plan('É 10% das comissões, não sobre ' + base + '.')))

    def test_false_positive_sales_base_is_replaced_by_approved_commission_base(self):
        for false in ('São 10% do seu GMV.', 'Cobramos 10% das suas vendas.', 'A taxa é 50% e uma multa de R$ 500.'):
            with self.subTest(false=false):
                reply = render('Qual é a taxa?', plan(false))
                self.assert_cost(reply)
                self.assertNotIn('50%', reply)
                self.assertNotIn('R$', reply)
                self.assertNotIn('das suas vendas', reply)

    def test_invalid_policy_never_fills_in_a_financial_value(self):
        for policy in (None, {}, {**POLICY, 'approved': False}, {**POLICY, 'commission': 50}):
            with self.subTest(policy=policy):
                reply = render('Comissão', plan('Custa 10% e dura 2 meses.'), policy=policy)
                self.assertTrue(reply)
                self.assertNotIn('%', reply)
                self.assertNotIn('2 meses', reply)
                self.assertNotIn('Posso te apresentar', reply)

    def test_approved_nondefault_rate_is_not_hardcoded(self):
        reply = render('Qual o percentual?', None, policy={**POLICY, 'commission': 8})
        self.assertIn('8%', reply)
        self.assertNotIn('10%', reply)

    def test_commission_is_meaningful_in_every_real_phase(self):
        for phase in journey.PHASES:
            with self.subTest(phase=phase):
                self.assert_cost(render('Comissão', plan(status='unknown'), phase=phase))

    def test_cost_answer_does_not_authorize_invite(self):
        state = state_at('consent_real')
        result = conversation.handle(state, 'Comissão', lambda *_: plan('10% do GMV.'),
            now=NOW, real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)
        self.assert_cost(result['reply'])
        self.assertIn(conversao.CONSENT_QUESTION, result['reply'])
        self.assertEqual(result['effects'], [])
        self.assertNotIn('consentimento_convite', result['state']['cycle']['facts'])
        self.assertEqual(result['state']['cycle']['phase'], 'consent_real')

    def test_cost_answer_at_form_uses_existing_private_link_only(self):
        reply = render('Comissão', None, phase='form')
        self.assert_cost(reply)
        self.assertIn('https://amplify-cadastro.up.railway.app/cadastro/ensaio#s=', reply)
        self.assertNotIn('já foi confirmado', reply)

    def test_three_menu_options_keep_subject_when_provider_unavailable(self):
        topics = [('Como funciona', 'funcionamento', 'A parceria oferece orientação para creators do TikTok Shop.'),
                  ('Benefícios', 'beneficios', 'Os recursos variam pela categoria. Não há garantia de amostras.')]
        for text, topic, answer in topics:
            for phase in journey.PHASES:
                with self.subTest(text=text, phase=phase):
                    reply = render(text, plan(status='unknown', approved=(topic, answer)), phase=phase)
                    self.assertIn(answer, reply)
                    self.assertNotIn('Posso te apresentar', reply)
                    self.assertLessEqual(reply.count('?'), 1)

    def test_natural_question_uses_current_approved_answer_after_rejected_model_reply(self):
        answer = 'Os benefícios dependem da categoria; não há garantia de amostras ou campanhas.'
        reply = render('O que eu ganho com vocês?',
                       plan('Você receberá acesso liberado e 50% de cashback.', approved=('beneficios', answer)))
        self.assertIn(answer, reply)
        self.assertNotIn('50%', reply)
        self.assertNotIn('acesso liberado', reply)

    def test_a_useful_model_answer_is_not_replaced_by_topic_fallback(self):
        answer = 'Live não é obrigatória para participar.'
        self.assertEqual(render('Preciso fazer live?', plan(answer, approved=('lives', 'Outro texto aprovado.'))), answer)

    def test_knowledge_version_mismatch_cannot_become_an_answer(self):
        proposal = plan(status='unknown', approved=('beneficios', 'Amostras gratuitas garantidas.'))
        proposal['approved_topic_answer']['knowledge_version'] = 'old-context'
        reply = render('Benefícios', proposal)
        self.assertNotIn('garantidas', reply)
        self.assertNotIn('Posso te apresentar', reply)

    def test_unknown_context_menu_has_honest_subject_specific_fallback(self):
        for text in ('Como funciona', 'Benefícios'):
            with self.subTest(text=text):
                reply = render(text, None)
                self.assertTrue(reply)
                self.assertNotIn('Posso te apresentar', reply)
                self.assertNotIn('10%', reply)

    def test_thematic_clarification_occupies_single_question_slot(self):
        reply = 'Você está falando da comissão da Amplify ou da comissão do produto?'
        self.assertEqual(render('Qual comissão?', plan(reply, intent='clarify'), phase='origin'), reply)

    def test_question_intent_cannot_add_second_question_in_qualification(self):
        reply = 'A orientação varia pela categoria. Você quer entender a comunidade ou as campanhas?'
        self.assertEqual(render('Como são os benefícios?', plan(reply), phase='origin'), reply)

    def test_qualification_fallback_requests_only_the_pending_field(self):
        answer = 'Os benefícios variam pela categoria.'
        reply = render('Benefícios', plan(status='unknown', approved=('beneficios', answer)), phase='origin')
        self.assertIn(answer, reply)
        # Release 40: a origem não é mais perguntada; o único campo pendente é o @.
        self.assertTrue(reply.endswith(journey.PROMPTS['tiktok']))
        self.assertEqual(reply.count('?'), 1)
        self.assertNotIn(journey.PROMPTS['origin'], reply)

    def test_operational_topic_fallback_cannot_invent_external_success(self):
        reply = render('Como funciona', plan(status='unknown', approved=(
            'funcionamento', 'Seu convite foi enviado, vínculo confirmado e acesso liberado.')))
        self.assertNotIn('Seu convite foi enviado', reply)
        self.assertNotIn('acesso liberado', reply)
        self.assertNotIn('vínculo confirmado', reply)

    def test_model_topic_id_does_not_turn_a_general_question_into_cost(self):
        proposal = plan('A parceria oferece orientação para creators.')
        proposal['topic_ids'] = ['custos']
        reply = render('Como funciona?', proposal)
        self.assertNotIn('%', reply)

    def test_real_context_has_current_relationship_boundary(self):
        seen = []
        conversation.handle({}, 'Quais são os benefícios?', lambda text, context: seen.append(context),
            now=NOW, real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)
        self.assertIs(seen[0]['relationship_check_in_form'], True)

    def test_natural_financial_questions_answer_with_and_without_policy(self):
        for text in ('Quanto custa?', 'Qual comissão?', 'A taxa incide no GMV?', 'O contrato é de quanto tempo?'):
            for phase in ('intro', 'origin', 'consent_real', 'form', 'blocked'):
                with self.subTest(text=text, phase=phase):
                    self.assert_cost(render(text, plan(status='invalid_response'), phase=phase))
                    unavailable = render(text, plan(status='invalid_response'), phase=phase, policy=None)
                    self.assertTrue(unavailable)
                    self.assertNotIn('%', unavailable)
                    self.assertNotIn('2 meses', unavailable)
                    self.assertNotIn('Posso te apresentar', unavailable)
                    self.assertNotIn('Se quiser começar', unavailable)

    def test_new_mode_backend_wait_does_not_claim_chat_relationship_lookup(self):
        state = state_at('checking')
        self.assertIn('elegibilidade', journey._phase_prompt(state['cycle']))
        self.assertNotIn('vínculo', journey._phase_prompt(state['cycle']))
        state['cycle']['relationship_check_in_form'] = False
        self.assertEqual(journey._phase_prompt(state['cycle']), journey.PROMPTS['checking'])

    def test_new_mode_legacy_acceptance_prompt_points_to_form_instead_of_chat(self):
        for phase in ('await_acceptance', 'checking_acceptance'):
            with self.subTest(phase=phase):
                state = state_at(phase)
                reply = journey._phase_prompt(state['cycle'])
                # Release 39: no internal rule; the next step is the chat check itself.
                self.assertNotIn('não confirma', reply)
                self.assertTrue('aceitei' in reply or 'conferindo' in reply)

    def test_financial_intro_has_one_optional_action_and_click_starts_only_qualification(self):
        first = conversation.handle(state_at('intro'), 'Comissão', lambda *_: plan(status='invalid_response'),
            now=NOW, real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)
        self.assertIn(conversao.CTA, first['reply'])
        self.assertEqual(first['buttons'], conversao.FIRST_BUTTONS)
        self.assertNotIn('interesse_agenciamento', first['state']['cycle']['facts'])
        next_turn = conversation.handle(first['state'], 'Quero me agenciar',
            now=NOW, real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)
        self.assertEqual(next_turn['state']['cycle']['phase'], 'tiktok')
        self.assertEqual(next_turn['reply'].count('?'), 1)
        self.assertEqual(next_turn['effects'], [])
        self.assertNotIn('consentimento_convite', next_turn['state']['cycle']['facts'])

    def test_missing_policy_removes_old_authorization_buttons_without_advancing(self):
        state = state_at('consent_real')
        self.assertIn('invite_offer', state['cycle'])
        result = conversation.handle(state, 'Qual comissão?', lambda *_: plan(status='invalid_response'),
            now=NOW, real_mode=True, operation_policy=None, relationship_check_in_form=True)
        self.assertNotIn('%', result['reply'])
        self.assertNotIn('invite_offer', result['state']['cycle'])
        self.assertEqual(result['buttons'], [])
        self.assertEqual(result['effects'], [])
        self.assertEqual(result['state']['cycle']['phase'], 'consent_real')

    def test_unavailable_model_functioning_faq_keeps_answer_and_one_optional_action(self):
        answer = 'A parceria oferece orientação para creators do TikTok Shop.'
        for status in ('invalid_response', 'unknown', 'failed'):
            with self.subTest(status=status):
                result = conversation.handle(state_at('intro'), 'Como funciona',
                    lambda *_: plan(status=status, approved=('funcionamento', answer)),
                    now=NOW, real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)
                self.assertIn(answer, result['reply'])
                self.assertEqual(result['reply'].count(conversao.CTA), 1)
                self.assertEqual(result['buttons'], conversao.FIRST_BUTTONS)
                self.assertEqual(result['state']['cycle']['phase'], 'intro')
                self.assertEqual(result['state']['cycle']['facts'], {})
                self.assertEqual(result['effects'], [])
                self.assertLessEqual(result['reply'].count('?'), 1)
        clarification = 'Você quer entender a comunidade ou as campanhas?'
        result = conversation.handle(state_at('intro'), 'Como funciona',
            lambda *_: plan(clarification, intent='clarify', approved=('funcionamento', answer)),
            now=NOW, real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)
        self.assertEqual(result['reply'], clarification)
        self.assertEqual(result['buttons'], [])

    def test_unavailable_model_benefits_faq_keeps_answer_and_one_optional_action(self):
        answer = 'Os benefícios dependem da categoria; não há garantia de amostras ou campanhas.'
        for status in ('invalid_response', 'unknown', 'failed'):
            with self.subTest(status=status):
                result = conversation.handle(state_at('intro'), 'Benefícios',
                    lambda *_: plan(status=status, approved=('beneficios', answer)),
                    now=NOW, real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)
                self.assertIn(answer, result['reply'])
                self.assertEqual(result['reply'].count(conversao.CTA), 1)
                self.assertEqual(result['buttons'], conversao.FIRST_BUTTONS)
                self.assertEqual(result['state']['cycle']['phase'], 'intro')
                self.assertEqual(result['state']['cycle']['facts'], {})
                self.assertEqual(result['effects'], [])
        result = conversation.handle(state_at('intro'), 'Não quero continuar',
            lambda *_: plan(status='invalid_response', approved=('beneficios', answer)),
            now=NOW, real_mode=True, operation_policy=POLICY, relationship_check_in_form=True)
        self.assertNotIn('Se quiser começar', result['reply'])
        self.assertEqual(result['buttons'], [])


if __name__ == '__main__':
    unittest.main()
