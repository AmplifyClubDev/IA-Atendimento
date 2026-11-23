-- Fonte "chatwoot" para os telefones dos agenciados (23/11/2026).
-- O n8n de renovação cria contatos no Chatwoot com o nome igual ao @ e com o telefone; o cruzamento só aceita
-- nome exatamente igual ao @ e um único contato. Prioridade: formulário > ficha da Bia > Chatwoot > base Amplify > Notion.
-- Depende de telefones_agenciados.sql e agenciados_categoria.sql.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE interno.telefones_creators DROP CONSTRAINT IF EXISTS telefones_creators_fonte_check;
ALTER TABLE interno.telefones_creators ADD CONSTRAINT telefones_creators_fonte_check
  CHECK (fonte IN ('formulario', 'ficha_bia', 'chatwoot', 'base_amplify', 'notion'));

-- p = {"fonte": "base_amplify"|"notion"|"chatwoot", "itens": [{"arroba", "telefone", "ref", "visto_em"}]}
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
  IF f NOT IN ('base_amplify', 'notion', 'chatwoot') OR jsonb_typeof(p -> 'itens') <> 'array' THEN
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
  ORDER BY array_position(ARRAY['formulario', 'ficha_bia', 'chatwoot', 'base_amplify', 'notion'], c.fonte),
           c.visto_em DESC NULLS LAST
  LIMIT 1) t ON true
WHERE a.ativo;

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
  ORDER BY array_position(ARRAY['formulario', 'ficha_bia', 'chatwoot', 'base_amplify', 'notion'], c.fonte), c.visto_em DESC NULLS LAST
  LIMIT 1) t ON true
LEFT JOIN LATERAL (SELECT x.id, x.origem FROM public.creators x
                   WHERE lower(btrim(ltrim(x.tiktok, '@'))) = a.arroba LIMIT 1) f ON a.arroba IS NOT NULL;

COMMIT;
