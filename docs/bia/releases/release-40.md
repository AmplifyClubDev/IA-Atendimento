# Release 40 da Bia: reconferência e conversão (01/11/2026)

**Nada foi publicado.** Não houve deploy nem mudança de variável, e o banco de produção não foi lido nem escrito.

**Base:** a release 39 no ar (deploy eb5f4874, 21 telefones no piloto). `base39/` é o conteúdo exato do zip selado 39 (sha `a9044daa…`). Considero que eb5f4874 publicou esse pacote, e o passo 0 confere isso.

**Pedidos atendidos:**
- reconferir quem esperou a ponte;
- os 7 ajustes da auditoria `../claude-cadastro-v5-20261030/AUDITORIA-CONVERSAO-20-ATENDIMENTOS.md`, aprovados pelo usuário com 3 restrições. O ajuste 7 é a exceção: precisa de mudança no banco (ver abaixo).

## O que muda

### 1. Quem esperou a ponte é reconferido sozinho
- **Marca de espera:** quando a conferência do perfil falha por ponte fora (`human_verification_required`, `session_not_ready`, falha de transporte e afins), o atendimento fica marcado com `bridge_wait`.
  - O lead recebe uma vez: "Anotei seu @! O sistema do TikTok tá um pouco lento agora, mas eu confiro sozinha assim que liberar e te chamo aqui. Você não precisa fazer nada 😊"
  - Se ele escrever enquanto espera, recebe um texto do mesmo tom.
  - Uma resposta do modelo que prometa "o time" é trocada por esse texto.
- **Varredura** (`reconferencia.py`), a cada minuto, um lead por vez:
  - **lê o `/bridge/ready` da pré-validação na hora**, com um GET novo a cada varredura e só quando há alguém esperando. Nada de resultado guardado: é o pedido "sem cache";
  - com a ponte pronta, refaz a consulta em silêncio. O resultado segue a conversa com "Pronto, conferi! ✅" e a autorização (item 4);
  - se a ponte cair de novo no meio, nada é dito ao lead. A próxima tentativa sai 10 min depois, no máximo 3 por atendimento.
- **Lista inicial:**
  - as conversas 56747, 56746, 56751, 56748 e 56752 (`INITIAL_RECHECK`) vêm primeiro e são reconferidas **uma vez, qualquer que tenha sido o motivo registrado**;
  - isso cobre a @larvitrine, que recebeu "verificação" às 22:16 com a ponte já de volta. O motivo real dela pode não ter sido ponte fora;
  - perfil inelegível nunca é reconferido.
- **"Shop sem status"** (`shop_unknown`): no lugar de "verificação de segurança", o lead recebe "Conferi seu @, mas o TikTok não mostrou se o seu TikTok Shop Creator está ativo 😕 Dá uma olhada no app e, quando estiver ativo, me manda “pronto” que eu confiro de novo."
  - A Bia confere mesmo de novo quando ele escreve, no máximo a cada 10 min.
  - Saiu o "vou pedir para o time".
- **Volta depois das 24 h:** quem esperava a conferência e escreve de novo depois que o atendimento venceu não precisa mandar o @ de novo. A Bia responde "Oi de novo! … Ainda tenho seu @x anotado. Já tô conferindo seu perfil 🔎" e já consulta o perfil. Isso vale até 7 dias depois.

### 2. Primeira mensagem e lembretes que vendem
- **Primeira resposta** (a mensagem pronta do anúncio, um "oi" ou qualquer primeiro contato genérico):
  > Oi! Aqui é a Bia, agente de IA da Amplify 💙 A gente apoia creators do TikTok Shop com campanhas com marcas, orientação sobre produtos e conteúdos, apoio em lives e uma comunidade de creators.
  >
  > Não tem mensalidade: a Amplify fica com 10% só da comissão que você ganhar. Quer ver se seu perfil pode entrar? Me manda seu @ do TikTok 👇
  > [Mandar meu @] [Como funciona?]
- **Antes do @, toda resposta termina com o próximo passo.**
  - "Conhecer a Amplify", "Comissão" e afins terminam com "Quer que eu confira se seu perfil pode entrar? Me manda seu @ do TikTok 👇".
  - Se a resposta já termina numa pergunta, nada é acrescentado, para não ficarem duas perguntas.
- **Lembretes** (15 min, 2 h e 23h30), cada um com um ângulo novo:
  1. "Quer contar com campanhas com marcas e orientação sobre produtos no TikTok Shop? 😊 Me manda seu @…"
  2. "A conferência do seu perfil leva 1 minutinho e você não precisa preencher nada agora. É só me mandar seu @ do TikTok 👇"
  3. "Vou deixar seu atendimento em pausa por aqui. Quando quiser, é só me mandar seu @ do TikTok. 😊" [Quero entrar] [Agora não]
- O @ mandado em resposta é aceito com ou sem "@".

### 3. Conferência logo depois do @
- Saíram as perguntas de nome e de origem. O formulário pede os dois.
- A origem "anúncio" é registrada sozinha quando a primeira mensagem é a mensagem pronta do anúncio.
- Depois do @: "Recebi, @x! Já tô conferindo seu perfil 🔎 Leva menos de 1 minuto."

