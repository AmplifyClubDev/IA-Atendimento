# Fase 1 — Código num lugar só (auditoria de 20/11/2026)

Relatório da auditoria: "Auditoria AmplifyOS — Atendimento IA (Bia)" (Claude Docs).
Branch de trabalho: `claude/blissful-brown-nq8qug`. Nada foi publicado no Railway.

## O que já foi feito

1. **Branch de trabalho = produção da Bia.** Partiu de `fix/bia-alertas-visual-20261117`
   (o que a Bia roda hoje). Ela é a `main` + 135 commits, sem nenhum commit que a `main`
   tenha e ela não. Mesclar na `main` é um avanço direto, sem conflito.
2. **Testes da Bia num lugar só.**
   - As 11 peças de apoio que a suíte nova usava de `bia/tests/` foram para
     `bia/review_tests/apoio/`. A pasta `bia/tests/` (suíte antiga, 137 falhas) foi apagada.
   - `bia/MANIFEST.json`: registro do `lead_alerts.py` atualizado (o commit `0cf3830`
     mudou o arquivo e esqueceu o manifesto). O código do alerta não mudou.
   - Resultado: **889 testes, todos passando** (antes 880 de 883).
   - Rodar: `cd bia && uv run --python 3.12 --with-requirements requirements.txt python review_tests/run_offline.py`
3. **CI da Bia**: `.github/workflows/bia-testes.yml` roda a suíte em todo push/PR que mexe em `bia/`.
4. **Correções do Cadastro que estavam soltas** foram mescladas (sem conflito):
   - `fix/cadastro-timeout-agenciamento-20261117` — espera da conferência do @ de 30 para 35 s.
   - `fix/cadastro-retomada-anexos-20261117` — formulário guarda o progresso e mostra erro de anexo.
   - `fix/cadastro-etiqueta-acesso-chatwoot` — etiqueta de acesso no Chatwoot (traz a migration
     `cadastro/sql/010_destino_etiqueta_acesso_circle.sql`: **conferir no Supabase se já foi aplicada**).

## Branches

Já 100% contidas na produção (podem ser apagadas sem perder nada):
`chore/testes-cadastro-portateis`, `codex/fix-convite-interrompido-54457`, `codex/journey-recovery-50`,
`feat/cadastro-conferencia-agenciamento`, `feat/cadastro-email-confirmacao`, `feat/cadastro-visual-v2`,
`fix/bia-51-followup`, `fix/bia-context-ack-20261116`, `fix/bia-post-invite-next-step-20261114`,
`release/bia-40`, `release/bia-40-1`, `release/bia-40-2`, `release/bia-41` … `release/bia-48`,
`release/cadastro-base`, `review/bia-approved-reference-20261105`, `review/bia-isolated-test-router-20261104`.
As tags `bia-rNN` continuam guardando cada release.

Com trabalho que a produção NÃO tem (decidir antes de apagar):

| Branch | O que traz | Sugestão |
| --- | --- | --- |
| `fix/bia-identificacao-20261117` | Bia coleta nome e TikTok antes do agenciamento | Revisar; não está em produção |
| `review/bia-isolated-knowledge-20261106` | Interpretar respostas declaradas na etapa ativa | Revisar; não está em produção |
| `docs/governanca-times-onboarding-20261106` | Documento de governança de times | Mesclar (só documentação) |
| `review/isolated-bridges-20261104` | Ensaio isolado das pontes (04/11) | Arquivar (antigo) |

## O que falta e depende de acesso ao Railway / Supabase

Esta sessão não tem chave do Railway nem do Supabase. Falta:

1. Baixar o código que roda no **Cadastro** (incluindo o que entra pelas variáveis
   `CADASTRO_PILOT_MODULE_B64`, `CADASTRO_PONTES_BOOTSTRAP_B64`, `CADASTRO_OTP_UI_PATCH_B64`,
   `CADASTRO_IMAGE_OTP_PATCH_B64`) e nas **3 pontes do TikTok** (Pré-validação, Agenciamento,
   Partner Bridge), e colocar no repositório.
2. Depois disso, tirar o código das variáveis base64 (variáveis só com segredos).
3. Ligar cada serviço do Railway à `main`, com auto deploy e "Wait for CI".

Como decodificar uma variável base64 para conferir (no seu computador, com o Railway CLI logado):

```bash
railway variables --service Cadastro --json | python3 -c "import json,sys,base64; v=json.load(sys.stdin); open('pilot.py','wb').write(base64.b64decode(v['CADASTRO_PILOT_MODULE_B64']))"
```

## Sessão de continuação (20/11/2026) — acessos testados

Branch desta sessão: `claude/festive-rubin-aip1ug` (avanço direto da `claude/blissful-brown-nq8qug`).

