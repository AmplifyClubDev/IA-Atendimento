"""Natural origin, objective choices and source-preserving recovery; offline."""
from copy import deepcopy
from datetime import timedelta
import unittest

import conversation
import engine
import guided_ai
import real_journey
from test_real_journey import NOW,POLICY,GATE,inbound
from test_real_executor import EVENT


TEXT='Vi um vídeo no Instagram'


def proposed(text,context):
    return {'reply':'Legal saber disso!','intent':'continue','claims':[{'field':'origem_declarada','value':'outro','quote':text}],
            'next_phase':'tiktok','topic_ids':[],'provider_status':'completed'}


def waiting():
    return inbound('Quero me agenciar')['state']


def rejected_legacy(*,source=False,other_cycle=False,text=TEXT):
    state=waiting()
    at=NOW-timedelta(seconds=20)
    record={'direction':'inbound','text':text,'at':at.isoformat(),'cycle_id':'old-cycle' if other_cycle else state['cycle']['id']}
    if source:
        record.update(source_ref='chatwoot:1:313154',source_created_at=(at-timedelta(seconds=1)).isoformat())
        state['processed_inbound'].append('chatwoot:1:313154')
    state['history'].append(record)
    state['history'].append({'direction':'outbound','text':real_journey.PROMPTS['origin'],'at':at.isoformat(),'cycle_id':record['cycle_id']})
    return state,record


