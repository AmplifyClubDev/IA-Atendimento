# Partner Center no banco: como funciona (25/11/2026)

Guia curto. Tudo o que o Partner Center tem da Amplify fica no Supabase da Bia, atualizado sozinho.

## As pontes (Railway)

Uma ponte é um navegador sempre aberto no Partner Center, já logado com a conta da Amplify.

| Ponte | Para quê | Quem usa |
|---|---|---|
| **TikTok Agenciamento** | Lê as listas do Partner Center (vinculados, saindo, convites, histórico) | A coleta da Bia, de hora em hora |
| **TikTok Pré-validação** | Confere se o @ pode ser convidado, antes do convite | A Bia, no atendimento |
| **TikTok Partner Bridge** | Envia o convite de agenciamento | A Bia, no atendimento |

- As três voltam sozinhas se o navegador cair. O login só é pedido quando o TikTok exige e-mail e senha.
- Quando uma ponte cai, chega um aviso por e-mail e no Telegram (Aquisição HQ), com o link do painel das pontes.
- As pontes só leem o Partner Center, com uma exceção: a Partner Bridge envia convites.

## O que entra no banco e quando

| Quando | O quê |
|---|---|
| A cada hora | Vinculados (status 1), saindo (status 4), convites pendentes (status 2), renovação de cada um, contagens oficiais |
| Uma vez por dia (logo depois da coleta) | Histórico: recusou (6), convite expirou (7), saiu (9), contrato venceu (10) |

## A tela para usar: `public.partner_center`

Uma linha por parceria. O ID é o `id_parceria` (o ID do TikTok).

| Coluna | O que é |
|---|---|
| `id_parceria` | ID da parceria no TikTok |
| `tiktok`, `nome` | @ e nome |
| `estado` | Vinculado · Saindo · Convite pendente · Convite não aceito · Recusou o convite · Convite expirou · Saiu (desvinculou) · Contrato venceu · Saiu |
| `convidado_em` | Quando o convite foi criado |
| `contrato_inicio`, `contrato_fim` | Vigência do contrato |
| `dias_para_vencer` | Dias até o fim (só ativos) |
| `renovacao` | Sem pedido · Aguardando aceite · Aceita · Não aceita |
| `renovacao_pedido_em`, `renovacao_expira_em`, `renovacao_novo_fim` | Datas do pedido de renovação |
| `desvinculo_pedido_em`, `desvinculo_conclui_em` | Pedido de saída e quando conclui |
| `saiu_em` | Quando saiu |
| `categoria`, `gmv_nivel` | Categoria Amplify e GMV |
| `origem` | De onde veio a linha: agenciados, convites ou historico |
| `atualizado_em` | Última vez que a coleta viu essa parceria |

Outras telas:
- `partner_center_resumo`: quantos em cada estado.
- `agenciados_conferencia`: contagem oficial do TikTok × banco.
- `agenciados_renovacao`, `agenciados_desvinculando`, `agenciados_convites_pendentes`, `agenciados_ficha` (com telefone).

## Diferença conhecida

O TikTok conta ~5 vinculados a mais do que mostra na lista (1.549 contados, 1.544 listados em 25/11).
Testado com páginas de 100 e de 50: os mesmos 1.544. Esses 5 não aparecem em nenhuma lista, então ficam fora.
A conferência mostra essa diferença em `diferenca_vinculados`.

## Primeira rodada completa (25/11/2026, 11:54 UTC) ✅

Coleta: 1.586 recebidos (1.544 vinculados + 42 saindo), 88 convites pendentes. Histórico (11:56): 2.981 contratos
vencidos, 2.903 convites expirados, 2.363 saídas, 426 recusas.

`partner_center_resumo`: Vinculado 1.544 · Saindo 42 · Convite pendente 88 · Recusou 426 · Convite expirou 2.904 ·
Saiu (desvinculou) 2.364 · Contrato venceu 2.983 · outros 3.

Pontes no momento: Agenciamento ✅ e Partner Bridge ✅. A Pré-validação está esperando login (modo "login").
