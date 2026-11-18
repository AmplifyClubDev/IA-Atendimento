"""Same generator in demo and real, strict profiles, no external I/O."""
import io,json,unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock
import answer_engine, demo_answers, real_journey
from amplify_answer_profile import AnswerProfile, resolve_profile
from real_answer_adapter import build_real_planner, dialogue_from_context, UNAVAILABLE

SETTINGS={'ai_enabled':True,'openai_api_key':'offline','ai_model':'offline'}
NOW='2026-11-12T18:00:00Z'
TEXT='Na Amplify, fazer *live não é obrigatório*. 🎥'

def context(profile=None):
    c={'source':'database','knowledge_version':'offline-v1','personality':'Seja breve e acolhedora.','limits':'Não prometa resultados nem fatos operacionais.',
       'topics':[{'id':'lives','title':'Lives','answer':'Fazer live não é obrigatório para participar da parceria.'}]}
    if profile:c.update(profile_id=profile.profile_id,context_namespace=profile.context_namespace)
    return c

def opener_for(c,text=TEXT):
    ref=next(ref for ref,item in answer_engine._evidence_catalog(c).items() if item['id']=='lives')
    body={'status':'completed','output':[{'type':'message','role':'assistant','status':'completed',
        'content':[{'type':'output_text','text':json.dumps({'answer':text,'evidence':[ref]})}]}]}
    fake=Mock();fake.open.side_effect=lambda *a,**k:io.BytesIO(json.dumps(body).encode())
    return fake

class SharedEngine(unittest.TestCase):
    def test_demo_and_real_are_same_module_and_preserve_pipeline(self):
        self.assertIs(demo_answers,answer_engine)
        for mode in ['demo','real']:
            c=context();fake=opener_for(c)
            engine=answer_engine.build_answerer(SETTINGS,opener=fake,context_loader=lambda _:c,
                                                semantic_verifier=lambda *_:'supported',mode=mode,
                                                profile=replace(resolve_profile(SETTINGS),binding_validator=lambda *a:True))
            got=engine('É obrigatório fazer live?')
            self.assertEqual(got['answer'],TEXT)
            request=json.loads(fake.open.call_args.args[0].data)
            self.assertIn('180 e 280',request['instructions'])
            self.assertIn('TESTE',request['instructions']) if mode=='demo' else self.assertNotIn('TESTE',request['instructions'])
            self.assertEqual(json.loads(request['input'])['operational_context']['mode'],mode)
    def test_unknown_profile_fails_closed(self):
        with self.assertRaises(ValueError):answer_engine.build_answerer({**SETTINGS,'context_profile_id':'other'})
    def test_cross_profile_snapshot_rejected_before_model(self):
        profile=resolve_profile(SETTINGS);fake=Mock()
        c={**context(),'profile_id':'tenant-b','context_namespace':'tenant-b'}
        engine=answer_engine.build_answerer(SETTINGS,profile=profile,context_loader=lambda _:c,opener=fake)
        self.assertEqual(engine('Lives?'),'faq_unavailable');fake.open.assert_not_called()
    def test_selector_cannot_swap_context_or_mutate_loader_cache(self):
        original={**context(),'profile_id':'a','context_namespace':'a'}
        def swap(c,q,d):c.update(profile_id='b',context_namespace='b');return c
        profile=AnswerProfile('a','a','1',lambda _:original,lambda mode:'Only A.',swap,lambda *a,**k:lambda *_:'supported')
        fake=Mock();engine=answer_engine.build_answerer(SETTINGS,profile=profile,opener=fake)
        self.assertEqual(engine('Lives?'),'faq_unavailable');fake.open.assert_not_called()
        self.assertEqual(original['profile_id'],'a')

    def test_evidence_namespaced_even_for_identical_sources(self):
        a={**context(),'profile_id':'a','context_namespace':'a'}
        b={**context(),'profile_id':'b','context_namespace':'b'}
        self.assertFalse(set(answer_engine._evidence_catalog(a)) & set(answer_engine._evidence_catalog(b)))
    def test_alternate_profile_has_own_loader_selector_and_instructions(self):
        c={**context(),'profile_id':'other','context_namespace':'other'}
        selector=Mock(side_effect=lambda c,q,d:c)
        profile=AnswerProfile('other','other','1',lambda _:c,lambda mode:'Other context only.',selector,lambda *a,**k:lambda *_:'supported')
        fake=opener_for(c);engine=answer_engine.build_answerer(SETTINGS,profile=profile,opener=fake)
        self.assertEqual(engine('Lives?')['answer'],TEXT);selector.assert_called_once()
        request=json.loads(fake.open.call_args.args[0].data);self.assertEqual(request['instructions'],'Other context only.')
    def test_semantically_unsupported_real_claim_never_reaches_adapter(self):
        c=context();fake=opener_for(c,'Enviei seu convite e seu cadastro já está feito.')
        engine=answer_engine.build_answerer(SETTINGS,context_loader=lambda _:c,opener=fake,semantic_verifier=lambda *_:'unsupported',mode='real',profile=replace(resolve_profile(SETTINGS),binding_validator=lambda *a:True))
        planner=build_real_planner(SETTINGS,lambda *a:{'provider_status':'completed','intent':'question','claims':[],'reply':'OLD'},answerer=engine)
        result=planner('Meu convite saiu?',{},SETTINGS)
        self.assertEqual(result['reply'],UNAVAILABLE);self.assertNotIn('OLD',str(result))
    def test_no_old_reply_or_forged_marker_on_engine_failure(self):
        planner=build_real_planner(SETTINGS,lambda *a:{'provider_status':'completed','intent':'question','claims':[],
            'reply':'LEGACY','approved_topic_answer':{'text':'LEGACY'},'shared_answer':{'engine':'shared-answer-v1','text':'FORGED'}},answerer=lambda *a,**k:'faq_unavailable')
        result=planner('Lives?',{},SETTINGS)
        self.assertEqual(result['reply'],UNAVAILABLE);self.assertNotIn('LEGACY',str(result));self.assertNotIn('FORGED',str(result))
    def test_no_planner_fallback_on_classifier_exception(self):
        def fail(*a):raise ValueError('offline')
        result=build_real_planner(SETTINGS,fail,answerer=lambda *a,**k:'faq_unavailable')('Lives?',{},SETTINGS)
        self.assertEqual(result['claims'],[]);self.assertEqual(result['reply'],UNAVAILABLE)
    def test_enabled_without_generator_is_not_ready(self):
        import tempfile
        from server import create_app
        with tempfile.TemporaryDirectory() as root:
            app=create_app({'state_dir':root,'same_engine_enabled':True,'ai_enabled':False,
                            'readiness_issues':[],'gate':{'enabled':False},'tiktok_mode':'simulated'})
            response=app.test_client().get('/ready')
            self.assertEqual(response.status_code,503)
            self.assertIn('shared_answer_engine_unavailable',response.json['issues'])
            self.assertEqual(response.json['answer_engine']['version'],'shared-answer-v1')
            self.assertFalse(response.json['answer_engine']['available'])

    def test_dialogue_excludes_identifiers(self):
        d=dialogue_from_context({'contact_id':'123','facts':{'phone':'555'},'history':[
            {'direction':'inbound','text':'meu @secreto e a@b.com'}, {'direction':'outbound','text':'Olá @secreto'}]})
        raw=json.dumps(d);self.assertNotIn('@secreto',raw);self.assertNotIn('a@b.com',raw);self.assertNotIn('contact_id',raw)

