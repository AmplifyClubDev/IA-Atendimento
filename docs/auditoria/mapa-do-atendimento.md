# Mapa do atendimento da Bia (caixa 3) — 20/11/2026

**Em 1 linha:** a sequência é fixa e está no código. A IA entende o contexto e responde dentro da etapa atual,
mas não avança etapa, não confirma nada e não cria roteiro. Quem confirma são as pontes do TikTok e o formulário.

## Como cada mensagem é tratada

1. **Chatwoot → Bia** (`server.py`): a mensagem do lead chega pela caixa 3. Antes de responder, a Bia confere
   ao vivo se pode responder: atendente humano, `human_control`, `bia_paused`, conversa fechada, renovação de contrato.
2. **IA interpreta** (`guided_ai.py`, `answer_engine.py`, `real_answer_adapter.py`): lê a mensagem e o contexto do
   ciclo (etapa, dados já ditos, histórico). Ela **propõe**: é pergunta? é um dado (nome, @, GMV)? é aceite?
3. **Jornada valida e decide** (`conversation.py`, `real_journey.py`, `lead_validation.py`): só a jornada muda a etapa,
   faz a próxima pergunta, mostra botões e pede efeitos às pontes. A resposta da IA a uma dúvida é mantida e a
   pergunta da etapa atual vem junto.
4. **Nada de "sucesso" inventado** (`receipt_grounding.py`): sobre convite, vínculo, cadastro e acesso, a IA só
   fala o que tem comprovante. Sem comprovante: "Ainda não tenho confirmação…".

## A linha do atendimento (sequência fixa)

| # | Etapa | O que a Bia pede / faz | Avança quando | Etiqueta no Chatwoot |
|---|---|---|---|---|
| 1 | `intro` | Benefícios + "quer se agenciar ou conhecer primeiro?" | Lead escolhe | conhecer |
| 2 | `origin` | Nome e "como conheceu a Amplify?" | Lead responde | qualificação |
| 3 | Qualificação (`lead_validation`) | Agência atual → Shop ativo → GMV 30 dias | Cada resposta | qualificação |
| 3a | GMV ≥ R$ 50 mil | Pede o @ → alerta no Slack → "Seguir com a Bia" ou "Especialista" | Recibo do Slack / escolha | qualificação |
| 4 | `tiktok` | "Qual é o seu @?" | @ válido | qualificação |
| 5 | `checking` | **Ponte Pré-validação** confere o perfil e o Shop | Resultado da ponte | validação |
| 6 | `consent_real` | Condições da parceria + "Posso te mandar o convite?" | "Pode mandar" | convite |
| 7 | `inviting` | **Partner Bridge** envia o convite | Recibo do envio | convite |
| 8 | `await_acceptance` | Como aceitar o convite no TikTok | "Aceitei" | convite |
| 9 | `checking_acceptance` | **Ponte Agenciamento** confere o vínculo | Vínculo confirmado | convite |
| 10 | `form` | Link do formulário (o @ é conferido de novo no formulário) | Formulário enviado e validado | cadastro |
| 11 | `acesso` | Circle liberado (o aviso sai pelo Cadastro) | — | cadastro |
| — | `blocked` | Ponte fora, Shop sem status, convite falhou | Reconferência automática ou nova mensagem | validação |

Fora da linha: lembretes (`retomada.py`, 2 no máximo; o 2º fecha o ciclo e marca `encerrado`) e o vigia do
Cadastro (lead sem resposta há 30 min).

## As 3 pontes

| Ponte | Usada em | Operação | Só leitura? |
|---|---|---|---|
| Pré-validação | Etapa 5 | `precheck` (perfil e status do Shop) | Sim |
| Partner Bridge | Etapa 7 | `invite` (envia o convite) | **Não** (nunca repetida sozinha) |
| Agenciamento | Etapa 9 e formulário | `relationship` (vínculo com a Amplify) | Sim |

## O que as correções da auditoria tocam

| Mudança | Toca na linha / no que o lead lê? |
|---|---|
| 1. Especialista → alerta para o time; sem `encerrado` | **Não.** O lead lê o mesmo texto. |
| 2. Limite do "Pronto" (2 reconferências + mensagem nova + sem lembrete) | **Sim.** Muda a etapa `blocked`. |
| 3. Alerta de lead parado (`team_alert`) | **Não.** Só Slack. |
| 7a. Trava de repetição (confere a frase, não a palavra) | Não muda a linha; só evita a mesma frase 2×. |
| 7b. Parágrafo duplicado sai uma vez | Não muda a linha; só tira a duplicata. |
| 8. 7 textos reescritos | **Sim.** Muda as falas da linha. |
| 9. Log do erro genérico | **Não.** |
| 10. Conversa "resolvida" (chave desligada) | **Não.** Só Chatwoot. |
| 11. `encerrado` após o 2º lembrete | **Não.** Só etiqueta. |
| Cadastro: 3 códigos válidos, @ sem resultado velho, versão única | Formulário, não a conversa. |
