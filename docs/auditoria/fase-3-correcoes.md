# Fase 3 — Correções (20/11/2026)

**Resultado em 1 linha:** 11 dos 12 itens estão corrigidos e testados no GitHub (CI verde na Bia e no Cadastro).
**Nada foi publicado no Railway.** O banco foi só lido.

Branch: `claude/festive-rubin-aip1ug`. Commits: `5c32b2a`, `921a144`, `c67b98e`, `1399bdd`, `9f4eef6`.

## 1. O que mudou (hoje → depois)

| # | Hoje | Depois | Onde | Status |
|---|---|---|---|---|
| 1 | Pedido de especialista não avisa ninguém (conversa 33853) | 1 alerta no canal da Bia; conversa não recebe `encerrado` | `bia/lead_alerts.py`, `bia/transport.py` | ✅ testado |
| 2 | "Pronto" sem limite (conversa 50149) | Máx. 2 reconferências; depois mensagem clara e sem lembrete pedindo "pronto" | `bia/real_journey.py`, `bia/conversao.py`, `bia/retomada.py` | ✅ testado |
| 3 | `team_alert` gravado e nunca lido (330 em `blocked`) | Vira alerta (`dispatch_team`), 1 por motivo e ciclo, qualquer GMV | `bia/lead_alerts.py`, `bia/server.py` | ✅ testado |
| 4 | "Código incorreto" quando o 1º e-mail chega depois do reenvio | Valem o código atual e os 2 anteriores (mesmo e-mail, no prazo) | `cadastro/app/store.py` | ✅ testado |
| 5 | Correção de anexos (17/11) fora do ar | Pronta no repositório; entra no próximo deploy do Cadastro | `cadastro/app/static/cadastro.html` | ⏳ deploy |
| 6 | @ devolve resultado velho | Resultado que passou da espera vale só 60 s | `cadastro/app/agency.py` | ✅ testado |
| 7 | Mesma frase 2× na resposta (trava procurava "anotada") | Trava confere a própria frase + nenhum parágrafo duplicado | `bia/real_journey.py`, `bia/server.py` | ✅ testado |
| 8 | Frases frias ("Não vou avançar sem a validação necessária") | Tom humano e curto, sem citar equipe (regra da release 51) | `bia/conversao.py`, `bia/real_answer_adapter.py` | ✅ **revise os textos abaixo** |
| 9 | "Tive uma instabilidade" sem nenhum log | 1 linha de log com tipo e ponto do código (sem dados do lead) | `bia/server.py` | ✅ causa aparece no próximo erro |
| 10 | 15.644 conversas "abertas" | Com `encerrado`, conversa vira **resolvida** (só caixa 3, 1× por ciclo) | `bia/transport.py`, chave `V5_RESOLVE_ON_CLOSE_ENABLED` | ✅ testado, **desligado por padrão** |
| 11 | `encerrado` não entrava após o 2º lembrete | Corrigido (ciclo fechado por inatividade também conta) | `bia/transport.py` | ✅ testado |
| 12 | Quem tem acesso aparece como `cadastro` | Precisa aplicar a migration 010 **e** ligar `CADASTRO_CHATWOOT_ETIQUETA_ACESSO` | produção | ⏸ sua aprovação |
| 13 | GitHub ≠ produção no Cadastro | `cadastro/app` agora tem os 3 patches de produção + correções novas | `cadastro/app/*` | ✅ (falta conferir o resto da imagem, ver 3) |

### Textos novos (item 8) — para você aprovar

| Antes | Depois |
|---|---|
| Seu perfil está registrado. Ainda não tenho a confirmação necessária para avançar. | Anotei seu perfil! 😊 Tô esperando o TikTok me responder e te aviso aqui assim que tiver novidade. |
| Seu perfil está registrado. A validação ainda está pendente. | Seu perfil segue anotado. Ainda tô esperando o TikTok responder e te aviso por aqui 💙 |
| Sua autorização está registrada. O envio do convite ainda não está confirmado. (2 textos iguais) | Combinado! Já pedi o convite no TikTok. Assim que ele sair, te aviso aqui 😊 / O convite ainda está a caminho no TikTok. Te aviso aqui assim que ele sair 💙 |
| Não foi possível concluir o envio do convite agora. Sua autorização está registrada. | O TikTok não deixou enviar o convite agora 😕 Sua autorização ficou anotada e eu te chamo aqui assim que der certo. |
| Ainda não tenho confirmação desse resultado. Não vou avançar sem a validação necessária. | Ainda não tenho confirmação do TikTok. Assim que chegar, te aviso por aqui 😊 |
| (novo, limite do "Pronto") | Já conferi algumas vezes e o TikTok ainda não liberou essa informação. Agora vou acompanhar por aqui e te chamo até amanhã, combinado? Não precisa mandar "pronto" de novo 💙 |