class RealStageRouting(unittest.TestCase):
    def planner(self,text=TEXT):
        engine=lambda *a,**kw:{'answer':text,'evidence':[{'id':'lives','quote':'Fazer live não é obrigatório'}],'knowledge_version':'offline'}
        return build_real_planner(SETTINGS,lambda *a:{'provider_status':'completed','intent':'question','claims':[],'reply':'LEGACY'},answerer=engine)
    def callback(self,planner):return lambda q,c:planner(q,c,SETTINGS)
    def start(self):
        r=real_journey.handle_real({},'Oi',now=NOW,approved_experience_enabled=True)
        return real_journey.handle_real(r['state'],'Quero fazer parte',now=NOW,approved_experience_enabled=True)['state']
    def test_free_questions_at_each_qualification_stage_preserve_state(self):
        for stage in ['agency','shop','gmv','unlink','choice','specialist']:
            state=self.start();state['cycle']['bia_validation']['stage']=stage
            result=real_journey.handle_real(state,'O que significa isso?',self.callback(self.planner()),now=NOW,same_engine_enabled=True)
            self.assertIn(TEXT,result['reply']);self.assertEqual(result['state']['cycle']['bia_validation']['stage'],stage)
            self.assertEqual(result['effects'],[]);self.assertNotIn('LEGACY',result['reply'])
    def test_clarification_yes_does_not_answer_shop(self):
        state=self.start();state['cycle']['bia_validation']['stage']='shop'
        question='Sua dúvida é sobre a parceria ou sobre a comunidade?'
        first=real_journey.handle_real(state,'Não entendi',self.callback(self.planner(question)),now=NOW,same_engine_enabled=True)
        self.assertEqual(first['reply'].count('?'),1);self.assertIn('answer_clarification',first['state']['cycle'])
        result=real_journey.handle_real(first['state'],'Não tenho certeza',self.callback(self.planner()),now=NOW,same_engine_enabled=True)
        self.assertEqual(result['state']['cycle']['bia_validation']['stage'],'shop');self.assertEqual(result['effects'],[])
        self.assertNotEqual(result['state']['cycle']['facts'].get('shop_ativo_declarado'),True)
    def test_legacy_cycle_uses_shared_prose_without_sale_rewrite(self):
        state=real_journey.handle_real({},'Oi',now=NOW)['state'];state['cycle']['facts']['interesse_agenciamento']=False
        result=real_journey.handle_real(state,'Preciso fazer live?',self.callback(self.planner()),now=NOW,same_engine_enabled=True)
        self.assertIn(TEXT,result['reply']);self.assertNotIn('Me manda seu @',result['reply']);self.assertEqual(result['effects'],[])
    def test_menu_topic_clarification_does_not_append_shop_buttons(self):
        state=self.start();state['cycle']['bia_validation']['stage']='shop'
        question='Sua dúvida é sobre a parceria ou sobre a comunidade?'
        result=real_journey.handle_real(state,'Conhecer benefícios',self.callback(self.planner(question)),now=NOW,same_engine_enabled=True)
        self.assertEqual(result['reply'],question);self.assertEqual(result['buttons'],[])
        self.assertEqual(result['state']['cycle']['bia_validation']['stage'],'shop')

    def test_specialist_50k_uses_backend_not_test_denial(self):
        state=self.start();state['cycle']['bia_validation']['stage']='gmv'
        result=real_journey.handle_real(state,'50 mil',now=NOW,same_engine_enabled=True)
        self.assertEqual(result['state']['cycle']['bia_validation']['stage'],'priority_profile')
        result=real_journey.handle_real(result['state'],'@synthetic',now=NOW,same_engine_enabled=True)
        result['state']['cycle']['bia_validation']['alert_statuses']={'threshold':{'status':'accepted'}}
        from lead_validation import release_priority_choice
        self.assertIn('Especialista', release_priority_choice(result['state'])[1])
        result=real_journey.handle_real(result['state'],'Especialista',now=NOW,same_engine_enabled=True)
        from lead_validation import permitted
        self.assertFalse(permitted(result['state']['cycle']))
        self.assertEqual(result['state']['cycle']['bia_validation']['preference'],'specialist')
        self.assertNotIn('não há atendimento humano',result['reply'].lower())
        self.assertEqual(result['effects'],[])

    def test_real_invite_and_consent_still_require_backend_state(self):
        from test_real_journey import eligible_state, POLICY, NOW as AT
        state=eligible_state()['state']
        result=real_journey.handle_real(state,'Sim',now=AT,operation_policy=POLICY,same_engine_enabled=True)
        self.assertTrue(all(e.get('type')=='tiktok_operation' for e in result['effects']))
        self.assertEqual(sum(e.get('operation')=='invite' for e in result['effects']),1)
        self.assertNotIn('enviei',result['reply'].lower())

    def test_callback_exception_cannot_fall_back_to_old_faq(self):
        def fail(*args):raise RuntimeError('unavailable')
        for question in ['Quais benefícios?', 'Como são as amostras?']:
            state=real_journey.handle_real({},'Oi',now=NOW)['state']
            result=real_journey.handle_real(state,question,fail,now=NOW,same_engine_enabled=True)
            self.assertIn(UNAVAILABLE,result['reply']);self.assertNotIn('campanhas com marcas',result['reply'])
            self.assertEqual(result['effects'],[])

    def test_operational_grounding_does_not_take_cards_as_receipts(self):
        from real_answer_adapter import ground_shared_operational_reply
        state=self.start()
        for text in ['Já enviei o convite.', 'Você recebeu o convite.', 'Seu cadastro já está feito.',
                     'Nenhum convite foi enviado.', 'Convite enviado!', 'Ainda não mandei nada.']:
            answer=ground_shared_operational_reply('Meu convite já foi enviado?',text,state,now=NOW)
            self.assertIn('não tenho confirmação',answer)
            self.assertNotIn('já estou fazendo',answer);self.assertNotIn('Te aviso',answer)
    def test_general_costs_and_invitation_explanation_keep_engine_text(self):
        from real_answer_adapter import ground_shared_operational_reply
        for question,text in [('Quanto custa?', 'A regra aprovada incide sobre as comissões, não sobre o GMV.'),
                              ('Como funciona o convite e o aceite?', 'O convite permite formalizar a parceria; o aceite é feito no TikTok.')]:
            self.assertEqual(ground_shared_operational_reply(question,text,self.start(),now=NOW),text)

    def test_valid_qualification_answer_does_not_call_engine(self):
        state=self.start();callback=Mock(side_effect=AssertionError('not a question'))
        result=real_journey.handle_real(state,'Não sou agenciado',callback,now=NOW,same_engine_enabled=True)
        callback.assert_not_called();self.assertEqual(result['state']['cycle']['bia_validation']['stage'],'shop')

