# Bia: release 42 (02/11/2026)

## Resumo

- **Base:** a 41 que está no ar (deploy `09e8fb1c`, zip `d6785f18…`). A 42 contém a 41 inteira.
- **O que entra** (aprovado pelo usuário: "Então faça isso"):
  1. a prova pela lista de vínculos: o convite incerto é reenviado uma vez quando o @ não aparece na lista;
  2. o acompanhamento do convite pendente, sem o lead precisar dizer "aceitei";
  3. "Não aparece" com o convite pendente recebe o passo a passo.
- **Testes:** 23 novos em `src/tests/test_convite42.py`, com os 4 casos reais. Um deles passa pelo servidor inteiro: webhook, convite incerto, varredura, reenvio, texto 1, vínculo e texto 2.
- **Nada publicado.** Nenhuma variável, nenhum modelo do WhatsApp e nenhum dado do banco foi alterado, e nenhuma mensagem foi enviada. O banco, o Chatwoot e as pontes não foram lidos.

| | |
|---|---|
| Pacote | `atendimento-v5-release-20261102-42`, 37 arquivos |
| zip sha256 | `ed96fe5b44d64320b2683e9b6d744fcd8b5bde469388c1a427f73dac484cd9db` |
| Carregador | sha256 `1453813eb78c3ba8f1a24cd909a28bf54255bfb56e340f5cfe227988689e02a0` |
| Partes | 11, as mesmas variáveis da 41 (nenhuma variável nova) |
| Volta | `sealed42/volta41/`, idêntica a `sealed41/variaveis/` (a 41 no ar) |
| Diferença | `release42.diff` (41 → 42) |
| Testes | 742 passam (753 no total, 23 novos) e 9 fora de uso. Continuam as mesmas 2 falhas antigas: `test_connection_host` e `test_real_executor` com data fixa |

## 1. O que a 42 faz

Os três casos usam a ponte de **Agenciamento**, a mesma do formulário. Ela devolve a lista de vínculos do @: `not_found`, `pending` ou `linked`, com evidência completa e recente.

### Prova pela lista (item 1)

- **Quando lê:** o convite tem resultado incerto (`verification_pending` ou `outcome_unknown`), a autorização é deste atendimento e a 41 não pode reenviar (falta a prova de que nada chegou ao TikTok). A leitura espera 10 minutos depois da última tentativa.
- **Se o @ não aparece** (`not_found`, numa lista completa e recente):
  - a Bia valida o perfil de novo, se a validação passou de 15 minutos, e reenvia o convite uma vez;
  - quando sai, manda o **texto 1**.
  - O próprio envio confere a lista de novo antes de escrever; com o convite lá, não escreve.
  - A prova vale por 30 minutos.
- **Se aparece `pending`:** nunca reenvia. Manda o passo a passo aprovado na 41 (`INVITE_STEPS`) e passa a acompanhar.
- **Se aparece `linked`:** manda o **texto 2**.
- **Leitura falhou** (ponte fora): fica em silêncio e lê de novo 15 minutos depois, no máximo 3 leituras.
- **Pré-validação falhou no meio:** a prova vence e a lista é lida de novo, dentro das 3 leituras.
- **Reenvio falhou:** fica em silêncio. Não há segundo reenvio.

### Acompanhamento do convite pendente (item 2)

- **Quem entra:** todo atendimento com convite enviado ou pendente (`sent`, `pending`, `pending_verification`, ou o vínculo lido como `pending`), contado a partir do envio.
- **Frequência:**
  - menos de 2 h: a cada 15 min;
  - de 2 a 48 h: a cada 2 h;
  - de 48 h a 7 dias: 1 vez por dia.
- **Virou `linked`:** o **texto 2**, com o botão *Fazer cadastro*. O acompanhamento para.
- **Nada mudou:** nada é enviado.
- **O convite sumiu da lista:** o acompanhamento para em silêncio. Se o lead disser que não aparece, a Bia confere na hora (item 3).
- **Antes de cada leitura, a ficha é lida.** Com o cadastro confirmado, ou sem conseguir ler a ficha, não lê nem manda nada.

### "Não aparece" com o convite pendente (item 3)

