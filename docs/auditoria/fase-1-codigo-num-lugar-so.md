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

### Terceira sessão (20/11/2026) — Fase 1 retomada

**Resultado em 1 linha:** os acessos continuam bloqueados; o que dava para fazer só pelo código foi feito.

1. **Acessos (1 teste de cada, como combinado):**
   - Railway: `project(id: "896b1a40-d8b7-4a1b-a7a0-83fda2243933") { name services }` → **"Not Authorized"**.
   - Supabase: `GET https://api.supabase.com/v1/projects` → **401 "No access token provided"**.
   - Conclusão igual às anteriores: o token do Railway desta sessão não enxerga o projeto, e o Supabase
     não recebe chave. Nada foi alterado em produção.
2. **Busca no repositório inteiro (todas as branches e todo o histórico):**
   - `CADASTRO_PILOT_MODULE_B64`, `CADASTRO_PONTES_BOOTSTRAP_B64`, `CADASTRO_OTP_UI_PATCH_B64`,
     `CADASTRO_IMAGE_OTP_PATCH_B64`: só aparecem nesta documentação. **Nenhum código lê essas variáveis.**
     Ou seja: o Cadastro em produção roda com um comando de início que **não está no GitHub**
     (o `cadastro/app/Dockerfile` daqui só chama `cadastro_pilot:create_app()`).
   - Código das 3 pontes (Pré-validação, Agenciamento, Partner Bridge): **não existe em nenhuma branch**.
     O que existe é só o lado cliente: `cadastro/app/playwright_client.py`, `pontes.py`, `vigia_ponte.py`
     e `bridge_config.py` (este último só na branch `review/isolated-bridges-20261104`).
   - `docs/estado-do-atendimento.md:50` diz que o Cadastro foi publicado de
     `artifacts/claude-cadastro-v5-20261030/app/` com `railway up`. **Essa pasta não está no repositório.**
     Pode estar no computador de quem publicou.
3. **Migration 010** (`destino_etiqueta_acesso_circle_v5`):
   - Não deu para conferir no banco. Deixei pronta a consulta **só de leitura**
     `docs/auditoria/conferir-migration-010.sql` (cola no SQL Editor do Supabase; 0 linhas = não aplicada).
   - Risco se não estiver aplicada: **baixo**. A etiqueta só liga com a variável
     `CADASTRO_CHATWOOT_ETIQUETA_ACESSO` (`cadastro/app/chatwoot_access_label.py:10,98`). Se a função
     faltar, o erro é engolido e só aparece no log `[cadastro] etiqueta_chatwoot=pending`
     (`chatwoot_access_label.py:103-106`). A entrega do Circle não é afetada (`entrega.py:96-101`).
   - Observação: não existem migrations `008` nem `009` em nenhuma branch. Ou o número foi pulado, ou
     foram aplicadas à mão sem ir para o repositório. Vale conferir no Supabase.

**Para destravar o resto da Fase 1, preciso de UMA destas opções:**
- (A) Um token do Railway com acesso ao projeto AmplifyOS, configurado no ambiente desta sessão; **ou**
- (B) Você roda no seu computador (Railway CLI logado) e sobe os arquivos:
  `railway variables --service Cadastro --json > cadastro-vars.json` (eu tiro os segredos antes de commitar)
  e `railway ssh --service <ponte>` / download do código de cada ponte; **ou**
- (C) A pasta `artifacts/claude-cadastro-v5-20261030/` e as pastas das pontes, se estiverem no seu computador.
- Supabase: um token (Access Token do painel) liberado no ambiente, **ou** você roda o SQL acima e me manda o resultado.

**Complemento (mesma data, sessão paralela):**
- Prova concreta de que o Cadastro em produção ≠ repositório: `cadastro/app/static/cadastro.html:417-420`
  trata `status='devolvido'` com os motivos `caixa_cheia` e `dominio_sem_email`, mas o servidor do
  repositório (`cadastro/app/publico.py:230-245`, `emailer.py:48-57`) **nunca devolve `reason`**.
  Essa parte deve vir do `CADASTRO_OTP_UI_PATCH_B64`.
- Como a Fase 1 não avança sem acesso, a sessão seguiu para a **Fase 2 só com o código**
  (`docs/auditoria/fase-2-caixa-3-e-formulario.md`).
