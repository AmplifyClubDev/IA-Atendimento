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
