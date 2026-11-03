# Bia: release 46 (02/11/2026): visibilidade

**Base:** a 45 que está no ar (deploy `9ae9ac0e`). A 46 contém a 45 inteira. **Nada publicado, enviado ou lido em produção.**

| | |
|---|---|
| Pacote | `atendimento-v5-release-20261102-46`, 37 arquivos |
| zip sha256 | `c28de2b9a25068914e25b08ca0e2f37be291969cdba81c9f0406c05a3a6ddb10` |
| Carregador | sha256 `f995387cd9956c07170e757375c10d7c20c1a9ed00d40f7b810480a4c32f1110` |
| Partes | **12** (a 45 tem 11): **variável nova `V5_RELEASE_ARCHIVE_PART_12`** |
| Volta | `sealed46/volta45/` (11 partes, idênticas a `sealed45/variaveis/`). **Na volta, apagar ou esvaziar a `V5_RELEASE_ARCHIVE_PART_12`**: o carregador da 45 recusa uma parte a mais com valor |
| Diferença | `release46.diff` (45 → 46): `retomada.py`, `reconferencia.py`, `server.py` |
| Testes | 805 passam (816 no total, 6 novos em `src/tests/test_diagnostico46.py`), 9 fora de uso, as mesmas 2 falhas antigas |

## 1. Motivo em toda varredura

Cada conversa olhada pela pós-pausa, pela retomada e pela reconferência recebe um motivo fixo, da lista `REASONS` em `src/retomada.py`. O registro (`Decisoes.record`) **recusa** um motivo fora da lista, e o teste falha se isso acontecer.

| Grupo | Motivos |
|---|---|
| O que aconteceu | `respondida`, `reprocessada`, `lembrete_enviado`, `consulta_na_fila` |
| Pós-pausa | `conversa_invalida`, `outra_caixa`, `fora_do_piloto`, `sem_mensagem_do_lead`, `ja_respondida_no_chatwoot`, `fora_da_janela_23h`, `muito_recente`, `historico_indisponivel`, `mensagem_sem_texto`, `reprocessamento_ja_usado`, `controle_humano`, `outro_lead_nesta_varredura`, `resposta_ja_aceita`, `consulta_ja_na_fila_da_mensagem` |
| Retomada | `sem_atendimento`, `atendimento_fechado`, `fora_da_janela_24h`, `fase_sem_lembrete`, `mensagem_mais_nova`, `fora_do_piloto`, `controle_humano`, `pausa_ou_saida`, `nenhuma_etapa_vencida`, `fora_do_horario`, `intervalo_minimo`, `ficha_ilegivel`, `cadastro_confirmado`, `mudou_no_chatwoot`, `lembrete_ja_reservado` |
| Reconferência | `sem_pendencia`, `ponte_fora`, `controle_humano`, `cadastro_confirmado`, `ficha_ilegivel`, `origem_nao_confirmada`, `outro_lead_nesta_varredura` |
| Erro | `erro_envio:<código>`, com o código do transporte ou do servidor (ex.: `erro_envio:chatwoot_rejected`) |

`trava_ocupada` está na lista, mas hoje nenhuma varredura o usa: a trava da conversa espera em vez de recusar.

**Também na pós-pausa:**
- **Nota privada não conta como resposta**, como pede a regra ("saída da Bia, não privada").
- **A listagem do Chatwoot** passou a pedir `sort_by=last_activity_at_desc`, como o vigia do Cadastro. Antes, a ordem era a padrão do Chatwoot.

## 2. `GET /diagnostico/conversa/<id>` (só leitura)

**Autenticação:** `Authorization: Bearer <V5_WEBHOOK_TOKEN>`, o mesmo segredo do webhook, que já existe no serviço. Nenhuma variável nova.

```bash
curl -H "Authorization: Bearer $V5_WEBHOOK_TOKEN" https://atendimento-v5-ensaio-production.up.railway.app/diagnostico/conversa/56938
```

**O que devolve:**
- **`chatwoot`**, numa leitura do detalhe e das mensagens da conversa:
  - `piloto`: `no_piloto`, `variacao` (`igual`, `lista_com_9_chatwoot_sem`, `lista_sem_9_chatwoot_com`) e só os 4 últimos dígitos do telefone;
  - `status`, `pode_responder` e `tem_responsavel`;
  - `ultima_do_lead` (id e hora);
  - `depois_dela`: o tipo de cada mensagem posterior (`bia`, `humano`, `automatica`, `nota_privada`), sem o texto;
  - `resposta_publica_depois`.
- **`atendimento`**, do estado da Bia:
  - `existe`, `etapa`, `situacao` e `expira`;
  - `ultima_processada` e `processed_inbound_tem_ultima_do_lead`;
  - o status do evento e dos envios dessa mensagem;
  - as marcas `reprocessed` (modo e hora) e `retomada` (último lembrete e fonte);
  - `controle_humano`, `pausa_ou_saida` e `cadastro`.
- **`decisoes`:** a última decisão de cada varredura sobre a conversa (`pos_pausa`, `retomada`, `reconferencia`), com motivo e hora.
  - `{}` quer dizer que nenhuma varredura olhou a conversa desde o deploy. Na pós-pausa, isso significa que ela não apareceu na listagem.
  - As decisões ficam em memória e recomeçam a cada deploy.

**O endpoint não grava nada (testado):** o número de linhas das tabelas é o mesmo antes e depois da chamada.

## 3. /ready

Cada varredura (`pos_pausa`, `retomada`, `reconferencia`, dentro de `tiktok.followup`) mostra `puladas_por_motivo` da última varredura.

A pós-pausa mostra também:
- `conversas_lidas`;
- `respondidas`: agora conta toda resposta, inclusive a reprocessada. A Cristiane passa a contar;
- `reprocessadas`;
- `varreduras`, `intervalo_segundos` e `horario_silencioso: false`.

## 4. Diagnóstico local do 56938 (estado mais parecido possível)

Simulei:
- lead às 05:42 + aviso de manutenção;
- telefone `+558396914946` na lista;
- sem atendimento na Bia;
- depois, a resposta manual de 22:37 (mensagem de humano não atribuído) e a nota privada.

| Momento | Motivo da pós-pausa | `depois_dela` |
|---|---|---|
| Antes da resposta manual (22:01–22:37) | `respondida`, se a conversa aparece na listagem | `automatica` |
| Agora, depois da resposta manual | `ja_respondida_no_chatwoot` | `automatica`, `humano`, `nota_privada` |

- **Antes da resposta manual:** com a conversa na listagem, a 46 teria respondido. Se em produção o `decisoes` vier `{}`, ela não foi listada. A ordem pedida agora (`sort_by`) deve resolver isso.
- **Quando o lead responder:** a Bia segue normalmente, porque o atendente não está atribuído (teste `test_after_the_manual_reply_…`).
- **Se o Chatwoot atribuir a conversa ao atendente ao responder,** a Bia fica de fora de propósito. O diagnóstico mostra `tem_responsavel: true` e o motivo `controle_humano` (teste `test_assigned_to_the_agent_…`).

## Publicação (só com autorização do usuário)

1. Conferir no `/ready` que a release no ar é a 45.
2. Trocar as **12** partes (criar `V5_RELEASE_ARCHIVE_PART_12`) e o carregador pelos de `sealed46/variaveis/`.
3. Fazer o redeploy.
4. Conferir `/diagnostico/conversa/56938` com o bearer.
5. **Volta:**
   1. variáveis de `sealed46/volta45/`;
   2. **apagar ou esvaziar a `V5_RELEASE_ARCHIVE_PART_12`**.
