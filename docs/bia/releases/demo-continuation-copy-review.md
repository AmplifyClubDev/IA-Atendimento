# Continuação simples da Bia: textos para revisão

Este é um rascunho em branch isolada. Não foi implantado e nenhuma mensagem desta continuação foi enviada. A abertura que já chegou ao contato pertence à versão anterior, fixada no Railway no commit 46cccef.

O formulário fica fora desta experiência. Perfil, condições, convite e vínculo são demonstrações; não consultam TikTok, não geram cadastro e não representam aceite comercial. Não há benefícios, comissões, prazos ou exclusividade presumidos. A identidade da Amplify usada em Conhecer é a mesma da abertura aprovada pelo usuário.

## Fluxo

Abertura → Conhecer / Quero fazer parte / Já sou Amplify. Conhecer oferece seguir para o agenciamento; entrar usa perfil de exemplo → condições simuladas → convite simulado → confirmação simulada. Já sou Amplify oferece ajuda e entrada no roteiro. Perguntas levam a respostas estáticas de demonstração, sem IA ou consulta externa. Não é um atendimento aberto de perguntas gerais.

## Mensagens propostas

### about

Somos a *Amplify*, uma agência de creators do TikTok Shop 💜

Quer seguir com o seu agenciamento?

Botões: Quero me agenciar | Tenho uma dúvida | Voltar ao início

### profile

Vamos nessa! 💜

Neste teste, vamos usar um perfil de exemplo para conhecer as próximas etapas.

Botões: Usar perfil de teste | Tenho uma dúvida | Voltar ao início

### member

Que bom te ver por aqui de novo! 💜

Como posso te ajudar? Neste teste, não vou consultar seu cadastro.

Botões: Tenho uma dúvida | Ver o agenciamento | Voltar ao início

### conditions

Antes de um convite real, você precisa conhecer e confirmar as condições 💜

Aqui vamos simular essa etapa, sem aceitar condições comerciais.

Botões: Seguir no teste | Tenho uma dúvida | Voltar ao início

### invite

Convite de demonstração preparado 💜

Quer simular o aceite para ver como a confirmação aparece?

Botões: Simular aceite | Agora não | Tenho uma dúvida

### confirmed

Teste concluído! 💜

O aceite e o vínculo foram simulados. Seu perfil real não foi consultado nem agenciado.

Botões: Recomeçar teste | Tenho uma dúvida | Encerrar teste

### paused

Tudo bem 😊

O convite de teste ficou pausado. Quer retomar ou voltar ao início?

Botões: Retomar teste | Voltar ao início | Encerrar teste

### faq

Claro! 💜 Sobre o que você quer saber?

Botões: Como funciona? | Quais condições? | Sobre o convite

### faq_agency

Você pode conhecer a Amplify e tirar suas dúvidas antes de decidir se quer seguir 💜

Aqui mostramos as etapas com perfil e vínculo de exemplo.

Botões: Quero me agenciar | Quais condições? | Voltar ao início

### faq_terms

As condições reais ainda precisam ser confirmadas 💜

Nesta demonstração, nenhuma comissão, prazo ou exclusividade é aceita.

Botões: Seguir no teste | Sobre o convite | Voltar ao início

### faq_invite

Aqui, nenhum convite real é enviado 😊

O botão serve para você experimentar como seria o aceite e a confirmação.

Botões: Seguir no teste | Quais condições? | Voltar ao início

### closed

Teste encerrado 💜

Se quiser começar de novo, é só tocar abaixo.

Botões: Recomeçar teste

## Controle e ativação futura

V5_DEMO_CONTINUATION_ENABLED permanece false por padrão e não foi configurada no Railway. A nova versão v2 exige esse opt-in, usa botões e identificadores de mensagem próprios e só avança em respostas correlacionadas à mensagem atual. Perguntas livres recentes podem abrir uma resposta estática, mas nunca avançam para convite ou confirmação. Textos de perfis recebidos não são persistidos; ficam apenas no hash de deduplicação.

Reserva de envio e resultado incerto são persistidos antes da saída. Duplicatas não repetem mensagens. Uma saída incerta bloqueia novas etapas até reconciliação. Parada administrativa mantém o contato excluído; reconciliação não reativa uma sessão parada.

Antes de futura implantação, revisar estes textos e o commit, manter os bloqueios de produção já ativos e configurar a nova flag somente na versão revisada. É necessário iniciar uma nova abertura v2 com request_id novo; a mensagem v1 já entregue não é reinterpretada automaticamente. Esta preparação não altera a fonte fixada no Railway, variáveis, segurança ou serviços.
