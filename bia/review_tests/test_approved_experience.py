"""Production adoption: no network, no real recipients or provider actions."""
import unittest
from copy import deepcopy
import config
import real_journey
from approved_experience import OPENING, CHOICES
from lead_validation import stage
NOW='2026-11-12T18:00:00Z'
class ApprovedExperience(unittest.TestCase):
    def send(self,state,text,enabled=True):
        result=real_journey.handle_real(state,text,now=NOW,approved_experience_enabled=enabled,
            qualification_new_cycles_only=True,relationship_check_in_form=True)
        if result.get('reply'):
            outbound=[x for x in result['state']['history'] if x['direction']=='outbound']
            self.assertEqual(outbound[-1]['text'],result['reply'])
            self.assertNotIn('ensaio',result['reply'].lower())
            self.assertNotIn('ilustrativ',result['reply'].lower())
        return result
    def start(self):
        return self.send({},'Oi')
    def test_disabled_default(self):
        self.assertFalse(config.load_settings({})['approved_experience_enabled'])
        self.assertTrue(config.load_settings({'V5_APPROVED_EXPERIENCE_ENABLED':'true'})['approved_experience_enabled'])
    def test_opening_and_menus_no_effects(self):
        r=self.start(); self.assertEqual(r['reply'],OPENING); self.assertEqual(r['buttons'],CHOICES)
        self.assertFalse(r['effects']); cid=r['state']['cycle']['id']
        for message in ['Conhecer a Amplify','Parceria e regras','Mais assuntos','Ver tópicos','Tenho uma dúvida']:
            r=self.send(r['state'],message)
            self.assertFalse(r['effects']); self.assertEqual(r['state']['cycle']['id'],cid)
            self.assertEqual(r['state']['cycle']['phase'],'intro')
            self.assertLessEqual(len(r['buttons']),3)
            self.assertTrue(all(len(x)<=20 for x in r['buttons']))
    def test_no_retroactive_restart(self):
        old=self.send({},'Oi',enabled=False)['state']; before=deepcopy(old['cycle'])
        r=self.send(old,'Oi')
        self.assertNotIn('experience_version',r['state']['cycle'])
        self.assertEqual(r['state']['cycle']['id'],before['id'])
        self.assertNotEqual(r['reply'],OPENING)
    def test_reset_new_cycle(self):
        old=self.send({},'Oi',enabled=False)['state']; r=self.send(old,'resetar')
        self.assertEqual(r['reply'],OPENING)
        self.assertNotEqual(r['state']['cycle']['id'],old['cycle']['id'])
        r=self.send(r['state'],'Quero fazer parte'); self.assertEqual(stage(r['state']['cycle']),'agency')
    def test_in_progress_pinned_across_flag_off(self):
        r=self.start(); r=self.send(r['state'],'Quero fazer parte',enabled=False)
        self.assertEqual(stage(r['state']['cycle']),'agency'); self.assertFalse(r['effects'])
    def test_join_validation_and_threshold(self):
        for value, expected in [('49.999','complete'),('50 mil','choice'),('60 mil','choice')]:
            r=self.start()
            for message in ['Quero fazer parte','Não sou agenciado','Sim',value]:
                r=self.send(r['state'],message)
                self.assertFalse(r['effects'])
            self.assertEqual(stage(r['state']['cycle']),expected)
            if expected=='choice':
                self.assertTrue(r['state']['cycle']['bia_validation']['alert_requested'])
                r=self.send(r['state'],'Especialista')
                self.assertEqual(stage(r['state']['cycle']),'specialist'); self.assertFalse(r['effects'])
                r=self.send(r['state'],'Seguir com a Bia')
                self.assertEqual(stage(r['state']['cycle']),'complete')
    def test_other_agency_and_inactive_shop_block(self):
        r=self.start()
        for message in ['Quero fazer parte','Outra agência']:
            r=self.send(r['state'],message)
        self.assertEqual(stage(r['state']['cycle']),'unlink'); self.assertFalse(r['effects'])
        r=self.send(r['state'],'Já me desvinculei'); r=self.send(r['state'],'Não')
        self.assertEqual(stage(r['state']['cycle']),'activate'); self.assertFalse(r['effects'])
    def test_existing_member_does_not_invite(self):
        r=self.send(self.start()['state'],'Já sou Amplify')
        self.assertEqual(stage(r['state']['cycle']),'existing_profile'); self.assertFalse(r['effects'])
        r=self.send(r['state'],'@qa_example')
        self.assertTrue(r['state']['cycle']['bia_validation']['existing_amplify_declared'])
        self.assertFalse(any(e.get('operation')=='invite' for e in r['effects']))
    def test_menu_during_qualification_does_not_answer(self):
        r=self.send(self.start()['state'],'Quero fazer parte')
        before=deepcopy(r['state']['cycle']['bia_validation'])
        r=self.send(r['state'],'Ver tópicos')
        self.assertEqual(r['state']['cycle']['bia_validation'],before)
        self.assertFalse(r['effects'])
    def test_stop_wins_over_menus(self):
        r=self.send(self.start()['state'],'não quero mais')
        self.assertEqual(r['state']['cycle']['status'],'closed'); self.assertFalse(r['effects'])
    def test_faq_uses_grounded_planner_and_ignores_claims(self):
        seen=[]
        def planner(question,context):
            seen.append((question,context))
            return {'provider_status':'completed','intent':'question','claims':[
                {'field':'consentimento_convite','value':'true','quote':'Regras e saída'}],
                'reply':'Você pode conhecer as condições antes de decidir sobre a parceria.'}
        first=self.start()
        r=real_journey.handle_real(first['state'],'Regras e saída',planner,now=NOW,
                                  approved_experience_enabled=True)
        self.assertEqual(len(seen),1)
        self.assertTrue(seen[0][1]['real_mode'])
        self.assertEqual(seen[0][1]['allowed_claim_fields'],[])
        self.assertNotIn('consentimento_convite',r['state']['cycle']['facts'])
        self.assertFalse(r['effects'])
    def test_faq_unavailable_preserves_validation(self):
        r=self.send(self.start()['state'],'Quero fazer parte')
        r=self.send(r['state'],'Amplify Club')
        self.assertIn('Não consegui consultar',r['reply'])
        self.assertEqual(stage(r['state']['cycle']),'agency')
        self.assertIn('Você já está agenciado?',r['reply']); self.assertFalse(r['effects'])
    def test_member_bare_handle_is_requested_input_only(self):
        r=self.send(self.start()['state'],'Já sou Amplify')
        r=self.send(r['state'],'qa_creator')
        self.assertEqual(r['state']['cycle']['facts']['tiktok_declarado'],'@qa_creator')
        self.assertEqual(r['state']['cycle']['phase'],'form'); self.assertFalse(r['effects'])
    def test_full_real_flow_requires_actual_receipts(self):
        from datetime import datetime, timezone
        from test_relationship_form_chat30 import POLICY
        from test_regressao41 import settle
        at=datetime.fromisoformat(NOW.replace('Z','+00:00'))
        r=self.start()
        for text in ['Quero fazer parte','Não','Sim','0']:
            r=self.send(r['state'],text)
        self.assertEqual(r['state']['cycle']['phase'],'tiktok')
        r=real_journey.handle_real(r['state'],'qa_creator',now=at,operation_policy=POLICY,
                                 approved_experience_enabled=True,relationship_check_in_form=True)
        self.assertEqual(r['state']['cycle']['facts']['tiktok_declarado'],'@qa_creator')
        self.assertEqual({e['operation'] for e in r['effects']},{'lookup','precheck'})
        r=settle(r['state'],next(e for e in r['effects'] if e['operation']=='precheck'),'eligible',at)
        self.assertFalse(any(e.get('operation')=='invite' for e in r['effects']))
        self.assertEqual(r['state']['cycle']['phase'],'consent_real')
        r=real_journey.handle_real(r['state'],'Pode mandar',now=at,operation_policy=POLICY,
                                  approved_experience_enabled=True,relationship_check_in_form=True)
        self.assertEqual([e['operation'] for e in r['effects']],['invite'])
        r=settle(r['state'],r['effects'][0],'sent',at)
        self.assertIn(r['state']['cycle']['phase'],{'form','await_acceptance'})
        again=real_journey.handle_real(r['state'],'Pode mandar',now=at,operation_policy=POLICY,
                                      approved_experience_enabled=True,relationship_check_in_form=True)
        self.assertFalse(any(e.get('operation')=='invite' for e in again['effects']))

    def test_prefilled_ad_opens_approved_menu_and_preserves_origin(self):
        r=self.send({},'Quero saber mais sobre o agenciamento')
        self.assertEqual(r['reply'],OPENING)
        self.assertEqual(r['state']['cycle']['facts']['origem_declarada'],'anuncio')
        self.assertFalse(r['effects'])
    def test_natural_greetings_show_approved_menu(self):
        for text in ['Olá, tudo bem?', 'Oi, queria conversar', 'Bom dia! Quero conhecer vocês', 'Olá, vim pelo anúncio']:
            with self.subTest(text=text):
                r=self.send({},text); self.assertEqual(r['reply'],OPENING);self.assertEqual(r['buttons'],CHOICES)
                self.assertFalse(r['effects'])
    def test_approved_cycle_inactivity_still_closes(self):
        r=self.start();cycle=r['state']['cycle']
        closed=real_journey.close_inactive_cycle(r['state'],expected_cycle_id=cycle['id'],
            source_key='offline-source',warning_key='offline-warning',closure_key='offline-closure',
            warning_accepted_at='2026-11-12T18:05:00Z',now='2026-11-12T18:11:00Z')
        self.assertTrue(closed.get('inactivity_closed'),closed)
        self.assertEqual(closed['state']['cycle']['reason'],'inactivity_timeout')
    def test_approved_cta_matches_button(self):
        r=self.start(); at=real_journey.engine._clock(NOW)
        rendered=real_journey._finish(r['state'],at,reply=real_journey._INTRO_ACTION,
                                     buttons=['Quero me agenciar'])
        self.assertIn('*Quero fazer parte*',rendered['reply'])
        self.assertEqual(rendered['buttons'],['Quero fazer parte'])
    def test_faq_navigation_preserves_expected_profile_input(self):
        r=self.start()
        for text in ['Quero fazer parte','Não','Sim','0','Ver tópicos','qa_creator']:
            r=self.send(r['state'],text)
        self.assertEqual(r['state']['cycle']['facts']['tiktok_declarado'],'@qa_creator')
        self.assertTrue(any(e.get('operation')=='precheck' for e in r['effects']))
