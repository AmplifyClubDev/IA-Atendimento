-- Telefones dos creators por @ do TikTok, com a fonte de cada um (fase A da renovação, 23/11/2026).
-- Um @ pode ter vários telefones e várias fontes. A tela public.agenciados_contato escolhe o melhor.
-- Fontes: formulario (cadastro), ficha_bia (interno.creators), base_amplify (outro Supabase), notion.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE OR REPLACE FUNCTION interno.normalizar_arroba(v text)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  SELECT nullif(lower(regexp_replace(regexp_replace(regexp_replace(btrim(coalesce(v, '')),
           '^.*tiktok\.com/', '', 'i'), '[/?#].*$', ''), '^@+', '')), '')
$fn$;

-- Só dígitos; 10 ou 11 dígitos ganham o 55. Aceita 12 a 15 dígitos no fim.
CREATE OR REPLACE FUNCTION interno.normalizar_telefone(v text)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  SELECT CASE WHEN length(d) IN (10, 11) THEN '55' || d
              WHEN length(d) BETWEEN 12 AND 15 THEN d END
  FROM (SELECT regexp_replace(coalesce(v, ''), '\D', '', 'g') AS d) x
$fn$;

CREATE TABLE IF NOT EXISTS interno.telefones_creators (
  arroba text NOT NULL CHECK (arroba ~ '^[a-z0-9._]{1,64}$'),
  telefone text NOT NULL CHECK (telefone ~ '^[0-9]{12,15}$'),
  fonte text NOT NULL CHECK (fonte IN ('formulario', 'ficha_bia', 'base_amplify', 'notion')),
  fonte_ref text,                      -- id da linha na fonte (para conferir depois)
  visto_em timestamptz,                -- quando a fonte registrou esse telefone
  importado_em timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (arroba, telefone, fonte)
);
CREATE INDEX IF NOT EXISTS telefones_creators_telefone ON interno.telefones_creators (telefone);
ALTER TABLE interno.telefones_creators ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON interno.telefones_creators FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON interno.telefones_creators TO service_role;

-- p = {"fonte": "base_amplify"|"notion", "itens": [{"arroba", "telefone", "ref", "visto_em"}]}
CREATE OR REPLACE FUNCTION public.importar_telefones_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  f text := p ->> 'fonte';
  n_recebidos integer;
  n_validos integer;
  n_gravados integer;
BEGIN
  IF current_user NOT IN ('service_role', 'postgres') THEN
    RAISE EXCEPTION USING errcode = '42501', message = 'Só o sistema (service_role) importa telefones.';
  END IF;
  IF f NOT IN ('base_amplify', 'notion') OR jsonb_typeof(p -> 'itens') <> 'array' THEN
    RAISE EXCEPTION USING errcode = '23514', message = 'Importação inválida: informe fonte e itens.';
  END IF;
  n_recebidos := jsonb_array_length(p -> 'itens');
  DROP TABLE IF EXISTS pg_temp._tel;
  CREATE TEMP TABLE _tel ON COMMIT DROP AS
    SELECT DISTINCT ON (a, t) a, t, ref, visto
    FROM (SELECT interno.normalizar_arroba(i ->> 'arroba') a, interno.normalizar_telefone(i ->> 'telefone') t,
                 left(i ->> 'ref', 120) ref, (i ->> 'visto_em')::timestamptz visto
          FROM jsonb_array_elements(p -> 'itens') i) x
    WHERE a ~ '^[a-z0-9._]{1,64}$' AND t IS NOT NULL
    ORDER BY a, t, visto DESC NULLS LAST;
  SELECT count(*) INTO n_validos FROM _tel;
  INSERT INTO interno.telefones_creators AS c (arroba, telefone, fonte, fonte_ref, visto_em)
  SELECT a, t, f, ref, visto FROM _tel
  ON CONFLICT (arroba, telefone, fonte) DO UPDATE
    SET fonte_ref = excluded.fonte_ref, visto_em = greatest(c.visto_em, excluded.visto_em), importado_em = now();
  GET DIAGNOSTICS n_gravados = ROW_COUNT;
  RETURN jsonb_build_object('fonte', f, 'recebidos', n_recebidos, 'validos', n_validos, 'gravados', n_gravados);
