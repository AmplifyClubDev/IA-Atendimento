"""Envio Gmail por HTTPS. Nao repete POST de envio com resultado incerto."""
import base64
import time
from email.policy import SMTP
from email.utils import parseaddr

import requests

SEND_SCOPE = 'https://www.googleapis.com/auth/gmail.send'
READ_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'


class GmailAPI:
    def __init__(self, settings, session=None):
        self.settings = settings
        self.session = session or requests.Session()
        self._token = None
        self._expires_at = 0
        self._scopes = set()

    def authorize_sender(self):
        """Renova e confere a conta antes de liberar qualquer envio."""
        if self._token and self._expires_at > time.monotonic() + 60:
            return self._token
        settings = self.settings
        if not all((settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token)):
            raise RuntimeError('gmail_autorizacao_pendente')
        try:
            response = self.session.post('https://oauth2.googleapis.com/token', data={
                'grant_type': 'refresh_token', 'client_id': settings.gmail_client_id,
                'client_secret': settings.gmail_client_secret, 'refresh_token': settings.gmail_refresh_token,
            }, timeout=(5, 30), allow_redirects=False)
            if response.status_code != 200:
                raise RuntimeError('gmail_autorizacao_invalida')
            data = response.json()
            token = data.get('access_token')
            if not isinstance(token, str) or not token or data.get('token_type', '').lower() != 'bearer':
                raise RuntimeError('gmail_token_invalido')
            if SEND_SCOPE not in str(data.get('scope', '')).split():
                raise RuntimeError('gmail_permissao_envio_ausente')
            response = self.session.get('https://openidconnect.googleapis.com/v1/userinfo',
                headers={'Authorization': 'Bearer ' + token}, timeout=(5, 20), allow_redirects=False)
            if response.status_code != 200:
                raise RuntimeError('gmail_identidade_indisponivel')
            user = response.json()
            if user.get('email_verified') is not True or user.get('email', '').lower() != settings.smtp_usuario.lower():
                raise RuntimeError('gmail_remetente_divergente')
            self._token = token
            self._scopes = set(str(data.get('scope', '')).split())
            self._expires_at = time.monotonic() + min(max(int(data.get('expires_in', 0)), 0), 3600)
            return token
        except requests.RequestException:
            raise RuntimeError('gmail_conexao_autorizacao_indisponivel') from None
        except (ValueError, TypeError, KeyError):
            raise RuntimeError('gmail_resposta_autorizacao_invalida') from None

    def send(self, message):
        if parseaddr(str(message['From']))[1].lower() != self.settings.smtp_usuario.lower():
            raise RuntimeError('gmail_remetente_divergente')
        token = self.authorize_sender()
        raw = base64.urlsafe_b64encode(message.as_bytes(policy=SMTP)).decode('ascii')
        try:
            response = self.session.post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                headers={'Authorization': 'Bearer ' + token}, json={'raw': raw},
                timeout=(5, 30), allow_redirects=False)
        except requests.RequestException:
            raise RuntimeError('gmail_envio_a_reconciliar') from None
        if response.status_code != 200:
            if response.status_code == 403:
                raise RuntimeError('gmail_api_ou_permissao_indisponivel')
            if response.status_code == 429:
                raise RuntimeError('gmail_limite_de_envio')
            raise RuntimeError('gmail_envio_http_' + str(response.status_code))
        try:
            provider_id = response.json().get('id')
        except ValueError:
            raise RuntimeError('gmail_recibo_a_reconciliar') from None
        if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 200 or not provider_id.isalnum():
            raise RuntimeError('gmail_recibo_a_reconciliar')
        return 'gmail:' + provider_id

    def read(self, path, params=None):
        """Read only within this verified sender's mailbox; never expands OAuth grants."""
        import re
        if not re.fullmatch(r'(?:messages|threads)(?:/[a-zA-Z0-9]+)?', path):
            raise ValueError('gmail_caminho_invalido')
        token = self.authorize_sender()
        if not self._scopes.intersection({READ_SCOPE, 'https://www.googleapis.com/auth/gmail.modify', 'https://mail.google.com/'}):
            raise RuntimeError('gmail_permissao_leitura_ausente')
        try:
            response = self.session.get('https://gmail.googleapis.com/gmail/v1/users/me/' + path,
                headers={'Authorization': 'Bearer ' + token}, params=params or {},
                timeout=(5, 30), allow_redirects=False)
            if response.status_code != 200:
                raise RuntimeError('gmail_leitura_http_' + str(response.status_code))
            return response.json()
        except (requests.RequestException, ValueError):
            raise RuntimeError('gmail_leitura_indisponivel') from None
