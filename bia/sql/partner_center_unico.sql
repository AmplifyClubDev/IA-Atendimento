-- Tela única do Partner Center (25/11/2026): 1 linha por parceria (ID do TikTok), com o estado de hoje e as datas.
-- Junta: agenciados (vinculados, saindo, que saíram), convites (leads) e o histórico de todas as parcerias.
-- Prioridade por ID: agenciado > convite > histórico. Depende de agenciados_partner_completo.sql.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE OR REPLACE FUNCTION interno.parceria_rotulo(s smallint)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  SELECT CASE s WHEN 1 THEN 'Vinculado' WHEN 2 THEN 'Convite pendente' WHEN 4 THEN 'Saindo'
                WHEN 6 THEN 'Recusou o convite' WHEN 7 THEN 'Convite expirou'
                WHEN 9 THEN 'Saiu (desvinculou)' WHEN 10 THEN 'Contrato venceu'
                ELSE CASE WHEN s IS NOT NULL THEN 'Outro (' || s || ')' END END
$fn$;
GRANT EXECUTE ON FUNCTION interno.parceria_rotulo(smallint) TO PUBLIC;

-- A atualização diária do histórico vem sem detalhes: não apaga o tipo de registro que já existe.
CREATE OR REPLACE FUNCTION public.importar_parcerias_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE obs timestamptz := (p ->> 'observado_em')::timestamptz; n integer;
BEGIN
  IF current_user NOT IN ('service_role', 'postgres') THEN
    RAISE EXCEPTION USING errcode = '42501', message = 'Só a Bia (service_role) importa parcerias.';
  END IF;
  IF obs IS NULL OR obs > now() + interval '5 minutes' OR jsonb_typeof(p -> 'itens') <> 'array' THEN
    RAISE EXCEPTION USING errcode = '23514', message = 'Importação inválida: informe observado_em e itens.';
  END IF;
  INSERT INTO interno.parcerias_partner_center AS r
    (relation_id, arroba, nome, creator_id, status_tiktok, tipo_registro, status_dados, criado_em, vinculo_criado_em,
     inicio_em, fim_em, expira_em, primeira_vista_em, ultima_vista_em)
  SELECT DISTINCT ON (x ->> 'relation_id') x ->> 'relation_id',
         nullif(lower(btrim(ltrim(x ->> 'arroba', '@'))), ''), nullif(left(btrim(x ->> 'creator_name'), 200), ''),
         CASE WHEN (x ->> 'creator_id') ~ '^[0-9]{1,30}$' THEN x ->> 'creator_id' END,
         interno.int_ou_nulo(x ->> 'status', 99)::smallint, interno.int_ou_nulo(x ->> 'tipo_registro', 999)::smallint,
         interno.int_ou_nulo(x ->> 'status_dados', 99)::smallint,
         interno.ts_de_segundos(x ->> 'create_time_second'), interno.ts_de_segundos(x ->> 'vinculo_create_second'),
         interno.ts_de_segundos(x ->> 'start_second'), interno.ts_de_segundos(x ->> 'effective_end_date_second'),
         interno.ts_de_segundos(x ->> 'expire_time_second'), obs, obs
  FROM jsonb_array_elements(p -> 'itens') x
  WHERE (x ->> 'relation_id') ~ '^[0-9A-Za-z_-]{1,64}$'
  ON CONFLICT (relation_id) DO UPDATE SET
    arroba = coalesce(excluded.arroba, r.arroba), nome = coalesce(excluded.nome, r.nome),
    creator_id = coalesce(excluded.creator_id, r.creator_id),
    status_tiktok = coalesce(excluded.status_tiktok, r.status_tiktok),
    tipo_registro = coalesce(excluded.tipo_registro, r.tipo_registro),
    status_dados = coalesce(excluded.status_dados, r.status_dados),
    criado_em = coalesce(excluded.criado_em, r.criado_em),
    vinculo_criado_em = coalesce(excluded.vinculo_criado_em, r.vinculo_criado_em),
    inicio_em = coalesce(excluded.inicio_em, r.inicio_em), fim_em = coalesce(excluded.fim_em, r.fim_em),
    expira_em = coalesce(excluded.expira_em, r.expira_em),
    ultima_vista_em = greatest(r.ultima_vista_em, excluded.ultima_vista_em);
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN jsonb_build_object('status', 'importada', 'gravados', n);
END
$fn$;
REVOKE ALL ON FUNCTION public.importar_parcerias_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.importar_parcerias_v5(jsonb) TO service_role;

