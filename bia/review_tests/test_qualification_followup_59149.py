"""Qualification and truthful recovery guidance, offline."""
import unittest
from unittest.mock import Mock, patch

from lead_validation import stage
import real_journey as journey
from test_relationship_form_chat30 import AT, POLICY


class QualificationContextTests(unittest.TestCase):
    def send(self,state,text, callback=None):
        return journey.handle_real(
            state, text, callback, now=AT, operation_policy=POLICY,
            qualification_enabled=True, approved_experience_enabled=True,
            same_engine_enabled=True, relationship_check_in_form=True)

    def start(self):
        return self.send({},'Quero fazer parte')['state']

    def test_handle_during_agency_question_does_not_skip_it(self):
        r=self.send(self.start(),'@sintetico_42')
        c=r['state']['cycle']
        self.assertEqual(c['facts']['tiktok_declarado'],'@sintetico_42')
        self.assertEqual(stage(c),'agency'); self.assertFalse(r['effects'])
        self.assertIn('Anotei seu @',r['reply'])
        r=self.send(r['state'],'Sim')
        self.assertEqual(stage(r['state']['cycle']),'agency_kind')
        self.assertIn('outra agência',r['reply'])
        r=self.send(r['state'],'Já sou Amplify')
        self.assertTrue(r['state']['cycle']['bia_validation']['existing_amplify_declared'])
        self.assertNotIn('Qual é seu @',r['reply'])
        self.assertFalse(any(e['operation']=='invite' for e in r['effects']))

    def test_handle_and_agency_answer_stay_independent(self):
        r=self.send(self.start(),'Não, meu @ do TikTok é @Sintetico_42')
        c=r['state']['cycle']
        self.assertEqual(c['facts']['tiktok_declarado'],'@sintetico_42')
        self.assertIs(c['facts']['possui_agencia_declarada'],False)
        self.assertEqual(stage(c),'shop'); self.assertFalse(r['effects'])

    def test_no_store_for_bare_prose_or_third_party(self):
        for text in ('iniciante','Sou iniciante','perfil válido','O perfil dela é @terceira',
                     'É @terceira?', 'Exemplo "meu @ é @terceira"'):
            with self.subTest(text=text):
                r=self.send(self.start(),text)
                self.assertNotIn('tiktok_declarado',r['state']['cycle']['facts'])
                self.assertEqual(stage(r['state']['cycle']),'agency')
                self.assertFalse(r['effects'])

    def test_known_handle_is_not_replaced_in_other_qualification_stage(self):
        r=self.send(self.start(),'@sintetico_42')
        r=self.send(r['state'],'@different_49')
        self.assertEqual(r['state']['cycle']['facts']['tiktok_declarado'],'@sintetico_42')
        self.assertFalse(r['effects'])
        self.assertEqual(stage(r['state']['cycle']),'agency')

    def test_invite_permission_context_outranks_stale_gmv(self):
        s=self.start()
        c=s['cycle']; c['facts']['tiktok_declarado']='@sintetico_42'
        c['bia_validation']['stage']='gmv'
        c.update(phase='blocked',block_reason='creator_binding_not_permitted',real_operations={
            'invite':{'status':'failed','reason':'creator_binding_not_permitted',
                      'creator':'@sintetico_42','cycle_id':c['id']}
        })
        cb=Mock(side_effect=AssertionError('known rejection must not invoke model'))
        r=self.send(s,'Onde verifica?',cb)
        cb.assert_not_called()
        self.assertFalse(r['effects'])
        self.assertIn('Central do Criador',r['reply'])
        self.assertIn('não confirma a permissão',r['reply'])
        self.assertIn('Não vou reenviar',r['reply'])
        self.assertNotIn('GMV',r['reply'])
        self.assertEqual(r['state']['cycle']['phase'],'blocked')

    def test_unrelated_or_unbound_record_does_not_assert_rejection(self):
        s=self.start()
        c=s['cycle']; c['facts']['tiktok_declarado']='@sintetico_42'
        c.update(phase='blocked',block_reason='creator_binding_not_permitted',real_operations={
            'invite':{'status':'failed','reason':'creator_binding_not_permitted',
                      'creator':'@different_49','cycle_id':c['id']}
        })
        self.assertFalse(journey._invite_permission_followup(c,'Onde verifica?'))
        c['real_operations']['invite']['creator']='@sintetico_42'
        self.assertFalse(journey._invite_permission_followup(c,'Onde verifica o GMV?'))

    def test_gmv_help_does_not_repeat_question_or_record_a_guess(self):
        s=self.start()
        s['cycle']['bia_validation']['stage']='gmv'
        example='No app, consulte o total vendido dos últimos 30 dias.'
        with patch.object(journey, '_question_reply', return_value=example):
            first=self.send(s,'Onde fica isso?')
            self.assertIn('Qual foi seu GMV',first['reply'])
            second=self.send(first['state'],'Ainda não achei')
            self.assertNotIn('Qual foi seu GMV',second['reply'])
            self.assertEqual(second['buttons'],['Não sei','Nenhuma venda'])
            self.assertEqual(stage(second['state']['cycle']),'gmv')
            self.assertNotIn('gmv_30d_declarado_centavos',second['state']['cycle']['facts'])
            final=self.send(second['state'],'Não sei')
            self.assertIsNone(final['state']['cycle']['facts']['gmv_30d_declarado_centavos'])
            self.assertEqual(stage(final['state']['cycle']),'complete')
