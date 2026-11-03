# Bia: release 43 (02/11/2026)

## Resumo

- **Base:** a 42 que está no ar (deploy `6268c308`, zip `ed96fe5b…`). A 43 contém a 42 inteira.
- **O que entra:**
  - a correção dos 4 casos de 02/11;
  - a regra do usuário: **nenhum lead fica sem resposta em silêncio**;
  - os **códigos das pontes como chave da automação** (tabela 5b, seção 1b).
- **Testes:** 45 novos:
  - 26 em `src/tests/test_correcao43.py`, um ou mais por caso real, 4 deles pelo servidor inteiro;
  - 19 em `src/tests/test_codigos43.py`: a cobertura de todos os códigos e o comportamento de cada linha da tabela.
- **Nada publicado.** Nenhuma variável, nenhum modelo do WhatsApp e nenhum dado do banco foi alterado, e nenhuma mensagem foi enviada. O banco, o Chatwoot e as pontes não foram lidos.

| | |
|---|---|
| Pacote | `atendimento-v5-release-20261102-43`, 37 arquivos |
| zip sha256 | `b9005a43cc6c61ea9899d38e6c776f5acc71df692e274d1a5377636bd5c72256` |
| Carregador | sha256 `33b9f26dbf00c334ed7b11a271c20cdb6dbce27afc5c4ebb8f4100390222c19e` |
| Partes | 11, as mesmas variáveis da 42 (nenhuma variável nova) |
| Volta | `sealed43/volta42/`, idêntica a `sealed42/variaveis/` (a 42 no ar) |
| Diferença | `release43.diff` (42 → 43) |
| Testes | 786 passam (797 no total, 45 novos) e 9 fora de uso. Continuam as mesmas 2 falhas antigas: `test_connection_host` e `test_real_executor` com data fixa |

## 1. Os 4 casos: causa no código e correção

Sem ler produção, a causa exata de cada caso precisa ser confirmada no estado guardado da Bia. O `listar_primeira_varredura.py` mostra o que importa (seção 3).

### 🔴 56932 @viralstoresbr: aceitou e não recebeu nada

Achei 3 jeitos de o resultado do "Já aceitei" sumir sem mensagem. Os 3 estão corrigidos:

1. **O resultado era descartado se havia outra mensagem mais nova na fila.**
   - O servidor só enviava o resultado de uma consulta se o evento que a pediu fosse o mais novo da conversa.
   - Uma mensagem admitida e ainda não processada, ou que falhou no processamento, tornava o resultado "velho". Então o estado avançava (a fase vira `form`, a etiqueta vira "cadastro") e **nada era enviado**. É exatamente o que se viu.
   - **Agora** o resultado de consulta do TikTok sempre é enviado.
2. **O botão "Fazer cadastro" ia para a grafia do número na lista.** O botão é a mensagem do WhatsApp com o link do formulário.
   - O WhatsApp aceitava, o Chatwoot só ganhava a nota privada "🔗 Botão enviado…", e a mensagem podia não chegar quando a lista e o WhatsApp grafam o número de jeitos diferentes (com ou sem o 9).
   - **Agora** o botão vai para o número que o próprio WhatsApp informou na conversa.
3. **A 42 não mandava o texto 2 a quem já tinha o vínculo gravado.**
   - O acompanhamento parava no vínculo, mesmo sem o aviso ter chegado, e uma leitura presa ("pending" para sempre) também travava tudo.
   - **Agora:**
     - todo aviso de vínculo é marcado como entregue ou não;
     - quem tem vínculo sem aviso entregue recebe uma nova leitura e o texto 2, no máximo 2 vezes. Isso vale para os atendimentos da 41 e da 42, que não têm a marca;
     - leitura parada há mais de 30 min deixa de travar;
     - a fase "conferindo aceite", onde ela ficou, entra no acompanhamento.

### 🔴 56933 @gabinaresse: "enviado agora" sem o convite no TikTok

- **Por que disse "enviado":**
  - Na 42, o texto 1 saía com qualquer destes resultados: `sent`, `pending` ou `pending_verification`.
  - `pending_verification` quer dizer que a ponte de Convites aceitou o pedido (`create_accepted`), mas a leitura da lista não confirmou o convite.
  - Com a lista dando `not_found` às 19:55, quase certamente foi isso. **O que a ponte respondeu** aparece no script da primeira varredura, em `ultimo_convite_na_ponte` (status, motivo, `create_accepted`, `post_attempted`).
