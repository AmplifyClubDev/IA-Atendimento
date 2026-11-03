# Bia: release 45 (02/11/2026)

**Base:** a 44 que está no ar (deploy `ce8a061c`). A 45 contém a 44 inteira. **Nada publicado, enviado ou lido em produção.**

| | |
|---|---|
| Pacote | `atendimento-v5-release-20261102-45`, 37 arquivos |
| zip sha256 | `d76023daaac22e6a77322b2cb17a06103e4c39ad130412c546e8b0ce883b946d` |
| Carregador | sha256 `0b893740fc64dc4c7e13da285f4c2aba43587be67001f695e80a6243188f29d2` |
| Partes | 11, as mesmas variáveis da 44 (nenhuma variável nova) |
| Volta | `sealed45/volta44/`, idêntica a `sealed44/variaveis/` (a 44 no ar) |
| Diferença | `release45.diff` (44 → 45): `retomada.py` e `server.py` |
| Testes | 799 passam (810 no total, 4 novos em `src/tests/test_reprocesso45.py`), 9 fora de uso, as mesmas 2 falhas antigas |

## O que muda

- **A decisão é pelo Chatwoot.**
  - **Quando entra:** a última mensagem do lead não tem saída da Bia depois dela (o aviso de manutenção e o template de fora do horário não contam) e tem entre 3 min e 23 h.
  - **O que a Bia faz:** responde uma vez, mesmo com a mensagem já registrada ou já marcada como processada (`processed_inbound`, o filtro "newest" que a 44 deixou de pé).
- **Como responde:**
  - **Se a Bia já tinha calculado a resposta** e ela não saiu (envio `failed` ou incerto), envia essa resposta, com o pedido de desculpas. Assim o atendimento não é processado duas vezes.
  - **Se não havia resposta guardada,** libera o registro e processa a mensagem de novo.
- **Proteções (as da 44):**
  - a marca `reprocessed` impede repetir;
  - nunca com atendente humano depois ou com responsável;
  - nunca com resposta já aceita;
  - trava da conversa;
  - registro no atendimento (modo `resend_stored_reply` ou `process_again`) e no log `unanswered_event_reprocessed`.
- **Sem horário silencioso:** a pós-pausa responde de dia e de noite, porque o lead escreveu (é resposta, não lembrete).
- **No /ready**, em `pos_pausa`, os campos novos:
  - `intervalo_segundos: 60` e `horario_silencioso: false`;
  - as contagens desde o deploy: `varreduras`, `respondidas` (1ª resposta) e `reprocessadas`;
  - em cada varredura: `status`, `result`, `reprocess` e `conversation`.

## Testes (`test_reprocesso45.py`, pelo servidor inteiro, com o estado real reproduzido)

- **56938:** mensagem processada, atendimento salvo e envio que falhou. A pós-pausa manda a resposta guardada, com "Desculpa a demora", uma vez; a varredura seguinte fica idle, e o /ready mostra `reprocessadas: 1`.
- **56938 às 23:30 de Brasília:** responde do mesmo jeito (sem horário silencioso).
- **56938 marcada como processada sem resposta guardada:** processa de novo e responde uma vez.
- **56935 (Cristiane):** "Já aceitei" e "missões" processados com o envio falhando e o atendimento encerrado no banco. Recebe uma resposta, no modo acesso (`MISSIONS`), uma vez.
- **Os testes da 44 continuam passando:** resposta da Bia ou de atendente depois da mensagem não duplica, e a mensagem com menos de 3 min espera.

## Primeira varredura

- **56938:** deve receber no 1º minuto depois do deploy, **se for antes de ~04:42 de 03/11**.
- **56935:** recebe se a última mensagem dela tiver menos de 23 h.
- **Outras conversas abertas na mesma situação** também recebem uma resposta, uma por minuto.

## Publicação (só com autorização do usuário)

1. Conferir no `/ready` que a release no ar é a 44.
2. Trocar as 11 partes e o carregador pelos de `sealed45/variaveis/`.
3. Fazer o redeploy.
4. Conferir no `/ready`, em `pos_pausa`, as contagens `reprocessadas` e `respondidas`.
5. **Volta:** `sealed45/volta44/`.
