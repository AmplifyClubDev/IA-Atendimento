# Cadastro — o que roda em produção (retrato de 20/11/2026)

**Resumo:** o Cadastro no ar é uma imagem antiga (versão de 03/11), publicada com `railway up`,
e corrigida na hora de subir por 3 patches que vêm de variáveis base64.
Esta pasta guarda esses patches decodificados e os arquivos **como ficam depois dos patches**.
Fonte: API do Railway (projeto AmplifyOS, serviço `Cadastro`, deploy `9e943414…` de 19/11/2026), só leitura.

**Esta pasta é um retrato. Ela não é publicada.** O serviço continua rodando a imagem dele.

## Como o serviço sobe (comando de início, em ordem)

1. Executa `CADASTRO_IMAGE_OTP_PATCH_B64` → [`patches/image_otp_v1.py`](patches/image_otp_v1.py).
   Altera `/app/publico.py` (imagens grandes) e `/app/store.py` (tentativas do código de e-mail).
2. Executa `CADASTRO_OTP_UI_PATCH_B64` → [`patches/otp_ui_v1.py`](patches/otp_ui_v1.py).
   Altera `/app/static/cadastro.html` (mensagem de "código incorreto").
3. Executa `CADASTRO_PONTES_BOOTSTRAP_B64` (gzip) → [`patches/pontes_bootstrap.py`](patches/pontes_bootstrap.py).
   Troca `/app/pontes.py` inteiro pela versão em [`efetivo/pontes.py`](efetivo/pontes.py),
   faz um teste rápido das pontes e inicia
   `gunicorn --bind 0.0.0.0:3000 --workers 1 --threads 16 --timeout 90 'cadastro_pilot:create_app()'`.
   (No arquivo daqui, o texto base64 foi trocado pelo nome do arquivo e pelo sha256.)

Log do deploy de 19/11, 13:08 UTC: os 3 patches aplicaram e o teste das pontes deu `status=200 ready=3`.

Variáveis com código que **não são usadas** pelo comando de início:
- `CADASTRO_PILOT_MODULE_B64`: é o `cadastro_pilot.py` do commit `769257f` (03/11). Sobrou de um deploy antigo.
- `CADASTRO_SAFE_IMAGE_PATCH_B64` → [`patches/safe_image_v1_NAO_USADO.py`](patches/safe_image_v1_NAO_USADO.py).
  A mesma mudança já está dentro do `image_otp_v1`.

## Produção × `cadastro/app/` (repositório)

| Arquivo | Base da imagem | Produção (após patch) × repositório |
| --- | --- | --- |
| `publico.py` | igual ao repositório | Produção aceita JPG até 40 MP (reduz antes de abrir). Repositório recusa acima de 20 MP. |
| `store.py` | commit `dd947e1` = repositório | Produção **zera as tentativas a cada novo código**. Repositório herda as tentativas do código anterior. |
| `static/cadastro.html` | commit `dd947e1` (03/11) | Produção tem a correção da mensagem "código incorreto". Repositório tem a de anexos (17/11) e a de 20/11, que **não estão no ar**. |
| `pontes.py` | commit `769257f` = repositório | Produção tem 461 linhas (sessão compartilhada, espera por `Retry-After`, sem reinício automático). Repositório tem 249. |
| demais arquivos | **não vistos** | Ficam dentro da imagem. Precisam de `railway ssh` com login de conta. |

## As 3 pontes do TikTok

`TikTok Pre-validacao`, `TikTok Agenciamento` e `TikTok Partner Bridge` foram publicadas em 30/10/2026
com `railway up`, sem repositório e sem comando de início próprio. **O código não está em variáveis**:
só existe dentro das imagens. Variáveis (só nomes):

- Pré-validação e Agenciamento: `BRIDGE_ROLE`, `BRIDGE_CONSOLE_TOKEN`, `TIKTOK_PARTNER_URL`, `TIKTOK_INVITE_SERVER_TOKEN`.
- Partner Bridge: as mesmas mais `TIKTOK_HEADLESS`, `TIKTOK_INVITE_SERVER_HOST`, `TIKTOK_WARM_SERVER_PORT`,
  `BRIDGE_UI_INVITE_ENABLED`, `TIKTOK_PLAYWRIGHT_PROFILE_DIR`, `PORT`.

## Variáveis do Cadastro (só nomes, 56)

Segredos e chaves: `CHATWOOT_API_TOKEN`, `CIRCLE_ADMIN_TOKEN`, `GMAIL_API_CLIENT_SECRET`, `GMAIL_API_REFRESH_TOKEN`,
`OPENAI_API_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_V5_SERVICE_KEY`, `SMTP_SENHA_APP`, `PONTES_LINK_SEGREDO`,
`PONTES_TELEGRAM_BOT_TOKEN`, `PONTE_*_TOKEN`, `V5_TIKTOK_AGENCY_TOKEN`, `CADASTRO_INVITATION_SECRET`, `ONBOARDING_FORM_SECRET`.

Chaves de liga/desliga e configuração: `CADASTRO_*_ATIVO/ATIVA/ATIVOS`, `CADASTRO_V5_PILOT_ENABLED`,
`CADASTRO_EMAIL_TRANSPORT`, `CADASTRO_STATE_PATH`, `CADASTRO_PUBLICO_PORTAL_ID`, `CADASTRO_*_ALLOWLIST`,
`CADASTRO_ENSAIO_ONBOARDING_IDS`, `GMAIL_SENDER`, `GMAIL_API_CLIENT_ID`, `SMTP_*`, `CHATWOOT_*`, `SUPABASE_URL`,
`SUPABASE_V5_URL`, `ONBOARDING_PUBLIC_URL`, `ALERTA_EMAIL`, `GMV_PRINT_MODEL`, `PONTES_TELEGRAM_*`, `PORT`.

Não existe `CADASTRO_CHATWOOT_ETIQUETA_ACESSO`. Ou seja: a etiqueta de acesso no Chatwoot está desligada.