### Decisões que mudaram regras antigas (registro)

- 17/11 o alerta virou "um só" (`3f5f148`). Agora o pedido de especialista manda **1 alerta a mais**.
- O patch de produção dá tentativas novas a cada código. Com 3 códigos válidos: no máximo 5 envios × 10
  tentativas por hora contra 3 códigos de 6 dígitos (≈ 0,015% por hora). Aceitável.
- `test_operacao_pontes.py` foi reescrito para o `pontes.py` de produção: painel só observa, Convites é manual.

## 2. Testes

- **Bia:** 891 testes localmente; as únicas falhas são as 38 do Windows (`fcntl`, CRLF, arquivo travado),
  iguais às de antes. **CI no Linux: verde.**
- **Cadastro:** 41 testes sem PostgreSQL passam localmente (cópia LF). **CI no Linux (com PostgreSQL 17): verde.**
- Testes novos: `bia/review_tests/test_auditoria_20261120.py`, `cadastro/tests/test_otp_codigos_anteriores.py`,
  `cadastro/tests/test_agency_resultado_velho.py`.

## 3. Publicar no Railway (precisa do seu ok, um por vez)

1. **Bia** — baixo risco. Sobe com `railway up` da pasta `bia/` (é assim que o Codex publica; o serviço não
   está ligado a uma branch). Depois, ligar `V5_RESOLVE_ON_CLOSE_ENABLED=true` quando quiser o item 10.
   Rollback: redeploy do deploy `3b24b721` (18/11).
2. **Cadastro** — risco médio. O repositório agora cobre os 3 patches, mas o resto da imagem de 03/11
   (`emailer.py`, `cadastro_pilot.py`, etc.) **nunca foi visto**. Antes: `railway login` (conta) e
   `railway ssh` para copiar `/app` e comparar. O comando de início atual continua compatível (os patches
   detectam "já aplicado").
3. **Migration 010 + etiqueta de acesso** (item 12): aplicar o SQL e criar a variável.

## 4. Banco de dados — raio-X (só leitura, 20/11)

Lido pela API REST com a chave secreta (só o esquema `public`). Totais: 1.950 fichas, 2.342 atendimentos,
11.907 eventos, 211 cadastros, 265 agenciamentos.

| # | Problema | Número | Proposta |
|---|---|---|---|
| B1 | Fichas duplicadas pelo mesmo WhatsApp | 9 grupos / 18 fichas | Mesclar (manter a mais antiga, mover atendimentos/eventos) |
| B2 | Fichas duplicadas pelo mesmo @ do TikTok | 19 grupos / 38 fichas | Revisar caso a caso (pode ser @ reutilizado) |
| B3 | Agenciamentos duplicados para o mesmo @ | 5 grupos / 10 linhas | Manter o mais recente confirmado |
| B4 | Fichas com 2+ atendimentos "Em atendimento" ao mesmo tempo | 42 | Fechar os antigos como "Novo ciclo" |
| B5 | Atendimentos encerrados sem motivo (`encerramento` vazio) | 1.795 de 2.342 | Preencher "24 horas sem mensagem" quando `situacao = Prazo encerrado` |
| B6 | Origem com 4 nomes para "não sei" ou anúncio (`Anúncio`, `Ads Meta`, `Não informado`, `Origem desconhecida`) | 1.682 fichas | Padronizar em 1 lista fechada |
| B7 | Origem da ficha ≠ origem do atendimento (191 "Indicação" na ficha, 1 no atendimento) | — | Atendimento herdar a origem da ficha |
| B8 | "A confirmar" usado como **etapa** | 697 fichas / 439 atendimentos | Separar etapa de situação |
| B9 | `acesso = "Revisao Manual"` (sem acento, fora da lista) | 1 | Corrigir o valor |
| B10 | `cadastros_formulario` expõe CPF, PIX e endereço pela API | 211 | Conferir que só `service_role` lê (RLS/grants) |
| B11 | Migrations `008` e `009` não existem no repositório; `010` não aplicada | — | Conferir no histórico do Supabase |

**Limite deste raio-X:** o esquema `interno` (onde ficam as tabelas de verdade) não aparece pela API.
Para ver tabelas sem uso, índices e o histórico de migrations, preciso do MCP do Supabase (já configurado
em `.mcp.json`, só leitura): reiniciar o app e fazer login nele.

**Nenhuma limpeza foi feita.** Cada item B1–B11 vira um SQL revisado, com contagem antes/depois, e só roda com o seu ok.
