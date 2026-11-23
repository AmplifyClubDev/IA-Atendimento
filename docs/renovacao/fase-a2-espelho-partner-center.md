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
