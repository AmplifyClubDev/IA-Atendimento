"""Release 43: os códigos das pontes são a chave da automação (ESTADO-DO-ATENDIMENTO.md, seção 5b).

1. Cobertura: todo código que a Bia pode receber (os status de cada operação, os motivos de ponte fora e os
   bloqueios que a ponte devolve) tem uma ação e uma mensagem na tabela; falha se aparecer um código novo sem tratamento.
2. Comportamento: cada linha da tabela é percorrida na jornada e a mensagem que sai é a da tabela.
"""
from datetime import timedelta
import unittest

import conversao
import playwright_client
import real_journey as journey
import test_convite42 as base
from test_convite42 import LINKED, LIST, PENDING, invite_unknown
from test_playwright_client import PlaywrightClient, SETTINGS, Script
from test_regressao41 import AD, eligible, invited, say, settle
from test_relationship_form_chat30 import AT

OPERATIONS = ('precheck', 'invite', 'relationship')
LOOKUP_ONLY = {'lookup_login_required', 'creator_lookup_session_unavailable', 'creator_lookup_human_verification_required'}


def every_code():
    codes = {(operation, status) for operation in OPERATIONS for status in journey._STATUS[operation]}
    codes.add(('invite', 'failed_again'))
    codes |= {('*', code) for code in journey.CLIENT_BLOCKED + tuple(journey.BRIDGE_DOWN_REASONS)}
    return codes


class CoverageTests(unittest.TestCase):
    def test_every_code_has_one_action_and_one_message(self):
        missing = []
        for key in sorted(every_code()):
            row = journey.BRIDGE_CODE_TABLE.get(key)
            if (not isinstance(row, tuple) or len(row) != 2 or not isinstance(row[0], str) or not row[0].strip()
                    or not isinstance(row[1], str) or not hasattr(conversao, row[1])):
                missing.append(key)
        self.assertEqual(missing, [], 'código sem ação ou sem mensagem na tabela')
        self.assertEqual(set(journey.BRIDGE_CODE_TABLE), every_code(), 'linha da tabela sem código correspondente')

    def test_the_bridge_blocks_are_all_known(self):
        # Todo bloqueio que a ponte devolve (playwright_client._BLOCKED) está na tabela, fora os da consulta de dados públicos.
        self.assertEqual(set(playwright_client._BLOCKED) - LOOKUP_ONLY, set(journey.CLIENT_BLOCKED))

    def test_a_bridge_block_reaches_the_bia_as_human_verification(self):
        for code in journey.CLIENT_BLOCKED:
            with self.subTest(code):
                client = PlaywrightClient(SETTINGS, Script([(503, {'ok': False, 'status': code})]))
                result = client.execute('precheck', 'teste')
                self.assertEqual((result['status'], result['reason']), ('verification_pending', 'human_verification_required'))


def text(name):
    return getattr(conversao, name)


