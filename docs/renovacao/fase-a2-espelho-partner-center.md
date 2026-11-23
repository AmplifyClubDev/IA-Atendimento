# Fase A2: espelho do Partner Center no banco (proposta, 23/11/2026)

**Em 1 linha:** cada agenciado do Partner Center vira uma ficha completa no Supabase, atualizada de hora em hora,
com histórico de tudo que muda (entrou, saiu, renovou, mudou de nível). A renovação e os alertas leem daqui.

## O que temos hoje

A ponte de Agenciamento (Playwright, Chrome logado) já lê a lista inteira de hora em hora, mas devolve só 6 campos:

| Campo da ponte | Vai para |
|---|---|
| @, nome | `arroba`, `nome_tiktok` |
| status (vinculado / solicitado) | só "vinculado" é guardado |
| create_time_second | `vinculado_em` |
| expire_time_second | **descartado** |
| effective_end_date_second | `vigencia_fim` |

Contagens da ponte agora: **1.542 vinculados**, **94 com vinculação solicitada**.

**Falta (está na tela, a ponte não lê):** nível atual e estimado, GMV do nível, seguidores, categorias, tag,
"Estender" disponível, "Desvinculação solicitada" (49) e "Prestes a expirar" (223).

## Como fica

### Tabelas (só o sistema grava)

| Tabela | 1 linha por | Colunas principais |
|---|---|---|
| `interno.agenciados_tiktok` (já existe, ganha colunas) | vínculo | situação, entrou em, contrato até, expira em, pode estender, nível atual, nível estimado, GMV do nível, seguidores, categorias, tag, última coleta |
| `interno.agenciados_eventos` (nova) | mudança | quando, quem, tipo (entrou, saiu, renovou, mudou de nível, pediu desvinculação), antes → depois, nível e GMV no momento |
| `interno.telefones_creators` (fase A) | @ + telefone + fonte | telefone, fonte, quando |

### Telas para usar no dia a dia (e nos sistemas)

| Tela | Responde |
|---|---|
| `agenciados` | A ficha: @, nome, situação, entrou em, contrato até, dias para vencer, nível, GMV, seguidores, categoria, telefone, origem, passou pela Bia |
| `agenciados_movimento` | Por hora e por dia: quem entrou e quem saiu, **com nível e GMV** ("saíram 3 Silver hoje") |
| `agenciados_a_vencer` | Quem vence nos próximos 30 dias, se pode estender, se tem telefone |
| `agenciados_por_nivel` | Quantos em cada nível, por dia |

## O que precisa mudar

1. **Trazer o código das pontes para o GitHub.** Hoje ele só existe dentro do Railway. Só cópia, sem mexer.
2. **Ponte de Agenciamento:** passar a devolver os campos que já estão na tela (nível, GMV, seguidores, categorias,
   estender, desvinculação). Testar com 1 página antes, comparando com a tela.
3. **Banco:** novas colunas + tabela de eventos + telas (com simulação desfeita antes, como na fase A).
4. **Coleta da Bia:** gravar os campos novos e os eventos. Continua só leitura no TikTok.

## Telefones (andamento)

- Fontes internas: 238 agenciados com telefone.
- Chatwoot: o n8n cria contatos com o **nome igual ao @** e com o telefone. Cruzamento dos 1.298 sem telefone
  (só leitura, nome exatamente igual ao @): **219 achados**, nenhum ambíguo, 882 não estão no Chatwoot,
  197 deram erro de consulta (repetir). Ainda **não gravado**: precisa da fonte `chatwoot` na tabela.
- Com isso: cerca de 457 de 1.536 (30%). O resto depende da base Amplify ou do Notion.

## Andamento (23/11/2026)

1. ✅ Código das 3 pontes no GitHub (`pontes/`). Agenciamento e Pré-validação rodam o mesmo código.
2. ✅ Achado: a ponte recebe o registro **completo** do TikTok e a função `normalizeRelation` descarta quase tudo.
   A rota de GMV por creator (`/gmv-report`) já existe, mas só abre para um papel "gmv" que nenhum serviço usa.
3. ✅ Melhoria pronta, **não publicada** (`pontes/tiktok-ponte`):
   - `/relations?detalhes=1` devolve também os campos do TikTok achatados (sem imagens nem links). Sem o
     parâmetro, a resposta é igual à de hoje: a Bia e o Cadastro não percebem diferença.
   - Papel `agency` passa a poder ler `/gmv-report` (só leitura).
   - 15 testes passando (2 novos), roda os testes no build.
