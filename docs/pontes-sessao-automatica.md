# Pontes do TikTok: sessão automática (plano, 23/11/2026)

**Em 1 linha:** a ponte só vai pedir você quando o TikTok pedir e-mail e senha. Todo o resto ela resolve sozinha.
E quando você entrar em uma, as outras pegam a mesma sessão.

## Por que hoje pede login tanto

Lido no código (`pontes/tiktok-ponte/server-quente.mjs` e `railway-supervisor.mjs`):

| Situação | Hoje | Sessão do TikTok ainda vale? |
|---|---|---|
| Ponte reinicia (deploy, queda, manutenção do Railway) | Sobe em "modo login" e espera você clicar | **Sim**: os cookies ficam no disco (`/data`) |
| Qualquer erro numa operação (lentidão, página travada) | Fecha o navegador e espera você | **Quase sempre sim** |
| TikTok expira a sessão ou pede verificação | Espera você | Não: aqui precisa de você mesmo |
| 3 pontes, 3 navegadores | Você entra 3 vezes | — |

Ou seja: a maior parte dos "logins" é só **reativar uma sessão que ainda funciona**.

## Como fica

### 1. Volta sozinha (sem você)

- Ao subir: abre o navegador com os cookies do disco, vai ao Partner Center, faz **1 leitura de prova**
  (1 item da lista, só leitura) e se ativa sozinha.
- Depois de um erro: não fecha tudo. Recarrega a página e tenta a leitura de prova de novo:
  3 tentativas, com espera crescente (30 s, 2 min, 10 min).
- Mantém a sessão viva: a leitura de prova a cada poucos minutos, que já existe, continua.

### 2. Só pede você quando precisa mesmo

- A ponte reconhece quando o TikTok mostra a **tela de login** ou pede **verificação** (e-mail, senha, código).
  Só aí ela para e entra em "precisa de você".
- **Aviso automático**: e-mail e WhatsApp para o time com o link do painel da ponte. Hoje ninguém é avisado.
- A proteção contra bloqueio do TikTok (pausa quando o TikTok reclama de excesso) continua igual.

### 3. Renovou uma, renovou todas

- Quando você entra em uma ponte, ela guarda a sessão (cookies) **criptografada** e manda para as outras pela
  rede interna do Railway (não sai para a internet).
- As outras recebem, fazem a leitura de prova e se ativam sozinhas.
- Também ao contrário: se uma ponte perder a sessão, ela primeiro pede a sessão atual às outras, e só depois chama você.

⚠️ Risco a testar: o TikTok pode estranhar a mesma sessão em dois servidores. Por isso: testar primeiro entre
2 pontes, observar 48 h e só depois ligar na terceira. Se o TikTok derrubar, desligamos o compartilhamento
(as partes 1 e 2 continuam valendo sozinhas).

### 4. Menos navegadores

Agenciamento e Pré-validação rodam **o mesmo código**. Juntar as duas num serviço só, com os dois papéis:
- 1 login a menos;
- menos custo (cada uma reserva 4 GB / 2 vCPU).

Fica para depois das partes 1 a 3 funcionarem.

## Ordem e segurança

| Passo | O que | Onde testa primeiro |
|---|---|---|
| 1 | Volta sozinha + reconhece tela de login | Testes locais com navegador falso; depois Pré-validação |
| 2 | Aviso automático para o time | Só o seu número primeiro |
| 3 | Sessão compartilhada | Pré-validação ↔ Agenciamento, observar 48 h |
| 4 | Juntar Agenciamento + Pré-validação | Depois que 1 a 3 estiverem estáveis |

Junto com o passo 1, sobe a melhoria de detalhes da parceria (`?detalhes=1`), que já está pronta e testada.

Em cada publicação: só uma ponte por vez, conferir `/ready`, e voltar à versão anterior se não ficar pronta em 5 min.
O login guardado em `/data` não é apagado em nenhum passo.

## Passo 1 publicado (23/11/2026) ✅

Na **Agenciamento** e na **Pré-validação** (mesmo código, `pontes/tiktok-ponte`) e na **Partner Bridge**.

| O que | Como |
|---|---|
| Lembra onde estava | `/data/partner-context.json`: endereço da lista e página de parcerias do último login |
| Volta sozinha | Ao subir e depois de erro: 30 s, 2 min, 10 min, depois a cada 30 min |
| Trava do Chrome | Remove a trava deixada por container antigo (era a causa de "precisa logar" depois de reinício) |
| Só pede humano | Quando o TikTok mostra a tela de login/verificação |
| Erro de configuração | Contexto nunca aprendido (ex.: relatório de GMV) não fecha mais o navegador |
| Ver o estado | `/health` interno → `autoRecuperacao` (estado, tentativas, próxima, último resultado) |

Resultado: 5 publicações hoje. 4 reativaram sozinhas (12:25, 12:29, 12:37, 12:39 UTC), nenhum login.
A de 12:32 na Pré-validação não abriu o Chrome (trava órfã); a correção da trava saiu às 12:36 e resolveu.

Lições do dia:
- Às 12:21 uma operação passou de 2 min e a Agenciamento ficou parada esperando humano — o caso clássico.
- `/gmv-report` na Agenciamento derrubou a sessão (precisa da tela de relatórios). Voltou a ficar só no papel `gmv`.

### Partner Bridge (23/11, 13:30 UTC)

Código de outra geração: ela já reabria o navegador e voltava à página de parcerias sozinha. Faltava só a
**trava órfã do Chrome** (`trava-chrome.mjs`). Publicada: subiu, removeu a trava do container antigo e ficou pronta
sem login. Testes: 50 passando; 1 falha antiga (procura um arquivo de referência que não veio do container).

## Passo 2 publicado (23/11/2026, 13:47 UTC) ✅

O **vigia das pontes já existia** no Cadastro (`cadastro/app/vigia_ponte.py`): lê `/bridge/ready` de cada ponte a
cada 5 min e, depois de 2 leituras pedindo login (5 a 10 min), manda **e-mail** para `ALERTA_EMAIL` com o botão do
painel de login, e outro quando a ponte volta. Antes não avisava em mais nenhum lugar.

Novo: o mesmo aviso vai também para o **Telegram** (grupo **Aquisição HQ**, tópico das pontes), pelo bot
@AmplifyAquisicao_bot que já estava configurado (`cadastro/app/telegram_alerta.py`). Um canal com erro não bloqueia o outro.
Testes: 4 novos; suíte do Cadastro e CI verdes. Publicado: formulário 200, pontes `ready=3 login=0`.

Como a volta sozinha tenta em 30 s, 2 min e 10 min, o aviso só sai quando ela não resolveu (TikTok pedindo login
de verdade ou ponte fora por mais de ~10 min).

Próximo: passo 3 (renovou uma, renovou todas).
