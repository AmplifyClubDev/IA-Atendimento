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
