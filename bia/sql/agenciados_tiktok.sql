-- Agenciados do TikTok Partner Center: foto de hora em hora, entradas e saídas (21/11/2026).
-- A Bia lê a lista completa na ponte de Agenciamento (só leitura) e grava aqui pela função
-- public.registrar_coleta_agenciados_v5. As telas ficam em public.agenciados*.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS interno.agenciados_tiktok (
  relation_id text PRIMARY KEY CHECK (relation_id ~ '^[0-9A-Za-z_-]{1,64}$'),
  arroba text,                        -- minúsculo, sem "@"
  nome_tiktok text,
  vinculado_em timestamptz,           -- create_time_second do TikTok
  vigencia_fim timestamptz,           -- effective_end_date_second
  primeira_coleta_em timestamptz NOT NULL,
  ultima_coleta_em timestamptz NOT NULL,
  ativo boolean NOT NULL DEFAULT true,
  saiu_em timestamptz
);
CREATE INDEX IF NOT EXISTS agenciados_tiktok_arroba ON interno.agenciados_tiktok (arroba);
CREATE INDEX IF NOT EXISTS agenciados_tiktok_vinculado ON interno.agenciados_tiktok (vinculado_em);

CREATE TABLE IF NOT EXISTS interno.agenciados_tiktok_coletas (
  id bigserial PRIMARY KEY,
  observado_em timestamptz NOT NULL,
  total_informado integer,
  recebidos integer NOT NULL,
  completa boolean NOT NULL,
  entraram integer NOT NULL,
  sairam integer NOT NULL,
  ativos integer NOT NULL,
  saidas_aplicadas boolean NOT NULL,
  fonte text NOT NULL
);

ALTER TABLE interno.agenciados_tiktok ENABLE ROW LEVEL SECURITY;
ALTER TABLE interno.agenciados_tiktok_coletas ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON interno.agenciados_tiktok, interno.agenciados_tiktok_coletas FROM PUBLIC, anon, authenticated;

-- p = {"observado_em": iso, "total": int, "completa": bool, "fonte": text,
--      "itens": [{"relation_id", "arroba", "creator_name", "create_time_second", "effective_end_date_second"}]}
CREATE OR REPLACE FUNCTION public.registrar_coleta_agenciados_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  obs timestamptz;
  itens jsonb := p -> 'itens';
  n_recebidos integer;
  n_total integer;
  completa boolean := coalesce((p ->> 'completa')::boolean, false);
  n_novos integer;
  n_ativos_antes integer;
  n_sumiram integer;
  aplicar_saidas boolean;
  n_sairam integer := 0;
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

  CREATE TEMP TABLE _coleta ON COMMIT DROP AS
  SELECT DISTINCT ON (x ->> 'relation_id')
         x ->> 'relation_id' AS relation_id,
         nullif(lower(btrim(ltrim(x ->> 'arroba', '@'))), '') AS arroba,
         nullif(btrim(x ->> 'creator_name'), '') AS nome,
         CASE WHEN (x ->> 'create_time_second') ~ '^[1-9][0-9]{8,10}$'
              THEN to_timestamp((x ->> 'create_time_second')::bigint) END AS vinculado_em,
         CASE WHEN (x ->> 'effective_end_date_second') ~ '^[1-9][0-9]{8,10}$'
              THEN to_timestamp((x ->> 'effective_end_date_second')::bigint) END AS vigencia_fim
  FROM jsonb_array_elements(itens) x
  WHERE (x ->> 'relation_id') ~ '^[0-9A-Za-z_-]{1,64}$';

  SELECT count(*) INTO n_novos FROM _coleta c
  WHERE NOT EXISTS (SELECT 1 FROM interno.agenciados_tiktok a WHERE a.relation_id = c.relation_id);

  INSERT INTO interno.agenciados_tiktok AS a
    (relation_id, arroba, nome_tiktok, vinculado_em, vigencia_fim, primeira_coleta_em, ultima_coleta_em, ativo, saiu_em)
  SELECT relation_id, arroba, nome, vinculado_em, vigencia_fim, obs, obs, true, NULL FROM _coleta
  ON CONFLICT (relation_id) DO UPDATE SET
    arroba = coalesce(excluded.arroba, a.arroba), nome_tiktok = coalesce(excluded.nome_tiktok, a.nome_tiktok),
    vinculado_em = coalesce(a.vinculado_em, excluded.vinculado_em), vigencia_fim = excluded.vigencia_fim,
    ultima_coleta_em = obs, ativo = true, saiu_em = NULL;

  -- Saídas só com lista completa e sem queda brusca (proteção contra lista cortada).
  SELECT count(*) INTO n_ativos_antes FROM interno.agenciados_tiktok WHERE ativo AND ultima_coleta_em < obs;
  SELECT count(*) INTO n_sumiram FROM interno.agenciados_tiktok WHERE ativo AND ultima_coleta_em < obs;
  aplicar_saidas := completa AND n_total IS NOT NULL AND n_recebidos >= n_total - 10
                    AND n_sumiram <= greatest(20, (SELECT count(*) FROM _coleta) / 20);
  IF aplicar_saidas THEN
    UPDATE interno.agenciados_tiktok SET ativo = false, saiu_em = obs WHERE ativo AND ultima_coleta_em < obs;
    GET DIAGNOSTICS n_sairam = ROW_COUNT;
  END IF;

  INSERT INTO interno.agenciados_tiktok_coletas
    (observado_em, total_informado, recebidos, completa, entraram, sairam, ativos, saidas_aplicadas, fonte)
  VALUES (obs, n_total, n_recebidos, completa, n_novos, n_sairam,
          (SELECT count(*) FROM interno.agenciados_tiktok WHERE ativo), aplicar_saidas,
          coalesce(nullif(p ->> 'fonte', ''), 'ponte_agenciamento'));

  RETURN jsonb_build_object('status', 'registrada', 'recebidos', n_recebidos, 'entraram', n_novos,
                            'sairam', n_sairam, 'saidas_aplicadas', aplicar_saidas);
