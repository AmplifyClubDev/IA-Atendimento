# Plugin Railway para o Claude Code

Deixa o Claude consultar e operar o Railway: status, deploys, logs, variáveis, redeploy e restart.

## O que vem dentro

| Arquivo | Para que serve |
| --- | --- |
| `.claude-plugin/plugin.json` | Identidade do plugin (nome, versão) |
| `skills/railway/SKILL.md` | Ensina o Claude **quando** e **como** usar o Railway |
| `scripts/railway_api.py` | Faz as chamadas à API (Python puro, nada para instalar) |
| `commands/railway-status.md` | `/railway-status` — status de cada serviço |
| `commands/railway-logs.md` | `/railway-logs <serviço>` — logs do último deploy, com resumo dos erros |
| `commands/railway-redeploy.md` | `/railway-redeploy <serviço>` — redeploy, sempre pedindo confirmação |

O catálogo que aponta para este plugin fica em `.claude-plugin/marketplace.json`, na raiz do repositório.

## Instalar (3 passos)

1. Adicione o catálogo do repositório:
   `/plugin marketplace add AmplifyClubDev/IA-Atendimento`
2. Instale o plugin:
   `/plugin install railway@amplify-plugins`
3. Defina o token (veja abaixo) e teste com `/railway-status <ID do projeto>`.

Para testar sem instalar: `claude --plugin-dir plugins/railway`.

## Token

| Variável | Tipo de token | Onde criar |
| --- | --- | --- |
| `RAILWAY_API_TOKEN` | Conta ou workspace | Railway › Account Settings › Tokens |
| `RAILWAY_TOKEN` | Projeto (um projeto + um ambiente) | Projeto › Settings › Tokens |

No Claude Code na nuvem com o Railway conectado, não precisa definir nada: o proxy da sessão
coloca o token sozinho.

Opcional: `RAILWAY_PROJECT_ID`, `RAILWAY_ENVIRONMENT_ID` e `RAILWAY_SERVICE_ID` viram o padrão
dos comandos.

## Notas do processo (para não pesquisar de novo)

- API: GraphQL em `https://backboard.railway.com/graphql/v2`, sempre `POST`.
- O Railway **valida o formato da consulta antes** de checar permissão. Então um erro
  `Not Authorized` / `not found` significa "consulta certa, falta acesso ou o ID não existe";
  já `GRAPHQL_VALIDATION_FAILED` significa "consulta escrita errado".
- Todas as consultas do script foram validadas assim em 20/11/2026.
- Não existe `workspaces` na raiz da API (é `workspace(id)`).
- Com token de workspace, `me` e `projects` dão `Not Authorized`: use `project(id: ...)` direto.
- Token de projeto usa o header `Project-Access-Token`, não `Authorization`.
- Mutations usadas: `serviceInstanceRedeploy(serviceId, environmentId)` e `deploymentRestart(id)`.
- Logs: `deploymentLogs` (execução) e `buildLogs` (build), ambos com `deploymentId`, `limit`, `filter`.
- Variáveis: `variables(projectId, environmentId, serviceId)` devolve um JSON nome → valor.
  O script mostra só os nomes, a menos que se passe `--show-values`.
