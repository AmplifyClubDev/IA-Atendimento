# Chatwoot — visual de WhatsApp

**Ativo desde 21/11/2026** em Super Admin › Installation Configs › `DASHBOARD_SCRIPTS` (config #117).
Vale para todos os usuários do painel. É só aparência: mensagens, envio, etiquetas e a Bia não mudam.

| O que muda | Como era | Como ficou |
|---|---|---|
| Balões | azul / cinza | verde (Bia e time) e branco ou cinza (lead), fundo do WhatsApp, claro e escuro |
| `*negrito*` | aparecia em itálico | negrito, como no celular |
| Vídeos | miniatura de 72 px | tamanho de tela de celular, com play |
| Botões das perguntas | brancos no tema escuro | cinza-escuro com texto verde |
| Notas privadas | amarelas | continuam amarelas |

- Fonte editável: `visual-whatsapp.css`. Versão para colar (uma linha, com `<style>`): `visual-whatsapp.html`.
- Para mudar: editar o CSS, gerar o `.html` e trocar o valor da config `DASHBOARD_SCRIPTS`.
- Para desligar: apagar a config `DASHBOARD_SCRIPTS` no Super Admin.
- Os seletores dependem do Chatwoot 4.15. Depois de atualizar o Chatwoot, confira se o visual continua certo.
