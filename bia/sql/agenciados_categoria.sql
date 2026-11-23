-- Categoria Amplify de cada agenciado (23/11/2026), pela regra oficial (card "Categorias e GMV" e Cadastro):
-- Start até R$ 4.999, Silver a partir de R$ 5 mil, Gold a partir de R$ 30 mil, Diamond a partir de R$ 100 mil.
-- Usa o GMV que o Partner Center mostra para o nível do creator (creator_tier_progress.current_gmv).
-- Não é o "Level" do TikTok (Level 0 a 6), que tem outra régua. Depende de agenciados_ficha.sql.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE OR REPLACE FUNCTION interno.categoria_amplify(gmv numeric)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  SELECT CASE WHEN gmv IS NULL OR gmv < 0 THEN NULL
              WHEN gmv >= 100000 THEN 'Diamond'
              WHEN gmv >= 30000 THEN 'Gold'
              WHEN gmv >= 5000 THEN 'Silver'
              ELSE 'Start' END
$fn$;

CREATE OR REPLACE FUNCTION interno.ordem_categoria(categoria text)
RETURNS smallint LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  SELECT CASE categoria WHEN 'Start' THEN 1 WHEN 'Silver' THEN 2 WHEN 'Gold' THEN 3 WHEN 'Diamond' THEN 4 END::smallint
$fn$;

-- Telas existentes ganham a coluna "categoria" no fim (as colunas de antes não mudam).
CREATE OR REPLACE VIEW public.agenciados_ficha AS
SELECT '@' || a.arroba AS tiktok, a.nome_tiktok AS nome,
       CASE WHEN a.ativo THEN 'Ativo' ELSE 'Saiu' END AS situacao,
       (a.vinculado_em AT TIME ZONE 'America/Sao_Paulo') AS agenciado_em,
       (a.saiu_em AT TIME ZONE 'America/Sao_Paulo') AS saiu_em,
       (a.contrato_inicio AT TIME ZONE 'America/Sao_Paulo')::date AS contrato_inicio,
       (a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date AS contrato_fim,
       CASE WHEN a.ativo THEN (a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date
                              - (now() AT TIME ZONE 'America/Sao_Paulo')::date END AS dias_para_vencer,
       a.nivel, a.nivel_nome, a.gmv_nivel, a.gmv_meta, a.progresso_pct, a.nivel_proximo,
       a.seguidores, array_to_string(a.categorias, ', ') AS categorias, a.comissao_pct,
       t.telefone, t.fonte AS fonte_telefone,
       CASE WHEN f.id IS NOT NULL THEN 'Sim' ELSE 'Não' END AS passou_pela_bia, f.origem,
       (SELECT count(*) FROM interno.agenciados_eventos e WHERE e.relation_id = a.relation_id AND e.tipo = 'renovou')
         AS renovacoes,
       (a.ultima_coleta_em AT TIME ZONE 'America/Sao_Paulo') AS conferido_em,
       (a.detalhes_em AT TIME ZONE 'America/Sao_Paulo') AS detalhes_em,
       a.relation_id, a.creator_id,
       interno.categoria_amplify(a.gmv_nivel) AS categoria
FROM interno.agenciados_tiktok a
LEFT JOIN LATERAL (
  SELECT c.telefone, c.fonte FROM interno.telefones_creators c WHERE c.arroba = a.arroba
  ORDER BY array_position(ARRAY['formulario', 'ficha_bia', 'base_amplify', 'notion'], c.fonte), c.visto_em DESC NULLS LAST
  LIMIT 1) t ON true
LEFT JOIN LATERAL (SELECT x.id, x.origem FROM public.creators x
                   WHERE lower(btrim(ltrim(x.tiktok, '@'))) = a.arroba LIMIT 1) f ON a.arroba IS NOT NULL;

CREATE OR REPLACE VIEW public.agenciados_movimento AS
SELECT (e.observado_em AT TIME ZONE 'America/Sao_Paulo') AS quando,
       (e.observado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
       e.tipo, '@' || e.arroba AS tiktok, e.nivel, e.nivel_nome, e.gmv_nivel,
       e.antes, e.depois, e.relation_id,
       interno.categoria_amplify(e.gmv_nivel) AS categoria
FROM interno.agenciados_eventos e;

CREATE OR REPLACE VIEW public.agenciados_a_vencer AS
SELECT f.tiktok, f.nome, f.contrato_fim, f.dias_para_vencer, f.nivel_nome, f.gmv_nivel, f.seguidores,
       f.telefone, f.fonte_telefone, f.renovacoes, f.relation_id, f.categoria
FROM public.agenciados_ficha f
WHERE f.situacao = 'Ativo' AND f.dias_para_vencer BETWEEN 0 AND 45;

-- Novas: por categoria Amplify.
CREATE OR REPLACE VIEW public.agenciados_por_categoria AS
SELECT coalesce(interno.categoria_amplify(a.gmv_nivel), 'Sem GMV') AS categoria,
       interno.ordem_categoria(interno.categoria_amplify(a.gmv_nivel)) AS ordem,
       count(*) AS agenciados, coalesce(sum(a.gmv_nivel), 0) AS gmv_total,
       count(*) FILTER (WHERE a.vigencia_fim < now() + interval '30 days') AS vencem_em_30_dias
FROM interno.agenciados_tiktok a
WHERE a.ativo
GROUP BY 1, 2;

-- Por dia e categoria: "saíram 3 Silver hoje".
CREATE OR REPLACE VIEW public.agenciados_movimento_por_categoria AS
SELECT (e.observado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
       coalesce(interno.categoria_amplify(e.gmv_nivel), 'Sem GMV') AS categoria,
       count(*) FILTER (WHERE e.tipo IN ('entrou', 'voltou')) AS entraram,
       count(*) FILTER (WHERE e.tipo = 'saiu') AS sairam,
       count(*) FILTER (WHERE e.tipo = 'renovou') AS renovaram,
       coalesce(sum(e.gmv_nivel) FILTER (WHERE e.tipo = 'saiu'), 0) AS gmv_de_quem_saiu
FROM interno.agenciados_eventos e
GROUP BY 1, 2;

-- Funções só de cálculo (sem dados): execução liberada, como as outras do schema interno; quem lê as telas
-- precisa poder executá-las. O schema interno não é exposto ao público.
GRANT EXECUTE ON FUNCTION interno.categoria_amplify(numeric), interno.ordem_categoria(text) TO PUBLIC;
REVOKE ALL ON public.agenciados_ficha, public.agenciados_movimento, public.agenciados_a_vencer,
  public.agenciados_por_categoria, public.agenciados_movimento_por_categoria FROM anon, authenticated;
GRANT SELECT ON public.agenciados_ficha, public.agenciados_movimento, public.agenciados_a_vencer,
  public.agenciados_por_categoria, public.agenciados_movimento_por_categoria TO service_role;
COMMIT;
