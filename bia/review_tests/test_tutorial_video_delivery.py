import unittest
from unittest.mock import patch
from datetime import datetime, timezone
import tutorial_videos as videos
import lead_validation as validation
import conversao
import real_journey as journey

class TutorialTests(unittest.TestCase):
    def test_inactive_shop_guidance(self):
        cycle={'facts':{},'bia_validation':{'stage':'shop'}}
        reply,_=validation.advance(cycle,'Não',datetime.now(timezone.utc))
        self.assertIn(videos.ACTIVATE_SHOP_URL,reply)
        self.assertEqual(cycle['bia_validation']['stage'],'activate')
        self.assertFalse(validation.permitted(cycle))
        reply,_=validation.advance(cycle,'Já está ativo',datetime.now(timezone.utc))
        self.assertNotIn(videos.ACTIVATE_SHOP_URL,reply)
    def test_help_templates(self):
        for text in [conversao.INVITE_WHERE,conversao.INVITE_STEPS,conversao.INVITE_IS_THERE,journey._ACCEPT_INVITE_GUIDE]:
            self.assertEqual(text.count(videos.ACCEPT_INVITE_URL),1)
        self.assertIn(videos.ACTIVATE_SHOP_URL,conversao.SHOP_STEPS)
    def test_confirmed_invite_offers_once(self):
        for status in ['sent','pending','pending_verification','linked','failed']:
            state={'cycle':{'real_operations':{'invite':{'status':status}}}}
            with patch.object(journey,'form_entry_allowed',return_value=True),patch.object(journey,'_finish',side_effect=lambda s,a,**kw:kw):
                first=journey._form_after_invite(state,None)
                second=journey._form_after_invite(state,None)
            self.assertEqual(videos.ACCEPT_INVITE_URL in first['reply'],status in {'sent','pending'})
            self.assertNotIn(videos.ACCEPT_INVITE_URL,second['reply'])
            self.assertEqual(first['effects'],[])
    def test_no_tutorial_claim_when_invite_forbidden(self):
        with patch.object(journey,'form_entry_allowed',return_value=False):
            self.assertIsNone(journey._form_after_invite({'cycle':{}},None))

    def test_explicit_acceptance_questions_return_video_without_provider_work(self):
        from test_relationship_form_chat30 import invited, inbound
        for question in ['como aceitar o convite?', 'não sei aceitar o convite', 'não sei como aceitar', 'vídeo do convite']:
            result = inbound(question, invited()['state'])
            self.assertIn(videos.ACCEPT_INVITE_URL, result['reply'], question)
            self.assertEqual(result['effects'], [])