4. Próximo: publicar só a **TikTok Agenciamento**, ler 1 página com detalhes, comparar com a tela e então
   desenhar as colunas do banco com os nomes reais.

## Campos reais com `?detalhes=1` (lidos em 23/11/2026)

| Campo do TikTok | Vira coluna |
|---|---|
| `creator_info.user_name`, `nick_name`, `id` | @, nome, id do creator |
| `creator_info.fans_cnt` | seguidores |
| `creator_info.categories.N.name` | categorias |
| `creator_tier.name` / `.level` | nível atual (ex.: Level 2) |
| `creator_tier_progress.current_gmv` / `target_gmv` / `progress_percent` | GMV do nível, meta, % |
| `creator_tier_progress.target_tier.level` | próximo nível |
| `effective_start_date_second` / `effective_end_date_second` | início e fim do contrato |
| `expire_time_second`, `create_time_second` | expiração e vínculo |
| `commission_relation.commission_proportion` | comissão (%) |
| `partner_reject_unlink_times` | pedidos de desvinculação recusados |

## Fase A2 — andamento (23/11/2026, 14:00 UTC)

- ✅ Banco aplicado e testado (`bia/sql/agenciados_ficha.sql` + teste): colunas da ficha, `interno.agenciados_eventos`,
  telas `agenciados_ficha`, `agenciados_movimento`, `agenciados_movimento_por_nivel`, `agenciados_por_nivel`,
  `agenciados_a_vencer`. Ficha com 1.570 agenciados (1.542 ativos), 319 vencem em 45 dias.
- ✅ Bia: a coleta pede `?detalhes=1` e manda a ficha (`agenciados_sync.py`), testes e CI verdes (commit `6671542`).
- ⏸️ **Publicação da Bia parada.** Às 13:22 e 13:29 UTC alguém publicou na Bia o commit `ce72056` (17/11, branch
  apagado `fix/bia-alertas-visual-20261117`), com um patch no comando de início. Essa versão é anterior a 20/11:
  não tem a coleta de hora em hora (a última coleta foi 13:15 UTC), nem as correções da auditoria. O alerta
  "Lead parado precisa do time" continua desligado (essa versão não tem esse alerta).
  O serviço agora aparece ligado ao repositório no Railway. Esperando decisão antes de publicar o `main`.

## Fase A2 publicada (23/11/2026, 16:05 UTC) ✅

- O `main` voltou para a Bia (deploys `a11dbe90`, `0e7687a1`, `fb5ea954`), substituindo a versão de 17/11
  publicada às 13:29. O patch de início `bia-shop-16004004` (convite recusado com
  `creator_binding_not_permitted` → ativar o TikTok Shop) foi **mantido** e aplica sobre o `main`.
  O alerta "Lead parado" continua desligado (`TEAM_ALERTS_ENABLED = False`).
- Duas correções no caminho: a lista com detalhes tem **7,5 MB**, e o cliente da Bia cortava em 2 MB em dois
  lugares (`_transport` e `_json_object`). Agora só a coleta aceita até 16 MB; o resto continua em 2 MB.
- 1ª coleta com detalhes (16:07 UTC): **1.542 agenciados com ficha completa**. Eventos já registrados:
  2 entraram, 2 saíram (sem nível: saíram antes da 1ª ficha), **3 renovaram** (fim passou de nov/26 para nov/27).

Hoje, por nível:

| Nível | Agenciados | GMV do nível (soma) | Vencem em 30 dias |
|---|---|---|---|
| Level 0 | 761 | 54.762 | 111 |
| Level 1 | 637 | 523.336 | 90 |
| Level 2 | 50 | 316.083 | 5 |
| Level 3 | 34 | 730.753 | 4 |
| Level 4 | 27 | 2.541.715 | 5 |
| Level 5 | 27 | 5.335.695 | 3 |
| Level 6 | 6 | 416.809 | 2 |

`agenciados_a_vencer` (45 dias): 315 pessoas, **77 com telefone**.

Pendências: nomes dos níveis (ex.: Level 2 = Silver?) e telefones (base Amplify / Notion / Chatwoot).

## Categoria Amplify (23/11/2026) ✅

Regra oficial (card "Categorias e GMV" e Cadastro): Start até R$ 4.999 · Silver a partir de R$ 5 mil ·
Gold a partir de R$ 30 mil · Diamond a partir de R$ 100 mil. Calculada pelo GMV que o Partner Center mostra
para o nível (`gmv_nivel`). É diferente do "Level" do TikTok (0 a 6). Migration: `bia/sql/agenciados_categoria.sql`.

