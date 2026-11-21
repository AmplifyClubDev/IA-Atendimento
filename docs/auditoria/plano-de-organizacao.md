# Plano de organização — Railway, banco, GitHub (20/11/2026)

**Em 1 linha:** dá para cortar o Railway de 19 para 10 serviços e o GitHub de 35 para ~5 branches sem quebrar nada,
desde que a ordem abaixo seja seguida. Nada foi alterado. Cada passo espera o seu ok.

## 0. Avaliação do que já está funcionando (dados reais de produção)

| Ponto | Resultado | Evidência |
|---|---|---|
| Cadastro confere o vínculo do @ | ✅ 211 de 211 cadastros têm agenciamento confirmado | eventos × agenciamentos |
| Acesso ao Circle | ✅ 210 de 211 entregues; caminho normal em ~6 s | `Acesso entregue` |
| Pendente | ⚠️ 1 pessoa do incidente do Circle (16–19/11) ainda sem acesso | `acesso = Revisao Manual` |
| E-mail de boas-vindas | ✅ 210 aceitos pelo Gmail API | `E-mail aceito para envio` |
| E-mail do código (formulário) | ❓ não fica no banco, não dá para medir | SQLite do Cadastro |
| Vídeos (aceitar convite, ativar Shop) | ✅ no ar, idênticos aos aprovados | sha256 e tamanho |
| Vídeo "sair de outra agência" | ⛔ não existe (mensagem vai sem vídeo) | bucket `bia-orientacoes` |
| E-mail da Bia | Só no formulário antigo; no fluxo real quem envia é o Cadastro | `bia/forms.py` |

**Aviso:** o Codex fez um redeploy do Cadastro hoje às 17:27 UTC com um patch novo (`vinculo-clock`).
O patch já foi copiado para `cadastro/app/publico.py`. Duas ferramentas mexendo em produção ao mesmo tempo é risco:
combinar quem publica.

## 1. Railway — de 19 para 10 serviços

**Ficam (em uso):** Bia - Atendimento, Cadastro, TikTok Pre-validacao, TikTok Agenciamento, TikTok Partner Bridge,
Consulta TikTok, Chatwoot Web, Chatwoot Worker, Chatwoot Postgres, Chatwoot Redis.

**Saem (sem atividade desde 30/10 ou nunca publicados):** Back-End, Worker (falhou em 11/09), Redis,
Entrega de Acessos, Processamento de Cadastros, Aviso de Manutenção, amplify-workspace, amplify-results-cache,
TikTok Catalog Collector.

**Por que não dá para apagar direto:** os serviços ativos ainda "pegam emprestado" segredos dos parados.
É isso que desenha as linhas no painel.

| Serviço ativo | Pega do | Variáveis |
|---|---|---|
| Bia | Back-End | `SLACK_BOT_TOKEN`, `SLACK_GMV_CHANNEL_ID`, `CHATWOOT_API_TOKEN`, `SMTP_USUARIO`, `SMTP_SENHA_APP`, `DECISION_ENGINE_MODEL` |
| Cadastro | Entrega de Acessos | `GMAIL_API_CLIENT_ID`, `GMAIL_API_CLIENT_SECRET`, `GMAIL_API_REFRESH_TOKEN`, `GMAIL_SENDER` |
| TikTok Partner Bridge | Worker | `TIKTOK_INVITE_SERVER_TOKEN` |

**Ordem segura:**
1. Criar **variáveis compartilhadas do projeto** (hoje: 0) com esses segredos: Slack, Chatwoot, SMTP, Gmail API,
   OpenAI, Supabase, tokens do TikTok.
2. Apontar Bia, Cadastro e as pontes para as compartilhadas (mesmo valor, outra origem). Redeploy e conferir.
3. Só então apagar os 9 serviços, um por vez, conferindo os logs entre cada um.
4. Tirar o código das variáveis base64 do Cadastro (passa a vir do GitHub).

## 2. Banco de dados

O banco já tem uma "vitrine" boa para ver (esquema `public`): Fichas (`creators`), Atendimentos, Linha do tempo
(`eventos`), Cadastros, Agenciamentos, GMV, Métricas. A bagunça está nos **valores** e nas **tabelas por trás**
(esquema `interno`). Ver os 11 problemas em `fase-3-correcoes.md` §4 (duplicados, origem com 4 nomes,
"A confirmar" como etapa, 1.795 encerramentos sem motivo…).

**Proposta de modelo simples (o que cada tela responde):**

| Tela | Uma linha por | Colunas que importam |
|---|---|---|
| Fichas | pessoa | nome, WhatsApp, @, origem, etapa atual, situação, agenciado?, cadastro?, acesso? |
| Atendimentos | conversa (ciclo) | pessoa, início, última mensagem, etapa, situação, motivo do encerramento |
| Linha do tempo | acontecimento | pessoa, data, o que aconteceu |
| Agenciamentos | vínculo no TikTok | pessoa, @, início, situação |
| Cadastros | formulário enviado | os 63 campos |

**Etapas (lista fechada, igual às etiquetas do Chatwoot):** conhecer → qualificação → validação → convite → cadastro → acesso.
**Situação (separada da etapa):** em atendimento · parado · encerrado · especialista.

**Para apagar colunas/tabelas preciso enxergar o esquema `interno`:** a chave secreta só lê a vitrine.
Opções: (a) reiniciar o app e fazer login no MCP do Supabase (já configurado em `.mcp.json`), ou
(b) um Access Token do Supabase (Account › Access Tokens). Com isso: listar tabelas sem uso, colunas sempre vazias
e o histórico de migrations, e montar o SQL de limpeza com contagem antes/depois.

## 3. GitHub

- 35 branches remotas. **29 já estão dentro** da branch da auditoria → podem ser apagadas.
- 5 com trabalho que não está em produção: `fix/bia-identificacao-20261117`, `review/bia-isolated-knowledge-20261106`,
  `docs/governanca-times-onboarding-20261106`, `review/isolated-bridges-20261104`, `claude/relaxed-einstein-h7mkax`
  (plugin do Railway).
- `main` está **162 commits atrás** e 0 à frente → avanço direto, sem conflito.

**Ordem:** PR da branch da auditoria para a `main` → mesclar → apagar as 29 branches já contidas → decidir as 5.
As 12 tags `bia-rNN` ficam (são o histórico de releases).
