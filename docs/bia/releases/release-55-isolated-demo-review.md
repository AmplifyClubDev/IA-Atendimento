# Bia: roteador de demonstração isolado

Estado: código preparado para revisão, sem publicação, implantação ou envio. Base local sanitizada: `2190b692cbdb11bd4a5e413dded904e15ff704ca`. O código de produção continua sendo o artefato Railway anterior.

## Comportamento preparado

- Reserva a identidade do contato de teste antes da entrada no atendimento real, incluindo mensagens antigas, eventos incompletos e outras conversas da mesma identidade.
- Bloqueia respostas do fluxo real, jobs, retomadas, acompanhamentos e recuperação de tarefas para a identidade reservada. As tarefas anteriores permanecem guardadas, sem exclusão.
- Guarda o estado de demonstração em SQLite separado. Recusa o caminho ou esquema da base operacional. Confirmação de entrega e vínculo da mensagem são atômicos.
- Apresenta somente a abertura aprovada, com três escolhas. Cliques precisam responder à mensagem atual e respeitar a validade. Duplicatas, mensagens antigas e falhas não retornam ao fluxo real.
- TikTok, formulário e convites usam simulações sem chamadas externas. A escolha fica aguardando revisão; não há segunda mensagem automática ainda.
- O adaptador futuro do WhatsApp permite somente a abertura aprovada para a identidade fixa. Confere destinatário, janela de atendimento e recibo; resultado incerto exige reconciliação, sem repetição automática.

O roteador e o envio real ficam desligados por padrão. Nenhum número, identificador de cliente ou segredo real foi incorporado à configuração de exemplo. Os testes usam dados sintéticos.

## Validação

Executar `bia/review_tests/run_offline.py` com Python 3.12 e Flask 3.1.2 disponíveis. O executor limpa variáveis de credenciais e bloqueia rede e subprocessos. Os testes cobrem as três escolhas, entrada antiga, duplicatas, falhas de armazenamento e envio, reinício, jobs pendentes, contatos diferentes, separação das bases, formato e destino das requisições HTTP simuladas e preservação do fluxo dos demais contatos.

As três falhas da primeira execução foram corrigidas: argumento duplicado na construção do evento de teste; exemplo de telefone fora da regra de equivalência brasileira, substituído por casos positivo e negativo válidos; e hashes desatualizados do manifesto. A revisão adicional reproduziu e corrigiu duas falhas reais do protótipo: aceitar uma base operacional em caminho inesperado e confirmação de recibo sem transação. Também foi unificada a exclusão por identidade na recuperação de consultas incertas.

Esta validação é offline. Ela não comprova uma implantação ativa, entrega atual no WhatsApp ou inexistência de operações externas já iniciadas pelo processo antigo.

## Requisitos antes do uso

1. Revisar e autorizar a publicação do conteúdo sanitizado e deste patch na branch isolada do repositório privado. Não alterar `main` ou o deploy atual nessa publicação.
2. Conferir novamente o artefato Railway ativo e os pontos de entrada e workers efetivamente executados. A base sanitizada difere do pacote original e precisa de configuração explícita das identidades antes de qualquer substituição.
3. Preparar a configuração privada do escopo exato e `V5_DEMO_STATE_PATH` em armazenamento persistente Railway, separado da base operacional. Não usar o INSPIRON como serviço ou armazenamento operacional.
4. Para uma ativação autorizada, interromper e drenar todas as instâncias e workers antigos, verificar trabalhos em execução e resultados incertos e manter a identidade excluída do fluxo real em todos os processos. Uma implantação gradual com processos antigos ainda ativos não fornece isolamento exclusivo.
5. Implantar primeiro com `V5_DEMO_ROUTER_ENABLED=true` e `V5_DEMO_WHATSAPP_LIVE=false`, verificar configuração, armazenamento, autenticação e bloqueios sem envio. Somente depois de aprovação de implantação e verificação da janela do WhatsApp habilitar o adaptador real e iniciar uma única abertura autenticada.
6. Conferir recibo antes de qualquer repetição. Validar cada clique sem convites ou acompanhamentos reais. As próximas mensagens e um eventual link de formulário de teste precisam ser revisados separadamente.

Parar a demonstração mantém a identidade excluída do fluxo real. Não desligar o roteador ou reativar tarefas antigas automaticamente: isso exige inspeção das filas e restauração controlada. Os históricos e a base operacional não devem ser apagados.

## Bloqueios atuais

O código ainda é local e não foi implantado. A publicação anterior do pacote sanitizado foi recusada pela revisão automática por exigir autorização explícita para enviar aquele conteúdo ao repositório indicado; não houve nova tentativa. Não há link de formulário de teste validado, nem aprovação da sequência posterior à abertura. A ativação operacional ainda exige as verificações acima; nenhum teste ao vivo foi iniciado nesta etapa.
