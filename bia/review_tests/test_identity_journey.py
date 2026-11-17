"""Synthetic production journey coverage; no network or genuine lead data."""
import unittest
from copy import deepcopy
from unittest.mock import patch

import real_journey as journey
from lead_validation import stage

NOW = '2026-11-17T14:00:00Z'
NAME = 'Como posso te chamar?'
HANDLE = 'Qual é seu @ do TikTok?'


class IdentityJourney(unittest.TestCase):
    @staticmethod
    def delivery(reply, status='accepted'):
        return lambda opened_at: {
            'source': 'outbox', 'latest_attempt_status': status,
            'last_accepted_reply': {'text': reply},
        }

    def turn(self, state, msg, last='', *, status='accepted'):
        return journey.handle_real(state, msg, now=NOW, approved_experience_enabled=True,
                                   identity_delivery=self.delivery(last, status))

    def test_before_any_qualification_and_no_repeat(self):
        r = self.turn({}, 'Quero fazer parte')
        self.assertIn('agente de IA da Amplify', r['reply'])
        self.assertTrue(r['reply'].endswith(NAME))
        self.assertIsNone(stage(r['state']['cycle']))
        r = self.turn(r['state'], 'Clara Lima', r['reply'])
        self.assertTrue(r['reply'].endswith(HANDLE))
        r = self.turn(r['state'], '@clara.synthetic', r['reply'])
        self.assertEqual(stage(r['state']['cycle']), 'agency')
        self.assertIn('agência', r['reply'])
        self.assertEqual(r.get('effects'), [])

    def test_failed_name_delivery_does_not_turn_a_bare_name_into_identity(self):
        r = self.turn({}, 'Quero fazer parte')
        r = self.turn(r['state'], 'Clara Lima', r['reply'], status='failed')
        self.assertTrue(r['reply'].endswith(NAME))
        self.assertNotIn('nome_declarado', r['state']['cycle']['facts'])

    def old_choice(self):
        result = journey.handle_real({}, 'Quero fazer parte', now=NOW, approved_experience_enabled=True)
        state = result['state']
        state['cycle']['bia_validation'].update(stage='choice', alert_requested=True, high_gmv=True)
        state['cycle']['facts']['gmv_30d_declarado_centavos'] = 9_000_000
        state['cycle']['facts']['gmv_30d_moeda'] = 'BRL'
        return state

    def test_legacy_machine_keeps_choice_but_specialist_is_available_now(self):
        old = self.old_choice()
        r = self.turn(old, 'Seguir com a Bia')
        self.assertTrue(r['reply'].endswith(NAME))
        self.assertEqual(stage(r['state']['cycle']), 'choice')
        self.assertNotIn('preference', r['state']['cycle']['bia_validation'])
        r = self.turn(r['state'], 'Clara Lima', r['reply'])
        r = self.turn(r['state'], '@clara.synthetic', r['reply'])
        self.assertEqual(stage(r['state']['cycle']), 'complete')
        self.assertEqual(r['state']['cycle']['bia_validation']['preference'], 'machine')
        self.assertNotIn('identity_deferred_machine_choice', r['state']['cycle'])
        r = self.turn(old, 'Quero falar com um especialista')
        self.assertEqual(stage(r['state']['cycle']), 'specialist')
        self.assertTrue(r['state']['cycle']['bia_validation']['handoff_requested'])
        self.assertFalse(r['reply'].endswith(NAME))

    def test_explicit_human_request_does_not_add_identity_or_pause_outside_choice(self):
        old = self.old_choice()
        old['cycle']['bia_validation']['stage'] = 'shop'
        r = self.turn(old, 'Quero falar com um atendente')
        self.assertNotEqual(r['reply'], NAME)
        self.assertFalse(r['state']['cycle'].get('qualification_paused'))
        self.assertEqual(stage(r['state']['cycle']), 'shop')

    def test_legacy_already_sent_is_never_rewound_by_identity_gate(self):
        old = self.old_choice()
        old['cycle']['phase'] = 'form'
        old['cycle']['bia_validation']['stage'] = 'complete'
        old['cycle']['facts']['tiktok_declarado'] = '@clara.synthetic'
        before = deepcopy(old['cycle']['bia_validation'])
        with patch.object(journey, '_invite_known', return_value=True):
            r = self.turn(old, 'Onde encontro meu cadastro?')
        self.assertNotEqual(r['reply'], NAME)
        self.assertNotEqual(r['reply'], HANDLE)
        self.assertEqual(r['state']['cycle']['bia_validation'], before)
        self.assertNotIn('identity_question_pending', r['state']['cycle'])
        self.assertFalse(any(e.get('operation') == 'invite' for e in r.get('effects', [])))

    def test_queue_fence_also_covers_unmarked_preexisting_jobs_without_blocking_reads(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from real_operations import RealExecutor
        live = {'cycle': {'facts': {'tiktok_declarado': '@clara.synthetic'}}}
        guard_calls = []
        executor = SimpleNamespace(settings={'qualification_enabled': True},
            lock_for=lambda *_: nullcontext(),
            repository=SimpleNamespace(load_session=lambda *_: live),
            _valid=lambda *_: True, clock=lambda: NOW,
            guard=lambda *_: guard_calls.append(True) or {'allowed': True})
        job = {'operation': 'invite', 'event': {}, 'conversation_key': 'synthetic'}
        with patch('real_operations.production_blocked', return_value=False):
            self.assertFalse(RealExecutor._authorized(executor, job))
            self.assertEqual(executor.last_guard, 'identity_required_before_invite')
            self.assertEqual(guard_calls, [])
            self.assertTrue(RealExecutor._authorized(executor, {**job, 'operation': 'lookup'}))
            live['cycle']['facts']['nome_declarado'] = 'Clara Lima'
            self.assertTrue(RealExecutor._authorized(executor, job))

    def test_identity_hold_answers_unpunctuated_doubt(self):
        r = self.turn({}, 'Quero fazer parte')
        with patch.object(journey, '_question_reply', return_value='Os benefícios dependem da categoria.') as answer:
            r = self.turn(r['state'], 'quero saber os benefícios', r['reply'])
        answer.assert_called_once()
        self.assertIn('Os benefícios dependem da categoria.', r['reply'])
        self.assertTrue(r['reply'].endswith(NAME))
        self.assertNotIn('nome_declarado', r['state']['cycle']['facts'])

    def test_no_sales_report_is_not_a_name_or_unbound_gmv(self):
        old = self.old_choice()
        old['cycle']['bia_validation']['stage'] = 'gmv'
        del old['cycle']['facts']['gmv_30d_declarado_centavos']
        r = self.turn(old, 'ainda não tenho nenhuma venda')
        self.assertIn('informou que ainda não fez vendas', r['reply'])
        self.assertTrue(r['reply'].endswith(NAME))
        self.assertNotIn('nome_declarado', r['state']['cycle']['facts'])
        self.assertNotIn('gmv_30d_declarado_centavos', r['state']['cycle']['facts'])
        self.assertEqual(stage(r['state']['cycle']), 'gmv')

    def test_unconfirmed_inviting_cycle_collects_identity_without_any_retry(self):
        old = self.old_choice()
        old['cycle']['phase'] = 'inviting'
        old['cycle']['bia_validation']['stage'] = 'complete'
        old['cycle']['facts']['tiktok_declarado'] = '@clara.synthetic'
        r = self.turn(old, 'Pode seguir')
        self.assertTrue(r['reply'].endswith(NAME))
        r = self.turn(r['state'], 'Clara Lima', r['reply'])
        self.assertIn('Ainda não tenho confirmação de que o convite foi enviado.', r['reply'])
        self.assertIn('não vou iniciar outro envio', r['reply'])
        self.assertEqual(r['state']['cycle']['phase'], 'inviting')
        self.assertEqual(r.get('effects'), [])


if __name__ == '__main__':
    unittest.main()