- **Railway** (`https://backboard.railway.com/graphql/v2`, token injetado pelo proxy):
  a API responde, mas `me`, `projects`, `projects(workspaceId)` e `projectToken` voltam
  "Not Authorized" / "Project Token not found". `workspace(workspaceId: X)` volta
  "Workspace not found" (e não "Not Authorized"), sinal de token de **workspace**.
  Falta o **ID do projeto AmplifyOS** (está na URL do painel: `railway.com/project/<ID>`)
  para consultar `project(id: <ID>) { services ... }` e `variables(...)`.
- **Supabase**: nenhum host do Supabase está liberado na rede desta sessão
  (`*.supabase.co` e `api.supabase.com` → 403 do proxy). Sem isso não dá para conferir a
  migration 010.
- Nada foi alterado em produção.

### Segunda tentativa (20/11/2026, nova sessão)

- **Railway**: mesmo resultado. `me`, `projects`, `projectToken` → "Not Authorized" / "Project Token not found".
  Testado também `deployment(id: 384e3cec-…)` (deploy do Cadastro citado no `cadastro/README.md`) → "Not Authorized".
  O ID do projeto não aparece em nenhum arquivo do repositório. **Bloqueado até receber o ID do projeto AmplifyOS**
  (ou um token de conta/projeto).
- **Supabase**: `api.supabase.com` agora responde, mas sem chave (`401 "No access token provided"`) — o proxy
  não está injetando token. **Migration 010 continua sem conferência.**
- Nada foi alterado em produção.
- Recebido do usuário o ID `896b1a40-d8b7-4a1b-a7a0-83fda2243933`. Testado como projeto, ambiente, serviço
  (→ "Not Authorized") e workspace (→ "Workspace not found"). Conclusão: **o token do Railway injetado nesta
  sessão não tem acesso a esse projeto** (provavelmente é de outro workspace). Precisa de um token novo.

### Terceira tentativa (20/11/2026, sessão `claude/festive-rubin-aip1ug`)

Um teste de cada, como pedido:

- **Railway** — `project(id: "896b1a40-d8b7-4a1b-a7a0-83fda2243933") { name services }` → `"Not Authorized"`.
- **Supabase** — `GET https://api.supabase.com/v1/projects` → `401 "No access token provided"`.

Resultado: **a Fase 1 continua bloqueada** nas partes que dependem de produção
(baixar o código do Cadastro + as 4 variáveis `_B64`, baixar as 3 pontes, conferir a migration 010).
Nada foi alterado em produção.

O que o repositório mostra sobre isso (sem acesso):

- Nenhum arquivo do repositório lê `CADASTRO_PILOT_MODULE_B64`, `CADASTRO_PONTES_BOOTSTRAP_B64`,
  `CADASTRO_OTP_UI_PATCH_B64` ou `CADASTRO_IMAGE_OTP_PATCH_B64`. Ou seja: **o código que carrega essas
  variáveis também só existe no Railway** (provavelmente no comando de início do serviço).
- Sinal concreto de que produção ≠ repositório: o `cadastro/app/static/cadastro.html` (linhas 417–420)
  trata `status='devolvido'` com motivos `caixa_cheia` e `dominio_sem_email`, mas o servidor do
  repositório (`cadastro/app/publico.py` e `emailer.py`) **nunca devolve `reason`**. Essa parte deve vir
  do `CADASTRO_OTP_UI_PATCH_B64`.
- Também não há como saber, só pelo código, se `CADASTRO_CHATWOOT_ETIQUETA_ACESSO` está ligada.
  Se estiver ligada e a migration 010 não tiver sido aplicada, cada entrega imprime
  `[cadastro] etiqueta_chatwoot=pending` no log (`cadastro/app/chatwoot_access_label.py:96-107`).
  Esse texto no log do Cadastro é a forma mais rápida de conferir.

**Para destravar (escolha uma):**
1. Gerar um token de **conta** ou de **projeto** no Railway com acesso ao AmplifyOS e trocar o
   token da sessão; e um *Personal Access Token* do Supabase (`sbp_…`) para a conexão do Supabase.
2. Ou rodar no seu computador, com o Railway CLI logado, os comandos abaixo e mandar os arquivos
   (eles não contêm segredos; conferir antes de commitar):

```bash
railway link --project 896b1a40-d8b7-4a1b-a7a0-83fda2243933
railway variables --service Cadastro --json > /tmp/cadastro-vars.json
python3 -c "import json,base64; v=json.load(open('/tmp/cadastro-vars.json')); [open(k.lower()+'.py','wb').write(base64.b64decode(v[k])) for k in ('CADASTRO_PILOT_MODULE_B64','CADASTRO_PONTES_BOOTSTRAP_B64','CADASTRO_OTP_UI_PATCH_B64','CADASTRO_IMAGE_OTP_PATCH_B64') if k in v]"
```

   E, no SQL Editor do Supabase (só leitura):

```sql
select proname from pg_proc where proname = 'destino_etiqueta_acesso_circle_v5';
```

   Uma linha = migration 010 aplicada. Nenhuma = não aplicada.

Como a Fase 1 não avança sem acesso, a sessão seguiu para a **Fase 2 só com o código**
(ver `docs/auditoria/fase-2-caixa-3-e-formulario.md`).
