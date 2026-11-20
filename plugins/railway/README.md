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
- Para descobrir a quem pertence um token: `{ apiToken { workspaces { id name } } }`.
  Depois liste os projetos com `projects(workspaceId: "...")`.
- Consultas que não precisam de ID: `me`, `apiToken`, `projectToken`, `projects`.

## Instalação no Windows (o que funcionou em 20/11/2026)

1. Instalar o Git for Windows e depois o Claude Code no PowerShell:
   `irm https://claude.ai/install.ps1 | iex` (feche e abra o PowerShell depois).
2. `/plugin ...` só funciona **dentro** do Claude Code (`claude`), nunca direto no PowerShell.
3. Enquanto o plugin não está na `main`, adicione o catálogo pelo branch:
   `/plugin marketplace add https://github.com/AmplifyClubDev/IA-Atendimento.git#claude/relaxed-einstein-h7mkax`
4. `/plugin install railway@amplify-plugins`.

## Claude Code na nuvem (navegador)

- O token do Railway da sessão vem da configuração do **ambiente**, não do chat.
- Em 20/11/2026 o token ligado à sessão respondia `Not Authorized` em tudo, até em
  `apiToken`. Provável causa: token expirado, revogado ou sem permissão. A solução é
  salvar um token novo nas configurações do ambiente (variável `RAILWAY_API_TOKEN`)
  e abrir uma sessão nova.
