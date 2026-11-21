# Banco de dados (Supabase) — mapa e proposta de organização (21/11/2026)

**Em 1 linha:** o banco é pequeno (17 tabelas e 9 visões). A bagunça está em uma tabela inchada
(`interno.creators`, com 111 colunas), em 15 colunas que ninguém usa e em dados duplicados ou com nomes misturados.

## Como está hoje

| Esquema | Para que serve | O que tem |
|---|---|---|
| `public` | **Vitrine** para ver no painel. Só visões, nada é gravado aqui | Fichas (`creators`), Atendimentos, Linha do tempo (`eventos`), Cadastros, Agenciamentos, GMV, Métricas, Lista de agenciados |
| `interno` | **Onde os dados moram** | `creators` (1.987), `atendimentos` (2.370), `eventos` (22.880), `chatwoot_etiquetas_historico` (7.583), `agenciamentos` (240), `gmv` (168), `declaracoes_chat` (353), `contextos_ia` (21), `contextos_ia_ensaio` (116), 3 tabelas `tiktok_agenciamentos_*` |
| `analitico` | Métricas diárias | `eventos_minimos`, `pessoa_dia`, `pessoa_dia_revisoes`, `configuracao`, `execucoes` |

21 funções gravam e leem esses dados (a Bia e o Cadastro só falam com o banco por elas). 27 gatilhos.

## O que dá para tirar com segurança (ninguém usa: nem código, nem funções, nem visões, nem formulário)

| Tabela | Colunas (todas 100% vazias) |
|---|---|
| `interno.creators` (9) | `circle_cargos_entrada`, `convite_criado_em`, `cpf_validado`, `deseja_sair_agencia`, `formulario_disponibilizado_em`, `formulario_iniciado_em`, `possui_agencia_atual`, `saida_agencia_confirmada_em`, `validacao_motivo` |
| `interno.agenciamentos` (6) | `contrato_percentual`, `contrato_prazo_meses`, `contrato_ultima_renovacao_em`, `contrato_vigencia_fim`, `contrato_vigencia_inicio`, `motivo_saida` |

## O que parece vazio mas **fica**

- 11 campos opcionais do formulário (`camiseta_outro`, `idiomas_outros`, `restricao_alimentar`…): o formulário grava neles.
- `telefone`, `gmv_entrada_id`, `inicio_em`, `fim_em`, `periodo_*`, `formulario_id`, `submissao_id`: usados por funções ou visões.
- `contextos_ia_ensaio` e as funções `*_ensaio_v5`: modo de teste da Bia.

## Proposta em partes (cada uma com backup e contagem antes/depois)

| Parte | O que faz | Risco |
|---|---|---|
| A | Backup + apagar as 15 colunas sem uso | Baixo |
| B | Catálogo do TikTok parado desde 10/11: apagar `tiktok_agenciamentos_diario` e `_coletas` (cópias); manter o catálogo e a lista | Baixo |
| C | Padronizar nomes na vitrine: origem com 1 lista só; "A confirmar" deixa de ser etapa | Baixo (só visões) |
| D | Duplicados: 9 fichas com o mesmo WhatsApp, 19 com o mesmo @, 5 agenciamentos repetidos, 42 fichas com 2+ atendimentos abertos | Médio: revisão caso a caso |
| E | Dividir `creators` (111 colunas) em **Ficha** (quem é e em que etapa está) e **Respostas do formulário** (63 campos) | Alto: muda 6 funções, a Bia e o Cadastro. Projeto separado |