### 4. Autorização em linguagem de convite
- O bloco das condições sai **uma vez por oferta**:
  > Boa notícia: seu perfil pode entrar na Amplify! 🎉
  > • o seu conteúdo e as suas vendas continuam sendo seus
  > • a Amplify fica com 10% só da comissão que você ganhar (se não vender, não paga nada)
  > • prazo de 2 meses
  >
  > Posso te mandar o convite no TikTok (@x)?
  > [Pode mandar] [Tenho uma dúvida]
- Nas mensagens seguintes, só "Posso te mandar o convite no TikTok? 😊". É o caso da @sarahellen.off, que tinha recebido o bloco 4 vezes.
- "Pode mandar" (e "manda", "pode me mandar"…) autoriza o convite, como antes.
- "Tenho uma dúvida" abre as dúvidas comuns:
  - e se eu não vender?
  - preciso fazer live?
- Os lembretes respondem a uma objeção e nunca repetem o bloco:
  1. "e se eu não vender?";
  2. "preciso fazer live?";
  3. "vou deixar seu convite separado aqui".

### 5. Vínculo confirmado sem cadastro
- Lembretes em **2 h e 23h30**, com o link, que vira o botão *Fazer cadastro*:
  1. "Seu vínculo com a Amplify já está ativo 🎉 Falta só o cadastro: seu acesso ao Club sai na hora em que você envia."
  2. "Passando para lembrar do seu cadastro na Amplify. Leva poucos minutos e o acesso ao Club sai na hora em que você envia. 😊"
- **O lembrete de 72 h não foi feito.** O WhatsApp só aceita mensagem livre até 24 h depois da última mensagem do lead. Depois disso é preciso um template aprovado pela Meta, fora da Bia.

### 6. Dúvidas com o convite pendente
- Com o convite enviado e o vínculo ainda não confirmado, cada dúvida é respondida e termina com o caminho do aceite: "…em *Parcerias* ou *Notificações*… me manda “aceitei”".
- "Conhecer a Amplify", "Como funciona", "Benefícios" e "Comissão" deixaram de cair no menu ou ficar sem resposta. É o caso da ma.ribeiroh.
- Se o modelo não responder, entra o texto do tema aprovado.

### 7. Gravar o @ na ficha: **não está neste pacote**
- A Bia já manda o @ em todo registro de contato (`qualificacao.tiktok_declarado` em `registrar_contato_v5`).
- Quem decide gravar em `interno.creators.tiktok` é a função do banco. Na versão que eu conheço (`v5-integracao-real-20261028`), ela só grava o @ quando o vínculo é confirmado (`tiktok is null`). Por isso só a gabiosantana1 aparece.
- Para mudar, é preciso uma migration nessa função, o que exige a sua autorização.
- **Atenção:** se o @ declarado for gravado em `tiktok`, um @ errado impede depois a gravação do @ confirmado, porque a regra atual só grava quando o campo está vazio. O mais seguro é uma coluna própria, `tiktok_declarado`, que o painel pode ler.
- Antes de escrever a migration, preciso ler a definição atual da função no banco, só leitura.

## Restrições do usuário (testadas em `test_release40_conversao.py`)
- Nenhum texto cita quantos creators há no Club.
- Nada sobre regra depois do prazo: só "prazo de 2 meses".
- Benefícios: só os 4 do cartão aprovado (`beneficios`): campanhas com marcas, orientação sobre produtos e conteúdos, apoio em lives, comunidade de creators. Não há "garantia", "renda", "vender mais" nem "vai ganhar".

## Onde os textos diferem dos propostos
- **Primeira linha:** troquei "A gente ajuda creators … a vender mais" por "A gente apoia creators … com [benefícios]", por causa da restrição de não prometer venda.
- **Apresentação:** mantive "agente de IA" ("Aqui é a Bia, agente de IA da Amplify"), como a Bia já fazia.
- **Linguagem neutra:** troquei "você continua dona do seu conteúdo" por "o seu conteúdo e as suas vendas continuam sendo seus", porque não sabemos o gênero do lead.
- **Nome:** o "{nome}" da autorização só aparece se o nome já for conhecido. A Bia não pergunta mais o nome, e o nome do perfil do WhatsApp não chega até a jornada.
- **Lembrete das 24 h:** sai às 23h30, para caber na janela do WhatsApp.

Todas as conversas estão em `python tests/simular_conversas40.py`, que imprime cada caso.

## Quem recebe mensagem na primeira varredura
**Eu não li o banco de produção.** A lista exata da reconferência sai de `listar_reconferencia.py`, que só lê, sobre uma cópia do `state.sqlite3`:

```
python -I listar_reconferencia.py <cópia do state.sqlite3> [instante ISO]
```

