# Formulário único → banco novo AmplifyOS-v5

> **Para o estado atual do atendimento (o que está no ar, onde, pontes e melhorias), leia [ESTADO-DO-ATENDIMENTO.md](ESTADO-DO-ATENDIMENTO.md).** Este README é o histórico da preparação, de 30/10.

Preparado em 30/10/2026. **Nada foi publicado.** Nenhum deploy, migration, variável ou dado de produção foi alterado.
Tudo foi testado num PostgreSQL 17 local, descartável, montado com a mesma sequência de migrations do V5.

O link continua um só: `https://amplify-cadastro.up.railway.app/cadastro`, servido com o HTML original sem nenhuma alteração. Não existe link com chave por contato.

## Como funciona

| Etapa do formulário | O que o serviço faz | Onde fica |
|---|---|---|
| 1ª tela: digitar o @ | Consulta **ao vivo** a ponte de agenciamento (`tiktok-agenciamento-production…/bridge`), com o mesmo cliente da Bia (`playwright_client.py`, cópia sem alteração, operação `relationship`) | — |
| ↳ vinculado | Segue para nome, e-mail e WhatsApp | prova guardada na sessão |
| ↳ pendente | Não segue. Mostra: abrir Parcerias ou Notificações no TikTok Shop Creator e aceitar o convite da Amplify | — |
| ↳ não encontrado / falha | Não segue | — |
| E-mail | Código de 6 números por e-mail (SMTP) | sessão |
| Fim da 1ª etapa | `consultar_cadastro_publico_v5` procura a ficha por @, WhatsApp e e-mail, sem gravar | — |
| Fotos | Imagem limpa (sem EXIF) e salva num bucket privado | Storage `cadastro-privado` |
| Print do GMV | O robô lê o print em segundo plano assim que ele é enviado | sessão |
| Envio final | `registrar_cadastro_publico_v5`, numa transação só | banco novo |

### O que o envio grava (só em tabelas que já existem)

- **`interno.creators`**: os 63 campos, com o mesmo mapa e a mesma validação da Bia. Também grava `cadastro_situacao='confirmado'`, `formulario_situacao='recebido_formulario_publico'`, o consentimento, a confirmação do e-mail e `canal_entrada='formulario_publico'` (só para ficha nova).
- **`interno.agenciamentos`**: o vínculo confirmado (`fonte='tiktok_partner_center'`, `conta_referencia='formulario_publico'`), com a mesma regra da RPC de contato.
- **`interno.gmv`**: uma linha `entrada / declarado` com o valor digitado. O comprovante é o print.
- **`interno.eventos`**:
  - `cadastro_confirmado`, com a prova do vínculo e o resumo da leitura;
  - `gmv_atualizado`, com a leitura do print: valor, moeda, período, leitor, motivo e o sinal `diverge_do_digitado` (diferença acima de 10%).
- **`interno.atendimentos`**: não é alterado. Para um lead da Bia, os eventos e o GMV só são ligados ao atendimento aberto.

**Mesma ficha.** Quando o @ e o WhatsApp batem com uma ficha que já existe (lead da Bia), o cadastro é gravado nela. Quem chega por fora ganha ficha nova. Os casos abaixo vão para conferência e nada é gravado:

- @ ligado a outro WhatsApp;
- WhatsApp ligado a outro @;
- e-mail que já está em outra ficha.

A pessoa recebe uma mensagem clara em cada caso. Ficha já confirmada não é sobrescrita.

**Robô do print.** A IA (OpenAI Responses, o mesmo provedor da Bia) só transcreve o texto do GMV e as datas. O valor é calculado por regra fixa. Leitura incerta, imagem errada ou falha ficam como `indisponivel`, sem valor: nunca viram zero e nunca viram GMV verificado.

### Regras do banco descobertas no teste local

Essas regras não apareciam no catálogo de 28/10; a migration foi ajustada para respeitá-las:

1. **Só existe uma linha de GMV `entrada` por natureza** (índice `gmv_uma_entrada_por_natureza_idx`). Por isso a leitura do print não ganhou linha própria: ela fica no evento `gmv_atualizado`, ligado à linha declarada.
2. **`historico_jornada` é somente leitura.** O histórico fica em `eventos`.
3. **`creators.gmv_entrada_id` só pode apontar para GMV verificado**, porque é a referência da categoria do Circle. O formulário não mexe nesse campo.

