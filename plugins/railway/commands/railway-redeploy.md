---
description: Faz redeploy de um serviço no Railway (pede confirmação antes)
argument-hint: "<serviço>"
---

Use a skill `railway`. Serviço: $ARGUMENTS

1. Descubra projeto, ambiente e serviço com `project`.
2. Mostre ao usuário qual serviço e ambiente serão reiniciados e **peça confirmação**.
3. Só depois do "sim", rode `redeploy --service <ID> --env <ID> --yes`.
4. Acompanhe com `deploys --limit 1` até sair de BUILDING/DEPLOYING e informe o resultado.