Pelo que se sabe hoje (01/11 por volta das 19h, Brasília):
- **Reconferência:** dos 5 da lista, provavelmente **só a @larvitrine (56748)**.
  - A última mensagem dela foi por volta das 22:16 de 31/10, então o atendimento dela vale até cerca de 22:16 de hoje. Se a 40 subir antes disso e a ponte estiver pronta, ela recebe "Pronto, conferi! ✅" com a autorização, ou o texto de "shop sem status".
  - Emy (56747), Ana Cláudia (56746), Fabi (56751) e Thaina (56752) passaram de 24 h, salvo se escreveram depois. Nesse caso nada sai para elas.
  - Quando elas escreverem de novo (por exemplo, respondendo a um template), a Bia não pede o @ e confere na hora.
- **Retomada:** quem estiver parado entre 15 min e 23h30 recebe o lembrete da etapa com os textos novos. É o mesmo agendamento da 39, só os textos mudam.
- **Pós-pausa:** igual à 39.

## Testes (locais, sem rede)
- **Resultado:** 662 passam, 9 marcados como fora de uso e as mesmas 2 falhas de antes (um teste com data fixa e um arquivo ausente no pacote, que já falhavam na 35).
- **Testes novos:**
  - `src/tests/test_release40.py`: 9 casos de reconferência (Emy e Thaina pelo caminho inteiro, e a ponte oscilando);
  - `src/tests/test_release40_conversao.py`: 19 casos, com as conversas reais:
    - 56754/56750/56749/56745: lembretes diferentes;
    - @larvitrine e @fabi_augusta: conferência logo após o @;
    - @sarahellen.off: o bloco sai uma vez e os lembretes respondem objeções;
    - ma.ribeiroh: as 4 dúvidas respondidas com o aceite;
    - lemosalycee: lembrete do cadastro;
    - a lista inicial dos 5;
    - leitura da ponte na hora;
    - volta depois das 24 h;
    - as 3 restrições.
- **Testes antigos ajustados:** 13 arquivos, todos em `testes-antigos-ajustados.diff`.
  - Eles fixavam o que a auditoria mandou trocar: a pergunta da origem e do nome, o "Se quiser começar", os botões antigos e o texto "Você autoriza enviar esse convite real".
  - Os 9 testes que só verificavam a interpretação da resposta de origem e a pergunta do nome foram marcados com `@unittest.skip`, com o motivo escrito. Essas etapas não existem mais.
- **Mantidos de propósito:** a saudação do comando de teste `resetar`, a da volta de um atendimento encerrado e o "menu" continuam iguais.

## Pacote
- **Release:** `atendimento-v5-release-20261101-40`, com 36 fontes. Os arquivos novos são `reconferencia.py` e `conversao.py`.
- **Hashes:** zip sha256 `1bd9a72e1dcc9cb6c1a8ed6576e3e2e806e05b4682636c5a469af3fd2c09a137`; carregador `42d62d2b…`.
- **Partes:** 10, as mesmas variáveis da 39. O pacote é determinístico: gerado duas vezes, deu o mesmo sha.
- **Diferença de código:** `release40.diff`, de 39 para 40, sem os testes.
- **Interruptores:** `V5_RECONFERENCIA_ENABLED=false` desliga a reconferência. Os textos de conversão não têm interruptor; para voltar a eles, é preciso voltar para a 39.

## Plano de publicação (cada passo só com sua autorização)
0. **Conferir a versão no ar:** o `RELEASE` decodificado de `V5_RELEASE_LAUNCHER_B64` tem de ser `atendimento-v5-release-20261031-39`, e o launcher, igual a `sealed40/volta39/V5_RELEASE_LAUNCHER_B64.txt`. Se for diferente, parar.
1. **Guardar** os 11 valores atuais fora do repositório. `V5_PILOT_PHONES` não muda.
2. **Rodar `listar_reconferencia.py`** numa cópia do `state.sqlite3` (volume `/data`) para ver quem recebe mensagem.
3. **Trocar as 11 variáveis** pelos arquivos de `sealed40/variaveis/` e fazer o redeploy do serviço "Atendimento V5 - Ensaio". Para pegar a @larvitrine, isso precisa acontecer antes de cerca de 22:16 de hoje.
4. **Conferir:**
   - deploy em SUCCESS, sem `v5_release_bootstrap_failed`;
   - `/ready` com `tiktok.followup.reconferencia.enabled=true`;
   - a pasta `/data/releases/atendimento-v5-release-20261101-40`.
5. **Teste no seu número (final 4859):** mandar a mensagem do anúncio, conferir a primeira resposta e mandar o @. Deve chegar "Recebi, @… Já tô conferindo".

## Volta
- Repor os 11 valores da 39 e fazer o redeploy. Reserva: `sealed40/volta39/`, idêntica byte a byte às variáveis do pacote 39.
- O estado é compatível:
  - a 39 ignora `bridge_wait`, `consent_shown` e `lead_recheck_at`;
  - uma reconferência ainda na fila roda normalmente na 39;
  - atendimentos que já passaram da conferência não voltam atrás na 39;
  - um lead que estiver antes da conferência e sem origem receberia de novo, na 39, a pergunta da origem;
  - não há migration.
