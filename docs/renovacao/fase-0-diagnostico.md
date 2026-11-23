# Caixa 1 — agenciados e renovação de contrato · Fase 0: diagnóstico (23/11/2026)

**Em 1 linha:** o banco já sabe quando cada contrato vence. A caixa 1 já tem número e templates de renovação aprovados.
Mas ela **está em uso** (n8n), então o novo sistema precisa substituir o fluxo atual, não rodar em paralelo.

Tudo abaixo foi lido sem alterar nada.

## 1. Data de fim do contrato: já temos

A Bia lê a lista do Partner Center de hora em hora (ponte Agenciamento).
A data de fim de cada contrato fica em `interno.agenciados_tiktok.vigencia_fim`.

| Dado | Valor |
|---|---|
| Agenciados ativos | 1.536 (todos com data de fim) |
| Vencem nos próximos 7 dias | 62 |
| Vencem nos próximos 30 dias | 223 |
| Duração mais comum | 61 dias (462 pessoas) e cerca de 425 dias (~890) |
| Picos de vencimento | dez/26 (159), jan/27 (265), mai/27 (178) |

O que **ainda não** temos:
- O telefone de cada agenciado. A ligação é pelo @ e pelos cadastros e contatos do banco; isso ainda precisa ser conferido.
- Saber se a pessoa **aceitou** a renovação. Isso aparece quando a `vigencia_fim` muda na próxima coleta.
- O **envio** do pedido de renovação no TikTok, que seria uma ação nova numa ponte (Playwright).

## 2. Caixa 1 no Chatwoot

| Caixa | Nome | Número | Uso hoje |
|---|---|---|---|
| 1 | Amplify WhatsApp | final 1046 (GREEN) | **Ativa**: 44.148 conversas; envios de "renovação de contrato" em 22/11 21:32 |
| 3 | Amplify - Aquisição | final 4456 (GREEN) | Bia |
| 4 | (pessoal) | — | Fora do escopo |

As caixas 1 e 3 são contas WhatsApp (WABA) **diferentes**. Templates de uma não servem na outra.

## 3. Templates de contrato já aprovados na caixa 1

| Template | Tipo | Quando | Botões |
|---|---|---|---|
| `primeiro_contato_contrato` | UTILITY, com vídeo | Semana do vencimento | Já renovei! · Não tenho interesse! |
| `contrato_primeiro_contato` | MARKETING, com vídeo | Mesma ideia, outra versão | Já renovei · Não tenho interesse |
| `contrato_acompanhamento` | MARKETING, com vídeo | "Expira em {{1}} dias" | Já renovei · Não tenho interesse |
| `hoje_acompanhamento` | UTILITY, com vídeo | No dia (com passo a passo) | Já renovei · Não tenho interesse |
| `hoje_contrato_final` | UTILITY, com vídeo | No dia (curto) | Já renovei! · Não tenho interesse! |

Também há templates de convite, vínculo e desvinculação (`aceite_o_convite`, `convite_enviado`, `desvincular`…).
UTILITY é mais barato e entrega melhor que MARKETING.

## 4. Riscos

- **Envio em dobro:** se o n8n continuar mandando, a pessoa recebe duas vezes. É preciso desligar a parte do n8n
  que vai ser substituída, no dia da troca.
- **Responder pelo n8n e pela IA ao mesmo tempo:** só um pode atender a caixa 1.
- **Texto do template "já enviamos a renovação":** só pode sair depois que o pedido foi mesmo enviado no TikTok.

## 5. Proposta de fases (a confirmar)

1. **Mapa do n8n:** o que ele faz hoje na caixa 1 (precisa do acesso ou da exportação dos fluxos).
2. **Régua de renovação:** semana do vencimento, no dia e depois do aceite. Lida do banco, com registro de quem
   recebeu o quê (sem duplicar). Só com o seu número primeiro.
3. **Respostas na caixa 1:** "Já renovei" (conferir na coleta), "Não tenho interesse" (alerta pro time), dúvidas (IA).
4. **Boas-vindas, acesso ao Circle e alertas** para agenciados, com as mesmas regras da Bia.
5. **Pedido de renovação no TikTok** por Playwright (se hoje é manual).
