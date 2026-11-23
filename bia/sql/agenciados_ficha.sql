-- Fase A2 (23/11/2026): ficha completa de cada agenciado e histórico do que muda, espelhando o Partner Center.
-- A coleta de hora em hora (public.registrar_coleta_agenciados_v5) passa a receber os detalhes da ponte
-- (?detalhes=1: nível, GMV do nível, seguidores, categorias, comissão, datas do contrato) e a gravar eventos:
-- entrou, voltou, saiu, renovou, mudou_nivel. Sem detalhes (ponte antiga), tudo funciona como antes.
-- Depende de agenciados_tiktok.sql e telefones_agenciados.sql.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

ALTER TABLE interno.agenciados_tiktok
  ADD COLUMN IF NOT EXISTS creator_id text,
  ADD COLUMN IF NOT EXISTS contrato_inicio timestamptz,      -- effective_start_date_second
  ADD COLUMN IF NOT EXISTS expira_em timestamptz,            -- expire_time_second
  ADD COLUMN IF NOT EXISTS nivel smallint,                   -- creator_tier.level
  ADD COLUMN IF NOT EXISTS nivel_nome text,                  -- creator_tier.name (ex.: "Level 2")
  ADD COLUMN IF NOT EXISTS nivel_proximo smallint,           -- creator_tier_progress.target_tier.level
  ADD COLUMN IF NOT EXISTS gmv_nivel numeric(14, 2),         -- creator_tier_progress.current_gmv
  ADD COLUMN IF NOT EXISTS gmv_meta numeric(14, 2),          -- creator_tier_progress.target_gmv
  ADD COLUMN IF NOT EXISTS progresso_pct smallint,           -- creator_tier_progress.progress_percent
  ADD COLUMN IF NOT EXISTS seguidores bigint,                -- creator_info.fans_cnt
  ADD COLUMN IF NOT EXISTS categorias text[],                -- creator_info.categories[].name
  ADD COLUMN IF NOT EXISTS comissao_pct numeric(6, 2),       -- commission_relation.commission_proportion
  ADD COLUMN IF NOT EXISTS desvinculos_recusados integer,    -- partner_reject_unlink_times
  ADD COLUMN IF NOT EXISTS detalhes_em timestamptz;          -- última coleta que trouxe detalhes

CREATE TABLE IF NOT EXISTS interno.agenciados_eventos (
  id bigserial PRIMARY KEY,
  relation_id text NOT NULL,
  arroba text,
  tipo text NOT NULL CHECK (tipo IN ('entrou', 'voltou', 'saiu', 'renovou', 'mudou_nivel')),
  observado_em timestamptz NOT NULL,
  nivel smallint,                 -- nível no momento (para "saíram 3 Silver")
  nivel_nome text,
  gmv_nivel numeric(14, 2),
  antes jsonb,                    -- renovou: {"vigencia_fim"}; mudou_nivel: {"nivel"}
  depois jsonb
);
CREATE INDEX IF NOT EXISTS agenciados_eventos_quando ON interno.agenciados_eventos (observado_em);
CREATE INDEX IF NOT EXISTS agenciados_eventos_relacao ON interno.agenciados_eventos (relation_id);
ALTER TABLE interno.agenciados_eventos ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON interno.agenciados_eventos FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON interno.agenciados_eventos TO service_role;
GRANT USAGE ON SEQUENCE interno.agenciados_eventos_id_seq TO service_role;

-- p = {"observado_em", "total", "completa", "fonte", "itens": [{"relation_id", "arroba", "creator_name",
--      "create_time_second", "effective_end_date_second", e opcionais: "creator_id", "start_second",
--      "expire_time_second", "nivel", "nivel_nome", "nivel_proximo", "gmv_nivel", "gmv_meta", "progresso_pct",
--      "seguidores", "categorias": [..], "comissao_pct", "desvinculos_recusados"}]}
CREATE OR REPLACE FUNCTION public.registrar_coleta_agenciados_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  obs timestamptz;
  itens jsonb := p -> 'itens';
  n_recebidos integer;
  n_total integer;
  completa boolean := coalesce((p ->> 'completa')::boolean, false);
  n_novos integer;
  n_sumiram integer;
  aplicar_saidas boolean;
  n_sairam integer := 0;
  n_eventos integer := 0;
  n_detalhes integer;
