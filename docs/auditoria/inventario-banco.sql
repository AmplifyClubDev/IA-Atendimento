-- Inventário do banco (SÓ LEITURA). Cole no SQL Editor do Supabase e clique em Run.
-- Resultado: 1 linha, 1 coluna "inventario" (JSON). Copie o valor inteiro e cole no chat.
-- Não lê nenhum dado de pessoas: só nomes de tabelas/colunas, contagens e dependências.
WITH tabelas AS (
  SELECT n.nspname AS esquema, c.relname AS nome,
         CASE c.relkind WHEN 'r' THEN 'tabela' WHEN 'v' THEN 'visao' WHEN 'm' THEN 'visao_mat' WHEN 'p' THEN 'tabela' END AS tipo,
         c.reltuples::bigint AS linhas_aprox,
         pg_total_relation_size(c.oid) AS bytes,
         s.seq_scan + COALESCE(s.idx_scan, 0) AS leituras,
         s.n_tup_ins + s.n_tup_upd + s.n_tup_del AS escritas,
         GREATEST(s.last_autoanalyze, s.last_analyze) AS ultima_analise
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
  WHERE c.relkind IN ('r','v','m','p')
    AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast','auth','storage','realtime',
                          'supabase_functions','supabase_migrations','extensions','graphql','graphql_public',
                          'vault','pgsodium','pgsodium_masks','net','cron','_realtime','pgbouncer')
),
colunas AS (
  SELECT a.table_schema AS esquema, a.table_name AS tabela, a.column_name AS coluna, a.data_type AS tipo,
         st.null_frac AS fracao_vazia, st.n_distinct AS distintos
  FROM information_schema.columns a
  LEFT JOIN pg_stats st ON st.schemaname = a.table_schema AND st.tablename = a.table_name AND st.attname = a.column_name
  WHERE (a.table_schema, a.table_name) IN (SELECT esquema, nome FROM tabelas)
),
dependencias AS (
  SELECT DISTINCT vn.nspname || '.' || v.relname AS visao, tn.nspname || '.' || t.relname AS usa
  FROM pg_depend d
  JOIN pg_rewrite r ON r.oid = d.objid
  JOIN pg_class v ON v.oid = r.ev_class
  JOIN pg_namespace vn ON vn.oid = v.relnamespace
  JOIN pg_class t ON t.oid = d.refobjid
  JOIN pg_namespace tn ON tn.oid = t.relnamespace
  WHERE d.classid = 'pg_rewrite'::regclass AND v.oid <> t.oid
    AND (tn.nspname, t.relname) IN (SELECT esquema, nome FROM tabelas)
),
funcoes AS (
  SELECT n.nspname || '.' || p.proname AS funcao,
         (SELECT array_agg(DISTINCT t.esquema || '.' || t.nome)
            FROM tabelas t WHERE p.prosrc ~* ('\m' || t.nome || '\M')) AS usa
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname IN (SELECT DISTINCT esquema FROM tabelas)
),
gatilhos AS (
  SELECT tn.nspname || '.' || c.relname AS tabela, tg.tgname AS gatilho, pn.nspname || '.' || p.proname AS funcao
  FROM pg_trigger tg JOIN pg_class c ON c.oid = tg.tgrelid JOIN pg_namespace tn ON tn.oid = c.relnamespace
  JOIN pg_proc p ON p.oid = tg.tgfoid JOIN pg_namespace pn ON pn.oid = p.pronamespace
  WHERE NOT tg.tgisinternal
)
SELECT jsonb_build_object(
  'tabelas', (SELECT jsonb_agg(to_jsonb(t) ORDER BY esquema, nome) FROM tabelas t),
  'colunas', (SELECT jsonb_agg(to_jsonb(c) ORDER BY esquema, tabela, coluna) FROM colunas c),
  'visoes_usam', (SELECT jsonb_agg(to_jsonb(d)) FROM dependencias d),
  'funcoes_usam', (SELECT jsonb_agg(to_jsonb(f)) FROM funcoes f WHERE f.usa IS NOT NULL),
  'gatilhos', (SELECT jsonb_agg(to_jsonb(g)) FROM gatilhos g)
) AS inventario;

-- OPCIONAL (rode separado; se der erro "does not exist", ignore): histórico de migrations.
-- SELECT version, name FROM supabase_migrations.schema_migrations ORDER BY version;
