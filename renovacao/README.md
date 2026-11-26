# Renovação de contrato (serviço)

Serviço próprio no Railway, separado da Bia. Sem n8n. Plano: `docs/renovacao/fase-d-servico-railway.md`.

- `envio.mjs`: monta e envia o template `renovacao_contrato` pela caixa 3 (seco · teste · enviar).
- `respostas.mjs`: lê a resposta aos botões e responde (Quero renovar · Não quero renovar + motivos · Tenho dúvidas → Bia).
- `servico.mjs`: de hora em hora prepara a fila (e envia, se ligado); recebe o webhook do Chatwoot.

Tudo fica no Supabase: `renovacao_envios`, `renovacao_respostas`, `renovacao_regua`.

Chaves de segurança (variáveis do Railway): `RENOVACAO_ENVIO_LIGADO` e `RENOVACAO_RESPOSTAS_LIGADAS` só ligam com `true`.
Webhook: `POST /webhook/<RENOVACAO_WEBHOOK_SEGREDO>` (evento `message_created`). Saúde: `GET /health`.

Testes: `npm test` (Node 22, sem dependências).