BEGIN
  IF current_user NOT IN ('service_role', 'postgres') THEN
    RAISE EXCEPTION USING errcode = '42501', message = 'Só a Bia (service_role) registra coletas.';
  END IF;
  obs := (p ->> 'observado_em')::timestamptz;
  IF obs IS NULL OR obs > now() + interval '5 minutes' OR jsonb_typeof(itens) <> 'array' THEN
    RAISE EXCEPTION USING errcode = '23514', message = 'Coleta inválida: informe observado_em e itens.';
  END IF;
  -- Uma coleta por 45 minutos (vários processos da Bia não duplicam).
  IF EXISTS (SELECT 1 FROM interno.agenciados_tiktok_coletas WHERE observado_em > obs - interval '45 minutes') THEN
    RETURN jsonb_build_object('status', 'ignorada', 'motivo', 'coleta_recente');
  END IF;
  n_recebidos := jsonb_array_length(itens);
  n_total := nullif(p ->> 'total', '')::integer;

  DROP TABLE IF EXISTS pg_temp._coleta;
  CREATE TEMP TABLE _coleta ON COMMIT DROP AS
  SELECT DISTINCT ON (x ->> 'relation_id')
         x ->> 'relation_id' AS relation_id,
         nullif(lower(btrim(ltrim(x ->> 'arroba', '@'))), '') AS arroba,
         nullif(btrim(x ->> 'creator_name'), '') AS nome,
         CASE WHEN (x ->> 'create_time_second') ~ '^[1-9][0-9]{8,10}$'
              THEN to_timestamp((x ->> 'create_time_second')::bigint) END AS vinculado_em,
         CASE WHEN (x ->> 'effective_end_date_second') ~ '^[1-9][0-9]{8,10}$'
              THEN to_timestamp((x ->> 'effective_end_date_second')::bigint) END AS vigencia_fim,
         CASE WHEN (x ->> 'creator_id') ~ '^[0-9]{1,30}$' THEN x ->> 'creator_id' END AS creator_id,
         CASE WHEN (x ->> 'start_second') ~ '^[1-9][0-9]{8,10}$'
              THEN to_timestamp((x ->> 'start_second')::bigint) END AS contrato_inicio,
         CASE WHEN (x ->> 'expire_time_second') ~ '^[1-9][0-9]{8,10}$'
              THEN to_timestamp((x ->> 'expire_time_second')::bigint) END AS expira_em,
         CASE WHEN (x ->> 'nivel') ~ '^[0-9]{1,2}$' THEN (x ->> 'nivel')::smallint END AS nivel,
         nullif(left(btrim(x ->> 'nivel_nome'), 40), '') AS nivel_nome,
         CASE WHEN (x ->> 'nivel_proximo') ~ '^[0-9]{1,2}$' THEN (x ->> 'nivel_proximo')::smallint END AS nivel_proximo,
         CASE WHEN (x ->> 'gmv_nivel') ~ '^[0-9]{1,11}(\.[0-9]{1,2})?$' THEN (x ->> 'gmv_nivel')::numeric END AS gmv_nivel,
         CASE WHEN (x ->> 'gmv_meta') ~ '^[0-9]{1,11}(\.[0-9]{1,2})?$' THEN (x ->> 'gmv_meta')::numeric END AS gmv_meta,
         CASE WHEN (x ->> 'progresso_pct') ~ '^[0-9]{1,3}$' AND (x ->> 'progresso_pct')::int <= 100
              THEN (x ->> 'progresso_pct')::smallint END AS progresso_pct,
         CASE WHEN (x ->> 'seguidores') ~ '^[0-9]{1,12}$' THEN (x ->> 'seguidores')::bigint END AS seguidores,
         CASE WHEN jsonb_typeof(x -> 'categorias') = 'array'
              THEN (SELECT array_agg(left(btrim(c), 80)) FROM (
                      SELECT c FROM jsonb_array_elements_text(x -> 'categorias') c
                      WHERE btrim(c) <> '' LIMIT 10) cs) END AS categorias,
         CASE WHEN (x ->> 'comissao_pct') ~ '^[0-9]{1,3}(\.[0-9]{1,2})?$' THEN (x ->> 'comissao_pct')::numeric END AS comissao_pct,
         CASE WHEN (x ->> 'desvinculos_recusados') ~ '^[0-9]{1,6}$' THEN (x ->> 'desvinculos_recusados')::int END
           AS desvinculos_recusados
  FROM jsonb_array_elements(itens) x
  WHERE (x ->> 'relation_id') ~ '^[0-9A-Za-z_-]{1,64}$';

  SELECT count(*) INTO n_novos FROM _coleta c
  WHERE NOT EXISTS (SELECT 1 FROM interno.agenciados_tiktok a WHERE a.relation_id = c.relation_id);
  SELECT count(*) INTO n_detalhes FROM _coleta WHERE nivel IS NOT NULL OR seguidores IS NOT NULL;

  -- Eventos comparando a coleta com o que o banco já sabia (antes de atualizar).
  INSERT INTO interno.agenciados_eventos (relation_id, arroba, tipo, observado_em, nivel, nivel_nome, gmv_nivel, antes, depois)
  SELECT c.relation_id, c.arroba, e.tipo, obs, coalesce(c.nivel, a.nivel), coalesce(c.nivel_nome, a.nivel_nome),
         coalesce(c.gmv_nivel, a.gmv_nivel), e.antes, e.depois
  FROM _coleta c
  LEFT JOIN interno.agenciados_tiktok a ON a.relation_id = c.relation_id
  CROSS JOIN LATERAL (VALUES
    (CASE WHEN a.relation_id IS NULL THEN 'entrou' WHEN NOT a.ativo THEN 'voltou' END, NULL::jsonb, NULL::jsonb),
    (CASE WHEN a.vigencia_fim IS NOT NULL AND c.vigencia_fim > a.vigencia_fim + interval '1 day' THEN 'renovou' END,
     jsonb_build_object('vigencia_fim', a.vigencia_fim), jsonb_build_object('vigencia_fim', c.vigencia_fim)),
    (CASE WHEN a.nivel IS NOT NULL AND c.nivel IS NOT NULL AND c.nivel <> a.nivel THEN 'mudou_nivel' END,
     jsonb_build_object('nivel', a.nivel, 'nivel_nome', a.nivel_nome),
     jsonb_build_object('nivel', c.nivel, 'nivel_nome', c.nivel_nome))
  ) e(tipo, antes, depois)
  WHERE e.tipo IS NOT NULL;
  GET DIAGNOSTICS n_eventos = ROW_COUNT;

  INSERT INTO interno.agenciados_tiktok AS a
    (relation_id, arroba, nome_tiktok, vinculado_em, vigencia_fim, primeira_coleta_em, ultima_coleta_em, ativo, saiu_em,
     creator_id, contrato_inicio, expira_em, nivel, nivel_nome, nivel_proximo, gmv_nivel, gmv_meta, progresso_pct,
     seguidores, categorias, comissao_pct, desvinculos_recusados, detalhes_em)
  SELECT relation_id, arroba, nome, vinculado_em, vigencia_fim, obs, obs, true, NULL,
         creator_id, contrato_inicio, expira_em, nivel, nivel_nome, nivel_proximo, gmv_nivel, gmv_meta, progresso_pct,
         seguidores, categorias, comissao_pct, desvinculos_recusados,
         CASE WHEN nivel IS NOT NULL OR seguidores IS NOT NULL THEN obs END
  FROM _coleta
  ON CONFLICT (relation_id) DO UPDATE SET
    arroba = coalesce(excluded.arroba, a.arroba), nome_tiktok = coalesce(excluded.nome_tiktok, a.nome_tiktok),
    vinculado_em = coalesce(a.vinculado_em, excluded.vinculado_em), vigencia_fim = excluded.vigencia_fim,
    ultima_coleta_em = obs, ativo = true, saiu_em = NULL,
    creator_id = coalesce(excluded.creator_id, a.creator_id),
    contrato_inicio = coalesce(excluded.contrato_inicio, a.contrato_inicio),
    expira_em = coalesce(excluded.expira_em, a.expira_em),
    nivel = coalesce(excluded.nivel, a.nivel), nivel_nome = coalesce(excluded.nivel_nome, a.nivel_nome),
    nivel_proximo = coalesce(excluded.nivel_proximo, a.nivel_proximo),
    gmv_nivel = coalesce(excluded.gmv_nivel, a.gmv_nivel), gmv_meta = coalesce(excluded.gmv_meta, a.gmv_meta),
    progresso_pct = coalesce(excluded.progresso_pct, a.progresso_pct),
    seguidores = coalesce(excluded.seguidores, a.seguidores), categorias = coalesce(excluded.categorias, a.categorias),
    comissao_pct = coalesce(excluded.comissao_pct, a.comissao_pct),
    desvinculos_recusados = coalesce(excluded.desvinculos_recusados, a.desvinculos_recusados),
    detalhes_em = coalesce(excluded.detalhes_em, a.detalhes_em);

  -- Saídas só com lista completa e sem queda brusca (proteção contra lista cortada).
  SELECT count(*) INTO n_sumiram FROM interno.agenciados_tiktok WHERE ativo AND ultima_coleta_em < obs;
  aplicar_saidas := completa AND n_total IS NOT NULL AND n_recebidos >= n_total - 10
                    AND n_sumiram <= greatest(20, (SELECT count(*) FROM _coleta) / 20);
  IF aplicar_saidas THEN
    INSERT INTO interno.agenciados_eventos (relation_id, arroba, tipo, observado_em, nivel, nivel_nome, gmv_nivel)
    SELECT relation_id, arroba, 'saiu', obs, nivel, nivel_nome, gmv_nivel
    FROM interno.agenciados_tiktok WHERE ativo AND ultima_coleta_em < obs;
    UPDATE interno.agenciados_tiktok SET ativo = false, saiu_em = obs WHERE ativo AND ultima_coleta_em < obs;
    GET DIAGNOSTICS n_sairam = ROW_COUNT;
    n_eventos := n_eventos + n_sairam;
  END IF;

  INSERT INTO interno.agenciados_tiktok_coletas
    (observado_em, total_informado, recebidos, completa, entraram, sairam, ativos, saidas_aplicadas, fonte)
  VALUES (obs, n_total, n_recebidos, completa, n_novos, n_sairam,
          (SELECT count(*) FROM interno.agenciados_tiktok WHERE ativo), aplicar_saidas,
          coalesce(nullif(p ->> 'fonte', ''), 'ponte_agenciamento'));

  RETURN jsonb_build_object('status', 'registrada', 'recebidos', n_recebidos, 'entraram', n_novos,
                            'sairam', n_sairam, 'saidas_aplicadas', aplicar_saidas,
                            'com_detalhes', n_detalhes, 'eventos', n_eventos);
