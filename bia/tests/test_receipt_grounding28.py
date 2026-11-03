"""Offline operational prose is rendered from bound backend evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

import receipt_grounding as subject
import real_journey as journey


NOW = datetime(2026, 10, 29, 15, tzinfo=timezone.utc)
POLICY = {'approved': True, 'commission': 10, 'commission_unit': 'percent',
          'duration_fixed_months': 2, 'duration_label': '2 meses', 'version': 'approved-fixture'}


def base():
    state = journey.handle_real({}, 'Quero me agenciar', now=NOW)['state']
    state['cycle']['facts'].update(origem_declarada='indicacao', tiktok_declarado='@teste')
    return state


def proven(operation, status, **updates):
    state = base()
    identifier = 'proof-' + operation
    cycle = state['cycle']
    record = {'operation': operation, 'status': status, 'creator': '@teste', 'observed_at': NOW.isoformat(),
              'confirmed': True, 'job_id': identifier, 'cycle_id': cycle['id'], 'evidence': {'complete': True}, **updates}
    cycle.setdefault('real_operations', {})[operation] = record
    state['effects'][identifier] = {'type': 'tiktok_operation', 'operation': operation, 'creator': '@teste',
        'cycle_id': cycle['id'], 'status': 'done', 'id': identifier}
    return state


class ReceiptGrounding28Tests(unittest.TestCase):
    def render(self, reply, *, question='Onde aceito o convite?', state=None, topics=None, policy=POLICY):
        return subject.ground_reply(question, reply, {'intent': 'question', 'topic_ids': topics or []},
                                    state or base(), policy=policy, now=NOW)

    def test_unproven_success_paraphrases_are_replaced_not_verb_filtered(self):
        for phrase in ('Acabei de mandar o convite para você.', 'Seu convite já está na sua conta.',
                       'Prontinho, deixei o convite na sua caixa.', 'Já finalizei seu vínculo.',
                       'Você já está agenciada conosco.', 'Seu cadastro está certinho e finalizado.',
                       'Pode usar seus acessos, está tudo pronto.'):
            with self.subTest(phrase=phrase):
                answer = self.render(phrase)
                self.assertNotIn(phrase, answer)
                self.assertNotIn('foi confirmado', answer)
                self.assertNotIn('confirmou o envio', answer)

    def test_where_to_accept_is_explained_without_assuming_invitation_exists(self):
        answer = self.render('Veja o convite que enviei.')
        self.assertIn('Parcerias', answer)
        self.assertIn('Notificações', answer)
        self.assertIn('depois da conferência do seu perfil', answer)
        self.assertNotIn('confirmou o envio', answer)

    def test_pending_invitation_does_not_become_linked(self):
        answer = self.render('Seu vínculo está pronto.', state=proven('relationship', 'pending'))
        self.assertIn('esperando o seu aceite', answer)
        self.assertNotIn('vínculo com a Amplify foi confirmado', answer)

    def test_sent_receipt_only_confirms_send(self):
        answer = self.render('Você está agenciada.', state=proven('invite', 'sent'))
        self.assertIn('confirmou o envio', answer)
        self.assertIn('me manda “aceitei”', answer)
        self.assertNotIn('vínculo com a Amplify foi confirmado', answer)

    def test_linked_receipt_confirms_only_relationship_not_registration_or_access(self):
        answer = self.render('Cadastro e acessos liberados; vínculo pronto.', state=proven('relationship', 'linked'))
        self.assertIn('vínculo com a Amplify foi confirmado', answer)
        self.assertIn('assim que você envia', answer)
        self.assertNotIn('por si só', answer)
        self.assertNotIn('acessos liberados', answer)

    def test_declared_acceptance_is_not_relationship_evidence(self):
        state = base()
        state['cycle']['facts']['aceite_declarado'] = True
        answer = self.render('Já confirmei seu vínculo.', question='Já aceitei', state=state)
        self.assertIn('depois da conferência do seu perfil', answer)
        self.assertNotIn('vínculo com a Amplify foi confirmado', answer)

    def test_wrong_profile_cycle_and_missing_evidence_do_not_ground_success(self):
        for change in ({'creator': '@outro'}, {'cycle_id': 'other-cycle'}, {'evidence': {}}, {'confirmed': False},
                       {'observed_at': (NOW-timedelta(hours=25)).isoformat()}):
            with self.subTest(change=change):
                answer = self.render('Vínculo confirmado.', state=proven('relationship', 'linked', **change))
                self.assertNotIn('vínculo com a Amplify foi confirmado', answer)

    def test_unknown_or_accepted_post_does_not_prove_send(self):
        state = proven('invite', 'outcome_unknown', confirmed=False, evidence={'create_accepted': True})
        answer = self.render('Acabei de mandar o convite.', state=state)
        self.assertIn('*Parcerias* ou *Notificações*', answer)
        self.assertNotIn('confirmou o envio', answer)

    def test_commission_question_keeps_explicit_approved_terms_when_mentioning_invite(self):
        answer = self.render('A comissão do convite é de 50%.', question='Como funciona a comissão do convite?', topics=['custos'])
        self.assertIn('10%', answer)
        self.assertIn('comissões que você recebe', answer)
        self.assertIn('2 meses', answer)
        self.assertNotIn('50%', answer)

    def test_unapproved_policy_cannot_supply_price_or_duration(self):
        answer = self.render('Seu convite custa 20%.', question='Qual a taxa do convite?', policy={'approved': False})
        self.assertNotIn('20%', answer)
        self.assertNotIn('10%', answer)
        self.assertIn('condições precisam estar confirmadas', answer)

    def test_other_helpful_explanations_remain_untouched(self):
        text = 'A Amplify orienta creators do TikTok Shop. 😊'
        self.assertEqual(self.render(text, question='O que é a Amplify?'), text)

    def test_canonical_reply_creates_no_new_question_effect_or_state_change(self):
        state = proven('invite', 'sent')
        before = deepcopy(state)
        answer = self.render('Acabei de mandar o convite.', state=state)
        self.assertEqual(state, before)
        self.assertEqual(answer.count('?'), 0)
        self.assertLess(len(answer), 650)

    def test_journey_integration_keeps_grounded_negative_status_and_one_current_question(self):
        state = base()
        state['cycle']['phase'] = 'tiktok'
        state['cycle']['facts'].pop('tiktok_declarado')
        plan = {'reply': 'Acabei de mandar o convite para você.', 'intent': 'question', 'claims': [],
                'next_phase': 'tiktok', 'topic_ids': [], 'provider_status': 'completed'}
        answer = journey._question_reply('Onde vejo o convite?', plan, state['cycle'], POLICY, state=state, now=NOW)
        self.assertIn('depois que eu confiro seu perfil', answer)
        self.assertIn('Qual é o seu @', answer)
        self.assertEqual(answer.count('?'), 1)
        self.assertNotIn('Acabei de mandar', answer)

    def test_journey_integration_allows_success_only_from_fresh_bound_receipt(self):
        state = proven('relationship', 'linked')
        state['cycle']['phase'] = 'form'
        plan = {'reply': 'Acabei de mandar o convite.', 'intent': 'question', 'claims': [],
                'next_phase': 'form', 'topic_ids': [], 'provider_status': 'completed'}
        answer = journey._question_reply('Como está o vínculo?', plan, state['cycle'], POLICY, state=state, now=NOW)
        self.assertIn('vínculo com a Amplify foi confirmado', answer)
        self.assertNotIn('Acabei de mandar', answer)


if __name__ == '__main__':
    unittest.main()
