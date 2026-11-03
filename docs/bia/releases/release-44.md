# Bia: release 44 (02/11/2026)

**Base:** a 43 que está no ar (deploy `6865a432`). A 44 contém a 43 inteira. **Nada publicado, enviado ou lido em produção.**

| | |
|---|---|
| Pacote | `atendimento-v5-release-20261102-44`, 37 arquivos |
| zip sha256 | `31adaa5ee2886fa3731c72517f2ff9661b7b362a3df83fc2551454e325de367b` |
| Carregador | sha256 `2e9ff58f05b3072a8287d0f62226208ba1c470ff886f7f359b8660ce4cea107e` |
| Partes | 11, as mesmas variáveis da 43 (nenhuma variável nova) |
| Volta | `sealed44/volta43/`, idêntica a `sealed43/variaveis/` (a 43 no ar) |
| Diferença | `release44.diff` (43 → 44): `repository.py`, `retomada.py`, `server.py` |
| Testes | 792 passam (803 no total, 6 novos em `src/tests/test_reprocesso44.py`), 9 fora de uso, as mesmas 2 falhas antigas |

## A regra nova (aprovada pelo usuário: "Sim, mudar")

Uma mensagem do lead que já está registrada no banco da Bia volta a ser processada quando o Chatwoot não mostra nenhuma resposta da Bia depois dela. O aviso de manutenção da regra 3 e o aviso de fora do horário não contam como resposta.

- **Onde roda:** na pós-pausa. Ela já varre a cada minuto todas as conversas abertas da caixa cuja última mensagem é do lead, entre 2 min e 23 h atrás.
  - Para o reprocessamento, a mensagem precisa ter pelo menos 3 min.
  - Esta é a varredura periódica pedida; roda a cada minuto, não a cada 5.
- **Proteções:**
  - **1 reprocessamento por mensagem:** a marca `reprocessed` fica no atendimento e sobrevive a reinícios, e a varredura também guarda a marca.
  - **Atendente humano depois da mensagem:** a mensagem não é mais a última, então não entra.
  - **Conversa com responsável humano:** o controle humano bloqueia, como antes.
  - **Trava da conversa:** a liberação do registro acontece com a trava, então o webhook da mesma mensagem não corre junto.
  - **Nunca libera** se houve resposta aceita para aquela mensagem (o botão do WhatsApp deixa só uma nota privada no Chatwoot) ou se ela pôs consulta ao TikTok na fila.
  - **Registro:** o atendimento guarda o que havia antes (status do evento, operações e envios) em `reprocessed`, e o log grava `unanswered_event_reprocessed`.

## Testes (`test_reprocesso44.py`, pelo servidor inteiro)

- **56938:** lead às 05:42 + aviso de manutenção, telefone de 12 dígitos, mensagem já registrada → responde uma vez, com o pedido de desculpas. A 2ª varredura não repete.
- **56935 (Cristiane):** "Já aceitei" e a pergunta sobre missões, registrados sem resposta, com o atendimento encerrado no banco → responde no modo acesso (`MISSIONS`), uma vez.
- **Resposta da Bia depois → não duplica.** Atendente humano depois → não reprocessa. Resposta já aceita (só o botão) → não reprocessa. Menos de 3 min → espera.
- **Teste antigo ajustado:** `test_release39` exigia pular toda mensagem registrada; agora confere 1 reprocessamento e nunca 2.

## Primeira varredura

- **56938:** recebe na 1ª varredura depois do deploy, **se for antes de ~04:42 de 03/11** (23 h da mensagem).
- **Qualquer outra conversa aberta** cuja última mensagem seja do lead, registrada e sem resposta da Bia nas últimas 23 h, também recebe uma resposta, um lead por minuto.
- **Antes de publicar,** vale olhar no Chatwoot quantas conversas abertas estão nessa situação.

## Publicação (só com autorização do usuário)

1. Conferir no `/ready` que a release no ar é a 43.
2. Trocar as 11 partes e o carregador pelos de `sealed44/variaveis/`.
3. Fazer o redeploy.
4. **Volta:** `sealed44/volta43/`.