## Arquivos

- `sql/001_cadastro_publico_v5.sql` — **migration para revisão** (SHA-256 `2e980b03…69d7e`). Cria só:
  - o bucket privado `cadastro-privado`;
  - `interno.cadastro_publico_resolver`;
  - `public.consultar_cadastro_publico_v5`;
  - `public.registrar_cadastro_publico_v5`.

  As três funções só podem ser executadas por `service_role`. A migration não cria nem altera tabelas, colunas, constraints, triggers nem as funções da Bia. Um guard aborta tudo se o catálogo de produção estiver diferente do esperado.
- `sql/build_migration.py` + `template_…sql` — geram a migration. A validação dos 63 campos e o upsert da ficha são copiados **literalmente** de `registrar_cadastro_ensaio_v5` (a fonte é conferida por hash).
- `sql/001_reverter_cadastro_publico_v5.sql` — volta para trás (remove as 3 funções e o bucket, se estiver vazio).
- `app/` — o serviço novo (Flask/gunicorn). Arquivos copiados **sem alteração**:
  - `static/cadastro.html` (original);
  - `cadastro_pilot.py` (mantém vivo o `/cadastro/ensaio` que a Bia envia hoje);
  - `playwright_client.py`;
  - `data/` (mapa de 63 campos).
- `tests/` — 17 testes (`pytest tests`) e `run_local_server.py`, que serve o formulário real com o banco local.

## Testes feitos (todos locais)

- **17/17 testes passando** contra o PostgreSQL local com a migration aplicada:
  - um @ vinculado passa e grava tudo: ficha, agenciamento, GMV declarado, evento da leitura e evento do cadastro;
  - reenviar não duplica;
  - um @ não vinculado é barrado na 1ª etapa e também ao tentar pular a checagem;
  - um @ pendente recebe a orientação de aceite;
  - um lead da Bia cai na mesma ficha e fica ligado ao atendimento aberto;
  - o mesmo @ com outro WhatsApp vai para conferência;
  - um print ilegível fica `indisponivel` sem valor;
  - o banco recusa prova pendente, @ diferente, evento forjado, leitura incoerente e e-mail não confirmado;
  - `anon` não executa as funções;
  - o link `/cadastro/ensaio` continua funcionando.
- **Navegador, com o HTML original:**
  - `@sem.vinculo` → bloqueado (“Não encontramos vínculo…”);
  - `@convite.pendente` → orientação de aceite;
  - `@vinculada.ok` → passou, o código de e-mail foi confirmado, a identidade foi validada e a etapa 2 abriu.

  As etapas 2 a 6 e o envio final estão cobertos pelos testes de API (os mesmos endpoints).
- **Não testado contra o real:** a ponte de agenciamento de produção, o SMTP, a OpenAI, o Supabase novo e o Storage. Isso é a parte do smoke test descrita abaixo.

## ⚠️ Riscos — decidir antes de publicar

1. **Entrega dos acessos (Circle e boas-vindas) deixa de acontecer para quem usar o formulário.** Hoje a entrega lê o banco antigo. Os cadastros novos vão para o banco novo, e nada no banco novo libera o Circle (o formulário mostra “Cadastro recebido… acompanhe com o atendimento”). Precisa de um consumidor no V5 ou de entrega manual. **É o maior risco.**
2. **A Bia não fica sabendo** quando um lead dela usa o link público: a ficha vira `confirmado`, mas o atendimento continua aberto. O link `/cadastro/ensaio` da Bia continua igual. Passar a Bia para o link único é um passo separado.
3. **Ponte de agenciamento:** cada checagem abre o Chromium. Por isso há limites:
   - 2 consultas em paralelo;
   - 8 por sessão a cada 10 minutos;
   - 20 por IP a cada 10 minutos;
   - se passar de 38 s, a pessoa vê “ainda consultando, toque de novo”.

   A ponte não é republicada (trava `SingletonLock`).
