"""Live-audit regressions for invalid self-labels and pre-invitation copy."""
import unittest
from unittest.mock import patch

import conversao
import real_journey as journey
from nome_contextual import extract_name, first_name
from test_regressao41 import eligible, settle
from test_relationship_form_chat30 import AT, POLICY


class AuditNameAndEligibilityTests(unittest.TestCase):
    def test_roles_are_not_names_even_after_a_name_question(self):
        for text in ('Sou iniciante', 'Eu sou a Iniciante!', 'Sou uma novata',
                     'sou muito experiente', 'sou iniciante no tiktok', 'Sou intermediário',
                     'Sou novo por aqui', 'Sou interessada', 'Iniciante', 'Sou afiliada'):
            with self.subTest(text=text):
                self.assertIsNone(extract_name(text))
                self.assertIsNone(extract_name(text, requested=True))

    def test_true_names_are_preserved(self):
        for text, name in [('Eu sou Vitor', 'Vitor'), ('Me chamo Ana Maria', 'Ana Maria'),
                           ('Sou a Joana Marques', 'Joana Marques'), ('Meu nome é José das Neves', 'José das Neves')]:
            with self.subTest(text=text):
                self.assertEqual(extract_name(text), name)
        self.assertEqual(extract_name('Ana', requested=True), 'Ana')

    def test_invalid_anonymous_model_claim_is_not_persisted(self):
        reply = 'Sou iniciante'
        plan = {'claims':[{'field':'nome_declarado','value':'iniciante','quote':reply}]}
        self.assertNotIn('nome_declarado', journey._extract_claims(reply, 'intro', plan, requested_name=True))

    def test_invalid_historical_name_is_not_used_in_message(self):
        self.assertIsNone(first_name('Iniciante'))
        self.assertIsNone(journey._first_name({'facts':{'nome_declarado':'Iniciante'}}))
        self.assertEqual(journey._first_name({'facts':{'nome_declarado':'Ana Maria'}}), 'Ana')

    def test_pre_invite_terms_do_not_announce_eligibility_or_send(self):
        unsafe = r'boa notícia|pode entrar|passou pela|perfil apt|elegível|já foi enviado|foi enviado|já tô enviando'
        for template in (conversao.auto_invite, conversao.consent_full):
            reply = template('Ana','@sintetico', POLICY)
            self.assertIn('@sintetico',reply)
            self.assertIn('10%',reply)
            self.assertIn('2 meses',reply)
            self.assertNotRegex(reply.lower(),unsafe)
        auto_off = patch.object(journey, 'AUTO_INVITE', False)
        with auto_off:
            draft = eligible('@sintetico')['state']
        draft['cycle']['facts']['nome_declarado'] = 'Iniciante'
        with patch.object(journey, 'AUTO_INVITE', True):
            result = journey._auto_invite(draft, AT, POLICY)
        self.assertEqual([effect['operation'] for effect in result['effects']],['invite'])
        self.assertEqual(result['state']['cycle']['phase'],'inviting')
        self.assertTrue(result['state']['cycle']['facts']['consentimento_convite'])
        self.assertNotRegex(result['reply'].lower(),unsafe + '|iniciante')
        sent = settle(result['state'], result['effects'][0], 'sent')
        self.assertIn('convite', sent['reply'].lower())
        self.assertNotIn('iniciante', sent['reply'].lower())
