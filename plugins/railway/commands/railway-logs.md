---
description: Lê os logs do último deploy de um serviço no Railway e resume os erros
argument-hint: "<serviço> [texto para filtrar]"
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/railway_api.py:*)
---

Use a skill `railway`. Pedido: $ARGUMENTS

1. Descubra o projeto e o serviço (por nome) com `project`.
2. Pegue o último deploy com `deploys --limit 1`.
3. Leia `logs --deployment <ID> --limit 200` (e `--build` se o deploy falhou no build).
4. Responda em passos curtos: o que está acontecendo, as linhas de erro com horário e o próximo passo sugerido.
