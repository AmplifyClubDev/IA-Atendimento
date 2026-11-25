# Amplify OS — Fase 0: desenho (25/11/2026)

Painel interno **só de automações e processos** (aquisição, renovação, suporte). Mesma estrutura e visual do
Amplify Hub; nenhum conteúdo do Hub é reaproveitado.

## O que foi visto no Hub (só leitura, modo demonstração)

| Item | Como é no Hub | No Amplify OS |
|---|---|---|
| Tecnologia | Preact + htm, sem build; `server.mjs` em Node; rotas `#/...`; Supabase | Igual (mesmo jeito de escrever, mesmo deploy no Railway) |
| Visual | Fonte **Inter** (+ Archivo, Fraunces), azul `#1a56ff`, fundo `#f7f9fc`, cantos 16 px, `styles/base.css` | Mesmos tokens e fontes |
| Estrutura | Barra do topo + menu lateral em grupos (CONTEÚDO, COMUNIDADE, PESSOAS…) + página | Mesma estrutura, grupos por área |
| Equipe | Cartões por pessoa; papéis **Admin** (tudo) e **Editor** (conteúdo); "Gerenciar" muda papel; nunca fica sem admin | Papéis **+ times** (Aquisição, Retenção, Suporte); cada time vê só a área dele |
| Tabelas | Abas com contagem (Ativos 7 · Saíram 1 · Todos 8), busca, filtros em botões, tabela com avatar e selo, "Gerenciar" por linha | Mesmo padrão, para as tabelas do banco |
| Suporte | Chamados com abas (Abertos/Respondidos/Resolvidos) e filtro por tipo | Grupos de suporte, quem responde, visão por time |
| Histórico | Quem criou, editou ou apagou, e quando; filtro por ação e por pessoa | Igual: tudo que alguém mudar no OS fica registrado |
| Início | "Visão geral": números em cartões + "Para fazer" (pendências com link) | Dashboard com números do dia + pendências |

Observação: o Hub mostra a categoria **Safira** (GMV R$ 612 mil), que não existe na régua usada no banco da Bia
(Start · Silver · Gold · Diamond). Confirmar a régua oficial antes dos painéis.

## Menu do Amplify OS (proposta)

| Grupo | Páginas | Quem vê |
|---|---|---|
| INÍCIO | Visão geral (números do dia, pendências) | Todos (cada um vê os números da sua área) |
| AQUISIÇÃO | Funil do dia · Leads e etapas · Convites · Atendimentos da Bia | Aquisição, Admin |
| RETENÇÃO | Renovações (a vencer, pedido enviado, aceito, falta receber) · Saindo · Agenciados | Retenção, Admin |
| MENSAGENS | E-mails enviados · Templates · Follow-ups | Por área do template |
| SUPORTE | Chamados · Grupos e quem responde | Suporte, Admin |
| DADOS | Tabelas do banco (como planilha, com filtros) | Por área da tabela |
| PESSOAS | Equipe e times · Histórico | Admin |

## Dados que já existem (banco da Bia)

- **Aquisição:** `creators` (2.460), `atendimentos` (3.000), `eventos` (28.620), `metricas_diarias_v5`,
  `metricas_pessoa_dia_v5`, `origens_por_dia`, `cadastros_formulario`, `agenciados_por_dia`.
- **Retenção / Partner Center:** `partner_center` (1 linha por parceria), `agenciados_renovacao`,
  `agenciados_a_vencer`, `agenciados_desvinculando`, `agenciados_convites_pendentes`, `agenciados_conferencia`,
  `agenciados_movimento_por_categoria`.
- **Contato:** `agenciados_contato` / `agenciados_ficha` (telefone).
- **Ainda não existe no banco:** registro dos **e-mails enviados**, os **templates** (hoje no código e na Meta) e o
  registro dos **follow-ups**. A fase 4 cria isso.

## Como fica seguro

- O navegador nunca recebe a chave do banco. O `server.mjs` do OS confere quem está logado e de qual time,
  e só então lê as telas do banco.
- Fases 1 a 3: só leitura. Fase 4 em diante grava (templates); peço aprovação antes.
- Tudo que alguém mudar no OS entra no Histórico.

## Fases

| Fase | Entrega |
|---|---|
| 0 | Este desenho ✅ |
| 1 | Base: login, times e permissões, layout do Hub, Histórico |
| 2 | Painéis: contatos e agenciamentos por dia, funil por etapa, renovação; cada número abre a lista |
| 3 | Tabelas tipo planilha: filtros, ordenação, busca, exportar |
| 4 | Mensagens: e-mails enviados, templates editáveis, follow-ups |
| 5 | Suporte: grupos, quem responde, visão por time |

## Decisões pendentes (Vitor)

1. **Login:** Google com e-mail `@amplifyugc.co` (recomendado) ou e-mail e senha.
2. **Onde fica o código:** repositório próprio `Amplify-OS` na AmplifyClubDev (recomendado, como o Hub) ou pasta
   dentro do IA-Atendimento.
3. **Régua de categorias:** existe Safira (e acima de Diamond)? Quais valores?