- **Agora:**
  - "enviado agora" só sai com a confirmação da lista. Isso vale para o `sent` da ponte, que já inclui a leitura, e para a leitura da lista 5 min depois do "Tô confirmando o envio no TikTok, já te aviso 😊", mostrando o convite;
  - se a lista não mostrar o convite: **aviso honesto e novo envio**;
  - se esse também não aparecer, a Bia avisa uma vez e segue conferindo, sem 3º envio;
  - também vale para o envio normal: convite "enviado" que some da lista ganha aviso e novo envio, em vez de silêncio.
- **Limite de reenvio:** passa de 1 para **2 por lead**. O 2º só sai quando a lista prova que o 1º não chegou ao TikTok, então não há risco de convite duplicado. *Precisa do OK do usuário: muda a regra da 42.*
- **Lembrete das 18:27:**
  - os lembretes contavam da última mensagem do lead (de manhã). Às 18:27 já tinham passado 2 h, e saiu o lembrete "continua no TikTok" 11 min depois do envio;
  - **agora** contam do envio de convite mais recente quando ele é posterior. O 1º lembrete sai 15 min depois do envio, e o "continua" 2 h depois.

### 🔴 56938 (+558396914946, sem o 9): a pós-pausa não respondeu

1. **Causa mais provável: o aviso de fora do horário.**
   - Às 05:42 a caixa estava fora do horário de atendimento, e o Chatwoot responde com o aviso automático da caixa, que é do tipo `template`.
   - A pós-pausa só reconhecia como automático o aviso de manutenção (tipo `outgoing`, da regra 3). Com o `template` como última mensagem, ela não via o lead.
   - Os 4 respondidos às 19:47 escreveram em horário comercial.
   - **Agora** o `template` conta como aviso automático.
   - *Para confirmar:* a mensagem logo depois da dela, no Chatwoot, deve ser o aviso de fora do horário.
2. **Telefone sem o 9: a comparação só funcionava num sentido.**
   - Lista com o 9 e Chatwoot sem o 9: funcionava.
   - Lista sem o 9 e Chatwoot com o 9: **não**, nem no portão nem na pós-pausa.
   - **Agora** vale nos dois sentidos, só para celular (1º dígito local de 6 a 9). A lista continua recusando o mesmo número duas vezes.

### 🟡 32922 "Não tenho interesse": sem resposta

- **Na conversa da Bia, a frase não ficava sem resposta:** caía no funil e recebia um novo pedido do @ ou do convite (testei em todas as fases).
- **O silêncio veio de fora da conversa.** As causas possíveis:
  - **conversa antiga** (32922) com responsável humano ou fora do status "aberta": o controle humano bloqueia de propósito;
  - número fora da lista;
  - erro no processamento.
- O erro no processamento agora tem aviso (regra geral, abaixo). Os outros dois casos ficam no Chatwoot.
- **Agora**, "Não tenho interesse" (e variações curtas, sem pergunta) recebe **uma** resposta: "Tudo bem! Se mudar de ideia, é só chamar 💙".
  - O atendimento encerra, sem lembretes nem leituras.
  - Se ela escrever de novo, começa um atendimento novo.

## 1b. Os códigos das pontes como chave da automação (tabela 5b)

A tabela está no código: `BRIDGE_CODE_TABLE` em `src/real_journey.py`. Cada código leva a uma ação e a uma mensagem, que é o nome do texto em `conversao.py`.