END
$fn$;
REVOKE ALL ON FUNCTION public.registrar_coleta_agenciados_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_coleta_agenciados_v5(jsonb) TO service_role;

-- ---- Telas (horário de São Paulo; só o sistema lê) ----

-- A ficha: 1 linha por agenciado (ativo ou que saiu), com contrato, nível, GMV e o melhor telefone.
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
       a.relation_id, a.creator_id
FROM interno.agenciados_tiktok a
LEFT JOIN LATERAL (
  SELECT c.telefone, c.fonte FROM interno.telefones_creators c WHERE c.arroba = a.arroba
  ORDER BY array_position(ARRAY['formulario', 'ficha_bia', 'base_amplify', 'notion'], c.fonte), c.visto_em DESC NULLS LAST
  LIMIT 1) t ON true
LEFT JOIN LATERAL (SELECT x.id, x.origem FROM public.creators x
                   WHERE lower(btrim(ltrim(x.tiktok, '@'))) = a.arroba LIMIT 1) f ON a.arroba IS NOT NULL;

-- O que mudou, hora a hora: quem entrou, saiu, voltou, renovou ou mudou de nível (com nível e GMV no momento).
CREATE OR REPLACE VIEW public.agenciados_movimento AS
SELECT (e.observado_em AT TIME ZONE 'America/Sao_Paulo') AS quando,
       (e.observado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
       e.tipo, '@' || e.arroba AS tiktok, e.nivel, e.nivel_nome, e.gmv_nivel,
       e.antes, e.depois, e.relation_id
FROM interno.agenciados_eventos e;

-- Por dia e nível: "saíram 3 do Level 2 hoje".
CREATE OR REPLACE VIEW public.agenciados_movimento_por_nivel AS
SELECT (e.observado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
       coalesce(e.nivel_nome, 'Sem nível') AS nivel,
       count(*) FILTER (WHERE e.tipo IN ('entrou', 'voltou')) AS entraram,
       count(*) FILTER (WHERE e.tipo = 'saiu') AS sairam,
       count(*) FILTER (WHERE e.tipo = 'renovou') AS renovaram,
       coalesce(sum(e.gmv_nivel) FILTER (WHERE e.tipo = 'saiu'), 0) AS gmv_de_quem_saiu
FROM interno.agenciados_eventos e
GROUP BY 1, 2;

-- Hoje, por nível.
CREATE OR REPLACE VIEW public.agenciados_por_nivel AS
SELECT coalesce(a.nivel_nome, 'Sem nível') AS nivel, a.nivel AS ordem,
       count(*) AS agenciados, coalesce(sum(a.gmv_nivel), 0) AS gmv_total,
       count(*) FILTER (WHERE a.vigencia_fim < now() + interval '30 days') AS vencem_em_30_dias
FROM interno.agenciados_tiktok a
WHERE a.ativo
GROUP BY 1, 2;

-- Renovação: quem vence nos próximos 45 dias, com nível, GMV e telefone.
CREATE OR REPLACE VIEW public.agenciados_a_vencer AS
SELECT f.tiktok, f.nome, f.contrato_fim, f.dias_para_vencer, f.nivel_nome, f.gmv_nivel, f.seguidores,
       f.telefone, f.fonte_telefone, f.renovacoes, f.relation_id
FROM public.agenciados_ficha f
WHERE f.situacao = 'Ativo' AND f.dias_para_vencer BETWEEN 0 AND 45;

REVOKE ALL ON public.agenciados_ficha, public.agenciados_movimento, public.agenciados_movimento_por_nivel,
  public.agenciados_por_nivel, public.agenciados_a_vencer FROM anon, authenticated;
GRANT SELECT ON public.agenciados_ficha, public.agenciados_movimento, public.agenciados_movimento_por_nivel,
  public.agenciados_por_nivel, public.agenciados_a_vencer TO service_role;
COMMIT;
