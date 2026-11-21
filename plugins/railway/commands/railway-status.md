---
description: Mostra o status dos serviços de um projeto no Railway (último deploy de cada um)
argument-hint: "[ID do projeto]"
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/railway_api.py:*)
---

Use a skill `railway`. Projeto: $ARGUMENTS (se vazio, use RAILWAY_PROJECT_ID ou tente `projects`).

Rode `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/railway_api.py project --project <ID>` e responda com
uma linha por serviço: emoji de status, nome, data do último deploy e URL, se houver.