-- Histórico com os rótulos novos (o código 4 passa a se chamar "Saindo", como na ficha).
CREATE OR REPLACE VIEW public.parcerias_historico AS
SELECT '@' || r.arroba AS tiktok, r.nome, r.status_tiktok, r.tipo_registro, r.status_dados,
       interno.parceria_rotulo(r.status_tiktok) AS estado,
       (r.vinculo_criado_em AT TIME ZONE 'America/Sao_Paulo') AS convidado_em,
       (r.criado_em AT TIME ZONE 'America/Sao_Paulo') AS ultimo_movimento_em,
       (r.inicio_em AT TIME ZONE 'America/Sao_Paulo')::date AS inicio,
       (r.fim_em AT TIME ZONE 'America/Sao_Paulo')::date AS fim,
       (r.ultima_vista_em AT TIME ZONE 'America/Sao_Paulo') AS visto_em,
       EXISTS (SELECT 1 FROM interno.agenciados_tiktok a WHERE a.relation_id = r.relation_id AND a.ativo) AS agenciado_hoje,
       r.relation_id, r.creator_id
FROM interno.parcerias_partner_center r;

-- A tela única. Datas em horário de São Paulo.
CREATE OR REPLACE VIEW public.partner_center AS
-- 1) Agenciados (coleta de hora em hora): vinculado, saindo ou que saiu.
SELECT a.relation_id AS id_parceria, a.creator_id, '@' || a.arroba AS tiktok, a.nome_tiktok AS nome,
       CASE WHEN a.ativo AND a.situacao_tiktok = 'desvinculando' THEN 'Saindo'
            WHEN a.ativo THEN 'Vinculado'
            WHEN h.status_tiktok IN (6, 7, 9, 10) THEN interno.parceria_rotulo(h.status_tiktok)
            ELSE 'Saiu' END AS estado,
       (a.vinculado_em AT TIME ZONE 'America/Sao_Paulo') AS convidado_em,
       (a.contrato_inicio AT TIME ZONE 'America/Sao_Paulo')::date AS contrato_inicio,
       (a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date AS contrato_fim,
       CASE WHEN a.ativo THEN (a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date
                              - (now() AT TIME ZONE 'America/Sao_Paulo')::date END AS dias_para_vencer,
       CASE WHEN a.ativo THEN coalesce(interno.renovacao_rotulo(a.renovacao_status), 'Sem pedido') END AS renovacao,
       (a.renovacao_pedido_em AT TIME ZONE 'America/Sao_Paulo') AS renovacao_pedido_em,
       (a.renovacao_expira_em AT TIME ZONE 'America/Sao_Paulo') AS renovacao_expira_em,
       (a.renovacao_novo_fim AT TIME ZONE 'America/Sao_Paulo')::date AS renovacao_novo_fim,
       (a.desvinculo_pedido_em AT TIME ZONE 'America/Sao_Paulo') AS desvinculo_pedido_em,
       (a.desvinculo_conclui_em AT TIME ZONE 'America/Sao_Paulo') AS desvinculo_conclui_em,
       (a.saiu_em AT TIME ZONE 'America/Sao_Paulo') AS saiu_em,
       interno.categoria_amplify(a.gmv_nivel) AS categoria, a.gmv_nivel,
       'agenciados'::text AS origem,
       (a.ultima_coleta_em AT TIME ZONE 'America/Sao_Paulo') AS atualizado_em
FROM interno.agenciados_tiktok a
LEFT JOIN interno.parcerias_partner_center h ON h.relation_id = a.relation_id AND NOT a.ativo
UNION ALL
-- 2) Convites (leads) que ainda não viraram agenciados.
SELECT v.relation_id, NULL, '@' || v.arroba, v.nome,
       CASE WHEN v.pendente THEN 'Convite pendente'
            WHEN h.status_tiktok IN (6, 7) THEN interno.parceria_rotulo(h.status_tiktok)
            ELSE 'Convite não aceito' END,
       (v.convidado_em AT TIME ZONE 'America/Sao_Paulo'), NULL, (v.contrato_fim_proposto AT TIME ZONE 'America/Sao_Paulo')::date,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       (v.resolvido_em AT TIME ZONE 'America/Sao_Paulo'), NULL, NULL,
       'convites', (v.ultima_vista_em AT TIME ZONE 'America/Sao_Paulo')
FROM interno.agenciados_convites v
LEFT JOIN interno.parcerias_partner_center h ON h.relation_id = v.relation_id
WHERE NOT EXISTS (SELECT 1 FROM interno.agenciados_tiktok a WHERE a.relation_id = v.relation_id)
UNION ALL
-- 3) O resto do histórico (recusas, convites expirados, saídas e contratos vencidos de antes).
SELECT r.relation_id, r.creator_id, '@' || r.arroba, r.nome,
       CASE WHEN r.status_tiktok IN (1, 2, 4) THEN 'Sem coleta recente' ELSE interno.parceria_rotulo(r.status_tiktok) END,
       (coalesce(r.vinculo_criado_em, r.criado_em) AT TIME ZONE 'America/Sao_Paulo'),
       (r.inicio_em AT TIME ZONE 'America/Sao_Paulo')::date, (r.fim_em AT TIME ZONE 'America/Sao_Paulo')::date,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       CASE WHEN r.status_tiktok IN (9, 10) THEN (r.criado_em AT TIME ZONE 'America/Sao_Paulo') END, NULL, NULL,
       'historico', (r.ultima_vista_em AT TIME ZONE 'America/Sao_Paulo')
