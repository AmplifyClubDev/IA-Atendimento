# Fase E: "Já sou Amplify" e controle do chat (desenho, 26/11/2026)

Pedido do Vitor (26/11). Mantém toda a lógica da renovação; amplia o atendimento para quem já é da Amplify.

## 1. "Já sou Amplify" (caixa 3)

1. No menu da Bia entra a opção **Já sou Amplify**. Quem escolhe sai do roteiro de aquisição e passa para a
   **Bia dos agenciados** (serviço de renovação), com a etiqueta `Agenciado` (a Bia de aquisição não entra).
2. A Bia pede o **@ do TikTok** e confirma: "Seu perfil é este: @fulano, agenciado desde dd/mm, contrato até dd/mm?".
3. **Segurança:** pede os **4 últimos dígitos do CPF** e confere no banco (a conferência é feita no banco; o CPF nunca
   vai para a conversa nem para a IA). Até 3 tentativas; depois, passa para o time.
4. **Sem CPF no banco** (não preencheu o formulário): recebe de novo o **link do formulário**, com a validação de hoje
   (foto, perfil, e-mail). Depois de preencher, da próxima vez segue normal.
5. **Confirmado:** a Bia mostra a situação do perfil (contrato, categoria, GMV, pedido de renovação) e oferece a
   renovação com os botões **Quero renovar · Não quero renovar** (mesmo fluxo da régua, inclusive motivos).

## 2. Follow-up (FUP)

Quem recebeu o alerta e **não renovou nem disse que não quer**: **1 FUP no dia seguinte** (template `renovacao_contrato`
de novo, 24 h depois). Sem resposta de novo: fica só no banco e no Amplify OS.

## 3. Limpar a caixa

Conversa parada há **24 h**: o serviço **resolve** a conversa (sai da lista de abertas). Etiquetas e histórico ficam;
se a pessoa voltar, reabre sozinha. Nenhuma mensagem é apagada.

## 4. Controle do chat pelo time

- Alguém do time **se atribui** à conversa no Chatwoot → a Bia dos agenciados e o serviço **param de responder**.
- **Resolver** a conversa encerra o fluxo (o FUP não sai para quem foi resolvido pelo time).
- Depois: botões no Amplify OS (assumir, devolver para a Bia, encerrar).

## Ordem sugerida

1. Controle do chat (atribuído = silêncio) e limpar a caixa (resolver em 24 h). Só no serviço.
2. FUP do dia seguinte. Serviço + banco.
3. "Já sou Amplify": conferência do CPF no banco (função que responde só sim/não), link do formulário (Cadastro),
   opção no menu da Bia (mudança pequena na Bia: menu + etiqueta `Agenciado` fora do roteiro de aquisição).

Decisões assumidas (Vitor não escolheu opção; usar as recomendadas até ele corrigir): resolver (não apagar), 1 FUP,
controle pelo Chatwoot.

## Feito em 27/11/2026: "Já sou Amplify" (pronto para teste, ainda não em produção)

Fluxo:
1. A pessoa toca **Já sou Amplify** no menu da Bia (caixa 3).
2. A Bia **não responde** (`gate_exclusion`: o texto exato "Já sou Amplify" e a etiqueta de renovação são do serviço,
   em qualquer modo e também no número de teste). A demo continua com o seu próprio "Já sou Amplify".
3. O serviço de renovação põe a etiqueta `Renovacao de contrato` e pede o **@ do TikTok**.
4. Acha o agenciado (Ativo ou Saindo) e pede os **4 últimos dígitos do CPF**.
5. **Segunda pergunta** (escolha do Vitor, 27/11: "CPF + nascimento"):
   - WhatsApp da conversa = telefone do cadastro (DDD + 8 últimos dígitos) → basta o CPF.
   - Outro número → depois do CPF, pede a **data de nascimento**. Os 234 agenciados ativos com CPF têm a data.
6. O banco confere (`atendimento_agenciado_v5`, SECURITY DEFINER, só service_role). **CPF e nascimento nunca saem do banco.**
   - Algo errado → "Os dados não conferem", **sem dizer qual**, e recomeça pelo CPF.
   - **Sem limite de tentativas e sem chamar o time** (decisão do Vitor, 27/11). O banco só conta as tentativas.
   - Com as duas perguntas, adivinhar fica inviável (10 mil finais de CPF × milhares de datas).
   - Sem CPF no cadastro → manda o link do formulário (`/cadastro`, a mesma validação de hoje).
6. Conferido → mostra o **perfil**: situação, categoria, GMV, agenciado desde, contrato (início, fim, dias), renovação.
   Com os botões **Quero renovar / Não quero renovar** (menos para quem já renovou ou está saindo).
7. Depois disso, a conversa segue no fluxo de renovação: botões, motivos e a Bia dos agenciados para dúvidas.
   `registrar_resposta_renovacao_v5` passou a aceitar conversa de agenciado conferido (sem envio do alerta).

Segurança: os dígitos e a data só vão ao banco. Os dígitos ficam guardados só entre a pergunta do CPF e a da data,
e são apagados na conferência. Nada disso vai para as respostas; a IA vê "[número oculto]" no histórico.

Arquivos: `bia/sql/agenciado_atendimento.sql` (+ teste), `renovacao/agenciado.mjs` (+ teste), `bia/real_operations.py`,
`bia/server.py`, `bia/review_tests/test_ja_sou_amplify_gate.py`.

Testes: SQL simulado e desfeito (novo + 3 antigos ok; o teste antigo de "sem envio" foi atualizado para a regra da
auditoria; o novo cobre os dois caminhos: outro número e WhatsApp do cadastro). Serviço: 41 ok. Bia: teste novo ok; nenhuma falha nova na suíte offline.

Falta (precisa de aprovação): aplicar o SQL, publicar o serviço e a Bia, e simular no número de teste.
Usar o **47 99115-4859** (o 47 99291-6992 está na demo da Bia e receberia 2 respostas).
