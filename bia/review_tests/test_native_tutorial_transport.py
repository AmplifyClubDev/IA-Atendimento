"""Synthetic offline tests: no recipient, network, or real provider credentials."""
import hashlib
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.error import HTTPError
import tutorial_videos as videos
from transport import ChatwootTransport, _download_tutorial
from test_release55_sanitized import event, settings

class NativeTutorialTransport(TestCase):
    def setUp(self):
        self.bytes = b'\x00\x00\x00\x18ftypmp42synthetic-video'
        self.assets = {url: {**value, 'size':len(self.bytes), 'sha256':hashlib.sha256(self.bytes).hexdigest()}
                       for url,value in videos.ASSETS.items()}
        self.patcher=patch.dict(videos.ASSETS,self.assets,clear=True);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.http=Mock(return_value={'id': '999', 'attachments':[{'id': '10','file_type':'video'}], 'status':'sent'})
        self.fetch=Mock(return_value=self.bytes)
        self.transport=ChatwootTransport('https://synthetic.invalid','synthetic',settings()['gate'],
            http=self.http,media_fetch=self.fetch,cloud={'token':'unused','phone_number_id':'123456'})
        self.transport._read_target=Mock(return_value=True)
        self.evt=event()
    def send(self,**kwargs):
        return self.transport.send_reply(self.evt,videos.invitation_help('Aceite no TikTok.'),['Já aceitei'],'synthetic:video',**kwargs)
    def test_native_mp4_single_post_no_cloud_or_url_text(self):
        answer=self.send()
        self.assertEqual(answer,{'status':'accepted','message_id':'999','media_type':'video'})
        self.assertEqual(self.http.call_count,1)
        call=self.http.call_args.kwargs
        self.assertTrue(call['url'].endswith('/conversations/7/messages'))
        self.assertEqual(call['headers']['Idempotency-Key'],'synthetic:video')
        self.assertNotIn('json_body',call)
        msg=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+call['headers']['Content-Type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+call['raw_body'])
        parts={part.get_param('name',header='content-disposition'):part for part in msg.iter_parts()}
        attachment=parts['attachments[]']
        self.assertEqual(attachment.get_content_type(),'video/mp4')
        self.assertEqual(attachment.get_filename(),'como-aceitar-convite.mp4')
        self.assertEqual(attachment.get_payload(decode=True),self.bytes)
        caption=parts['content'].get_payload(decode=True).decode()
        self.assertEqual(caption,'Aceite no TikTok.\n\nResponda: Já aceitei')
        self.assertNotIn('supabase',caption)
        self.assertEqual(parts['content_attributes[amplify_idempotency_key]'].get_payload(decode=True),b'synthetic:video')
        self.assertEqual(self.transport._read_target.call_count,2)
    def test_shop_video_uses_correct_file_and_caption(self):
        answer=self.transport.send_reply(self.evt,videos.activation_help('Ative o Shop.'),['Já está ativo'],'shop')
        self.assertEqual(answer['status'],'accepted')
        body=self.http.call_args.kwargs['raw_body']
        self.assertIn(b'como-ativar-tiktok-shop.mp4',body)
        self.assertNotIn(videos.ACTIVATE_SHOP_URL.encode(),body)
    def test_hash_mismatch_or_download_failure_never_posts(self):
        for failure in ['mismatch','exception']:
            self.http.reset_mock();self.fetch.side_effect=None
            if failure=='mismatch':self.fetch.return_value=b'changed'
            else:self.fetch.side_effect=RuntimeError('unavailable')
            self.assertEqual(self.send()['status'],'failed');self.http.assert_not_called()
    def test_cancel_or_closed_window_after_download_never_posts(self):
        self.assertEqual(self.send(before_write=lambda:False)['status'],'failed');self.http.assert_not_called()
        self.transport._read_target.side_effect=[True,False]
        self.assertEqual(self.send()['status'],'failed');self.http.assert_not_called()
    def test_post_timeout_unknown_no_text_retry(self):
        self.http.side_effect=TimeoutError()
        self.assertEqual(self.send()['status'],'outcome_unknown');self.assertEqual(self.http.call_count,1)
    def test_receipt_requires_video_not_id_alone(self):
        for reply in [{'id':'999'},{'id':'999','attachments':[{'id':'1','file_type':'image'}]}]:
            self.http.return_value=reply
            self.assertEqual(self.send()['status'],'outcome_unknown')
    def test_rejection_and_failure_not_accepted(self):
        self.http.side_effect=HTTPError('https://synthetic.invalid',422,'invalid',{},None)
        self.assertEqual(self.send()['status'],'failed')
        self.http.side_effect=None;self.http.return_value={'id':'999','status':'failed','attachments':[{'id':'1','file_type':'video'}]}
        self.assertEqual(self.send()['status'],'failed')
    def test_plain_text_unchanged(self):
        self.http.return_value={'id':'999'}
        self.assertEqual(self.transport.send_reply(self.evt,'Mensagem normal',[],'plain')['status'],'accepted')
        self.assertIn('json_body',self.http.call_args.kwargs);self.fetch.assert_not_called()
    def test_ambiguous_asset_and_caption_length_fail_closed(self):
        for text in [videos.ACCEPT_INVITE_URL+' '+videos.ACTIVATE_SHOP_URL, videos.invitation_help('x'*1025)]:
            self.assertEqual(self.transport.send_reply(self.evt,text,[],'bad')['status'],'failed')
        self.http.assert_not_called()
    def test_reconcile_does_not_accept_missing_video_or_failed_channel(self):
        attrs={'amplify_idempotency_key':'video','amplify_tutorial':'accept_invite'}
        for message,status in [({'id':'1','content_attributes':attrs},'outcome_unknown'),
                               ({'id':'1','status':'failed','content_attributes':attrs},'failed'),
                               ({'id':'1','attachments':[{'id':'9','file_type':'video'}],'content_attributes':attrs},'accepted')]:
            self.http.return_value={'payload':[message]}
            self.assertEqual(self.transport.reconcile_reply(self.evt,'video')['status'],status)
    def test_downloader_allowlist_precedes_network(self):
        with patch('transport.build_opener') as opener:
            with self.assertRaises(ValueError):_download_tutorial({'url':'https://unapproved.invalid/x'})
            opener.assert_not_called()
    def test_downloader_public_no_credentials_bounded_exact_hash(self):
        response=Mock();response.status=200;response.headers.get_content_type.return_value='video/mp4';response.read.return_value=self.bytes
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        opener=Mock();opener.open.return_value=response
        asset={'url':videos.ACCEPT_INVITE_URL,**self.assets[videos.ACCEPT_INVITE_URL]}
        with patch('transport.build_opener',return_value=opener):
            self.assertEqual(_download_tutorial(asset),self.bytes)
        req=opener.open.call_args.args[0];self.assertEqual(req.full_url,videos.ACCEPT_INVITE_URL)
        self.assertIsNone(req.get_header('Authorization'));self.assertIsNone(req.get_header('Api_access_token'))
        response.read.assert_called_once_with(len(self.bytes)+1)