FROM interno.parcerias_partner_center r
WHERE NOT EXISTS (SELECT 1 FROM interno.agenciados_tiktok a WHERE a.relation_id = r.relation_id)
  AND NOT EXISTS (SELECT 1 FROM interno.agenciados_convites v WHERE v.relation_id = r.relation_id);

-- Resumo por estado (para conferir de olho com o Partner Center).
CREATE OR REPLACE VIEW public.partner_center_resumo AS
SELECT estado, count(*) AS parcerias, max(atualizado_em) AS atualizado_em
FROM public.partner_center GROUP BY estado;

-- Conferência: diferença em número (o TikTok conta ~5 vinculados que não aparecem em nenhuma lista).
CREATE OR REPLACE VIEW public.agenciados_conferencia AS
WITH u AS (SELECT * FROM interno.partner_center_contagens ORDER BY observado_em DESC LIMIT 1),
b AS (SELECT count(*) FILTER (WHERE ativo AND situacao_tiktok IS DISTINCT FROM 'desvinculando') AS vinculados,
             count(*) FILTER (WHERE ativo AND situacao_tiktok = 'desvinculando') AS desvinculando
      FROM interno.agenciados_tiktok)
SELECT (u.observado_em AT TIME ZONE 'America/Sao_Paulo') AS conferido_em,
       u.vinculados AS tiktok_vinculados, b.vinculados AS banco_vinculados,
       u.desvinculando AS tiktok_desvinculando, b.desvinculando AS banco_desvinculando,
       u.pendentes AS tiktok_pendentes,
       (SELECT count(*) FROM interno.agenciados_convites WHERE pendente) AS banco_pendentes,
       (u.vinculados = b.vinculados AND u.desvinculando = b.desvinculando) AS confere,
       u.convite_recusado, u.convite_expirado, u.sairam, u.contrato_vencido, u.total, u.vencem_em_breve,
       (u.vinculados - b.vinculados) AS diferenca_vinculados
FROM u CROSS JOIN b;

REVOKE ALL ON public.partner_center, public.partner_center_resumo, public.parcerias_historico,
  public.agenciados_conferencia FROM anon, authenticated;
GRANT SELECT ON public.partner_center, public.partner_center_resumo, public.parcerias_historico,
  public.agenciados_conferencia TO service_role;
COMMIT;
