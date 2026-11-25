# Renovação de contrato · Fase D: serviço próprio no Railway (plano, 25/11/2026)

Decisão do Vitor (25/11): sem n8n. Tudo em código nosso, num serviço só de renovação no Railway ("card" próprio),
separado da Bia e do Cadastro. Começa em 26/11, depois de tudo polido e testado.

## O que roda dentro do serviço "Renovação de contrato"

| Rotina | Quando | O que faz |
|---|---|---|
| Preparar a fila | De hora em hora | `preparar_fila_renovacao_v5()`: quem vence em 7 a 1 dias entra na fila (1 vez por contrato) |
| Enviar | De hora em hora, das 9h às 20h | Template `renovacao_contrato` pela caixa 3, etiqueta "Renovacao de contrato", 8 s entre envios, marca cada envio no banco |
| Ouvir respostas | Na hora (webhook do Chatwoot, só caixa 3 com a etiqueta) | Quero renovar → pedido no Partner Center + "aceite no TikTok"; Não quero → lista de motivos → grava + alerta retenção; Tenho dúvidas → time |
| Confirmar | De hora em hora | Coleta viu o contrato estendido → `renovacao_confirmada` e tira a etiqueta de renovação |
| Etiquetas | De hora em hora | `Agenciado` em quem está vinculado; tira "Renovacao de contrato" de quem renovou, recusou ou saiu |

Tudo fica no Supabase: fila e envios (`renovacao_envios`), respostas e motivos (tabela nova), régua (`renovacao_regua`).
O Amplify OS mostra tudo (Régua de mensagens).

## Ordem (26/11 em diante)

1. Teste com um número interno (template, etiqueta, Bia não responde).
2. Serviço no Railway com envio desligado; ligar o envio com a aprovação do Vitor.
3. Respostas automáticas aos botões e motivos.
4. Pedido de renovação automático no Partner Center (ponte, Playwright): teste com 1 agenciado antes de ligar.
5. Etiqueta `Agenciado` e a Bia reconhecendo agenciados (inclusive "quero ser agenciado" → "você já é").

## Já pronto (25/11)

Régua e fila no banco, envio (`renovacao/envio.mjs`: seco, teste, enviar desligado), 2 templates aprovados na caixa 3
(Marketing), a Bia ignora a etiqueta de renovação, tela no Amplify OS.