4. **A imagem do print vai para a OpenAI** (contém números de vendas). Isso precisa da sua aprovação e da definição de `GMV_PRINT_MODEL`. Sem o modelo configurado, toda leitura fica `indisponivel` e o resto funciona.
5. **O estado temporário fica em `/tmp`.** Se o serviço reiniciar, quem estiver no meio do preenchimento precisa reconfirmar o e-mail. O @ é reconferido sozinho. Opcional: um volume no Railway.
6. **Quem estiver preenchendo o formulário antigo na hora da troca** perde a sessão e, em geral, o rascunho local, porque a revisão do servidor muda. Os links pessoais antigos passam a redirecionar para `/cadastro`.
7. **Risco que já existia:** alguém pode cadastrar um @ vinculado que ainda não está no banco usando o próprio WhatsApp e e-mail. O e-mail é provado; a posse do TikTok, não.
8. **O catálogo usado é dos arquivos de 28 e 29/10.** O guard da migration confere o catálogo na hora de aplicar.

## Plano de publicação (cada passo só com a sua autorização)

0. **Leitura, sem alterar nada.**
   - Anotar o deployment ativo do serviço Cadastro (`ebace04d…`), que é o alvo da volta para trás.
   - Ler o catálogo do V5: colunas, índices e o bucket ainda inexistente.
   - Confirmar como o Cadastro é publicado hoje (os recibos `verify_publication25/30`).
1. **Migration** `001_cadastro_publico_v5.sql` no `divlvdmsqbwplervsqwu`. Inofensiva sozinha: ninguém chama as funções ainda.
2. **Variáveis do serviço Cadastro.** Usar referências do Railway sempre que possível, sem copiar segredos.

   **Novas:**
   - `SUPABASE_V5_URL` e `SUPABASE_V5_SERVICE_KEY` (referência à chave do V5 que o “Atendimento V5 - Ensaio” já usa);
   - `V5_TIKTOK_AGENCY_TOKEN` (referência a `TIKTOK_INVITE_SERVER_TOKEN` do serviço TikTok Agenciamento);
   - `SMTP_USUARIO` e `SMTP_SENHA_APP`;
   - `OPENAI_API_KEY` e `GMV_PRINT_MODEL`;
   - `CADASTRO_PUBLICO_V5_ATIVO=true`.

   **Mantidas:** `ONBOARDING_FORM_SECRET`, `ONBOARDING_PUBLIC_URL`, `CADASTRO_V5_PILOT_ENABLED`.

   **Sem uso, mas não apagar até o fim:** `SUPABASE_URL` e `SUPABASE_SERVICE_KEY` (banco antigo).
3. **Deploy** do conteúdo de `app/` (Dockerfile próprio) num horário de pouco movimento.
4. **Smoke test** com o seu próprio @ e WhatsApp:
   - um @ não vinculado é barrado;
   - o seu @ vinculado passa;
   - o envio completo funciona;
   - conferir no banco a ficha, o agenciamento, o GMV e os 2 eventos;
   - `/cadastro/ensaio` continua respondendo.
5. **Acompanhar os logs** (`[cadastro-publico-v5]`) por 24 h.

**Volta para trás:**
- **Rápida:** redeploy do deployment anotado no passo 0. O formulário antigo volta a gravar no banco antigo. As variáveis novas podem ficar, porque o código antigo não as lê.
- **Banco, opcional:** `001_reverter_cadastro_publico_v5.sql`. Os cadastros já recebidos ficam no V5 e são encontrados por `eventos.instancia='formulario_publico'` ou `creators.formulario_submissao_referencia LIKE 'cadastro-publico-v5:%'`.
- **Desligar a API pública sem redeploy:** `CADASTRO_PUBLICO_V5_ATIVO=false`. O formulário mostra “em manutenção”.

## Rodar localmente

```
pytest tests --basetemp <pasta-temporária>      # PostgreSQL local descartável, sem rede
python tests/run_local_server.py                 # http://127.0.0.1:8765/cadastro
```

Usa o PostgreSQL portátil em `.maestri/…/pgsql`, copiado para uma pasta ASCII em `%TEMP%`.

## Reativar o que já existia (orientação de 30/10, tarde)

O que o código antigo fazia de verdade (lido em `deployment-source/cadastro_worker.py` e `src/cadastro_delivery.py`, e nas migrations 086/090/115):

