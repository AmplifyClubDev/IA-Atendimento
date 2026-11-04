# Bia: roteador de demonstração isolado

Estado: a revisão `46cccef` foi implantada para a abertura isolada, entregue como mensagem 318718. A continuação v2 desta revisão é um rascunho desabilitado por padrão, sem implantação ou envio. Base sanitizada: `2190b692cbdb11bd4a5e413dded904e15ff704ca`. O Railway permanece fixado em `46cccef`.

## Comportamento preparado

- Reserva a identidade do contato de teste antes da entrada no atendimento real, incluindo mensagens antigas, eventos incompletos e outras conversas da mesma identidade.
- Bloqueia respostas do fluxo real, jobs, retomadas, acompanhamentos e recuperação de tarefas para a identidade reservada. As tarefas anteriores permanecem guardadas, sem exclusão.
- Guarda o estado de demonstração em SQLite separado. Recusa o caminho ou esquema da base operacional. Confirmação de entrega e vínculo da mensagem são atômicos.
- Apresenta somente a abertura aprovada, com três escolhas. Cliques precisam responder à mensagem atual e respeitar a validade. Duplicatas, mensagens antigas e falhas não retornam ao fluxo real.
- TikTok, convites e vínculo usam simulações sem chamadas externas. Formulário removido do teste, inclusive da API de simulação. Sem a nova flag de continuação, a escolha continua aguardando revisão. A v2 propõe uma continuação com mensagens estáticas e botões; os textos estão em [revisão separada](demo-continuation-copy-review.md).
- A inicialização compartilha o escopo verificado do servidor com os formulários e provedores. Links antigos, rotas nativas e de compatibilidade, geração de links e atualização de vínculos de formulário recusam a identidade de teste antes de alterar dados ou chamar provedores. O formulário dos demais contatos permanece disponível.
- O adaptador futuro do WhatsApp permite somente a abertura aprovada para a identidade fixa. Confere destinatário, janela de atendimento e recibo; resultado incerto exige reconciliação, sem repetição automática.

O roteador e o envio real ficam desligados por padrão. Nenhum número, identificador de cliente ou segredo real foi incorporado à configuração de exemplo. Os testes usam dados sintéticos.

## Validação

Executar `bia/review_tests/run_offline.py` com Python 3.12 e Flask 3.1.2 disponíveis. O executor limpa variáveis de credenciais e bloqueia rede e subprocessos. Os testes cobrem as três escolhas, entrada antiga, duplicatas, falhas de armazenamento e envio, reinício, jobs pendentes, contatos diferentes, separação das bases, formato e destino das requisições HTTP simuladas e preservação do fluxo dos demais contatos.

As três falhas da primeira execução foram corrigidas: argumento duplicado na construção do evento de teste; exemplo de telefone fora da regra de equivalência brasileira, substituído por casos positivo e negativo válidos; e hashes desatualizados do manifesto. A revisão adicional reproduziu e corrigiu duas falhas reais do protótipo: aceitar uma base operacional em caminho inesperado e confirmação de recibo sem transação. Também foi unificada a exclusão por identidade na recuperação de consultas incertas.

Esta validação é offline. Ela não comprova uma implantação ativa, entrega atual no WhatsApp ou inexistência de operações externas já iniciadas pelo processo antigo.

A regressão de inicialização usa o bootstrap completo, bases sintéticas com formulários antigos e provedores falsos. Verifica os 18 métodos das rotas nativas e de compatibilidade, outra conversa do mesmo telefone e a equivalência brasileira do nono dígito; as tentativas recusadas não alteram nenhuma tabela. Um contato diferente mantém o envio de OTP e a atualização de vínculo iguais com o teste ligado ou desligado.

O fluxo solicitado é boas-vindas → conhecer ou agenciar → perfil → condições → convite → confirmação. A v2 implementa essa sequência apenas como demonstração com perfil de exemplo e confirmações simuladas. Dúvidas têm respostas estáticas sobre o teste; não há atendimento geral por IA, benefícios presumidos ou condições comerciais inventadas. Os textos propostos precisam de revisão antes de implantar a continuação.

## Requisitos antes do uso

1. Conferir o commit atualizado na branch isolada do repositório privado. Não alterar `main` ou o deploy atual nessa publicação.
2. Conferir novamente o artefato Railway ativo e os pontos de entrada e workers efetivamente executados. A base sanitizada difere do pacote original e precisa de configuração explícita das identidades antes de qualquer substituição.
3. Preparar a configuração privada do escopo exato e `V5_DEMO_STATE_PATH` em armazenamento persistente Railway, separado da base operacional. Não usar o INSPIRON como serviço ou armazenamento operacional.
4. Para uma ativação autorizada, interromper e drenar todas as instâncias e workers antigos, verificar trabalhos em execução e resultados incertos e manter a identidade excluída do fluxo real em todos os processos. Uma implantação gradual com processos antigos ainda ativos não fornece isolamento exclusivo.
5. Implantar primeiro com `V5_DEMO_ROUTER_ENABLED=true` e `V5_DEMO_WHATSAPP_LIVE=false`, verificar configuração, armazenamento, autenticação e bloqueios sem envio. Somente depois de aprovação de implantação e verificação da janela do WhatsApp habilitar o adaptador real e iniciar uma única abertura autenticada.
6. Revisar os textos e o commit da continuação antes de implantar. Manter a nova flag desabilitada até essa revisão e iniciar uma abertura v2 nova; a mensagem v1 anterior não deve ser reaproveitada. Conferir recibo antes de qualquer repetição. Não incluir formulário ou convites reais no teste.

Parar a demonstração mantém a identidade excluída do fluxo real. Não desligar o roteador ou reativar tarefas antigas automaticamente: isso exige inspeção das filas e restauração controlada. Os históricos e a base operacional não devem ser apagados.

## Bloqueios atuais

A abertura isolada da revisão `46cccef` está ativa. A continuação v2 desta revisão não foi implantada e precisa da revisão dos textos e de sua própria ativação controlada. Nenhuma configuração ou mensagem da versão ativa foi alterada nesta preparação.