END
$fn$;
REVOKE ALL ON FUNCTION public.registrar_coleta_agenciados_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_coleta_agenciados_v5(jsonb) TO service_role;
GRANT SELECT, INSERT, UPDATE ON interno.agenciados_tiktok TO service_role;
GRANT SELECT, INSERT ON interno.agenciados_tiktok_coletas TO service_role;
GRANT USAGE ON SEQUENCE interno.agenciados_tiktok_coletas_id_seq TO service_role;

-- Telas (horário de São Paulo).
CREATE OR REPLACE VIEW public.agenciados AS
SELECT '@' || a.arroba AS tiktok, a.nome_tiktok AS nome,
       (a.vinculado_em AT TIME ZONE 'America/Sao_Paulo') AS agenciado_em,
       CASE WHEN a.ativo THEN 'Ativo' ELSE 'Saiu' END AS situacao,
       (a.saiu_em AT TIME ZONE 'America/Sao_Paulo') AS saiu_em,
       CASE WHEN c.id IS NOT NULL THEN 'Sim' ELSE 'Não' END AS passou_pela_bia,
       c.nome AS nome_na_ficha, c.origem,
       (a.ultima_coleta_em AT TIME ZONE 'America/Sao_Paulo') AS conferido_em
FROM interno.agenciados_tiktok a
LEFT JOIN LATERAL (SELECT f.id, f.nome, f.origem FROM public.creators f
                   WHERE lower(btrim(ltrim(f.tiktok, '@'))) = a.arroba LIMIT 1) c ON a.arroba IS NOT NULL;

CREATE OR REPLACE VIEW public.agenciados_por_hora AS
SELECT date_trunc('hour', a.vinculado_em AT TIME ZONE 'America/Sao_Paulo') AS hora,
       count(*) AS novos_agenciados,
       count(*) FILTER (WHERE c.id IS NOT NULL) AS novos_pela_bia
FROM interno.agenciados_tiktok a
LEFT JOIN LATERAL (SELECT f.id FROM public.creators f
                   WHERE lower(btrim(ltrim(f.tiktok, '@'))) = a.arroba LIMIT 1) c ON a.arroba IS NOT NULL
WHERE a.vinculado_em >= now() - interval '31 days'
GROUP BY 1;

CREATE OR REPLACE VIEW public.agenciados_por_dia AS
WITH dias AS (
  SELECT (a.vinculado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia, a.arroba, 'entrou' AS tipo
  FROM interno.agenciados_tiktok a WHERE a.vinculado_em IS NOT NULL
  UNION ALL
  SELECT (a.saiu_em AT TIME ZONE 'America/Sao_Paulo')::date, a.arroba, 'saiu'
  FROM interno.agenciados_tiktok a WHERE a.saiu_em IS NOT NULL
)
SELECT d.dia,
       count(*) FILTER (WHERE d.tipo = 'entrou') AS novos_agenciados,
       count(*) FILTER (WHERE d.tipo = 'entrou' AND EXISTS (
         SELECT 1 FROM public.creators f WHERE lower(btrim(ltrim(f.tiktok, '@'))) = d.arroba)) AS novos_pela_bia,
       count(*) FILTER (WHERE d.tipo = 'saiu') AS sairam,
       (SELECT count(*) FROM interno.agenciados_tiktok x
         WHERE (x.vinculado_em AT TIME ZONE 'America/Sao_Paulo')::date <= d.dia
           AND (x.saiu_em IS NULL OR (x.saiu_em AT TIME ZONE 'America/Sao_Paulo')::date > d.dia)) AS total_no_fim_do_dia
FROM dias d
GROUP BY d.dia;

CREATE OR REPLACE VIEW public.origens_por_dia AS
SELECT (f.primeiro_contato AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
       f.origem,
       count(*) AS novos_contatos,
       count(*) FILTER (WHERE f.etapa IN ('Convite', 'Formulário', 'Cadastro confirmado')) AS chegaram_ao_convite,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM interno.agenciados_tiktok a
                                      WHERE a.arroba = lower(btrim(ltrim(f.tiktok, '@'))) AND a.ativo)) AS agenciados,
       count(*) FILTER (WHERE f.cadastro = 'Confirmado') AS cadastros
FROM public.creators f
WHERE f.primeiro_contato IS NOT NULL
GROUP BY 1, 2;

REVOKE ALL ON public.agenciados, public.agenciados_por_hora, public.agenciados_por_dia, public.origens_por_dia
  FROM anon, authenticated;
GRANT SELECT ON public.agenciados, public.agenciados_por_hora, public.agenciados_por_dia, public.origens_por_dia
  TO service_role;
COMMIT;