- **Convite `pending`:** o **texto 3**, sem novo convite.
- **Convite sumiu (`not_found`):** o reenvio único, com o texto 1.
- **Depois de 48 h sem aceite, o lead diz de novo que não aparece:** a regra era cancelar e reenviar, se a ponte permitir. **A ponte não permite:** o cliente da Bia não tem operação de cancelar convite, e não achei uma no código das pontes. Então a Bia só repete o texto 3, como a regra prevê.

### Regras gerais

- **Horário:** mensagens só das 8h às 21h (Brasília). Como cada leitura vira mensagem em poucos minutos, a Bia só começa uma leitura das 8h às 20h45. O que vence à noite espera as 8h.
- **No máximo 1 reenvio por lead,** guardado no atendimento (`invite_resends`). O reenvio da 41 para convite de atendimento anterior (item 6) também conta.
  - As novas tentativas da 41 com a prova de que nada chegou ao TikTok continuam e não contam: nelas o convite nunca foi enviado.
- **Mensagem já registrada nunca é reprocessada.** A varredura usa o evento original só para saber a conversa, como na 41.
- **Leituras espaçadas:** a varredura começa no máximo uma leitura por minuto, somando todos os leads; para o mesmo lead, no mínimo 15 minutos entre leituras. Cada leitura faz 1 ou 2 consultas à lista.
- **Textos aprovados saem exatamente como aprovados.** O filtro de "um emoji por parágrafo" tiraria o 😊 do texto 1; esses textos não passam por ele.

### Textos (os três aprovados)

1. "Pronto, {nome}! Seu convite da Amplify foi enviado agora 🎉 Abra o TikTok Shop Creator → Parcerias ou Notificações → aceite o convite da Amplify. Quando aceitar, eu já fico sabendo e te mando o cadastro 😊" (sem nome: "Pronto! …")
2. "Vi aqui que você aceitou o convite! 🎉 Agora falta só o cadastro, e seu acesso ao Club sai na hora em que você envia." + botão [Fazer cadastro] (/cadastro)
3. "Seu convite está lá, sim! 😊 Para achar: 1. … 2. … 3. … Se não achar mesmo, me avisa que eu envio de novo." (os passos em linhas separadas)

## 2. Decisões e limites que precisam do usuário

1. **A janela de 24 h do WhatsApp.**
   - O atendimento encerra 24 h depois da última mensagem do lead, e fora dela o WhatsApp só aceita um modelo aprovado.
   - Por isso a Bia só lê e avisa com o atendimento aberto. Na prática, o acompanhamento de 2 a 48 h vale até a janela fechar, e o de 48 h a 7 dias não acontece.
   - Para avisar depois disso seria preciso um modelo aprovado para o texto 2. Criar ou usar modelo pede autorização.
   - Se o lead voltar a escrever, a conferência do convite anterior (41) cuida do caso.
2. **O texto 1 só sai no reenvio.**
   - No envio normal, a Bia continua mandando o que a 41 manda: o aviso do convite junto com o link do cadastro.
   - Trocar o envio normal pelo texto 1 (e mandar o cadastro só no texto 2) é uma mudança pequena, mas muda o fluxo de todo lead novo; não fiz sem a sua decisão.
3. **O texto 3 promete "me avisa que eu envio de novo".** Com o convite pendente, a ponte não cancela, então a Bia não reenvia; repete o passo a passo. Ela só reenvia se o convite sumir da lista.
4. **Lista com `pending` na prova:** usei o passo a passo aprovado na 41. Nenhum dos 3 textos novos serve (o texto 1 diria "enviado agora").

## 3. Quem recebe na primeira varredura

Sem ler produção, não dá para dizer a lista exata. O que decide cada caso é o estado guardado da Bia e a lista de vínculos na hora da leitura. Pelo que a sessão principal leu na ponte:

