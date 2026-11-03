"""Explicit email effects with stable message IDs and no implicit resend."""
from email.message import EmailMessage
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.utils import formataddr
from hashlib import sha256
import smtplib
import ssl
from uuid import UUID


def _single_mailbox(value):
    if not isinstance(value, str) or not value or len(value) > 254 or any(c in value for c in '\r\n\t ,;<>'):
        return False
    try:
        address = Address(addr_spec=value)
        return bool(address.username and address.domain and address.addr_spec == value)
    except (ValueError, TypeError, IndexError, HeaderParseError):
        return False


class SmtpSender:
    def __init__(self, settings, factory=None):
        self.settings = settings
        self.factory = factory or smtplib.SMTP_SSL

    def _send(self, recipient, subject, text, operation_id):
        sender = self.settings.get('smtp_user', '')
        password = self.settings.get('smtp_password', '')
        name = self.settings.get('smtp_from_name', 'Bia · Amplify')
        if (not _single_mailbox(sender) or not password or not _single_mailbox(recipient)
                or not isinstance(name, str) or any(c in name for c in ('\r', '\n'))):
            return {'status': 'failed', 'reason': 'email_configuration_invalid'}
        message_id = '<v5-' + sha256(str(operation_id).encode()).hexdigest() + '@amplify-ensaio.invalid>'
        try:
            message = EmailMessage()
            message['From'] = formataddr((name, sender))
            message['To'] = recipient
            message['Subject'] = subject
            message['Message-ID'] = message_id
            message.set_content(text)
            with self.factory(self.settings.get('smtp_host', 'smtp.gmail.com'),
                              int(self.settings.get('smtp_port', 465)), timeout=15,
                              context=ssl.create_default_context()) as client:
                client.login(sender, password)
                refused = client.send_message(message)
                if refused:
                    return {'status': 'failed', 'message_id': message_id, 'reason': 'recipient_rejected'}
        except smtplib.SMTPAuthenticationError:
            return {'status': 'failed', 'message_id': message_id, 'reason': 'authentication_failed'}
        except (smtplib.SMTPException, OSError, ValueError, HeaderParseError):
            return {'status': 'outcome_unknown', 'message_id': message_id}
        return {'status': 'accepted', 'message_id': message_id, 'inbox_delivery_confirmed': False}

    def send_otp(self, email, code, operation_id):
        if self.settings.get('tiktok_mode') == 'real':
            return self._send(email, 'Seu código de confirmação · Amplify',
                              'Olá! Aqui é a Bia, agente de IA da Amplify.\n\n'
                              'Use este código para confirmar seu e-mail: ' + str(code) +
                              '\nEle expira em 10 minutos.', operation_id)
        return self._send(email, 'Seu código de confirmação · Ensaio Amplify',
                          'Olá! Aqui é a Bia, agente digital da Amplify.\n\n'
                          'Use este código para confirmar seu e-mail no ensaio: ' + str(code) +
                          '\nEle expira em 10 minutos.\n\nEste é um teste do novo cadastro da Amplify.', operation_id)

    def send_receipt(self, email, receipt, operation_id):
        if self.settings.get('tiktok_mode') == 'real':
            try:
                valid = (isinstance(receipt, dict) and receipt.get('status') == 'cadastro_recebido_real'
                         and all(str(UUID(receipt[key])) == receipt[key]
                                 and UUID(receipt[key]).int != 0 for key in ('creator_id', 'event_id')))
            except (ValueError, TypeError, AttributeError, KeyError):
                valid = False
            if not valid:
                return {'status': 'failed', 'reason': 'real_registration_receipt_required'}
            return self._send(email, 'Cadastro recebido · Amplify',
                              'Olá! Aqui é a Bia, agente de IA da Amplify.\n\n'
                              'Seu formulário foi recebido e registrado na base da Amplify. '
                              'Este e-mail confirma o recebimento do cadastro. '
                              'A entrega dos acessos terá sua própria confirmação.\n\n'
                              'Obrigada por participar!', operation_id)
        return self._send(email, 'Cadastro recebido · Ensaio Amplify',
                          'Olá! Aqui é a Bia, agente digital da Amplify.\n\n'
                          'Seu formulário foi recebido e consolidado na base do ensaio. '
                          'As verificações de convite e vínculo deste teste foram simuladas. '
                          'Este e-mail confirma o recebimento do cadastro.\n\nObrigada por participar do teste.', operation_id)