Coluna `categoria` nas telas `agenciados_ficha`, `agenciados_movimento`, `agenciados_a_vencer`; telas novas
`agenciados_por_categoria` e `agenciados_movimento_por_categoria` ("saíram 3 Silver hoje").

| Categoria | Agenciados | GMV (soma) | Vencem em 30 dias | Vencem em 45 dias (com telefone) |
|---|---|---|---|---|
| Start | 1.391 | 437.137 | 200 | 282 (72) |
| Silver | 66 | 811.295 | 6 | 9 (1) |
| Gold | 25 | 1.406.373 | 5 | 8 (1) |
| Diamond | 36 | 7.264.348 | 4 | 9 (2) |
| Sem GMV | 24 | 0 | 5 | 7 (1) |

⚠️ O período desse GMV é o que o TikTok usa para o nível; pode não ser o mesmo período do print do cadastro.

## Telefones do Chatwoot gravados (23/11/2026) ✅

- Fonte nova `chatwoot` (`bia/sql/telefones_chatwoot.sql` + teste). Prioridade: formulário > ficha da Bia >
  Chatwoot > base Amplify > Notion.
- Cruzamento só leitura dos agenciados sem telefone com contatos do Chatwoot cujo **nome é exatamente o @**
  (como o n8n cria): **248 gravados**, nenhum ambíguo. 37 consultas deram erro (repetir depois).
- Agenciados ativos com telefone: **238 → 492** (formulário 179, Chatwoot 248, ficha da Bia 65).
- A vencer em 45 dias: 107 de 315 com telefone (Diamond 2/9, Gold 2/8, Silver 2/9, Start 99/282).
- O resto depende da base Amplify (outro Supabase) ou do Notion.

## Telefones da base Amplify gravados (23/11/2026) ✅

- Fonte: o outro Supabase ("Base de dados - Amplify", `criadores`), com o acesso que o Cadastro já usa
  (`SUPABASE_URL` / `SUPABASE_SERVICE_KEY`). Só leitura na fonte; `bia/tools/importar_telefones.py --gravar`.
- 4.765 creators com @ e telefone gravados (`fonte = base_amplify`), não só agenciados: servem para quem entrar depois.
- Agenciados ativos com telefone: 492 → **759** (formulário 179, Chatwoot 248, base Amplify 267, ficha da Bia 65).
- A vencer em 45 dias com telefone: 107 → **254 de 315** (Diamond 5/9, Gold 4/8, Silver 5/9, Start 237/282).
- Falta: ~780 agenciados sem telefone em nenhuma fonte; o Notion é a última fonte conhecida.

## Levantamento do Partner Center: o que falta no banco (23/11/2026)

Contagens oficiais (`statusCount`, vêm em toda resposta da lista):

| Estado | Quantos | No banco hoje? |
|---|---|---|
| Vinculados (`bound`, status 1) | 1.549 | ✅ sim |
| Vinculação solicitada (`pending`, status 2) | 99 | ❌ |
| **Desvinculação solicitada** (`unbinding`, status 4) | 45 | ❌ — 10 estão marcados como "saiu" (errado), 35 nunca entraram |
| Convite recusado (`binding_failed_reject`, status 6) | 425 | ❌ |
| Convite expirado (`binding_failed_expired`) | 2.894 | ❌ |
| Saíram (`unbound_unlink`) | 2.405 | ❌ (só as saídas vistas desde 21/11) |
| Contrato venceu (`unbound_expired`) | 2.994 | ❌ |
| Prestes a expirar (`binding_expire_soon`) | 220 / 139 / 8 | — (faixas) |

**Pedido de renovação** = bloco `extend_relation` na parceria (74 vinculados hoje):
`status` (1 = aguardando aceite: 51 · 2 = aceito, novo fim já aplicado: 18 · 3 = sem aceite, 0 pedidos restantes: 5),
`create_time_second` (pedido enviado; todos nos últimos 7 dias), `expire_time_second` (pedido expira em até 7 dias),
`effective_end_date_second` (novo fim: +365 dias), `original_effective_end_date_second`, `remaining_extend_request_count`.
Os pedidos já são enviados ~7 dias antes do vencimento (74 dos 76 que vencem em 7 dias têm pedido).

**Desvinculação solicitada**: status 4, `record.type = 7`; continuam vinculados até o TikTok concluir.