| Conversa | Lista hoje | O que a 42 faz | Condições |
|---|---|---|---|
| **56933 @gabinaresse** | not_found | Valida o perfil, reenvia o convite uma vez e manda o **texto 1** | Atendimento aberto (24 h desde a última mensagem dela), das 8h às 20h45, pontes de Agenciamento, Pré-validação e Convites prontas, cadastro não confirmado |
| **56932 @viralstoresbr** | linked | **Texto 2** com o botão, na 1ª leitura | Atendimento aberto e convite deste atendimento (enviado, pendente ou incerto). Se a janela de 24 h já fechou, não recebe: precisaria de modelo |
| 56629 @ma.ribeiroh | pending | Lê em silêncio; texto 2 quando aceitar | Vínculo pendente lido neste atendimento, atendimento aberto |
| 56931 @sabrinasalazar33 | pending | Igual | Igual |

- **Ordem:** a 56933 vem primeiro na fila, como na 41. Depois, um lead por minuto.
- **Para ver a lista exata antes de publicar** (só lê, numa cópia do `state.sqlite3` do serviço):
  ```bash
  python -I listar_primeira_varredura.py <cópia do state.sqlite3>
  ```
  - Para cada um dos 4 casos, o script mostra se a lista será lida agora e o que cada resultado manda. Se não for ler, diz o motivo: janela fechada, fora do horário, cadastro confirmado ou outra consulta em andamento.
  - Mostra também todos os outros atendimentos com convite que entram no acompanhamento.
- **Risco a olhar antes de publicar:** a 56932 escreveu de manhã em 02/11. Se a janela dela fechar antes da publicação, ela não recebe nada.

## 4. Testes

`src/tests/test_convite42.py`:

| Caso | Testes |
|---|---|
| 56933 @gabinaresse | reenvio único com o texto 1 (com e sem nome); `pending`/`linked` nunca reenviam; lista incompleta ou velha não é prova; um reenvio só; leitura falha em silêncio, espera 15 min, para em 3; Pré-validação caída no meio; só das 8h às 21h; pelo servidor inteiro, com a ficha lida antes de cada leitura |
| 56932 @viralstoresbr | aceite visto pela Bia manda o texto 2 com o botão; nada mudou, nada enviado; cadastro confirmado não é lido nem avisado |
| 56629 @ma.ribeiroh | "não aparece nada para eu aceitar" com convite pendente: texto 3; convite antigo achado pendente e acompanhado até o vínculo |
| 56931 @sabrinasalazar33 | calendário 15 min / 2 h / 1 dia por 7 dias (35 leituras, nenhuma mensagem); depois de 48 h, "não aparece" de novo repete o texto 3 sem novo convite; convite sumido é reenviado uma vez, e só uma |
| Varredura | a lista é lida pela ponte de Agenciamento, um lead por vez, 56933 primeiro |

A matriz das auditorias antigas e das conversas de 02/11 continua em `test_regressao41.py` e `test_conversas0211.py` e passa inteira na 42 (ver `claude-bia-release41-20261102/README.md`, seção 1).

## Publicação (só com autorização do usuário, passo a passo)

1. Conferir no `/ready` que a release no ar é a `atendimento-v5-release-20261102-41`.
2. Rodar o `listar_primeira_varredura.py` numa cópia do `state.sqlite3` e conferir quem recebe.
3. Trocar as variáveis pelas de `sealed42/variaveis/`. São as mesmas 11 partes mais o carregador; nenhuma variável nova.
4. Redeploy e prova no número de teste: autorizar o convite, ver o texto 1 (ou o aviso normal) e, depois de aceitar no TikTok, o texto 2 em até 15 minutos.
5. **Volta:** as variáveis de `sealed42/volta41/`. São as variáveis da 41 que está no ar, recompostas do pacote selado e conferidas iguais a `sealed41/variaveis/`.

## Arquivos

- `src/`: o código da 42 (a 41 + as mudanças em `conversao.py`, `real_journey.py`, `real_operations.py`, `reconferencia.py` e `server.py`).
- `src/tests/test_convite42.py`: os testes novos.
- `release42.diff`: o que mudou da 41 para a 42.
- `suite42.log`: a suíte inteira.
- `empacotar_release42.py`: monta e confere o pacote (`python -I empacotar_release42.py`, com o Python do sistema).
- `listar_primeira_varredura.py`: quem recebe na primeira varredura (só lê).
- `sealed42/`: zip, carregador, manifesto, `variaveis/` e `volta41/`.