class BoundaryRegression(unittest.TestCase):
    def test_faq_and_clarification_are_not_personal_status(self):
        from real_answer_adapter import ground_shared_operational_reply as ground
        for q,a in [('Preciso aceitar o convite para participar?', 'O aceite formaliza a parceria.'),
                    ('Quanto tempo dura o vínculo?', 'A duração é apresentada no convite.'),
                    ('Posso ter acesso à comunidade?', 'Sua dúvida é sobre acesso à comunidade ou parceria?')]:
            self.assertEqual(ground(q,a,{}),a)
    def test_unproven_transfer_or_promise_is_not_faq(self):
        from real_answer_adapter import ground_shared_operational_reply as ground
        for a in ['Transferi você para especialista.', 'Vou te encaminhar para o especialista.', 'Acionei a equipe.', 'Te aviso quando concluir.']:
            self.assertEqual(ground('Quero especialista',a,{}),UNAVAILABLE)
    def test_real_default_profile_requires_explicit_commercial_binding(self):
        self.assertIsNone(answer_engine.build_answerer(SETTINGS,mode='real'))
    def test_binding_hook_checked_before_api_and_after_selection(self):
        c={**context(),'profile_id':'other','context_namespace':'other'}
        hook=Mock(side_effect=lambda snapshot,settings,mode:snapshot is None or snapshot.get('knowledge_version')=='approved')
        profile=AnswerProfile('other','other','1',lambda _:c,lambda mode:'Other',lambda c,q,d:c,lambda *a,**k:lambda *_:'supported',binding_validator=hook)
        fake=Mock();engine=answer_engine.build_answerer(SETTINGS,mode='real',profile=profile,opener=fake)
        self.assertEqual(engine('Lives?'),'faq_unavailable');fake.open.assert_not_called()
        self.assertGreaterEqual(hook.call_count,2)
    def test_selector_cannot_change_facts_with_unchanged_version(self):
        c={**context(),'profile_id':'other','context_namespace':'other'}
        def changed(c,q,d):
            c['topics'][0]['answer']='99% por 99 meses.'
            return c
        profile=AnswerProfile('other','other','1',lambda _:c,lambda mode:'Other',changed,lambda *a,**k:lambda *_:'supported')
        fake=Mock();engine=answer_engine.build_answerer(SETTINGS,profile=profile,opener=fake)
        self.assertEqual(engine('Lives?'),'faq_unavailable');fake.open.assert_not_called()
    def test_commercial_binding_rejects_text_or_policy_mutation(self):
        from amplify_answer_profile import validate_commercial_binding, APPROVED_COMMERCIAL_BINDINGS
        from unittest.mock import patch
        import hashlib
        c=context();settings={**SETTINGS,'tiktok_policy_approved':True,'tiktok_policy_version':'test-approved',
            'tiktok_invite_commission':'10','tiktok_commission_unit':'percent','tiktok_duration_fixed_months':'2','tiktok_duration_label':'2 meses'}
        from real_operations import policy_for
        from real_journey import _policy_fingerprint
        digest=hashlib.sha256(json.dumps({k:c.get(k) for k in ('knowledge_version','personality','limits','topics')},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        with patch('amplify_answer_profile.APPROVED_COMMERCIAL_BINDINGS',frozenset({('1',c['knowledge_version'],_policy_fingerprint(policy_for(settings)),digest)})):
            self.assertTrue(validate_commercial_binding(c,settings,'real'))
            changed=deepcopy(c);changed['topics'][0]['answer']='99% por 99 meses'
            self.assertFalse(validate_commercial_binding(changed,settings,'real'))
            self.assertFalse(validate_commercial_binding(c,{**settings,'tiktok_invite_commission':'99'},'real'))

    def test_personal_status_synonyms_cannot_accept_generic_success(self):
        from real_answer_adapter import ground_shared_operational_reply as ground
        for q in ['Meu convite saiu?', 'Deu certo meu cadastro?', 'Conseguiram liberar meu acesso?', 'O convite chegou?', 'Liberaram meu acesso?']:
            self.assertIn('não tenho confirmação',ground(q,'Sim, deu certo! ✅',{'cycle':{}},now=NOW))
    def test_contextual_status_without_subject_needs_proof(self):
        from real_answer_adapter import ground_shared_operational_reply as ground
        for phase in ['inviting','invite_pending','await_acceptance','form']:
            for q in ['Deu certo?', 'Conseguiu?', 'Já foi?']:
                self.assertIn('não tenho confirmação',ground(q,'Sim, deu certo! ✅',{'cycle':{'phase':phase}},now=NOW))
        state={'cycle':{'phase':'form','answer_clarification':'Sua dúvida é sobre parceria ou comunidade?'}}
        self.assertEqual(ground('Conseguiu?','Sua dúvida é sobre parceria ou comunidade?',state), 'Sua dúvida é sobre parceria ou comunidade?')

class GmvFirstUseConfirmation(unittest.TestCase):
    def cycle(self):return {'phase':'validation','facts':{},'bia_validation':{'stage':'gmv'}}
    def test_activation_is_not_inferred_zero(self):
        from lead_validation import advance,parse_gmv
        from engine import _clock
        at=_clock(NOW)
        for text in ['Ainda não comecei, somente ativei a conta','Só ativei o shop']:
            c=self.cycle();self.assertIsNone(parse_gmv(text))
            response=advance(c,text,at)
            self.assertEqual(c['bia_validation']['stage'],'gmv_zero_confirmation')
            self.assertNotIn('gmv_30d_declarado_centavos',c['facts'])
            self.assertIn('Só para confirmar',response[0])
            advance(c,'Sim',at)
            self.assertEqual(c['facts']['gmv_30d_declarado_centavos'],0)
    def test_no_unknown_and_numeric_are_distinct(self):
        from lead_validation import advance
        from engine import _clock
        at=_clock(NOW)
        c=self.cycle();advance(c,'Só ativei o shop',at);advance(c,'Não sei',at)
        self.assertNotIn('gmv_30d_declarado_centavos',c['facts'])
        advance(c,'Já tive vendas',at)
        self.assertEqual(c['bia_validation']['stage'],'gmv')
        advance(c,'50 mil',at)
        self.assertEqual(c['bia_validation']['stage'],'priority_profile')
    def test_no_model_called_for_dedicated_confirmation(self):
        t=RealStageRouting();c=t.start();c['cycle']['bia_validation']['stage']='gmv'
        callback=Mock(side_effect=AssertionError('not needed'))
        r=real_journey.handle_real(c,'Só ativei o shop',callback,now=NOW,same_engine_enabled=True)
        self.assertIn('Só para confirmar',r['reply']);callback.assert_not_called()


class SharedBudgetReservation(unittest.TestCase):
    def test_generation_18_keeps_six_seconds_for_mandatory_verifier(self):
        ticks=[0.0];c=context();fake=opener_for(c);original=fake.open.side_effect
        def open_delayed(*a,**kw):
            self.assertEqual(kw['timeout'],18.0);ticks[0]+=18
            return original(*a,**kw)
        fake.open.side_effect=open_delayed
        verifier=Mock(return_value='supported');verifier.accepts_time_budget=True
        engine=answer_engine.build_answerer(SETTINGS,opener=fake,context_loader=lambda _:c,semantic_verifier=verifier,clock=lambda:ticks[0])
        self.assertEqual(engine('Lives?')['answer'],TEXT)
        self.assertEqual(verifier.call_args.kwargs['timeout'],10)
    def test_less_than_reserve_does_not_call_model(self):
        ticks=[0.0];c=context();fake=Mock()
        def loader(_):ticks[0]=23;return c
        engine=answer_engine.build_answerer(SETTINGS,opener=fake,context_loader=loader,clock=lambda:ticks[0])
        self.assertEqual(engine('Lives?'),'faq_unavailable');fake.open.assert_not_called()
    def test_verifier_timeout_never_accepts_generated_answer(self):
        c=context();fake=opener_for(c)
        verifier=Mock(side_effect=TimeoutError())
        engine=answer_engine.build_answerer(SETTINGS,opener=fake,context_loader=lambda _:c,semantic_verifier=verifier)
        self.assertEqual(engine('Lives?'),'faq_unavailable');verifier.assert_called_once()
    def test_total_deadline_still_rejects_late_verification(self):
        ticks=[0.0];c=context();fake=opener_for(c)
        def verify(*args,**kw):ticks[0]=29;return 'supported'
        engine=answer_engine.build_answerer(SETTINGS,opener=fake,context_loader=lambda _:c,semantic_verifier=verify,clock=lambda:ticks[0])
        self.assertEqual(engine('Lives?'),'faq_unavailable')
