# Renovação de contrato · Fase B: régua no banco, sem envio (25/11/2026)

Tarefa da reunião "Implementar Renovação" (prazo 26/11, 9h30). Decisão do Vitor: **primeiro só preparar**; o envio
só liga depois da aprovação final.

## O que existe agora

| Peça | O que faz |
|---|---|
| `public.renovacao_regua` | Quem deve receber qual mensagem **hoje** e, quando não pode, o motivo |
| `interno.renovacao_envios` | A fila. Uma linha por contrato e etapa (trava: nunca repete). Situação: previsto → enviado / falhou / cancelado |
| `public.preparar_fila_renovacao_v5()` | Copia a régua de hoje para a fila como "previsto" e cancela quem renovou ou pediu para sair. **Não envia** |
| `public.renovacao_fila` | A fila com o estado de renovação de agora |
| Amplify OS › Régua de mensagens | Podem receber · Segurados (com motivo) · Fila |

## Régua

| Etapa | Quando | Template aprovado (caixa 1) |
|---|---|---|
| 7 dias antes | faltam 5 a 7 dias | `primeiro_contato_contrato` (UTILITY, vídeo) |
| Lembrete | faltam 1 a 3 dias | `contrato_acompanhamento` (MARKETING, vídeo, {{1}} = dias) — único aprovado com dias |
| No dia | vence hoje | `hoje_acompanhamento` (UTILITY, vídeo) |
| Renovou | — | **falta template** (não há aprovado) |

Todos com os botões "Já renovei / Não tenho interesse".

**Melhor que o n8n:** só entra quem tem o pedido de renovação **aguardando aceite** no TikTok (o template diz
"já enviamos a solicitação"). Fica de fora, com motivo: sem telefone, TikTok ainda não enviou o pedido, pedido não aceito
(time decide), pediu para sair, já renovou.

## Hoje (25/11)

33 podem receber (15 de 7 dias, 16 lembretes, 2 no dia) e já estão na fila como "previsto". Segurados: 8 sem telefone,
4 sem pedido do TikTok, 4 com pedido não aceito, 2 pediram para sair.

## Falta para ligar o envio (fase D)

1. Vídeo do cabeçalho dos templates (o link que o n8n usa).
2. Envio pela caixa 1 do Chatwoot (template + etiquetas), só das 9h às 20h, com espera entre envios.
3. Teste só com o número do Vitor.
4. Desligar o n8n de renovação no mesmo momento em que ligar o novo (não pode mandar em dobro).

## Envio pronto, desligado (25/11/2026, noite)

`renovacao/envio.mjs` (Node 22, sem dependências) + `bia/sql/renovacao_envio.sql` (`marcar_envio_renovacao_v5`).

| Modo | O que faz |
|---|---|
| `node envio.mjs seco` | Mostra o que sairia da fila. Não envia. Rodado em 25/11: 33 mensagens, todas com telefone válido e template certo |
| `node envio.mjs teste <telefone> [etapa]` | Manda 1 de cada etapa só para esse número. Não mexe na fila |
| `node envio.mjs enviar` | Manda a fila "previsto". Só roda com `RENOVACAO_ENVIO_LIGADO=true` e das 9h às 20h |

Como o n8n faz (visto no Chatwoot, conversa 61344): cria a conversa na **caixa 1** com o template e o texto
"renovação de contrato", e etiqueta **"Renovacao de contrato"**. O envio novo faz igual (Chatwoot 4.15.1,
`template_params` com vídeo no cabeçalho), acha ou cria o contato pelo telefone e espera 8 s entre envios.
Cada envio é marcado na fila: enviado (com o nº da conversa), falhou (com o motivo) ou cancelado.

Falta: o **link fixo do vídeo** de cada template (`RENOVACAO_VIDEO_SEMANA`, `_LEMBRETE`, `_HOJE`; os do exemplo da Meta
expiram) e o **teste com o número do Vitor**. Depois: onde roda de hora em hora (serviço pequeno no Railway) e desligar o n8n.
