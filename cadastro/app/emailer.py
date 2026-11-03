"""Envio do código de confirmação de e-mail (SMTP, mesma conta usada pela Bia)."""
from __future__ import annotations

import html
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr


class EmailSender:
    def __init__(self, *, host, port, user, password, factory=None):
        self.host, self.port, self.user, self.password = host, int(port), user, password
        self.factory = factory or smtplib.SMTP_SSL

    def configured(self):
        return bool(self.user and self.password)

    def send_code(self, email, code, message_id):
        """'enviado' quando o servidor SMTP aceitou; 'incerto' quando não dá para saber."""
        message = EmailMessage()
        message["From"] = formataddr(("Amplify — notificações", self.user))
        message["To"] = email
        # A referência do pedido também aparece na tela; não inclui o código secreto.
        reference = message_id.split('@', 1)[0].rsplit('-', 1)[-1][-6:]
        message["Subject"] = "Confirme seu e-mail na Amplify 💙 — pedido " + reference
        message["Message-ID"] = message_id
        message["Auto-Submitted"] = "auto-generated"
        message["X-Auto-Response-Suppress"] = "All"
        # Texto e HTML iguais ao e-mail do formulário original (src/cadastro_email.py: code_message).
        message.set_content(
            f"Pedido {reference}. Seu código Amplify é: {code}\n\nDigite no formulário para confirmar seu e-mail. "
            "Válido por 10 minutos. Use o código do pedido mais recente.\n\n"
            "A confirmação não significa que os acessos já foram liberados. "
            "Se você não solicitou este código, ignore esta mensagem. Não compartilhe o código.\n\n"
            "Mensagem automática — não responda a este e-mail. Este endereço é usado apenas para notificações.")
        message.add_alternative(f'''<!doctype html><html lang="pt-BR"><body style="margin:0;background:#f4f6fc;font-family:Arial,sans-serif;color:#14213b">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:28px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:white;border-radius:20px;border:1px solid #e0e6f0">
<tr><td style="padding:30px 28px;background:#2148d4;color:white;border-radius:20px 20px 0 0"><strong style="font-size:30px">amplify</strong><br><span style="font-size:11px;letter-spacing:3px">CREATOR CLUB</span></td></tr>
<tr><td style="padding:28px"><h1 style="font-size:24px;margin:0 0 14px">Só falta confirmar seu e-mail 💙</h1>
<p style="line-height:1.6">Pedido <strong>{html.escape(reference)}</strong>. Digite este código no formulário da Amplify:</p>
<p style="font-size:34px;font-weight:bold;letter-spacing:8px;text-align:center;background:#eef3ff;color:#2148d4;padding:20px 8px;border-radius:12px">{code}</p>
<p style="font-size:14px;line-height:1.6">Válido por <strong>10 minutos</strong>. Se pedir outro código, use o mais recente.</p>
<p style="font-size:12px;line-height:1.6;color:#64728a">A confirmação do e-mail não significa que os acessos já foram liberados. Se não foi você quem pediu, ignore esta mensagem. Não compartilhe o código.</p>
<p style="font-size:12px;line-height:1.6;color:#64728a">Mensagem automática — não responda a este e-mail. Este endereço é usado apenas para notificações.</p>
</td></tr></table></td></tr></table></body></html>''', subtype='html')
        try:
            with self.factory(self.host, self.port, timeout=15, context=ssl.create_default_context()) as client:
                client.login(self.user, self.password)
                if client.send_message(message):
                    return "devolvido"
        except (smtplib.SMTPRecipientsRefused,):
            return "devolvido"
        except (smtplib.SMTPException, OSError, ValueError):
            return "incerto"
        return "enviado"

    def send_alert(self, to, subject, text, *, titulo=None, selo=None, cor="#2148d4", passos=(), botao=None):
        """Alerta interno para a equipe (sem dados pessoais do lead no texto).

        Mesmo visual dos e-mails da Amplify (cabeçalho azul, cartão branco), com selo de
        situação colorido, passos numerados e um botão de ação quando houver.
        """
        message = EmailMessage()
        message["From"] = formataddr(("Amplify — notificações", self.user))
        message["To"] = to
        message["Subject"] = subject
        message["Auto-Submitted"] = "auto-generated"
        message["X-Auto-Response-Suppress"] = "All"
        plain = [text] + ([f"{i}. {p}" for i, p in enumerate(passos, 1)] if passos else [])
        if botao:
            plain.append(f"{botao[0]}: {botao[1]}")
        message.set_content("\n\n".join(plain) + "\n\nMensagem automática da operação Amplify — não responda a este e-mail.")
        paragraphs = "".join(
            '<p style="font-size:15px;line-height:1.6;margin:0 0 14px">' + html.escape(part).replace("\n", "<br>") + "</p>"
            for part in text.split("\n\n"))
        badge = (f'<p style="margin:0 0 16px"><span style="display:inline-block;background:{cor};color:white;font-size:12px;'
                 f'font-weight:bold;letter-spacing:1px;padding:6px 12px;border-radius:999px">{html.escape(selo)}</span></p>') if selo else ""
        steps = ""
        if passos:
            steps = ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 18px;background:#eef3ff;border-radius:12px">'
                     + "".join(f'<tr><td style="padding:12px 14px;width:28px;vertical-align:top"><span style="display:inline-block;width:24px;height:24px;'
                               f'line-height:24px;text-align:center;border-radius:50%;background:#2148d4;color:white;font-size:13px;font-weight:bold">{i}</span></td>'
                               f'<td style="padding:12px 14px 12px 0;font-size:14px;line-height:1.5">{html.escape(p)}</td></tr>'
                               for i, p in enumerate(passos, 1)) + "</table>")
        button = (f'<p style="text-align:center;margin:8px 0 18px"><a href="{html.escape(botao[1])}" style="display:inline-block;background:#2148d4;'
                  f'color:white;text-decoration:none;font-weight:bold;font-size:15px;padding:14px 26px;border-radius:12px">{html.escape(botao[0])} →</a></p>') if botao else ""
        message.add_alternative(f'''<!doctype html><html lang="pt-BR"><body style="margin:0;background:#f4f6fc;font-family:Arial,sans-serif;color:#14213b">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:28px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:white;border-radius:20px;border:1px solid #e0e6f0">
<tr><td style="padding:30px 28px;background:#2148d4;color:white;border-radius:20px 20px 0 0"><strong style="font-size:30px">amplify</strong><br><span style="font-size:11px;letter-spacing:3px">CREATOR CLUB · OPERAÇÃO</span></td></tr>
<tr><td style="padding:28px">{badge}<h1 style="font-size:22px;line-height:1.3;margin:0 0 14px">{html.escape(titulo or subject)}</h1>{paragraphs}{steps}{button}
<p style="font-size:12px;line-height:1.6;color:#64728a;margin-top:18px">Mensagem automática da operação Amplify — não responda a este e-mail.</p>
</td></tr></table></td></tr></table></body></html>''', subtype="html")
        try:
            with self.factory(self.host, self.port, timeout=15, context=ssl.create_default_context()) as client:
                client.login(self.user, self.password)
                client.send_message(message)
            return True
        except (smtplib.SMTPException, OSError, ValueError):
            return False