| Função pedida | Como era | Situação aqui |
|---|---|---|
| Confirmação de e-mail por código | Fila no banco antigo + thread do worker (Gmail API) | Já reativada no formulário: mesmo HTML, mesmos endpoints, envio direto por SMTP |
| Checagem de agenciamento | `cadastro_v5_consultar_agenciamento_publico` no banco **antigo**, com tabela parada desde 27/10 (por isso `gabiosantana1` aparece como “não ativo”) | Substituída pela consulta **ao vivo** na ponte de agenciamento |
| Criar acesso no Circle | Worker (`deliver` + `Circle.provision`, grupos Start/Silver/Gold/Diamond, e-mail de boas-vindas, aviso no Chatwoot) | **Ainda não ligado ao banco novo** |
| Leitura do print de GMV | **Não existia.** A entrega esperava um GMV **verificado de 28 dias do Partner Center** (`gmv_registros`, `tipo='partner_verificado'`, motivo `gmv_verificado_28_dias_pendente`). O print era só guardado. | Robô novo, gravando como **declarado** |

Religar os serviços antigos “apontando para o banco novo” sem reescrever exigiria recriar no V5 cerca de 20 RPCs `cadastro_v2_*`/`v3_*` e as tabelas `onboardings`, `cadastro_entregas`, `gmv_registros` e a fila de e-mail. Isso é a estrutura paralela que foi vetada.

Proposta: reaproveitar **literalmente** o código do Circle (`Circle.provision`, `welcome_message`, `welcome_templates.json`, `ChatwootAccessNotifier`) num consumidor que leia o banco novo. O estado da entrega usaria colunas e eventos que já existem:
- colunas `creators.circle_categoria_entrada`, `circle_cargos_entrada`, `circle_situacao`, `circle_acesso_criado_em`, `acesso_referencia`;
- eventos `acesso_solicitado`, `acesso_entregue`, `email_aceito_provedor`, `email_falha`.

Antes, falta uma decisão: **qual GMV define a categoria do Circle**.

## Autorização única para publicar (30/10)

Feito e testado: o formulário, a checagem do @ ao vivo, o código por e-mail, a gravação no V5 e a **criação do acesso no Circle**. O Circle usa `legado/cadastro_delivery.py` copiado sem alteração, com e-mail de boas-vindas. A categoria é **Start** enquanto não houver GMV verificado; o código antigo já sobe a categoria depois. São 17 testes locais passando.

1. **Migration** `sql/001_cadastro_publico_v5.sql` no V5 (`divlvdmsqbwplervsqwu`). Cria o bucket privado e 5 funções; não cria tabelas.
2. **Variáveis do serviço Cadastro.** São só referências do Railway; nenhum segredo é copiado.

   | Variável | Vem de |
   |---|---|
   | `SUPABASE_V5_URL` | `${{Atendimento V5 - Ensaio.V5_SUPABASE_URL}}` |
   | `SUPABASE_V5_SERVICE_KEY` | `${{Atendimento V5 - Ensaio.V5_SUPABASE_SERVICE_KEY}}` |
   | `V5_TIKTOK_AGENCY_TOKEN` | `${{Atendimento V5 - Ensaio.V5_TIKTOK_AGENCY_TOKEN}}` |
   | `SMTP_USUARIO`, `SMTP_SENHA_APP` (código do e-mail) | o mesmo da Bia |
   | `CIRCLE_ADMIN_TOKEN`, `GMAIL_SENDER`, `GMAIL_API_*` (boas-vindas) | serviço “Entrega de Acessos” |
   | `CADASTRO_EMAIL_TRANSPORT` | `gmail_api` |
   | `CADASTRO_PUBLICO_V5_ATIVO` | `true` |
   | `CADASTRO_ENTREGA_CIRCLE_ATIVA` | `true` |

   As variáveis antigas ficam como estão.
3. **Deploy** do conteúdo de `app/` no serviço Cadastro (`railway up --service Cadastro`, a partir de `app/`).
4. **Smoke test:**
   - `priscila.matias44` → barrado;
   - `lemosalycee` → orientação de aceite;
   - `gabiosantana1` → passa da etapa 1.

   O envio completo fica com o lead real ou com o seu número.

