# Atendimento Amplify: documento principal

Atualizado em 03/11/2026 às 01h (Brasília). Tudo o que está no ar, onde fica, como funciona e o que falta. As auditorias antigas ficam como histórico (lista no fim).

---

## 1. Situação agora

| | Item | Situação |
|---|---|---|
| ✅ | **Bia** (WhatsApp) | release **46** no ar (deploy `ab8dd843`), `/ready` pronto |
| ✅ | **3 pontes do TikTok** | autenticadas, sem erro |
| ✅ | **Formulário** `/cadastro` | no ar, grava no banco novo |
| ✅ | **Acesso ao Circle + boas-vindas** | automático, em cerca de 5 s depois do envio do formulário |
| ✅ | **Alertas por e-mail** | ponte caída, lead parado, Bia fora do ar (só quando ela não responde mesmo) |
| ✅ | **Diagnóstico** | a Bia registra o motivo de cada conversa que não respondeu |
| ⚠️ | **Piloto** | só **37 telefones** têm a Bia; o resto recebe "manutenção" |
| ⚠️ | **Ponte de Convites** | volta com o login, mas ainda pede o clique em "Concluí" |

## 2. Resultado (30/10 a 02/11)

**8 creators com acesso liberado, sem nenhuma intervenção manual na entrega:**

| Creator | Categoria | Cadastro |
|---|---|---|
| gabiosantana1 | Start | 30/10 17:43 |
| lumasantostiktokshop | Gold | 31/10 21:47 |
| kimberlyemorganashop | Diamond | 01/11 21:20 |
| mydearshop8 (Cristiane) | Start | 02/11 08:21 |
| arianyriibeiro | Start | 02/11 14:16 |
| viralstoresbr | Start | 02/11 14:42 |
| alexsantosvpc | Start | 02/11 20:56 |
| luna.achadinhosia | Start | 02/11 22:00 |

- **As 5 primeiras entraram no Circle entre 2 e 10 min depois do acesso.**
- Jornada típica, a da Cristiane: autorizou às 08:02 e entrou no Circle às 08:24. Foram 22 min, dos quais 19 foram dela aceitando o convite e preenchendo o formulário. A máquina levou cerca de 5 s.
- **Conversão do lote de 02/11 (40.x):** 7 de 8 mandaram o @, 6 autorizaram o convite e 4 já têm acesso. Antes da 40, só 50% mandavam o @.
- **Conversas do piloto agora (28):** 8 em cadastro, 8 em validação, 3 com convite, 5 em "conhecer" e 4 sem etiqueta.

---

## 3. As peças: onde estão e como funcionam

| Peça | Onde | Como funciona |
|---|---|---|
| **Bia** | Railway › "Atendimento V5 - Ensaio". Pacote em `artifacts/claude-bia-release46-20261102/` | O código roda de um zip selado guardado nas variáveis `V5_RELEASE_ARCHIVE_PART_1..12` + `V5_RELEASE_LAUNCHER_B64`. Publicar = trocar as variáveis + redeploy (`railway up` **não** muda o código) |
| **Piloto** | `V5_PILOT_PHONES` (Bia, limite 100) + regra 3 do Chatwoot | A Bia só atende a lista. A regra 3 manda "manutenção" para quem está fora; os números da lista ficam na exceção (com e sem "+") |
| **Formulário + entrega** | Railway › "Cadastro" (`amplify-cadastro.up.railway.app/cadastro`). Código em `artifacts/claude-cadastro-v5-20261030/app/` | Confere o vínculo na ponte de agenciamento, lê o print do GMV, grava a ficha, cria o acesso no Circle (categoria pelo GMV), manda as boas-vindas (o lead entra com o mesmo e-mail e cria a senha) e avisa no WhatsApp |
| **Banco** | Supabase `divlvdmsqbwplervsqwu` | Migrações 001 a 006 em `.../claude-cadastro-v5-20261030/sql/`. Ficha em `interno.creators`, conversa em `interno.atendimentos` (@ declarado em `qualificacao.tiktok_declarado`) |
| **Alertas** | dentro do Cadastro → `ALERTA_EMAIL` | **Só erro da máquina.** Pontes a cada 5 min. A cada 10 min: lead sem resposta da Bia há mais de 30 min (sem atendente humano) e Bia fora do ar. Lead esperando a si mesmo não gera e-mail. O que já foi avisado fica gravado e não se repete depois de reiniciar |
| **Login das pontes** | link único `amplify-cadastro.up.railway.app/pontes/<PONTES_LINK_SEGREDO>` | Abre direto a tela de login do TikTok da ponte caída |
| **Reconexão automática** | Cadastro (`app/pontes.py`) | Reabre o Partner Center e ativa sozinha as pontes de Agenciamento e Pré-validação quando o navegador ainda está logado |
| **Diagnóstico** | `GET /diagnostico/conversa/<id>` na Bia, com o bearer `V5_WEBHOOK_TOKEN` | Mostra o estado da Bia na conversa e o motivo de cada decisão. O `/ready` mostra `puladas_por_motivo` |

## 4. As 3 pontes do TikTok

