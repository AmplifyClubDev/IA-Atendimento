# Fase 2 — Caixa 3 e formulário: como funciona e onde quebra (20/11/2026)

Feito **só pelo código do repositório** (Railway e Supabase sem acesso; ver Fase 1).
Nada foi alterado em produção. Os números de conversas (33853, 50149, 53534, 55626) vêm do
relatório "Auditoria AmplifyOS — Atendimento IA (Bia)"; aqui está a **causa no código** de cada um.

> **Cuidado:** o Cadastro em produção roda com 4 patches em base64 que não estão no GitHub
> (Fase 1). Tudo que está abaixo sobre o formulário vale para o código do repositório.
> A parte do e-mail pode estar diferente em produção.

---

## 1. Resultado em 7 linhas

1. **Pedido de especialista não avisa ninguém.** O alerta existe, mas o código só manda o de GMV alto.
2. **O "Pronto" não tem limite.** A pessoa pode mandar "Pronto" para sempre e recebe a mesma mensagem.
3. **"Travado em blocked" não avisa ninguém.** O código marca "avisar o time", mas nada lê essa marca.
4. **"Código incorreto" no e-mail:** pedir outro código invalida o anterior; e-mail atrasado = código "incorreto".
5. **A Bia nunca marca conversa como resolvida** no Chatwoot. Só põe a etiqueta `encerrado`.
6. **Frases repetidas na mesma resposta:** a trava contra repetição procura palavras que não existem mais.
7. **Quem tem acesso aparece com a etiqueta `cadastro`:** não existe etiqueta de "acesso" na Bia.

---

## 2. O fluxo, passo a passo

```
WhatsApp → Chatwoot (caixa 3) → webhook → Bia → pontes do TikTok → link do formulário
        → Cadastro (formulário) → e-mail com código → ponte de agenciamento → Supabase
        → Circle → aviso no WhatsApp + etiqueta de acesso → Bia lê a ficha na próxima mensagem
```

| # | Passo | Onde no código | Observação |
|---|---|---|---|
| 1 | Chatwoot avisa a Bia | `bia/server.py:1609-1641` | Token pode vir na URL (`?token=`) ou no cabeçalho (`server.py:1093-1103`). |
| 2 | Filtro: só mensagem nova do contato, caixa certa | `bia/contracts.py:125-161` | Caixa vem de `CHATWOOT_INBOX_ID`. |
| 3 | Conferência ao vivo antes de responder | `bia/real_operations.py:128-172` | Não responde se: etiqueta "Renovacao de contrato", atributo `human_control`/`bia_paused`, conversa não `open`, ou atendente humano. |
| 4 | Pré-validação do @ | `bia/playwright_client.py:380-396` | `account_status == 1` = elegível. Sem status = `shop_unknown`. |
| 5 | Convite (Partner Bridge) | `bia/playwright_client.py:398-480` | Escrita nunca é repetida sozinha. |
| 6 | Link do formulário | `bia/real_journey.py:801` (`/cadastro`), `:813-829`, `:3019-3028` | Botão "Fazer cadastro" pela API do WhatsApp (`transport.py:508-537`). |
| 7 | Formulário: confere o @ ao vivo | `cadastro/app/publico.py:187-213`, `agency.py` | Espera até 38 s. |
| 8 | Código por e-mail | `cadastro/app/publico.py:254-311`, `store.py:79-128` | 6 números, 10 min, 10 tentativas. |
| 9 | Envio final → Supabase | `cadastro/app/publico.py:476-519` | RPC `registrar_cadastro_publico_v5`. |
| 10 | Circle + boas-vindas + aviso no WhatsApp | `cadastro/app/entrega.py:104-144` | Até 3 tentativas; depois e-mail de alerta. |
| 11 | Etiqueta de acesso no Chatwoot | `cadastro/app/chatwoot_access_label.py` | Só se `CADASTRO_CHATWOOT_ETIQUETA_ACESSO` estiver ligada **e** a migration 010 aplicada. |
| 12 | Bia descobre o cadastro | `bia/gateway.py:93-140`, `server.py:452-460` | **Não há aviso.** A Bia lê `creators.cadastro` quando o lead escreve de novo. |

Onde fica o estado (duas fontes):
- **Bia:** SQLite `/data/atendimento.sqlite3` (`bia/server.py:220`, `repository.py:28-55`).
- **Formulário:** SQLite `CADASTRO_STATE_PATH` (padrão `/tmp/...`, `cadastro/app/cadastro_server.py:94`).
- **Ficha:** Supabase. Por isso "formulário iniciado" fica vazio no banco: o progresso nunca sai do SQLite.

---

## 3. Onde quebra e por quê (com evidência)

### 3.1 Pedido de especialista fica sem ninguém (conversa 33853) — GRAVE

- A pessoa escolhe "Especialista" → a Bia grava `handoff_requested` e responde
  "O agenciamento automático está pausado" (`bia/lead_validation.py:21`, `:173-176`).
