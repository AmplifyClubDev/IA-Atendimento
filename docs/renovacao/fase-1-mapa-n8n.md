# Renovação de contrato · Fase 1: como o n8n faz hoje (23/11/2026)

**Em 1 linha:** a lista sai de uma tabela do **Notion** ("Base de Renovação"). O n8n completa o telefone de madrugada
e, à noite, manda o template pela caixa 1. Ninguém no n8n envia o pedido de renovação no TikTok.

Lido sem alterar nada (n8n: 961 fluxos, 25 ativos).

## Fluxo 1: "Abastecimento base - Renovação de contratos" (todo dia às 6h)

1. Lê no Notion "Base de Renovação" quem vence **na próxima semana** e ainda **não tem WhatsApp**.
2. Procura o telefone pelo @ do TikTok em 3 lugares:
   - nosso Supabase (`creators`);
   - outro Supabase ("Base de dados - Amplify", tabela `criadores`);
   - o Notion (Novos Creators e Base de creators).
3. Grava no Notion `WhatsApp1` (com 9) e `WhatsApp2` (sem 9).

## Fluxo 2: "Renovação de Contratos" (a cada 30 min, das 18h às 23h30)

1. Lê no Notion quem vence **de hoje até 7 dias** e tem WhatsApp.
2. Classifica:

| Situação | Tipo | Template enviado de fato |
|---|---|---|
| Vence em 7 dias, ou "Data de 1º contato" = hoje | 7dias | `contrato_primeiro_contato` (MARKETING, vídeo) |
| Vence em 1 a 6 dias, ou "Data do FUP" = hoje | 3dias | `contrato_acompanhamento` (MARKETING, vídeo, "expira em X dias") |
| Vence hoje | hoje | **`contrato_acompanhamento` também** ⚠️ |

3. Procura ou cria o contato no Chatwoot e abre uma conversa na **caixa 1** com o template.
   O texto da mensagem fica "renovação de contrato". Aplica etiquetas.
4. Marca uma etiqueta no Notion e bloqueia o lead em "Novos Creators" (não recebe outra campanha).
5. Espera um pouco entre cada envio.

## Problemas encontrados

1. **No dia do vencimento sai o template errado.** O código pede `contrato_hoje`, que não existe. A saída "hoje" está
   ligada ao `contrato_acompanhamento` ("expira em X dias"). Os templates certos (`hoje_acompanhamento`,
   `hoje_contrato_final`) existem, aprovados, e não são usados.
2. **Templates MARKETING** são usados onde há versões UTILITY aprovadas (mais baratas e com entrega melhor).
3. **A fonte é o Notion, não o TikTok.** O banco já tem a data real de fim do contrato, atualizada de hora em hora
   (`interno.agenciados_tiktok.vigencia_fim`). Se alguém renova, o Notion não fica sabendo sozinho.
4. **Não sabe se a pessoa renovou.** Os botões "Já renovei" e "Não tenho interesse" chegam na caixa 1, mas não há
   fluxo de renovação que os trate.
5. **O pedido de renovação no TikTok não está aqui.** Os templates dizem "já enviamos a solicitação", mas nenhum
   destes fluxos envia o pedido.
6. Ainda há restos do Huggy no código (IDs de template e vídeos de outro sistema).

## Perguntas em aberto

- Quem preenche a "Base de Renovação" no Notion (datas de expiração)?
- Quem envia hoje o pedido de renovação no Partner Center?