**Volta para trás:** `railway redeploy` do deployment `384e3cec-c135-4afe-b6ff-18ca56e00aec`, que volta o formulário antigo. Para desligar sem redeploy, `CADASTRO_PUBLICO_V5_ATIVO=false` (o formulário fica em manutenção) e `CADASTRO_ENTREGA_CIRCLE_ATIVA=false` (para o Circle). A migration é inofensiva parada; existe `001_reverter…sql`, e nenhum dado é apagado.

Ficou para depois: o print de GMV, que precisa de `OPENAI_API_KEY` e `GMV_PRINT_MODEL`. Sem essas variáveis a leitura fica “indisponível” e o resto funciona. O aviso no Chatwoot também ficou para depois, porque quem fala no Chatwoot é a Bia.

## Pacote "ativar para todos" (31/10) — pronto localmente, aguardando autorização

28 testes passando.

- **`sql/004_retomar_entrega_e_aviso.sql`**
  - A entrega do acesso se recupera sozinha: até 3 tentativas, com 10 minutos entre elas.
  - Uma nova tentativa só refaz o que falta: o Circle não é recriado e as boas-vindas não são reenviadas.
  - Devolve a conversa do Chatwoot do lead.
  - Nova função `listar_entregas_pendentes_v5`.
- **`sql/005_conversa_alimenta_ficha.sql`**
  - Um gatilho em `atendimentos` leva para a ficha: origem, interesse, aceite de convite, validação, situação do convite, pendência e próximo passo.
  - O @ declarado na conversa não vai para a ficha antes de o vínculo ser confirmado.
  - Preenche as fichas existentes uma vez. Foi ensaiado nos dados reais com ROLLBACK, sem alterar o número de eventos.
- **`app/`**
  - Retomada automática a cada 5 minutos e alerta por e-mail (`ALERTA_EMAIL`) quando as 3 tentativas se esgotam.
  - Aviso "acesso liberado" no WhatsApp, com o `ChatwootAccessNotifier` antigo.
  - Guarda por 6 h o resultado "vinculado" da ponte e por 1 h os grupos e etiquetas da Circle.
  - Contador do código de e-mail atômico, com teto de 10 tentativas, que não zera ao reenviar.
- **Variáveis novas no Cadastro**
  - `CHATWOOT_BASE_URL`, `CHATWOOT_ACCOUNT_ID` e `CHATWOOT_API_TOKEN`, por referência ao serviço da Bia.
  - `CADASTRO_AVISO_ACESSO_CHATWOOT_ATIVO=true`.
  - `ALERTA_EMAIL`.
  - Volume no Railway em `/data` + `CADASTRO_STATE_PATH=/data/cadastro-publico-v5.sqlite3`.

**Fica fora deste pacote:**
- trocar o link da Bia para `/cadastro` e abrir a Bia para todos (sessão da Bia);
- Turnstile, que precisa de uma chave da Cloudflare;
- consentimento separado para dados sensíveis, que precisa do texto revisado pelo jurídico.

## Etiqueta de acesso no Chatwoot

Aplique `sql/010_destino_etiqueta_acesso_circle.sql` antes de ativar a projeção. Ative `CADASTRO_CHATWOOT_ETIQUETA_ACESSO=acesso-liberado` somente após confirmar a etiqueta no catálogo da conta de produção. O valor vazio desativa a projeção. A conta vem de `CHATWOOT_ACCOUNT_ID`; a caixa esperada pode ser definida em `CADASTRO_CHATWOOT_ETIQUETA_CAIXA` (padrão: `3`). São usados o mesmo endereço e token do Chatwoot já configurados.

O fluxo acrescenta apenas a etiqueta de acesso após confirmação no Circle, sem tocar nas outras etiquetas ou nas mensagens. O retorno da ação em lote é apenas uma entrada na fila. Confirme a etiqueta pela leitura independente; se a falha persistir, reconcilie a etiqueta a partir dos eventos de acesso confirmados, sem reprocessar a entrega.

Para desligar a escrita, remova o valor de `CADASTRO_CHATWOOT_ETIQUETA_ACESSO` e reaplique a configuração. Isso não remove etiquetas existentes. Para desfazer uma aplicação específica, retire só a etiqueta de acesso da conversa verificada, sem alterar as demais.