| Ponte | Para que serve | Se cair | Volta sozinha? |
|---|---|---|---|
| **Pré-validação** | conferir se o @ pode entrar | a Bia avisa o lead e reconfere quando volta | ✅ se o navegador seguir logado |
| **Convites** | enviar o convite | o convite fica "em conferência" e a Bia confirma pela lista de vínculos | ✅ se o navegador seguir logado: o Cadastro reabre e reinicia sozinho (1 vez a cada 30 min). Com login de verdade, ainda pede o clique em "Concluí" |
| **Agenciamento** | lista de vínculos (fonte de verdade) e formulário | ninguém passa no formulário | ✅ se o navegador seguir logado |

**Única manutenção esperada:** quando chegar o e-mail "🔴 Ponte … pediu login", abrir o link e fazer o login no TikTok.

## 5. A automação da Bia (release 46)

| Etapa | O que acontece sozinho |
|---|---|
| 1ª mensagem | vende em poucas linhas e pede o @; aceita o link `tiktok.com/@…`; explica onde achar o @ |
| @ recebido | confere o perfil na hora, sem perguntar nome nem origem |
| Perfil aprovado | pede a autorização em tom de convite, com botões; responde dúvidas antes de pedir de novo |
| Convite | só diz "enviado" quando o @ aparece na lista de vínculos; se não aparece, reenvia uma vez |
| Aceite | lê a lista de vínculos (15 min, 2 h, depois 1 vez por dia); com `linked`, manda o cadastro sem esperar o "aceitei" |
| Depois do acesso | continua respondendo (Club, missões, Circle com o mesmo e-mail) e para os lembretes de convite |
| Ponte caída | uma mensagem honesta ("o TikTok tá lento, eu confiro sozinha") e reconferência quando ela volta |
| Mensagem sem resposta | a cada minuto, responde uma vez quem ficou sem resposta no Chatwoot (inclusive à noite) |
| Lembretes | 15 min / 2 h / 24 h, cada um com um ângulo novo, só das 8h às 20h45 |

Cada código de retorno das pontes (`linked`, `pending`, `not_found`, `eligible`, `failed`, bloqueios…) tem uma ação e uma mensagem. Um teste falha se algum código ficar sem tratamento. A tabela completa está no README da release 43.

---

## 6. O que ainda falta para ficar 100% automático

| # | Falta | Proposta | Depende de |
|---|---|---|---|
| 1 | 🔴 **Entrada de leads é manual** (lotes de 10, escolhidos à mão) | Todo lead novo de anúncio entra na Bia sozinho; ficam fora só "Renovacao de contrato" e as conversas de atendente | sessão da Bia + autorização |
| 2 | 🟠 **Leads parados há mais de 24 h** (janela do WhatsApp fechada) | Retomada com modelo aprovado da Meta, em 26 h e 72 h | aprovação dos modelos na Meta |
| 3 | 🟠 **Ponte de Convites** ainda pede o "Concluí" | Republicar com a versão das outras duas | autorização |
| 4 | 🟡 **Ver a conversão** depende de pedir | Relatório diário às 8h com ✅/❌ e o funil | autorização |
| 5 | 🟡 **32922 "Não tenho interesse"** | Responder uma vez com respeito e encerrar (já está na 43+; conferir no próximo caso) | — |
| 6 | 🟡 **Republicar derruba a Bia por cerca de 40 s** | Agrupar as mudanças em menos publicações; quem escreve nesse intervalo é respondido logo depois | — |

## 7. Erros que tive nesta rodada (para não repetir)
- **56938:** afirmei que estava sem resposta, mas a Bia tinha respondido às 19:52. Eu conferi às 19:51. Isso gerou releases a mais e uma saudação repetida, mandada à mão às 23:12.
- **viralstoresbr:** afirmei que não tinha recebido nada, mas ela fez o cadastro às 14:42 e tem acesso.
- **Regra a partir de agora:** antes de dizer "sem resposta", ler a conversa inteira e usar o `/diagnostico/conversa/<id>`.

---

## 8. Como operar (passo a passo curto)

- **Publicar a Bia:**
  1. Conferir o `RELEASE` no ar.
  2. Guardar as variáveis atuais (volta).
  3. Gravar as variáveis do pacote novo com `--skip-deploys`.
  4. Fazer o redeploy.
  5. Conferir o `/ready` e o diagnóstico.

  **Para voltar da 46 para a 45**, repor as 11 partes e **apagar a `V5_RELEASE_ARCHIVE_PART_12`**.
- **Publicar o Cadastro:** rodar `railway up -s Cadastro --ci` dentro de `.../claude-cadastro-v5-20261030/app/`.
- **Liberar leads, enquanto o item 6.1 não sair:**
  1. Acrescentar o telefone em `V5_PILOT_PHONES` e fazer o redeploy da Bia.
  2. Pôr o número, com e sem "+", na exceção da regra 3.
  
  A Bia responde sozinha quem escreveu nas últimas 23 h.
- **Ponte pediu login:** usar o link do e-mail. Na de Convites, clicar em "Concluí" no fim.
- **Toda mudança em produção** exige autorização em cada passo.

## Histórico
Os arquivos ficam nesta pasta: `AUDITORIA-10-ATENDIMENTOS.md`, `AUDITORIA-CONVERSAO-20-ATENDIMENTOS.md`, `AUDITORIA-POS-RELEASE-40.md`, `AUDITORIA-EXTERNA.md`, `AUDITORIA-CHATS-E-DADOS.md`, `AUDITORIA-ATENDIMENTO-E-ENTREGA.md` e `README.md` (preparação do formulário).

As releases ficam em `artifacts/claude-bia-release40…46-*/`, cada uma com README, diff e testes.