class BehaviourTests(base.DaytimeTests):
    """Cada linha da tabela, na jornada: a mensagem que sai é a da tabela."""

    def expect(self, key, reply):
        name = journey.BRIDGE_CODE_TABLE[key][1]
        if name == 'consent_full':
            self.assertIn('Boa notícia', reply, key)
        else:
            self.assertIn(text(name), reply, key)

    def unverified(self):
        state = invite_unknown('@lead5b')['state']
        at = AT + timedelta(minutes=20)
        gone = settle(state, journey.agency_read_effect(state, at), 'not_found', at, evidence=dict(LIST))
        fresh = settle(gone['state'], gone['effects'][0], 'eligible', at)
        return settle(fresh['state'], fresh['effects'][0], 'pending_verification', at, confirmed=False,
                      evidence={'post_attempted': True, 'create_accepted': True}), at + timedelta(minutes=5)

    # Vínculo (relationship)
    def test_relationship_linked(self):
        state = invited('@lead5b')['state']
        at = AT + timedelta(minutes=15)
        self.expect(('relationship', 'linked'),
                    settle(state, journey.agency_read_effect(state, at), 'linked', at, evidence=dict(LINKED))['reply'])

    def test_relationship_pending(self):
        turn = say('Não apareceu o convite', invited('@lead5b')['state'], AT + timedelta(minutes=20))
        pending = settle(turn['state'], turn['effects'][0], 'pending', AT + timedelta(minutes=20), evidence=dict(PENDING))
        self.expect(('relationship', 'pending'), pending['reply'])

    def test_relationship_not_found(self):
        sent, at = self.unverified()
        self.expect(('relationship', 'not_found'),
                    settle(sent['state'], sent['effects'][0], 'not_found', at, evidence=dict(LIST))['reply'])

    def test_relationship_without_result(self):
        for status in ('verification_pending', 'failed', 'outcome_unknown'):
            with self.subTest(status):
                turn = say('Já aceitei', invited('@lead5b')['state'])
                result = settle(turn['state'], turn['effects'][0], status, confirmed=False, evidence={},
                                reason='human_verification_required')
                self.expect(('relationship', status), result['reply'])

    # Perfil (precheck)
    def checking(self):
        turn = say('@lead5b', say(AD)['state'])
        return turn, next(item for item in turn['effects'] if item['operation'] == 'precheck')

    def test_precheck_eligible(self):
        self.expect(('precheck', 'eligible'), eligible('@lead5b')['reply'])

    def test_precheck_ineligible_closes_with_respect(self):
        turn, check = self.checking()
        result = settle(turn['state'], check, 'ineligible')
        self.expect(('precheck', 'ineligible'), result['reply'])
        self.assertEqual(result['reply'], conversao.PROFILE_INELIGIBLE)
        self.assertEqual(result['state']['cycle']['status'], 'closed')

    def test_precheck_shop_unknown_and_pronto_at_most_every_10_minutes(self):
        turn, check = self.checking()
        unknown = settle(turn['state'], check, 'verification_pending', confirmed=False, evidence={}, reason='shop_unknown')
        self.expect(('precheck', 'verification_pending'), unknown['reply'])
        soon = say('pronto', unknown['state'], AT + timedelta(minutes=4))
        self.assertEqual((soon['reply'], soon['effects']), (conversao.SHOP_RECHECK_SOON, []))
        later = say('pronto', soon['state'], AT + timedelta(minutes=10))
        self.assertEqual([item['operation'] for item in later['effects']], ['precheck'])

    def test_precheck_failed_or_unknown_waits_for_the_bridge(self):
        for status in ('failed', 'outcome_unknown'):
            with self.subTest(status):
                turn, check = self.checking()
                result = settle(turn['state'], check, status, confirmed=False, evidence={}, reason='invalid_creator')
                self.expect(('precheck', status), result['reply'])
                self.assertIn('bridge_wait', result['state']['cycle'])

    # Convite (invite)
    def invite(self, status, **updates):
        asked = say('Pode mandar', eligible('@lead5b')['state'])
        return settle(asked['state'], next(i for i in asked['effects'] if i['operation'] == 'invite'), status, **updates)

    def test_invite_sent(self):
        self.expect(('invite', 'sent'), self.invite('sent')['reply'])

    def test_invite_linked_sends_the_registration(self):
        self.expect(('invite', 'linked'), self.invite('linked', evidence=dict(LINKED))['reply'])

    def test_invite_already_pending(self):
        self.expect(('invite', 'pending'), self.invite('pending', evidence=dict(PENDING))['reply'])

    def test_invite_unconfirmed_never_says_sent(self):
        for status, evidence in (('pending_verification', {'post_attempted': True, 'create_accepted': True}),
                                 ('outcome_unknown', {'post_attempted': True})):
            with self.subTest(status):
                result = self.invite(status, confirmed=False, evidence=evidence, reason='invitation_result_unconfirmed')
                self.expect(('invite', status), result['reply'])
                self.assertNotIn('enviado', result['reply'])
                self.assertEqual([item['operation'] for item in result['effects']], ['relationship'])

    def test_invite_bridge_down(self):
        result = self.invite('verification_pending', confirmed=False, evidence={}, reason='human_verification_required')
        self.expect(('invite', 'verification_pending'), result['reply'])

    def test_invite_ineligible(self):
        result = self.invite('ineligible', evidence={'post_attempted': False})
        self.expect(('invite', 'ineligible'), result['reply'])
        self.assertEqual(result['state']['cycle']['status'], 'closed')

    def test_invite_failed_retries_once_then_alerts_the_team(self):
        failed = self.invite('failed', confirmed=False, evidence={'post_attempted': True, 'http_status': 400},
                             reason='invitation_rejected')
        self.expect(('invite', 'failed'), failed['reply'])
        check = failed['effects'][0]
        self.assertEqual(check['operation'], 'precheck')
        self.assertEqual(check['payload']['not_before'], (AT + timedelta(minutes=10)).isoformat())
        later = AT + timedelta(minutes=10)
        ready = settle(failed['state'], check, 'eligible', later)
        self.assertEqual((ready['reply'], [i['operation'] for i in ready['effects']]), ('', ['invite']))
        again = settle(ready['state'], ready['effects'][0], 'failed', later, confirmed=False,
                       evidence={'post_attempted': True, 'http_status': 400}, reason='invitation_rejected')
        self.expect(('invite', 'failed_again'), again['reply'])
        cycle = again['state']['cycle']
        # O vigia do Cadastro avisa a equipe de todo atendimento aberto em "blocked" há mais de 30 min.
        self.assertEqual((cycle['status'], cycle['phase'], cycle['block_reason']), ('open', 'blocked', 'invite_failed_twice'))

    # Ponte fora ou bloqueada (qualquer operação)
    def test_every_bridge_down_reason(self):
        for code in sorted(journey.BRIDGE_DOWN_REASONS) + ['human_verification_required']:
            with self.subTest(code):
                turn, check = self.checking()
                result = settle(turn['state'], check, 'verification_pending', confirmed=False, evidence={}, reason=code)
                self.expect(('*', code), result['reply'])
                self.assertIn('bridge_wait', result['state']['cycle'])


if __name__ == '__main__':
    unittest.main()