| Operação | Código | Ação automática | Mensagem |
|---|---|---|---|
| Vínculo | `linked` | cadastro na hora, sem esperar "aceitei" (leitura automática ou pedida) | texto 2 com o botão |
| | `pending` | acompanhar (15 min, 2 h, 1 dia) | passo a passo (texto 3) quando o lead diz que não aparece; nada se a leitura é automática e nada mudou (regra da 42) |
| | `not_found` | convite dado como feito ou incerto: aviso e reenvio, com a prova da lista | "O TikTok ainda não mostrou o seu convite… Vou enviar de novo agora" |
| | `verification_pending` / `failed` / `outcome_unknown` | ler de novo (automática: no próximo horário; pedida: 5, 15 e 60 min) | "Não consegui consultar o TikTok agora…" |
| Perfil | `eligible` | pedir a autorização | "Boa notícia: seu perfil pode entrar…" |
| | `ineligible` | **encerrar com respeito** (novo) | "Conferi seu perfil e, por enquanto, ele ainda não pode entrar…" (novo) |
| | `verification_pending` (Shop) | passo a passo; o "pronto" reconfere **no máximo a cada 10 min** (novo) | `SHOP_UNKNOWN`; antes dos 10 min, "Acabei de conferir há pouquinho…" (novo) |
| | `failed` / `outcome_unknown` | bridge_wait e reconferência (novo para motivo desconhecido) | "O sistema do TikTok tá lento…" |
| Convite | `sent` | aguardando aceite (o `sent` da ponte já inclui a leitura da lista) | "Seu convite foi enviado! 🎉…" |
| | `linked` | **cadastro na hora** (novo; antes: "Seu perfil já tem um registro") | texto 2 com o botão |
| | `pending` | acompanhar | "Seu convite já está no TikTok…" |
| | `pending_verification` / `outcome_unknown` | **não dizer "enviado"; ler a lista em 5 min** e seguir pelo código do vínculo (novo) | "Tô confirmando o envio no TikTok, já te aviso 😊" |
| | `verification_pending` (ponte fora) | invite_wait; a prova da lista (42) ou a reconferência (41) reenvia | "Sua autorização está anotada! ✅ O sistema do TikTok tá lento…" |
| | `ineligible` | encerrar com respeito | igual ao perfil |
| | `failed` | **1 nova tentativa em 10 min** (novo; antes, 3 min e só sem envio) | "Tive um probleminha para enviar, já tô tentando de novo 😊" |
| | `failed` de novo | **alerta à equipe:** o atendimento fica aberto em `blocked`, e o vigia do Cadastro (`listar_atendimentos_parados_v5`) avisa por e-mail em 30 min | "Não consegui enviar seu convite agora 😕 Já avisei a equipe…" (novo) |
| Qualquer | os 6 bloqueios da ponte (`human_login_required`, `captcha_required`, `mfa_required`, `session_or_partner_context_invalid`, `partner_probe_rejected`, `blocked_by_risk_guard`) e os 9 motivos de ponte fora | bridge_wait e reconferência quando a ponte volta | "O sistema do TikTok tá lento, eu confiro sozinha e te chamo", uma vez |

**O teste `test_codigos43.py`:**
- percorre todos os códigos: os status de cada operação, os motivos de ponte fora e os bloqueios do `playwright_client._BLOCKED`;
- falha se algum não tiver ação e mensagem, se a tabela tiver linha sem código, ou se a ponte devolver um bloqueio novo;
- em seguida percorre cada linha na jornada e confere que a mensagem enviada é a da tabela;
- prova também, pelo cliente da ponte, que cada bloqueio chega à Bia como verificação humana.

**Também mudaram:**
- O texto 1 sai quando a lista mostra o convite; com `pending_verification`, a 1ª leitura é em 5 min (antes, 15).
- A prova da lista vale 5 min depois da tentativa (antes, 10), como pede a tabela.
- Com o pedido aceito pela ponte (`create_accepted`), o link do formulário continua saindo se o lead pedir: o formulário confere o vínculo sozinho.

**Testes antigos ajustados para a tabela:** `test_relationship_form_chat30` (o envio incerto não abre o formulário), `test_conversas0211` e `test_release40_conversao` (o "pronto" a cada 10 min) e `test_convite42` (5 min; o reenvio que falha avisa a equipe).

## 2. Regra geral: nenhum lead sem resposta em silêncio

| Onde falhava em silêncio | Agora |
|---|---|
| Mensagem do lead que falha no processamento (como a da Cristiane, 56935) | "Recebi sua mensagem! 🙏 Tive uma instabilidade aqui e não consegui responder agora. Pode me mandar de novo, por favor?" |
| Resultado de consulta pedida pelo lead que não pôde ser aplicado | "Tive uma instabilidade aqui para conferir no TikTok 😕 Vou tentar de novo sozinha e te aviso por aqui." A leitura parada é refeita pelo acompanhamento depois de 30 min |
| Resultado descartado por haver mensagem mais nova | Sempre enviado |
| Aviso do vínculo não entregue | Nova leitura e o texto 2 (até 2 vezes) |
| Convite que não aparece na lista | "O TikTok ainda não mostrou o seu convite 😕 Vou enviar de novo agora…" e novo envio (ou "…Vou continuar conferindo sozinha…" sem novo envio) |

- **Limites dos avisos:**
  - no máximo 1 aviso de instabilidade por conversa e por hora;
  - nunca com responsável humano na conversa;
  - as leituras da varredura que falham continuam em silêncio e são refeitas.
- **Mensagem já registrada não é reprocessada.** A Bia avisa e pede para o lead mandar de novo.
- **Os textos novos precisam de aprovação do usuário:** `NOT_INTERESTED`, `INBOUND_FALLBACK`, `OPERATION_FALLBACK`, `INVITE_NOT_LANDED`, `INVITE_STILL_MISSING`, `INVITE_FAILED_TEAM`, `PROFILE_INELIGIBLE` e `SHOP_RECHECK_SOON`, em `src/conversao.py`. Os dois da tabela 5b (`INVITE_CONFIRMING` e `INVITE_RETRYING`) foram usados como estão.

## 3. Quem recebe na primeira varredura

