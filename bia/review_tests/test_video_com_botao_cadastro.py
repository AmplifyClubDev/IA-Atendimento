"""Auditoria 21/11/2026: link é botão também na mensagem com vídeo (convite enviado)."""
import hashlib
from email import policy
from email.parser import BytesParser
from unittest import TestCase
from unittest.mock import Mock, patch

import tutorial_videos as videos
from real_journey import PUBLIC_FORM_URL
from transport import ChatwootTransport
from test_release55_sanitized import event, settings

TEXTO = ('Seu convite foi enviado! 🎉\n\nAceite o convite no app do TikTok e depois faça seu cadastro por aqui:\n'
         + PUBLIC_FORM_URL + '\n\nNo formulário, informe seu @.')


class VideoComBotaoTests(TestCase):
    def setUp(self):
        self.bytes = b'\x00\x00\x00\x18ftypmp42synthetic-video'
        assets = {url: {**value, 'size': len(self.bytes), 'sha256': hashlib.sha256(self.bytes).hexdigest()}
                  for url, value in videos.ASSETS.items()}
        patcher = patch.dict(videos.ASSETS, assets, clear=True)
        patcher.start(); self.addCleanup(patcher.stop)
        self.calls = []
        self.status = 'sent'

        def http(**kw):
            self.calls.append(kw)
            if 'graph.facebook.com' in kw['url']:
                return {'messages': [{'id': 'wamid.1'}]}
            if kw['method'] == 'GET':
                return {'payload': [{'id': 999, 'status': self.status}]}
            if 'raw_body' in kw:
                return {'id': '999', 'attachments': [{'id': '10', 'file_type': 'video'}], 'status': 'progress'}
            return {'id': '1000'}

        self.transport = ChatwootTransport('https://synthetic.invalid', 'synthetic', {**settings()['gate'], 'mode': 'todos'},
                                           http=http, media_fetch=Mock(return_value=self.bytes),
                                           cloud={'token': 'synthetic', 'phone_number_id': '123456'})
        self.transport._read_target = Mock(return_value=True)
        self.evt = event()

    def enviar(self):
        return self.transport.send_reply(self.evt, videos.invitation_help(TEXTO), [], 'conv:video')

    def legenda(self):
        video = next(c for c in self.calls if 'raw_body' in c)
        msg = BytesParser(policy=policy.default).parsebytes(
            ('Content-Type: ' + video['headers']['Content-Type'] + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + video['raw_body'])
        parts = {p.get_param('name', header='content-disposition'): p for p in msg.iter_parts()}
        return parts['content'].get_payload(decode=True).decode()

    def test_video_sem_link_na_legenda_e_botao_depois(self):
        self.assertEqual(self.enviar()['status'], 'accepted')
        legenda = self.legenda()
        self.assertNotIn(PUBLIC_FORM_URL, legenda)
        self.assertIn('no botão abaixo', legenda)
        ordem = [('video' if 'raw_body' in c else 'botao' if 'graph.facebook.com' in c['url'] else c['method'])
                 for c in self.calls]
        self.assertLess(ordem.index('video'), ordem.index('botao'))
        botao = next(c for c in self.calls if 'graph.facebook.com' in c['url'])['json_body']
        self.assertEqual(botao['interactive']['type'], 'cta_url')
        self.assertEqual(botao['interactive']['action']['parameters'],
                         {'display_text': 'Fazer cadastro', 'url': PUBLIC_FORM_URL})
        nota = [c for c in self.calls if c.get('json_body', {}).get('private') is True]
        self.assertEqual(len(nota), 1)
        self.assertTrue(nota[0]['json_body']['content'].startswith('🔗 Botão enviado pelo WhatsApp: *Fazer cadastro*'))
        self.assertEqual(nota[0]['headers']['Idempotency-Key'], 'conv:video:botao')

    def test_espera_o_video_sair_antes_do_botao(self):
        estados = iter(['progress', 'progress', 'sent'])
        original = self.transport.http

        def http(**kw):
            if kw['method'] == 'GET':
                self.status = next(estados)
            return original(**kw)
        self.transport.http = http
        esperas = []
        self.transport._send_form_button_after_video(self.evt, self.transport._form_button(TEXTO), '999', 'k',
                                                     sleep=esperas.append)
        self.assertEqual(len(esperas), 2)
        self.assertTrue(any('graph.facebook.com' in c['url'] for c in self.calls))

    def test_video_que_falhou_nao_manda_botao(self):
        self.status = 'failed'
        self.assertFalse(self.transport._send_form_button_after_video(
            self.evt, self.transport._form_button(TEXTO), '999', 'k', sleep=lambda s: None))
        self.assertFalse(any('graph.facebook.com' in c['url'] for c in self.calls))

    def test_falha_do_botao_nao_muda_o_recibo_do_video(self):
        original = self.transport.http

        def http(**kw):
            if 'graph.facebook.com' in kw['url']:
                raise TimeoutError()
            return original(**kw)
        self.transport.http = http
        self.assertEqual(self.enviar()['status'], 'accepted')

    def test_video_sem_link_continua_igual(self):
        self.transport.send_reply(self.evt, videos.invitation_help('Aceite no TikTok.'), [], 'conv:simples')
        self.assertFalse(any('graph.facebook.com' in c['url'] for c in self.calls))
        self.assertEqual(sum(1 for c in self.calls if 'raw_body' in c), 1)
