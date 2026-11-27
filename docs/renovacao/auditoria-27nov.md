# Auditoria da renovação e da base (27/11/2026)

Pedida pelo Vitor. Revisão do código por um revisor independente + conferência do que está no ar.

## Saudável ✅
- Coleta do Partner Center: 24 coletas nas últimas 24 h, todas completas. Conferência: TikTok 1.551 × banco 1.546
  (os 5 que o TikTok não lista), desvinculando 44 × 44, convites 83 × 83. Histórico diário em dia.
- Pontes: Agenciamento, Pré-validação e Partner Bridge online, sem pedido de login. Bia pronta (3 pontes confirmadas).
- Cadastro no ar. Serviço de renovação: 21 rodadas sem erro, envio desligado.

## Problemas encontrados
1. **Grave — o serviço respondia conversas antigas do n8n.** A caixa 3 tem 1.000+ conversas abertas com a etiqueta
   "Renovacao de contrato" (de outubro até ontem, 26/11 21:33: **o fluxo de renovação do n8n continua enviando pela
   caixa 3**). O serviço respondia qualquer conversa com essa etiqueta. Aconteceu 1 vez (conversa 54162, número final
   7161, agenciado com contrato até 22/10/2027): ele escreveu "quero fazer parte" (mensagem de anúncio), a Bia dos
   agenciados respondeu, ele tocou "Não quero renovar" e escolheu "Seguir sem agência". **Ação imediata: respostas
   desligadas** (`RENOVACAO_RESPOSTAS_LIGADAS=false`, 27/11 ~10:55 UTC).
2. **Fila com contratos vencidos:** a fila não cancelava contrato que venceu sem renovar; ao ligar o envio, sairia
   mensagem com data passada.
3. **Envio em dobro possível:** duas rodadas ao mesmo tempo; horário conferido só no início; se "marcar enviado"
   falhasse, reenviaria.
4. **Motivo perdido:** quando a IA entendia "não quero" e mostrava a lista, o motivo escolhido não era gravado.
5. **Classificação ansiosa:** "renovar como?" virava "quero renovar".
6. **Falha sem aviso:** erro no meio da resposta deixava a pessoa sem resposta e ninguém sabia.
7. **Dados para a IA:** um CPF digitado pela pessoa iria para a IA. Sem limite de uso da IA por conversa.

## Correções (commit `2775600`, testadas, **não publicadas** — aguardam aprovação)
- Banco (`bia/sql/renovacao_auditoria_27nov.sql`): fila cancela vencido/renovado/saiu/sumiu; respostas só são
  registradas em conversas que o serviço enviou ou de números de teste (as do n8n ficam de fora).
- Serviço: reconfere cada mensagem antes de enviar (data, renovação, horário), 1 rodada de envio por vez, marca
  "enviado" com 3 tentativas; classificação só com resposta exata (o resto vai para a IA); motivo da lista sempre
  gravado; quem já renovou recebe "já está confirmada"; falha avisa o time (etiqueta + nota); CPF mascarado; até 15
  respostas da IA por conversa por dia; fila do webhook limitada; etiqueta comparada sem acento/maiúscula.
- 27 testes passando.

## Pendências (decisão do Vitor)
- Aplicar o SQL, publicar o serviço e religar as respostas.
- **Desligar o fluxo de renovação do n8n** na mesma hora em que o envio novo for ligado (senão a pessoa recebe 2 mensagens).
- Conferir a conversa 54162 (resposta real de "não quero renovar" gerada nesse cenário).
- Ainda abertos (menores): etiqueta é lida-e-trocada (corrida rara com outra mudança na mesma conversa); a etiqueta de
  renovação nunca sai (entra na fase E).