END
$fn$;
REVOKE ALL ON FUNCTION public.importar_telefones_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.importar_telefones_v5(jsonb) TO service_role;

-- Fontes internas (ficha da Bia e formulário). Pode rodar de novo a qualquer hora.
CREATE OR REPLACE FUNCTION public.atualizar_telefones_internos_v5()
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $fn$
DECLARE n_ficha integer; n_form integer;
BEGIN
  INSERT INTO interno.telefones_creators AS c (arroba, telefone, fonte, fonte_ref, visto_em)
  SELECT DISTINCT ON (a, t) a, t, 'ficha_bia', id::text, quando
  FROM (SELECT interno.normalizar_arroba(h) a,
               interno.normalizar_telefone(coalesce(nullif(cr.whatsapp, ''), nullif(cr.celular, ''), cr.telefone)) t,
               cr.id, cr.atualizado_em quando
        FROM interno.creators cr, LATERAL (VALUES (cr.tiktok), (cr.tiktok_declarado)) v(h)) x
  WHERE a ~ '^[a-z0-9._]{1,64}$' AND t IS NOT NULL
  ORDER BY a, t, quando DESC NULLS LAST
  ON CONFLICT (arroba, telefone, fonte) DO UPDATE
    SET fonte_ref = excluded.fonte_ref, visto_em = greatest(c.visto_em, excluded.visto_em), importado_em = now();
  GET DIAGNOSTICS n_ficha = ROW_COUNT;

  INSERT INTO interno.telefones_creators AS c (arroba, telefone, fonte, fonte_ref, visto_em)
  SELECT DISTINCT ON (a, t) a, t, 'formulario', NULL, NULL
  FROM (SELECT interno.normalizar_arroba(f."TikTok") a, interno.normalizar_telefone(f."WhatsApp") t
        FROM public.cadastros_formulario f) x
  WHERE a ~ '^[a-z0-9._]{1,64}$' AND t IS NOT NULL
  ON CONFLICT (arroba, telefone, fonte) DO UPDATE SET importado_em = now();
  GET DIAGNOSTICS n_form = ROW_COUNT;
  RETURN jsonb_build_object('ficha_bia', n_ficha, 'formulario', n_form);
END
$fn$;
REVOKE ALL ON FUNCTION public.atualizar_telefones_internos_v5() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.atualizar_telefones_internos_v5() TO service_role;

-- Agenciados ativos com o melhor telefone: formulário > ficha da Bia > base Amplify > Notion; depois o mais recente.
CREATE OR REPLACE VIEW public.agenciados_contato AS
SELECT '@' || a.arroba AS tiktok, a.nome_tiktok AS nome,
       (a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date AS vence_em,
       ((a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date - (now() AT TIME ZONE 'America/Sao_Paulo')::date)
         AS dias_para_vencer,
       t.telefone, t.fonte AS fonte_telefone,
       (SELECT count(DISTINCT x.telefone) FROM interno.telefones_creators x WHERE x.arroba = a.arroba) AS telefones_conhecidos,
       a.relation_id
FROM interno.agenciados_tiktok a
LEFT JOIN LATERAL (
  SELECT c.telefone, c.fonte FROM interno.telefones_creators c
  WHERE c.arroba = a.arroba
  ORDER BY array_position(ARRAY['formulario', 'ficha_bia', 'base_amplify', 'notion'], c.fonte),
           c.visto_em DESC NULLS LAST
  LIMIT 1) t ON true
WHERE a.ativo;

REVOKE ALL ON public.agenciados_contato FROM anon, authenticated;
GRANT SELECT ON public.agenciados_contato TO service_role;

SELECT public.atualizar_telefones_internos_v5();
COMMIT;
