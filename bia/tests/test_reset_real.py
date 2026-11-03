"""Reset the conversation, while retaining real identity and write receipts."""
from copy import deepcopy
import unittest

import conversation
import real_journey
from test_real_journey import NOW, POLICY, GATE, inbound, qualified, eligible_state, settle, pending_job


def requalify(state, creator='@teste'):
    for text in ('Quero me agenciar','Indicação',creator):
        turn=inbound(text,state)
        state=turn['state']
    precheck=pending_job(state,'precheck')
    turn=settle(state,precheck,'eligible')
    return settle(turn['state'],pending_job(turn['state'],'relationship'),'not_found')


class RealResetTests(unittest.TestCase):
    def test_reset_at_every_stage_is_fixed_intro_without_calling_ai(self):
        for phase in ('origin','checking','consent_real','inviting','await_acceptance','form','blocked'):
            with self.subTest(phase=phase):
                state=qualified()['state']
                state['cycle'].update(phase=phase, pending_profile_changes={'tiktok_declarado':'@other'},
                                      form_url='https://private.example.invalid/form',invite_offer={'old':'offer'})
                state['cadastro_situacao']='confirmado'
                state['creator_id']='b3e0fa4b-6d0d-48ed-b011-05f465846a1b'
                old_cycle=state['cycle']['id']
                result=inbound('RESETAR',state,callback=lambda *_: self.fail('Reset must not call AI'))
                self.assertEqual(result['reply'],conversation._RESET_GREETING)
                self.assertEqual(result['buttons'],['Conhecer a Amplify','Quero me agenciar'])
                self.assertEqual(result['state']['cycle']['phase'],'intro')
                self.assertNotEqual(result['state']['cycle']['id'],old_cycle)
                self.assertEqual(result['state']['cycle']['facts'],{})
                self.assertNotIn('pending_profile_changes',result['state']['cycle'])
                self.assertNotIn('form_url',result['state']['cycle'])
                self.assertEqual(result['state']['creator_id'],state['creator_id'])
                self.assertEqual(result['state']['cadastro_situacao'],'confirmado')
                self.assertEqual(result['effects'],[])

    def test_completed_cycle_reset_opens_only_one_new_cycle(self):
        state=qualified()['state']
        old=state['cycle']['id']
        old_number=state['cycle']['number']
        state['cycle'].update(status='closed',reason='form_completed')
        result=inbound('resetar',state)
        self.assertEqual(result['reply'],conversation._RESET_GREETING)
        self.assertEqual(result['state']['cycle']['number'],old_number+1)
        self.assertEqual([cycle['id'] for cycle in result['state']['closed_cycles']],[old])

    def test_first_reset_has_one_clean_cycle_and_fixed_greeting(self):
        result=inbound('resetar')
        self.assertEqual(result['state']['cycle']['number'],1)
        self.assertEqual(result['state']['closed_cycles'],[])
        self.assertEqual(result['reply'],conversation._RESET_GREETING)

    def test_duplicate_reset_webhook_does_not_create_another_cycle_or_reply(self):
        from test_real_executor import EVENT
        event={**EVENT,'text':'resetar','message_id':'313999'}
        state=qualified()['state']
        state['processed_inbound'].append('preserved-old-receipt')
        result=conversation.handle_event(state,event,GATE,lambda *_:self.fail('Unexpected AI'),now=NOW,
                                         real_mode=True,operation_policy=POLICY)
        duplicate=conversation.handle_event(result['state'],event,GATE,lambda *_:self.fail('Unexpected AI'),now=NOW,
                                            real_mode=True,operation_policy=POLICY)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(duplicate['reply'],'')
        self.assertEqual(duplicate['state'],result['state'])
        self.assertIn('preserved-old-receipt',duplicate['state']['processed_inbound'])

    def test_only_literal_commands_are_recognized_without_questions_quotes_or_punctuation(self):
        for text in ('resetar','/resetar','RESETAR','reiniciar atendimento','recomeçar'):
            with self.subTest(text=text):
                result=inbound(text,qualified()['state'],callback=lambda *_: self.fail('Unexpected AI'))
                self.assertEqual(result['reply'],conversation._RESET_GREETING)
        for text in ('Posso resetar?','resetar?','"resetar"','ele pediu para resetar','resetar.','resetar!'):
            self.assertFalse(conversation._chat_reset_requested(text,real_mode=True))

    def test_old_conversation_memory_is_not_visible_to_next_ai_turn(self):
        state=qualified()['state']
        state['history'].append({'direction':'outbound','text':'OLD_PENDING_QUESTION', 'at':NOW.isoformat(),'cycle_id':state['cycle']['id']})
        reset=inbound('resetar',state)
        seen=[]
        def planner(_text,context):
            seen.append(context)
            return {'reply':'Posso explicar a parceria. O que gostaria de conhecer?','intent':'question','claims':[],
                    'next_phase':context['phase'],'topic_ids':[],'provider_status':'completed'}
        result=inbound('Quais benefícios?',reset['state'],callback=planner)
        self.assertEqual(len(seen),1)
        self.assertNotIn('OLD_PENDING_QUESTION',str(seen[0]))
        self.assertEqual(seen[0]['facts'],{})
        self.assertEqual(seen[0]['next_action']['kind'],'understand_interest')
        self.assertTrue(all(item['cycle_id']==result['state']['cycle']['id'] for item in seen[0]['history']))
        self.assertIn('OLD_PENDING_QUESTION',str(result['state']['history']))

    def test_provider_receipts_and_identity_are_preserved_but_old_results_are_ignored(self):
        turn=qualified()
        precheck=pending_job(turn['state'],'precheck')
        turn=settle(turn['state'],precheck,'eligible')
        prior=deepcopy(turn['state']['cycle']['real_operations'])
        old_job=pending_job(turn['state'],'relationship')
        reset=inbound('resetar',turn['state'])
        self.assertEqual(reset['state']['closed_cycles'][-1]['real_operations'],prior)
        self.assertEqual(reset['state']['effects'][precheck['id']]['status'],'done')
        late=settle(reset['state'],old_job,'linked')
        self.assertTrue(late['ignored'])
        self.assertEqual(late['state']['cycle']['phase'],'intro')
        self.assertNotIn('form_effect_id',late['state']['cycle'])

    def test_uncertain_invite_survives_reset_and_cannot_be_posted_again_for_same_handle(self):
        turn=inbound('Autorizo o convite real',eligible_state()['state'])
        invite=turn['effects'][0]
        turn=settle(turn['state'],invite,'outcome_unknown',updates={'confirmed':False,'evidence':{'post_attempted':True}})
        reset=inbound('resetar',turn['state'])
        self.assertEqual(reset['state']['effects'][invite['id']]['status'],'outcome_unknown')
        new_offer=requalify(reset['state'])
        confirmed=inbound('Autorizo o convite real',new_offer['state'])
        self.assertEqual(confirmed['state']['cycle']['phase'],'blocked')
        self.assertEqual(confirmed['effects'],[])
        self.assertEqual(sum(effect.get('operation')=='invite' for effect in confirmed['state']['effects'].values()),1)

    def test_invite_in_flight_at_reset_is_preserved_as_uncertain(self):
        turn=inbound('Autorizo o convite real',eligible_state()['state'])
        invite=turn['effects'][0]
        reset=inbound('resetar',turn['state'])
        self.assertEqual(reset['state']['effects'][invite['id']]['status'],'outcome_unknown')
        self.assertTrue(real_journey._prior_invite_requires_reconciliation(reset['state'],'@teste'))

    def test_proven_sent_invite_is_not_deleted_or_repeated_by_reset(self):
        turn=inbound('Autorizo o convite real',eligible_state()['state'])
        invite=turn['effects'][0]
        turn=settle(turn['state'],invite,'sent')
        reset=inbound('resetar',turn['state'])
        self.assertEqual(reset['state']['closed_cycles'][-1]['real_operations']['invite']['status'],'sent')
        self.assertTrue(real_journey._prior_invite_requires_reconciliation(reset['state'],'@teste'))
        self.assertEqual(reset['state']['effects'][invite['id']]['status'],'done')

    def test_prior_invite_does_not_block_another_handle_after_new_real_checks(self):
        turn=inbound('Autorizo o convite real',eligible_state()['state'])
        turn=settle(turn['state'],turn['effects'][0],'sent')
        reset=inbound('resetar',turn['state'])
        offer=requalify(reset['state'],'@another_creator')
        confirmed=inbound('Autorizo o convite real',offer['state'])
        self.assertEqual(confirmed['state']['cycle']['phase'],'inviting')
        self.assertEqual(len(confirmed['effects']),1)
        self.assertEqual(confirmed['effects'][0]['creator'],'@another_creator')

    def test_conclusively_ineligible_no_write_receipt_does_not_block_new_cycle(self):
        turn=inbound('Autorizo o convite real',eligible_state()['state'])
        turn=settle(turn['state'],turn['effects'][0],'ineligible',updates={'evidence':{'post_attempted':False,'reason':'precheck'}})
        reset=inbound('resetar',turn['state'])
        self.assertFalse(real_journey._prior_invite_requires_reconciliation(reset['state'],'@teste'))
        offer=requalify(reset['state'])
        self.assertEqual(inbound('Autorizo o convite real',offer['state'])['effects'][0]['operation'],'invite')

    def test_sent_then_profile_change_then_reset_then_old_handle_never_repeats_invite(self):
        turn=inbound('Autorizo o convite real',eligible_state()['state'])
        invite=turn['effects'][0]
        turn=settle(turn['state'],invite,'sent')
        turn=inbound('@another_creator',turn['state'])
        turn=inbound('Sim confirmo',turn['state'])
        self.assertNotIn('invite',turn['state']['cycle'].get('real_operations',{}))
        self.assertEqual(turn['state']['effects'][invite['id']]['result_receipt']['status'],'sent')
        reset=inbound('resetar',turn['state'])
        offer=requalify(reset['state'],'@teste')
        result=inbound('Autorizo o convite real',offer['state'])
        self.assertEqual(result['effects'],[])
        self.assertEqual(result['state']['cycle']['phase'],'blocked')
        self.assertEqual(sum(effect.get('operation')=='invite' and effect.get('creator')=='@teste'
                             for effect in result['state']['effects'].values()),1)

    def test_pending_then_superseded_by_profile_change_still_fences_old_handle(self):
        turn=inbound('Autorizo o convite real',eligible_state()['state'])
        invite=turn['effects'][0]
        turn=inbound('@another_creator',turn['state'])
        turn=inbound('Sim confirmo',turn['state'])
        self.assertEqual(turn['state']['effects'][invite['id']]['status'],'superseded')
        reset=inbound('resetar',turn['state'])
        self.assertTrue(real_journey._prior_invite_requires_reconciliation(reset['state'],'@teste'))
        self.assertFalse(real_journey._prior_invite_requires_reconciliation(reset['state'],'@another_creator'))

    def test_legacy_done_effect_without_bound_receipt_fails_closed(self):
        turn=inbound('Autorizo o convite real',eligible_state()['state'])
        invite=turn['effects'][0]
        turn=settle(turn['state'],invite,'sent')
        turn['state']['effects'][invite['id']].pop('result_receipt',None)
        turn['state']['cycle'].pop('real_operations',None)
        reset=inbound('resetar',turn['state'])
        self.assertTrue(real_journey._prior_invite_requires_reconciliation(reset['state'],'@teste'))

    def test_explicit_no_post_receipt_survives_profile_change_and_allows_new_attempt(self):
        turn=inbound('Autorizo o convite real',eligible_state()['state'])
        invite=turn['effects'][0]
        turn=settle(turn['state'],invite,'ineligible',updates={'evidence':{'post_attempted':False}})
        turn=inbound('@another_creator',turn['state'])
        turn=inbound('Sim confirmo',turn['state'])
        reset=inbound('resetar',turn['state'])
        self.assertFalse(real_journey._prior_invite_requires_reconciliation(reset['state'],'@teste'))
        offer=requalify(reset['state'],'@teste')
        self.assertEqual(inbound('Autorizo o convite real',offer['state'])['effects'][0]['operation'],'invite')

    def test_simulated_reset_has_same_fixed_greeting_and_no_old_active_memory(self):
        state=conversation.handle({},'Quero me agenciar',now=NOW)['state']
        old_cycle=state['cycle']['id']
        result=conversation.handle(state,'resetar',lambda *_: self.fail('Unexpected AI'),now=NOW)
        self.assertEqual(result['reply'],conversation._RESET_GREETING)
        self.assertEqual(result['buttons'],['Conhecer a Amplify','Quero me agenciar'])
        self.assertEqual(result['state']['cycle']['facts'],{})
        self.assertTrue(any(item['cycle_id']==old_cycle for item in result['state']['history']))


if __name__=='__main__':
    unittest.main()