- O alerta de especialista **existe** (`bia/lead_alerts.py:98`, `:114`), mas a lista de envio é fixa:
  `kinds = ['threshold']` (`bia/lead_alerts.py:213`). **Só o alerta de GMV alto sai.**
- A Bia não põe atendente, não muda atributo, não muda o status. Ninguém fica sabendo.
- Depois de 24 h a janela do WhatsApp fecha (`bia/real_journey.py:1902`) e a Bia não usa modelo aprovado.

### 3.2 Ciclo do "Pronto" sem fim (conversa 50149) — GRAVE

- Perfil sem status do Shop → fase `blocked` + `shop_unknown` + texto `SHOP_UNKNOWN`
  "O TikTok ainda não trouxe a informação…" (`bia/real_journey.py:3434-3441`, `bia/conversao.py:26-29`).
- A cada "Pronto":
  - menos de 10 min desde a última consulta → `SHOP_RECHECK_SOON` (`real_journey.py:2445-2447`);
  - mais de 10 min → "Vou conferir seu perfil de novo agora 🔎" + nova consulta → `SHOP_UNKNOWN` de novo (`:2448-2458`, `:3438`).
- **Não há limite de tentativas.** Não há alerta. Não há trava contra repetir a mesma mensagem em respostas seguidas.
- A reconferência automática ignora esse caso, porque `shop_unknown` não está em `BRIDGE_DOWN_REASONS`
  (`real_journey.py:2697`).

### 3.3 330 travados em `blocked`, sem aviso — GRAVE

- "Conferir a pendência da integração" **não é da Bia**: é o gatilho do banco
  `interno.atendimento_resumir()` quando `etapa='blocked'`
  (`cadastro/sql/esquema-base/09_aplicar-integracao-real-v2.sql:677`, `:718`).
- A Bia grava `cycle['team_alert']` em 3 casos (`bia/real_journey.py:3192`, `:3218`, `:3285`).
  O comentário em `:3190` diz que "o vigia do Cadastro avisa a equipe em 30 min".
  **Nada no repositório lê `team_alert`**, e ele não vai para o Supabase (`bia/server.py:401-413`).
- O vigia do Cadastro só olha "última mensagem é do lead há mais de 30 min"
  (`cadastro/app/vigia_atendimento.py:39-56`). Se a Bia respondeu algo (mesmo inútil), não há alerta.
- O que tira de `blocked`: só a reconferência de ponte caída (3 vezes, 10 min) ou o lead escrevendo de novo.

### 3.4 "Código incorreto" no e-mail — GRAVE para o formulário

Duas causas no código do repositório:

1. **Reenviar invalida o código anterior.** Cada pedido grava um novo `otp_code_hash` por cima do anterior
   (`cadastro/app/store.py:96-98`). O botão "Reenviar código" libera em 60 s (`publico.py:29`).
   O Gmail costuma atrasar mais que isso. A pessoa pede de novo, chega o **primeiro** e-mail,
   ela digita → `codigo_incorreto` (`store.py:123-124`).
   A tela mostra "Pedido XXXXXX" para ajudar (`cadastro.html:411-412`), mas é fácil não perceber.
2. **Sessão perdida = código "expirado".** O código só vale na sessão que pediu (`publico.py:272`).
   A sessão fica no `sessionStorage` + IndexedDB do navegador (`cadastro.html:504-516`, `:556-566`).
   - Abrir o link de novo **em outro navegador** (ex.: sai do navegador do WhatsApp para o Chrome) → sessão nova.
   - Se o Cadastro reiniciar e o SQLite estiver em `/tmp`, todas as sessões somem (`publico.py:116-121`).
   Nos dois casos a tela diz "Este código expirou… Solicite outro" (`cadastro.html:462`).

Extra: o e-mail sai de uma conta Gmail comum (`emailer.py:22`, `entrega.py:48`), o que aumenta Spam/Promoções.

### 3.5 Conferência do @ pode devolver resultado velho — MÉDIO

- Se a consulta passa de 38 s, a pessoa vê "Ainda estamos consultando" e a consulta continua
  (`cadastro/app/agency.py:54-57`).
- Esse resultado fica guardado até alguém pedir de novo (`agency.py:50-53`, `:60-62`).
- Exemplo: 1ª consulta demora → pessoa vai ao TikTok, aceita o convite, volta 5 min depois →
  recebe o resultado **antigo** ("pendente") e é mandada aceitar de novo. Só a 2ª tentativa é nova.

### 3.6 Frases repetidas e frias (conversas 50149 e 53534) — MÉDIO

- A trava contra repetir o aviso procura "anotada"/"anotado" (`bia/real_journey.py:1604`, `:1607`).
  Os textos atuais dizem "registrada"/"registrado" (`bia/conversao.py:23-24`, `:43`, `:57-58`).
  **A trava nunca funciona.** A mesma frase pode sair duas vezes.