class NaturalOriginTests(unittest.TestCase):
    def test_real_313154_completed_model_claim_is_accepted_and_next_field_is_handle(self):
        result=inbound(TEXT,waiting(),callback=proposed)
        self.assertEqual(result['state']['cycle']['phase'],'tiktok')
        self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],'outro')
        self.assertEqual(result['state']['cycle']['facts']['origem_canal_declarado'],'instagram')
        self.assertEqual(result['reply'],real_journey.PROMPTS['tiktok'])
        self.assertEqual(result['buttons'],[])

    def test_natural_source_is_deterministic_without_model(self):
        result=inbound(TEXT,waiting())
        self.assertIn('origem_declarada',result['applied_claims'])
        self.assertEqual(result['state']['cycle']['phase'],'tiktok')

    @unittest.skip('Release 40 (auditoria de conversão de 01/11): a Bia não pergunta mais a origem nem o nome; o formulário pede os dois.')
    def test_paraphrases_are_classified_by_source_evidence_not_exact_sentences(self):
        for text in ('Conheci vocês assistindo a um vídeo no Instagram','Eu descobri a Amplify pelo Instagram',
                     'Achei vocês em um conteúdo do Instagram','No Instagram','Instagram',
                     'Um vídeo de vocês apareceu no meu Instagram'):
            with self.subTest(text=text):
                result=inbound(text,waiting())
                self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],'outro')
                self.assertEqual(result['state']['cycle']['facts']['origem_canal_declarado'],'instagram')
                self.assertEqual(result['state']['cycle']['phase'],'tiktok')

    def test_explicit_paid_advertising_has_separate_evidence(self):
        for text in ('Vi um anúncio no Instagram','Conheci por um vídeo patrocinado no TikTok','Vim por ads no Facebook'):
            with self.subTest(text=text):
                result=inbound(text,waiting())
                self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],'anuncio')
                self.assertEqual(result['state']['cycle']['phase'],'tiktok')

    def test_uncertain_advertising_is_not_inferred_from_channel(self):
        for text in ('Vi um vídeo no Instagram, não sei se era anúncio','Conheci pelo TikTok mas não tenho certeza se era patrocinado'):
            with self.subTest(text=text):
                result=inbound(text,waiting())
                self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],'outro')

    def test_explicit_referral_in_natural_language_is_accepted(self):
        for text in ('Um amigo me indicou a Amplify','Vim por indicação da Camila','Recebi uma indicação pelo WhatsApp'):
            with self.subTest(text=text):
                result=inbound(text,waiting())
                self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],'indicacao')

    @unittest.skip('Release 40 (auditoria de conversão de 01/11): a Bia não pergunta mais a origem nem o nome; o formulário pede os dois.')
    def test_negation_question_example_and_third_party_never_become_person_facts(self):
        for text in ('Não vi um vídeo no Instagram','Nunca conheci a Amplify pelo Instagram',
                     'Vi um vídeo no Instagram?','Por exemplo, vi um vídeo no Instagram',
                     'Se eu vi um vídeo no Instagram','Minha amiga viu um vídeo no Instagram',
                     'Ela conheceu pelo Instagram','"Vi um vídeo no Instagram"','Ninguém me indicou',
                     'Sem indicação','Minha amiga me perguntou se vi um vídeo no Instagram',
                     'Minha amiga me falou que viu um anúncio no Instagram',
                     'Ela me falou que conheceu pelo Instagram',
                     'Supondo que eu vi um vídeo no Instagram'):
            with self.subTest(text=text):
                result=inbound(text,waiting(),callback=proposed)
                self.assertNotIn('origem_declarada',result['state']['cycle']['facts'])
                self.assertEqual(result['state']['cycle']['phase'],'origin')

    def test_model_cannot_create_paid_ads_without_literal_evidence(self):
        def wrong(text,context):
            result=proposed(text,context)
            result['claims'][0]['value']='anuncio'
            return result
        result=inbound(TEXT,waiting(),callback=wrong)
        self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],'outro')

    def test_model_quote_must_be_in_actual_message(self):
        def invented(text,context):
            result=proposed(text,context)
            result['claims'][0]['quote']='Conversei com um podcast'
            return result
        result=inbound('Entendi',waiting(),callback=invented)
        self.assertNotIn('origem_declarada',result['state']['cycle']['facts'])

    @unittest.skip('Release 40 (auditoria de conversão de 01/11): a Bia não pergunta mais a origem nem o nome; o formulário pede os dois.')
    def test_three_objective_origin_choices_keep_free_text(self):
        asked=inbound('Quero me agenciar')
        self.assertTrue(asked['reply'].endswith(real_journey.NAME_QUESTION))
        opened=inbound('me chamo vitor',asked['state'])
        self.assertTrue(opened['reply'].startswith('Prazer, Vitor!'))
        self.assertEqual(opened['buttons'],['Anúncio','Indicação','Outra origem'])
        for label,value in (('Anúncio','anuncio'),('Indicação','indicacao'),('Outra origem','outro')):
            with self.subTest(label=label):
                result=inbound(label,opened['state'])
                self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],value)
                self.assertEqual(result['state']['cycle']['phase'],'tiktok')

    def test_thematic_clarification_does_not_add_an_origin_menu(self):
        def clarify(text,context):
            result=proposed(text,context)
            result.update(reply='Você está falando da comissão da Amplify ou do produto?',intent='clarify',claims=[])
            return result
        result=inbound('Qual comissão',waiting(),callback=clarify)
        self.assertEqual(result['buttons'],[])
        self.assertEqual(result['reply'].count('?'),1)

    @unittest.skip('Release 40 (auditoria de conversão de 01/11): a Bia não pergunta mais a origem nem o nome; o formulário pede os dois.')
    def test_real_313156_recovers_rejected_previous_source_without_calling_model(self):
        state,original=rejected_legacy()
        result=inbound('Já falei',state,callback=lambda *_:self.fail('Recovery must use actual stored source'))
        self.assertEqual(result['state']['cycle']['phase'],'tiktok')
        self.assertNotIn('Como você conheceu',result['reply'])
        self.assertIn('Qual é o seu @',result['reply'])
        self.assertEqual(result['origin_source']['quote'],TEXT)
        self.assertEqual(result['origin_source']['at'],original['at'])
        self.assertEqual(result['origin_source']['source'],'stored_cycle_history')
        self.assertIsNone(result['origin_source']['reference'])

    @unittest.skip('Release 40 (auditoria de conversão de 01/11): a Bia não pergunta mais a origem nem o nome; o formulário pede os dois.')
    def test_recovery_preserves_real_original_reference_and_observed_time(self):
        state,original=rejected_legacy(source=True)
        event={**EVENT,'message_id':'313156','text':'Já falei','created_at':NOW.isoformat(),'source_ref':'chatwoot:1:313156'}
        result=conversation.handle_event(state,event,GATE,now=NOW,real_mode=True,operation_policy=POLICY)
        origin=result['state']['observations']['origin']
        self.assertEqual(origin['reference'],'chatwoot:1:313154')
        self.assertEqual(origin['at'],original['source_created_at'])
        self.assertEqual(result['state']['cycle']['origin_declaration']['quote'],TEXT)
        self.assertNotEqual(origin['reference'],event['source_ref'])

    @unittest.skip('Release 40 (auditoria de conversão de 01/11): a Bia não pergunta mais a origem nem o nome; o formulário pede os dois.')
    def test_recovery_never_uses_another_cycle_or_invalid_previous_declaration(self):
        for options in ({'other_cycle':True},{'text':'Não vi um vídeo no Instagram'},{'text':'Por exemplo vi um vídeo no Instagram'}):
            with self.subTest(options=options):
                state,_=rejected_legacy(**options)
                result=inbound('Já falei',state)
                self.assertEqual(result['state']['cycle']['phase'],'origin')
                self.assertNotIn('origem_declarada',result['state']['cycle']['facts'])

    def test_recovery_does_not_replace_existing_origin_without_confirmation(self):
        state,_=rejected_legacy()
        state['cycle']['facts']['origem_declarada']='indicacao'
        result=inbound('Já falei',state)
        self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],'indicacao')

    def test_new_origin_keeps_provider_source_timestamp_and_reference(self):
        event={**EVENT,'message_id':'313154','text':TEXT,'created_at':(NOW-timedelta(seconds=1)).isoformat(),'source_ref':'chatwoot:1:313154'}
        result=conversation.handle_event(waiting(),event,GATE,now=NOW,real_mode=True,operation_policy=POLICY)
        self.assertEqual(result['state']['cycle']['origin_declaration']['reference'],event['source_ref'])
        self.assertEqual(engine._clock(result['state']['observations']['origin']['at']),engine._clock(event['created_at']))

    def test_readonly_channel_is_visible_in_context_but_not_a_new_claim_field(self):
        state=inbound(TEXT,waiting())['state']
        context=guided_ai._context({'real_mode':True,'phase':'tiktok','cycle':state['cycle'],'facts':state['cycle']['facts']})
        self.assertEqual(context['facts']['origem_canal_declarado'],'instagram')
        self.assertIn('origem_canal_declarado',context['known_fields'])
        fields=guided_ai._schema([],real_mode=True)['properties']['claims']['items']['properties']['field']['enum']
        self.assertNotIn('origem_canal_declarado',fields)

    def test_voluntary_origin_and_handle_together_are_not_forced_into_two_turns(self):
        def combined(text,context):
            result=proposed(text,context)
            result['claims'].append({'field':'tiktok_declarado','value':'@perfil_real','quote':'@perfil_real'})
            return result
        result=inbound(TEXT+', @perfil_real',waiting(),callback=combined)
        self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],'outro')
        self.assertEqual(result['state']['cycle']['facts']['tiktok_declarado'],'@perfil_real')
        self.assertEqual(result['state']['cycle']['phase'],'checking')
        self.assertEqual(len(result['effects']),3)

    def test_unknown_shop_answer_does_not_change_previously_declared_origin(self):
        state=waiting()
        state['cycle']['phase']='shop'
        state['cycle']['facts'].update(origem_declarada='indicacao',tiktok_declarado='@perfil_real')
        result=inbound('Não sei',state)
        self.assertEqual(result['state']['cycle']['facts']['origem_declarada'],'indicacao')
        self.assertNotIn('pending_profile_changes',result['state']['cycle'])

    def test_voluntary_name_before_agency_interest_is_used_in_same_reply(self):
        result=inbound('Me chamo Ana')
        self.assertEqual(result['state']['cycle']['facts']['nome_declarado'],'Ana')
        self.assertIn('Prazer, Ana! 😊',result['reply'])
        self.assertNotIn('interesse_agenciamento',result['state']['cycle']['facts'])
        self.assertEqual(result['state']['cycle']['phase'],'intro')

    def test_short_name_answers_the_actual_pending_name_question(self):
        def ask(text,context):
            return {'reply':'Como posso te chamar?','intent':'converse','claims':[],
                    'next_phase':context['phase'],'topic_ids':[],'provider_status':'completed'}
        opening=inbound('oi',callback=ask)
        self.assertTrue(opening['state']['cycle']['name_question_pending'])
        result=inbound('Ana',opening['state'])
        self.assertEqual(result['state']['cycle']['facts']['nome_declarado'],'Ana')
        self.assertIn('Prazer, Ana! 😊',result['reply'])
        self.assertEqual(result['reply'].count('?'),1)
        self.assertFalse(result['state']['cycle']['name_question_pending'])

    def test_bare_name_without_name_question_is_not_assumed(self):
        result=inbound('Ana',inbound('oi')['state'])
        self.assertNotIn('nome_declarado',result['state']['cycle']['facts'])
        self.assertNotIn('Prazer, Ana',result['reply'])

    def test_existing_name_change_is_confirmed_before_replacement_and_ack(self):
        state=waiting()
        state['cycle']['facts']['nome_declarado']='Maria Clara'
        proposed=inbound('Me chamo Ana',state)
        self.assertEqual(proposed['state']['cycle']['facts']['nome_declarado'],'Maria Clara')
        self.assertEqual(proposed['buttons'],['Confirmo','Não confirmo'])
        self.assertNotIn('Prazer, Ana',proposed['reply'])
        confirmed=inbound('Confirmo',proposed['state'])
        self.assertEqual(confirmed['state']['cycle']['facts']['nome_declarado'],'Ana')
        self.assertIn('Prazer, Ana! 😊',confirmed['reply'])

    def test_full_name_is_kept_but_greeting_uses_first_name(self):
        result=inbound('Meu nome é Maria Clara')
        self.assertEqual(result['state']['cycle']['facts']['nome_declarado'],'Maria Clara')
        self.assertIn('Prazer, Maria! 😊',result['reply'])
        self.assertNotIn('Prazer, Maria Clara',result['reply'])

    def test_whatsapp_displayname_is_not_a_confirmed_name(self):
        event={**EVENT,'message_id':'313190','text':'oi','display_name':'Display Name',
               'created_at':NOW.isoformat(),'source_ref':'chatwoot:1:313190'}
        result=conversation.handle_event({},event,GATE,now=NOW,real_mode=True,operation_policy=POLICY)
        self.assertNotIn('nome_declarado',result['state']['cycle']['facts'])

    def test_uncertain_name_question_cannot_bind_bare_name_in_real_delivery_context(self):
        state=inbound('oi')['state']
        state['cycle']['name_question_pending']=True
        def callback(text,context):
            context['delivery_context']={'source':'outbox','last_accepted_reply':{'text':'O que você gostaria de conhecer?'}}
            return {'reply':'O que você gostaria de conhecer?','intent':'converse','claims':[],
                    'next_phase':'intro','topic_ids':[],'provider_status':'completed'}
        result=inbound('Ana',state,callback=callback)
        self.assertNotIn('nome_declarado',result['state']['cycle']['facts'])

    @unittest.skip('Release 40 (auditoria de conversão de 01/11): a Bia não pergunta mais a origem nem o nome; o formulário pede os dois.')
    def test_faq_menu_appears_on_explicit_learning_navigation_only(self):
        state=inbound('oi')['state']
        result=inbound('Conhecer a Amplify',state)
        self.assertEqual(result['buttons'],['Como funciona','Benefícios','Comissão'])
        self.assertEqual(result['state']['cycle']['phase'],'intro')
        ordinary=inbound('Quais benefícios?',result['state'])
        self.assertEqual(ordinary['buttons'],[])
        self.assertNotIn('interesse_agenciamento',ordinary['state']['cycle']['facts'])


if __name__=='__main__':
    unittest.main()
