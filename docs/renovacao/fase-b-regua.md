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

## Régua nova (25/11/2026, decisão do Vitor) — substitui a de cima

Sem n8n e sem os templates antigos. A caixa 1 vira o canal dos agenciados; a 1ª função é renovação.

1. Faltam de **7 a 1 dias**: **uma** mensagem perguntando se a pessoa quer renovar (botões Quero renovar · Tenho dúvidas ·
   Não quero renovar).
2. "Quero renovar" → a ponte envia o pedido de renovação no Partner Center (Playwright) → resposta "aceite no TikTok"
   (na janela de 24 h, sem template).
3. A coleta vê o contrato estendido → confirmação.

**Tipos de contrato** (medido em 25/11 em convites, histórico e ativos): o 1º contrato é de **2 meses** (todo convite
propõe 61 dias) e a renovação estende **1 ano**. Ativos: 497 no 1º contrato, 1.049 renovados 1 vez, 11 renovados 2 vezes,
10 com 1 ano direto, 14 com datas quebradas. Template pelo tipo: contrato atual ≤ 90 dias → `renovacao_primeiro_contrato`;
senão → `renovacao_contrato_anual`. Parâmetros: {{1}} primeiro nome, {{2}} data do fim (dd/mm).

`bia/sql/renovacao_regua_v2.sql`: régua nova, `interno.primeiro_nome` (pula títulos e palavras de loja), fila antiga
cancelada (33 previstos, nada tinha sido enviado). `renovacao/envio.mjs` ajustado para os 2 templates (vídeo opcional).
Hoje: 44 podem receber (todos 1º contrato); segurados: 8 sem telefone, 6 sem pedidos restantes no TikTok, 2 pediram para
sair, 2 vencem hoje. A fila só é preparada quando os templates forem aprovados.

Atenção ao nome: quem não passou pela Bia só tem o nome do TikTok, às vezes nome de loja ("Ofertas", "Baratinho").

## Templates finais (25/11/2026, decisão do Vitor)

- `renovacao_contrato` (Utilidade): o alerta, para os dois tipos de contrato, sem nome. {{1}} = data do fim (dd/mm).
  Cabeçalho de texto "Renovação do seu contrato Amplify", 3 passos, botões Quero renovar · Não quero renovar · Tenho dúvidas.
- `renovacao_confirmada` (Utilidade): {{1}} = nova data do fim. Sai quando a coleta vê o contrato estendido,
  mesmo depois de fechada a janela de 24 h.
- O resto (resposta a cada botão, lista de motivos, agradecimento) sai dentro da conversa, sem template.

`bia/sql/renovacao_regua_v3.sql`: régua com o template único (44 podem receber em 25/11, todas as mensagens montadas
e com telefone válido). `renovacao/envio.mjs`: template único, 1 variável.