| Conversa | O que a 43 faz | Condições |
|---|---|---|
| **56932 @viralstoresbr** | Lê a lista; com `linked`, manda o **texto 2** com o botão | Atendimento aberto (24 h desde 14:42, até ~14:42 de 03/11), das 8h às 20h45, cadastro não confirmado |
| **56933 @gabinaresse** | Lê a lista; com `not_found`, manda "O TikTok ainda não mostrou o seu convite… Vou enviar de novo agora", reenvia e manda o texto 1 quando o envio for confirmado | Atendimento aberto, das 8h às 20h45, as 3 pontes prontas |
| **56938** | A pós-pausa responde a mensagem das 05:42 com o pedido de desculpas e a 1ª resposta | Conversa aberta no Chatwoot, sem responsável humano, mensagem com menos de 23 h (**até ~04:42 de 03/11**) |
| 56629, 56931 | Leitura em silêncio; texto 2 quando aceitarem | Atendimento aberto |
| 32922 | Nada até escrever de novo | — |

- **Ordem:** um lead por minuto na reconferência, e um por minuto na pós-pausa.
- **Prazos que podem fechar antes da publicação:**
  - a 56938 sai da janela da pós-pausa às ~04:42 de 03/11 (23 h);
  - a 56932 tem a janela de 24 h até ~14:42 de 03/11;
  - fora das 8h–20h45, as leituras esperam as 8h.
- **Lista exata, antes de publicar** (só lê, numa cópia do `state.sqlite3`):
  ```bash
  python -I listar_primeira_varredura.py <cópia do state.sqlite3>
  ```
  Para cada caso, o script mostra a fase e a janela, o aviso do vínculo, o envio esperando a lista, as leituras paradas e o que a ponte de Convites respondeu.

## 4. Testes

`src/tests/test_correcao43.py`:

| Caso | Testes |
|---|---|
| 56932 | o resultado do "Já aceitei" sai mesmo com mensagem mais nova na fila (servidor); envio do link recusado vira nova leitura e texto 2 (servidor); estado da 41 sem a marca recebe o texto 2; aviso entregue não repete; leitura presa não trava; botão vai para o número da conversa |
| 56933 | envio não confirmado nunca vira "enviado agora"; lista mostrando o convite anuncia; lista sem o convite: aviso honesto e 2º envio; depois de 2 envios sem chegar, segue conferindo sem 3º; lembrete conta do envio (nada às 18:27); caminho inteiro pelo servidor; estado deixado pela 42 (acompanhamento parado no `not_found`) volta a ler e reenvia |
| 56938 | aviso de fora do horário (template) não esconde o lead; lista com e sem o 9, nos dois sentidos; número fixo nunca ganha 9 |
| 32922 | "Não tenho interesse" em 4 fases: uma resposta e encerra; variações; pergunta ou frase longa não encerra; escrever de novo recomeça |
| Regra geral | mensagem que falha no processamento recebe o aviso honesto, uma vez por hora (servidor) |

**Testes antigos ajustados:** `test_worker_form_context` (2 testes). Eles exigiam silêncio depois de uma falha ao aplicar o resultado; agora conferem que sai só o aviso honesto.

## Publicação (só com autorização do usuário, passo a passo)

1. Conferir no `/ready` que a release no ar é a `atendimento-v5-release-20261102-42`.
2. Rodar o `listar_primeira_varredura.py` numa cópia do `state.sqlite3`.
3. Trocar as variáveis pelas de `sealed43/variaveis/`. São as mesmas 11 partes mais o carregador; nenhuma variável nova.
4. Redeploy e prova no número de teste:
   - "Não tenho interesse" recebe uma resposta;
   - autorizar o convite: o texto 1 só sai com o convite confirmado;
   - aceitar no TikTok: o texto 2 em até 15 min.
5. **Volta:** as variáveis de `sealed43/volta42/`. São as variáveis da 42 que está no ar, recompostas do pacote selado e conferidas iguais a `sealed42/variaveis/`.

## Arquivos

- `src/`: o código da 43. Muda em `contracts.py`, `conversao.py`, `real_journey.py`, `real_operations.py`, `retomada.py`, `server.py` e `transport.py`.
- `src/tests/test_correcao43.py` e `src/tests/test_codigos43.py`: os testes novos.
- `release43.diff`: o que mudou da 42 para a 43.
- `suite43.log`: a suíte inteira.
- `empacotar_release43.py`: monta e confere o pacote (`python -I empacotar_release43.py`, com o Python do sistema).
- `listar_primeira_varredura.py`: quem recebe na primeira varredura (só lê).
- `sealed43/`: zip, carregador, manifesto, `variaveis/` e `volta42/`.
