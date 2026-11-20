---
name: railway
description: Consultar e operar serviços no Railway — status de projetos e serviços, últimos deploys, logs de execução e de build, nomes de variáveis, redeploy e restart. Use quando o usuário falar de Railway, deploy, "está no ar?", logs de produção, variáveis de ambiente do Railway, ou dos serviços "Atendimento V5 - Ensaio" (Bia) e "Cadastro".
---

# Railway

Tudo passa pelo script `${CLAUDE_PLUGIN_ROOT}/scripts/railway_api.py` (Python, sem dependências).
Rode `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/railway_api.py --help` para ver os comandos.

## Passo a passo

1. **Descobrir IDs.** Comece por `projects`. Se der `Not Authorized`, o token é de workspace ou de
   projeto e não lista tudo: peça o ID do projeto ao usuário (Railway › projeto › Settings) e use
   `project --project ID`. Ele devolve ambientes, serviços e o último deploy de cada serviço.
2. **Ver deploys.** `deploys --project P --service S --env E --limit 5` mostra status, data e commit.
3. **Ler logs.** `logs --deployment D` (execução) ou `logs --deployment D --build` (build).
   Use `--filter "texto"` para buscar e `--limit` para mais linhas.
4. **Variáveis.** `vars --project P --env E --service S` mostra só os **nomes** e o tamanho.
   Só use `--show-values` se o usuário pedir explicitamente, e nunca cole segredos em commits,
   PRs ou mensagens para serviços externos.
5. **Ações que mudam produção** (`redeploy`, `restart`): explique o que vai acontecer, peça
   confirmação ao usuário e só então rode com `--yes`.
6. **Qualquer outra coisa:** `query 'GRAPHQL' '{"vars": ...}'` envia uma consulta crua à API
   (`https://backboard.railway.com/graphql/v2`).

## Token

- `RAILWAY_API_TOKEN` → token de conta/workspace (Authorization: Bearer).
- `RAILWAY_TOKEN` → token de projeto (Project-Access-Token).
- Nenhum definido → o script manda `Bearer dummy`; no Claude Code na nuvem o proxy da sessão
  troca pelo token real conectado.

IDs padrão podem ficar em `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_ID`, `RAILWAY_SERVICE_ID`.

## Como responder

O usuário prefere explicações curtas e em passos numerados. Ao mostrar resultados:
status em uma linha por serviço (✅ SUCCESS, ❌ FAILED/CRASHED, ⏳ BUILDING/DEPLOYING),
e para logs, destaque só as linhas de erro relevantes com o horário.
