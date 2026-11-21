# Railway — estrutura do projeto AmplifyOS (21/11/2026)

**Em 1 linha:** 10 cards em 3 grupos. Os segredos ficam em **variáveis compartilhadas** do projeto; nenhum card
pega segredo de outro card, a não ser o Cadastro, que lê alguns da Bia.

## Os 10 cards

| Grupo | Card | O que faz | Limite |
|---|---|---|---|
| Atendimento | **Bia - Atendimento** | A IA da caixa 3. Recebe o webhook do Chatwoot, conversa e chama as pontes | padrão |
| Atendimento | **Cadastro** | Formulário público, código por e-mail, entrega do acesso no Circle | padrão |
| TikTok | **TikTok Pre-validacao** | Ponte logada no Partner Center: confere perfil e Shop | 4 GB / 2 vCPU |
| TikTok | **TikTok Partner Bridge** | Ponte logada: envia o convite | 4 GB / 2 vCPU |
| TikTok | **TikTok Agenciamento** | Ponte logada: confere o vínculo (Bia e formulário) | 4 GB / 2 vCPU |
| TikTok | **Consulta TikTok** | Lê dados públicos do perfil, sem login | padrão |
| Chatwoot | **Chatwoot Web** | Site do time e API que a Bia usa | padrão |
| Chatwoot | **Chatwoot Worker** | Envia mensagens do WhatsApp, webhooks e etiquetas | padrão |
| Chatwoot | **Chatwoot Postgres** | Banco do Chatwoot (conversas, contatos, etiquetas) | padrão |
| Chatwoot | **Chatwoot Redis** | Fila entre o Web e o Worker | padrão |

## Segredos compartilhados (Project › Variables › Shared)

`SLACK_BOT_TOKEN`, `SLACK_GMV_CHANNEL_ID`, `CHATWOOT_API_TOKEN`, `SMTP_USUARIO`, `SMTP_SENHA_APP`,
`DECISION_ENGINE_MODEL` (Bia) · `GMAIL_API_CLIENT_ID`, `GMAIL_API_CLIENT_SECRET`, `GMAIL_API_REFRESH_TOKEN`,
`GMAIL_SENDER` (Cadastro) · `TIKTOK_INVITE_SERVER_TOKEN` (Partner Bridge).

Para trocar um segredo: mude **só** a variável compartilhada e faça redeploy de quem usa.

## Webhooks do Chatwoot (conta 1)

- `message_created` → Bia (`/webhook/chatwoot`).
- `message_created` → serviço externo na AWS (`execute-api.us-east-1`), fora do Railway.

## O que mudou em 21/11/2026 (00:21–00:32 UTC)

1. Ponte Agenciamento reiniciada: de **11,1 GB para 1,3 GB** de RAM, continuou logada (`ready`).
2. Limite de 4 GB / 2 vCPU nas 3 pontes (antes: 24 GB / 24 vCPU, o máximo do plano).
3. 11 segredos movidos para variáveis compartilhadas (valores conferidos por hash, iguais).
4. Apagados 9 cards sem atividade desde 30/10: Back-End, Worker, Redis, Entrega de Acessos,
   Processamento de Cadastros, Aviso de Manutenção, amplify-workspace, amplify-results-cache, TikTok Catalog Collector.
   Saúde de Bia, Cadastro, Chatwoot e das 3 pontes conferida depois de cada um.

Custo estimado (CPU + RAM): de ~US$ 177/mês para ~US$ 80/mês.

## Pendências

- O código das 3 pontes não está no GitHub (só nas imagens). Para trazer: `railway login` + `railway ssh`.
- O Cadastro ainda sobe com patches em variáveis base64 (`CADASTRO_*_B64`). O código equivalente já está em
  `cadastro/app/`; falta publicar o Cadastro a partir do GitHub e apagar essas variáveis.
- Bia e Cadastro são publicados com `railway up` (sem ligação com uma branch). Ideal: ligar à `main` com "Wait for CI".

## Como publicar a Bia (sem derrubar)

A Bia usa volume: no deploy o Railway **para a versão antiga antes** de subir a nova. Se a nova falhar, a Bia fica fora.
Em 21/11, um `railway up` feito da pasta do Windows (CRLF) quebrou a checagem do formulário e a Bia ficou ~4 min fora
(rollback para `3b24b721`; nenhum lead ficou sem resposta). Por isso:

1. Exportar do Git com quebras de linha de Linux: `git -c core.autocrlf=false archive HEAD bia | tar -x -C <pasta>`.
2. Na pasta exportada: `load_mapping()` precisa passar e o `MANIFEST.json` precisa bater (sha256 de cada arquivo).
3. `railway up <pasta> --path-as-root --service "Bia - Atendimento" --detach` e acompanhar até `/healthz` = 200.
4. Rollback: `deploymentRedeploy` do último deploy bom.

## Cadastro publicado a partir do GitHub (21/11/2026, 12:42 UTC)

- Antes: imagem de 03/11 + patches em variáveis base64. Comparação arquivo por arquivo (sha256 via `railway ssh`, só
  leitura): nada em produção faltava no GitHub; a única diferença real era a etiqueta de acesso (desligada).
- Publicado com `railway up <cópia LF de cadastro/app> --path-as-root` (deploy `093a0849`). Os 4 patches respondem
  "já aplicado" e não mudam nada; o teste das pontes deu `ready=3`.
- Entrou no ar: aviso "acesso liberado" no formato do WhatsApp, 3 códigos de e-mail válidos, @ sem resultado velho,
  erro de anexo e retomada do formulário.
- Próximo passo seguro: tirar as variáveis `CADASTRO_*_B64` e o comando de início com patches (hoje não fazem nada).
