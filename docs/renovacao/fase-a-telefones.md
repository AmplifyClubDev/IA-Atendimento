# Renovação · Fase A: telefones no Supabase (23/11/2026)

**Em 1 linha:** a tabela de telefones está no ar, com o que já tínhamos. Para chegar em todo mundo, falta a
base externa (outro Supabase) e o Notion.

## Feito

1. Tabela `interno.telefones_creators`: telefone por @, com a fonte de cada um. Sem duplicar.
2. Tela `public.agenciados_contato`: agenciado, data de vencimento, dias que faltam e o melhor telefone.
3. Preenchida com as fontes internas: 1.022 da ficha da Bia e 222 do formulário (1.244 linhas).
4. Testes: simulação completa desfeita antes de aplicar, teste rodado de novo depois. Público (anon) não lê.
5. Importador pronto: `bia/tools/importar_telefones.py` (só lê a fonte; sem `--gravar`, só conta).

## Resultado hoje

| | Total | Com telefone |
|---|---|---|
| Agenciados ativos | 1.536 | 238 |
| Vencem em 30 dias | 225 | 6 |

## Falta

- **Base Amplify (outro Supabase):** endereço + chave de leitura. O token atual não enxerga esse projeto.
- **Notion:** a "Base de Renovação" e os "Novos Creators" têm telefone. Dá para ler pela integração do Notion
  (acesso só leitura) ou por uma exportação CSV.