- `INVITE_WAIT` e `INVITE_STILL` são **idênticos**: "Sua autorização está registrada. O envio do convite
  ainda não está confirmado." (`bia/conversao.py:57-58`).
- "Ainda não tenho confirmação desse resultado. Não vou avançar sem a validação necessária."
  vem de `bia/real_answer_adapter.py:240`, `:265`, `:274`.

### 3.7 Mensagem de erro genérica (conversa 55626) — MÉDIO

- "Tive uma instabilidade aqui…" é `INBOUND_FALLBACK` (`bia/conversao.py:95-96`).
- Sai quando o processamento da mensagem dá erro (`bia/server.py:1490-1502`). No máximo 1 por hora.
- A causa do erro em cada caso só aparece nos logs da Bia (sem acesso).

### 3.8 Etiquetas e "resolvido" — MÉDIO

- A Bia nunca muda o status da conversa. `toggle_status` só existe no modo demo (`bia/demo_router.py:520-535`).
  Resultado: 15.644 conversas "abertas".
- `encerrado` junto da etapa é **de propósito** desde a release 48 (`bia/transport.py:28`, `:179-182`).
- A fase `acesso` vira a etiqueta `cadastro` (`bia/transport.py:23`). Não existe etiqueta de acesso na Bia.
  A do Cadastro (`acesso-liberado`) depende da variável + migration 010 — **não confirmado se está ligada.**
- A Bia só remove as etiquetas dela (`transport.py:385-386`). Ela **não** apaga a etiqueta do Cadastro.
- Provável falha: depois do 2º lembrete o ciclo é fechado **antes** de marcar "parou"
  (`bia/retomada.py:427-431`), e a marcação exige ciclo aberto (`transport.py:152-153`).
  Então `encerrado` pode não ser aplicado nesse caminho.

### 3.9 A Bia só sabe do cadastro quando o lead escreve de novo — BAIXO

- Não há aviso do Cadastro para a Bia. Ela lê a ficha no Supabase na próxima mensagem
  (`bia/server.py:452-460`) ou na varredura de lembretes, que só para os lembretes (`bia/retomada.py:336-356`).
- O lead recebe o aviso "acesso liberado" pelo Cadastro (`legado/cadastro_delivery.py:219-242`), então
  na prática funciona. Mas a etiqueta da Bia fica parada até a próxima mensagem.

---

## 4. Correções propostas (ordem: o que mais afeta o lead primeiro)

Nada disto foi feito. **Espera sua aprovação.**

| # | Correção | Arquivos | Risco | Precisa de produção? |
|---|---|---|---|---|
| 1 | **Especialista:** mandar o alerta (incluir `specialist` em `kinds`), pôr o atributo `bia_paused` na conversa da caixa 3 e parar de responder | `bia/lead_alerts.py`, `bia/lead_validation.py`, `bia/transport.py` | Baixo | Deploy da Bia |
| 2 | **"Pronto" com limite:** no máximo 2 reconferências; depois mensagem clara ("vou conferir e te chamo até X") + alerta no canal que já existe | `bia/real_journey.py`, `bia/conversao.py` | Médio | Deploy da Bia |
| 3 | **Alerta de `blocked`:** ler `team_alert` e mandar o alerta (uma vez por conversa) | `bia/server.py`, `bia/lead_alerts.py` | Baixo | Deploy da Bia |
| 4 | **Nunca repetir a mesma mensagem** em respostas seguidas; consertar a trava "anotada" | `bia/real_journey.py` | Baixo | Deploy da Bia |
| 5 | **Código do e-mail:** aceitar os últimos 3 códigos ainda válidos (não só o último) | `cadastro/app/store.py`, `publico.py` | Médio — **depende da Fase 1** (patch de produção) | Deploy do Cadastro |
| 6 | **@ com resultado velho:** descartar resultado guardado com mais de 60 s | `cadastro/app/agency.py` | Baixo — **depende da Fase 1** | Deploy do Cadastro |
| 7 | **Frases técnicas → tom humano e curto** (lista de textos para você aprovar antes) | `bia/conversao.py`, `bia/real_answer_adapter.py` | Baixo | Deploy da Bia |
| 8 | **Ao encerrar, marcar como resolvida** no Chatwoot (só caixa 3) + corrigir `encerrado` depois do 2º lembrete | `bia/transport.py`, `bia/retomada.py`, `bia/server.py` | Médio (muda o que o time vê) | Deploy da Bia |

**Sobre 5 e 6:** o Cadastro em produção tem patches que não estão no GitHub. Mexer nesses arquivos sem
antes trazer o código real pode desfazer correções que já estão no ar. Por isso ficam para depois da Fase 1.

Antes de implementar, cada correção ganha teste. Depois: suíte da Bia (889 testes) e do Cadastro.
Observação: esta máquina tem PostgreSQL 16; os testes do Cadastro pedem o 17 (`cadastro/tests/local_pg.py:35`).
Vou instalar o 17 só nesta sessão, ou rodar pelo CI (`.github/workflows/cadastro-testes.yml`).
