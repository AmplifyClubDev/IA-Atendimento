-- Fase A3 (23/11/2026): espelho completo do Partner Center.
-- 1) Desvinculação solicitada (status 4 do TikTok): a pessoa continua vinculada até o TikTok concluir a saída
--    (7 dias depois do pedido). Antes, sumia da lista de vinculados e o banco marcava "saiu" por engano.
-- 2) Pedido de renovação (extend_relation): situação, enviado em, expira em, novo fim, pedidos restantes.
-- 3) Convites pendentes (status 2): quem foi convidado e ainda não aceitou; quando some, aceitou ou não.
-- 4) Contagens oficiais do Partner Center a cada coleta, para o banco se conferir sozinho.
-- 5) Histórico de todas as parcerias (lista "todas" do Partner Center), importado à parte.
-- Depende de agenciados_tiktok.sql, agenciados_ficha.sql, agenciados_categoria.sql e telefones_chatwoot.sql.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE OR REPLACE FUNCTION interno.ts_de_segundos(t text)
RETURNS timestamptz LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  SELECT CASE WHEN t ~ '^[1-9][0-9]{8,10}$' THEN to_timestamp(t::bigint) END
$fn$;

CREATE OR REPLACE FUNCTION interno.int_ou_nulo(t text, maximo integer DEFAULT 100000000)
RETURNS integer LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  SELECT CASE WHEN t ~ '^[0-9]{1,9}$' AND t::bigint <= maximo THEN t::integer END
$fn$;

-- Situação do pedido de renovação (extend_relation.status), como o Partner Center mostrou em 23/11/2026:
-- 1 aguardando o creator aceitar; 2 aceito (o novo fim já vale); 3 não aceito (sem pedidos restantes).
CREATE OR REPLACE FUNCTION interno.renovacao_rotulo(s smallint)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  SELECT CASE s WHEN 1 THEN 'Aguardando aceite' WHEN 2 THEN 'Aceita' WHEN 3 THEN 'Não aceita'
                ELSE CASE WHEN s IS NOT NULL THEN 'Outra (' || s || ')' END END
$fn$;

ALTER TABLE interno.agenciados_tiktok
  ADD COLUMN IF NOT EXISTS situacao_tiktok text CHECK (situacao_tiktok IN ('vinculado', 'desvinculando')),
  ADD COLUMN IF NOT EXISTS desvinculo_pedido_em timestamptz,      -- status 4: create_time_second
  ADD COLUMN IF NOT EXISTS desvinculo_conclui_em timestamptz,     -- status 4: expire_time_second
  ADD COLUMN IF NOT EXISTS renovacao_status smallint,             -- extend_relation.status
  ADD COLUMN IF NOT EXISTS renovacao_pedido_em timestamptz,       -- extend_relation.create_time_second
  ADD COLUMN IF NOT EXISTS renovacao_expira_em timestamptz,       -- extend_relation.expire_time_second
  ADD COLUMN IF NOT EXISTS renovacao_novo_fim timestamptz,        -- extend_relation.effective_end_date_second
  ADD COLUMN IF NOT EXISTS renovacao_pedidos_restantes smallint;  -- extend_relation.remaining_extend_request_count

ALTER TABLE interno.agenciados_eventos DROP CONSTRAINT IF EXISTS agenciados_eventos_tipo_check;
ALTER TABLE interno.agenciados_eventos ADD CONSTRAINT agenciados_eventos_tipo_check CHECK (tipo IN
  ('entrou', 'voltou', 'saiu', 'renovou', 'mudou_nivel', 'pediu_desvinculo', 'cancelou_desvinculo', 'pedido_renovacao'));

CREATE TABLE IF NOT EXISTS interno.agenciados_convites (
  relation_id text PRIMARY KEY,
  arroba text,
  nome text,
  convidado_em timestamptz,            -- create_time_second
  convite_expira_em timestamptz,       -- expire_time_second (7 dias)
  contrato_fim_proposto timestamptz,   -- effective_end_date_second
  primeira_vista_em timestamptz NOT NULL,
  ultima_vista_em timestamptz NOT NULL,
  pendente boolean NOT NULL DEFAULT true,
  resolvido_em timestamptz,
  resultado text CHECK (resultado IN ('aceitou', 'nao_aceitou'))
);
CREATE INDEX IF NOT EXISTS agenciados_convites_arroba ON interno.agenciados_convites (arroba);
ALTER TABLE interno.agenciados_convites ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS interno.partner_center_contagens (
  observado_em timestamptz PRIMARY KEY,
  vinculados integer,             -- bound
  pendentes integer,              -- pending
  desvinculando integer,          -- unbinding
  nao_vinculados integer,         -- unbound
  convite_recusado integer,       -- binding_failed_reject
  convite_expirado integer,       -- binding_failed_expired
  sairam integer,                 -- unbound_unlink
  contrato_vencido integer,       -- unbound_expired
  total integer,                  -- all
  vencem_em_breve integer[],      -- binding_expire_soon
  bruto jsonb NOT NULL
);
ALTER TABLE interno.partner_center_contagens ENABLE ROW LEVEL SECURITY;

-- Todas as parcerias que o Partner Center lista (vinculados, convites, recusas, saídas, contratos vencidos).
CREATE TABLE IF NOT EXISTS interno.parcerias_partner_center (
  relation_id text PRIMARY KEY,
  arroba text,
  nome text,
  creator_id text,
  status_tiktok smallint,         -- status da parceria
  tipo_registro smallint,         -- record.type (último movimento)
  status_dados smallint,          -- data_relation.status
  criado_em timestamptz,          -- create_time_second (último movimento)
  vinculo_criado_em timestamptz,  -- data_relation.create_time_second
  inicio_em timestamptz,          -- effective_start_date_second
  fim_em timestamptz,             -- effective_end_date_second
  expira_em timestamptz,          -- expire_time_second
  primeira_vista_em timestamptz NOT NULL,
  ultima_vista_em timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS parcerias_partner_center_arroba ON interno.parcerias_partner_center (arroba);
ALTER TABLE interno.parcerias_partner_center ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON interno.agenciados_convites, interno.partner_center_contagens, interno.parcerias_partner_center
  FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON interno.agenciados_convites, interno.parcerias_partner_center TO service_role;
GRANT SELECT, INSERT ON interno.partner_center_contagens TO service_role;

-- p = {"observado_em", "total", "completa", "fonte",
--      "itens": [{... como antes, e: "estado": "vinculado"|"desvinculando", "desvinculo_pedido_second",
--                 "desvinculo_conclui_second", "renovacao_status", "renovacao_pedido_second",
--                 "renovacao_expira_second", "renovacao_novo_fim_second", "renovacao_restantes", "com_detalhes"}],
--      "pendentes": {"completa", "total", "itens": [{"relation_id", "arroba", "creator_name", "create_time_second",
--                    "expire_time_second", "effective_end_date_second"}]} (opcional),
--      "contagens": {statusCount do Partner Center} (opcional)}
CREATE OR REPLACE FUNCTION public.registrar_coleta_agenciados_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE
  obs timestamptz;
  itens jsonb := p -> 'itens';
  pend jsonb := p -> 'pendentes';
  cont jsonb := p -> 'contagens';
  n_recebidos integer;
  n_total integer;
  completa boolean := coalesce((p ->> 'completa')::boolean, false);
  n_novos integer;
  n_sumiram integer;
  aplicar_saidas boolean;
  n_sairam integer := 0;
  n_eventos integer := 0;
  n_detalhes integer;
  n_desvinculando integer;
  n_pendentes integer;
  n_pend_total integer;
  n_resolvidos integer := 0;
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
         interno.ts_de_segundos(x ->> 'create_time_second') AS vinculado_em,
         interno.ts_de_segundos(x ->> 'effective_end_date_second') AS vigencia_fim,
         CASE WHEN (x ->> 'creator_id') ~ '^[0-9]{1,30}$' THEN x ->> 'creator_id' END AS creator_id,
         interno.ts_de_segundos(x ->> 'start_second') AS contrato_inicio,
         interno.ts_de_segundos(x ->> 'expire_time_second') AS expira_em,
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
         interno.int_ou_nulo(x ->> 'desvinculos_recusados', 999999) AS desvinculos_recusados,
         CASE WHEN x ->> 'estado' = 'desvinculando' THEN 'desvinculando' ELSE 'vinculado' END AS estado,
         CASE WHEN x ->> 'estado' = 'desvinculando' THEN interno.ts_de_segundos(x ->> 'desvinculo_pedido_second') END
           AS desvinculo_pedido_em,
         CASE WHEN x ->> 'estado' = 'desvinculando' THEN interno.ts_de_segundos(x ->> 'desvinculo_conclui_second') END
           AS desvinculo_conclui_em,
         interno.int_ou_nulo(x ->> 'renovacao_status', 99)::smallint AS renovacao_status,
         interno.ts_de_segundos(x ->> 'renovacao_pedido_second') AS renovacao_pedido_em,
         interno.ts_de_segundos(x ->> 'renovacao_expira_second') AS renovacao_expira_em,
         interno.ts_de_segundos(x ->> 'renovacao_novo_fim_second') AS renovacao_novo_fim,
         interno.int_ou_nulo(x ->> 'renovacao_restantes', 999)::smallint AS renovacao_pedidos_restantes,
         (x ->> 'com_detalhes' = '1' OR (x ->> 'nivel') ~ '^[0-9]{1,2}$' OR (x ->> 'seguidores') ~ '^[0-9]{1,12}$')
           AS com_detalhes
  FROM jsonb_array_elements(itens) x
  WHERE (x ->> 'relation_id') ~ '^[0-9A-Za-z_-]{1,64}$';

  SELECT count(*) INTO n_novos FROM _coleta c WHERE c.estado = 'vinculado'
    AND NOT EXISTS (SELECT 1 FROM interno.agenciados_tiktok a WHERE a.relation_id = c.relation_id);
  SELECT count(*) INTO n_detalhes FROM _coleta WHERE com_detalhes;
  SELECT count(*) INTO n_desvinculando FROM _coleta WHERE estado = 'desvinculando';

  -- Eventos comparando a coleta com o que o banco já sabia (antes de atualizar).
  INSERT INTO interno.agenciados_eventos (relation_id, arroba, tipo, observado_em, nivel, nivel_nome, gmv_nivel, antes, depois)
  SELECT c.relation_id, c.arroba, e.tipo, obs, coalesce(c.nivel, a.nivel), coalesce(c.nivel_nome, a.nivel_nome),
         coalesce(c.gmv_nivel, a.gmv_nivel), e.antes, e.depois
  FROM _coleta c
  LEFT JOIN interno.agenciados_tiktok a ON a.relation_id = c.relation_id
  CROSS JOIN LATERAL (VALUES
    (CASE WHEN c.estado = 'vinculado' AND a.relation_id IS NULL THEN 'entrou'
          WHEN c.estado = 'vinculado' AND NOT a.ativo THEN 'voltou' END, NULL::jsonb, NULL::jsonb),
    (CASE WHEN a.vigencia_fim IS NOT NULL AND c.vigencia_fim > a.vigencia_fim + interval '1 day' THEN 'renovou' END,
     jsonb_build_object('vigencia_fim', a.vigencia_fim), jsonb_build_object('vigencia_fim', c.vigencia_fim)),
    (CASE WHEN a.nivel IS NOT NULL AND c.nivel IS NOT NULL AND c.nivel <> a.nivel THEN 'mudou_nivel' END,
     jsonb_build_object('nivel', a.nivel, 'nivel_nome', a.nivel_nome),
     jsonb_build_object('nivel', c.nivel, 'nivel_nome', c.nivel_nome)),
    (CASE WHEN c.estado = 'desvinculando' AND a.situacao_tiktok IS DISTINCT FROM 'desvinculando' THEN 'pediu_desvinculo'
          WHEN c.estado = 'vinculado' AND a.ativo AND a.situacao_tiktok = 'desvinculando' THEN 'cancelou_desvinculo' END,
     NULL::jsonb, jsonb_build_object('pedido_em', c.desvinculo_pedido_em, 'conclui_em', c.desvinculo_conclui_em)),
    (CASE WHEN a.relation_id IS NOT NULL AND c.renovacao_pedido_em IS NOT NULL
               AND c.renovacao_pedido_em IS DISTINCT FROM a.renovacao_pedido_em THEN 'pedido_renovacao' END,
     NULL::jsonb, jsonb_build_object('status', c.renovacao_status, 'pedido_em', c.renovacao_pedido_em,
                                     'expira_em', c.renovacao_expira_em, 'novo_fim', c.renovacao_novo_fim))
  ) e(tipo, antes, depois)
  WHERE e.tipo IS NOT NULL;
  GET DIAGNOSTICS n_eventos = ROW_COUNT;

  INSERT INTO interno.agenciados_tiktok AS a
    (relation_id, arroba, nome_tiktok, vinculado_em, vigencia_fim, primeira_coleta_em, ultima_coleta_em, ativo, saiu_em,
     creator_id, contrato_inicio, expira_em, nivel, nivel_nome, nivel_proximo, gmv_nivel, gmv_meta, progresso_pct,
     seguidores, categorias, comissao_pct, desvinculos_recusados, detalhes_em,
     situacao_tiktok, desvinculo_pedido_em, desvinculo_conclui_em, renovacao_status, renovacao_pedido_em,
     renovacao_expira_em, renovacao_novo_fim, renovacao_pedidos_restantes)
  SELECT relation_id, arroba, nome, vinculado_em, vigencia_fim, obs, obs, true, NULL,
         creator_id, contrato_inicio, expira_em, nivel, nivel_nome, nivel_proximo, gmv_nivel, gmv_meta, progresso_pct,
         seguidores, categorias, comissao_pct, desvinculos_recusados, CASE WHEN com_detalhes THEN obs END,
         estado, desvinculo_pedido_em, desvinculo_conclui_em, renovacao_status, renovacao_pedido_em,
         renovacao_expira_em, renovacao_novo_fim, renovacao_pedidos_restantes
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
    detalhes_em = coalesce(excluded.detalhes_em, a.detalhes_em),
    situacao_tiktok = excluded.situacao_tiktok,
    desvinculo_pedido_em = excluded.desvinculo_pedido_em,
    desvinculo_conclui_em = excluded.desvinculo_conclui_em,
    -- Pedido de renovação: com detalhes, vale o que o TikTok mostra agora (inclusive "nenhum pedido").
    renovacao_status = CASE WHEN excluded.detalhes_em IS NOT NULL THEN excluded.renovacao_status ELSE a.renovacao_status END,
    renovacao_pedido_em = CASE WHEN excluded.detalhes_em IS NOT NULL THEN excluded.renovacao_pedido_em ELSE a.renovacao_pedido_em END,
    renovacao_expira_em = CASE WHEN excluded.detalhes_em IS NOT NULL THEN excluded.renovacao_expira_em ELSE a.renovacao_expira_em END,
    renovacao_novo_fim = CASE WHEN excluded.detalhes_em IS NOT NULL THEN excluded.renovacao_novo_fim ELSE a.renovacao_novo_fim END,
    renovacao_pedidos_restantes = CASE WHEN excluded.detalhes_em IS NOT NULL THEN excluded.renovacao_pedidos_restantes
                                       ELSE a.renovacao_pedidos_restantes END;

  -- Saídas só com lista completa e sem queda brusca (proteção contra lista cortada).
  -- A lista inclui os vinculados e os em desvinculação: só sai quem o TikTok não mostra em nenhuma das duas.
  SELECT count(*) INTO n_sumiram FROM interno.agenciados_tiktok WHERE ativo AND ultima_coleta_em < obs;
  aplicar_saidas := completa AND n_total IS NOT NULL AND n_recebidos >= n_total - 10
                    AND n_sumiram <= greatest(20, (SELECT count(*) FROM _coleta) / 20);
  IF aplicar_saidas THEN
    INSERT INTO interno.agenciados_eventos (relation_id, arroba, tipo, observado_em, nivel, nivel_nome, gmv_nivel, antes)
    SELECT relation_id, arroba, 'saiu', obs, nivel, nivel_nome, gmv_nivel,
           jsonb_build_object('situacao_tiktok', situacao_tiktok, 'desvinculo_pedido_em', desvinculo_pedido_em)
    FROM interno.agenciados_tiktok WHERE ativo AND ultima_coleta_em < obs;
    UPDATE interno.agenciados_tiktok SET ativo = false, saiu_em = obs WHERE ativo AND ultima_coleta_em < obs;
    GET DIAGNOSTICS n_sairam = ROW_COUNT;
    n_eventos := n_eventos + n_sairam;
  END IF;

  -- Convites pendentes (opcional): quem some da lista aceitou (virou vinculado) ou não aceitou.
  IF jsonb_typeof(pend) = 'object' AND jsonb_typeof(pend -> 'itens') = 'array' THEN
    INSERT INTO interno.agenciados_convites AS v
      (relation_id, arroba, nome, convidado_em, convite_expira_em, contrato_fim_proposto, primeira_vista_em, ultima_vista_em)
    SELECT DISTINCT ON (x ->> 'relation_id') x ->> 'relation_id',
           nullif(lower(btrim(ltrim(x ->> 'arroba', '@'))), ''), nullif(btrim(x ->> 'creator_name'), ''),
           interno.ts_de_segundos(x ->> 'create_time_second'), interno.ts_de_segundos(x ->> 'expire_time_second'),
           interno.ts_de_segundos(x ->> 'effective_end_date_second'), obs, obs
    FROM jsonb_array_elements(pend -> 'itens') x
    WHERE (x ->> 'relation_id') ~ '^[0-9A-Za-z_-]{1,64}$'
    ON CONFLICT (relation_id) DO UPDATE SET
      arroba = coalesce(excluded.arroba, v.arroba), nome = coalesce(excluded.nome, v.nome),
      convidado_em = coalesce(excluded.convidado_em, v.convidado_em), convite_expira_em = excluded.convite_expira_em,
      contrato_fim_proposto = excluded.contrato_fim_proposto,
      ultima_vista_em = obs, pendente = true, resolvido_em = NULL, resultado = NULL;
    GET DIAGNOSTICS n_pendentes = ROW_COUNT;
    n_pend_total := nullif(pend ->> 'total', '')::integer;
    IF coalesce((pend ->> 'completa')::boolean, false) AND n_pend_total IS NOT NULL AND n_pendentes >= n_pend_total - 5 THEN
      UPDATE interno.agenciados_convites v SET pendente = false, resolvido_em = obs,
             resultado = CASE WHEN EXISTS (SELECT 1 FROM interno.agenciados_tiktok a
                                           WHERE a.relation_id = v.relation_id AND a.ativo) THEN 'aceitou' ELSE 'nao_aceitou' END
      WHERE v.pendente AND v.ultima_vista_em < obs;
      GET DIAGNOSTICS n_resolvidos = ROW_COUNT;
    END IF;
  END IF;

  -- Contagens oficiais (opcional), para conferir o banco.
  IF jsonb_typeof(cont) = 'object' THEN
    INSERT INTO interno.partner_center_contagens
      (observado_em, vinculados, pendentes, desvinculando, nao_vinculados, convite_recusado, convite_expirado,
       sairam, contrato_vencido, total, vencem_em_breve, bruto)
    VALUES (obs, interno.int_ou_nulo(cont ->> 'bound'), interno.int_ou_nulo(cont ->> 'pending'),
            interno.int_ou_nulo(cont ->> 'unbinding'), interno.int_ou_nulo(cont ->> 'unbound'),
            interno.int_ou_nulo(cont ->> 'binding_failed_reject'), interno.int_ou_nulo(cont ->> 'binding_failed_expired'),
            interno.int_ou_nulo(cont ->> 'unbound_unlink'), interno.int_ou_nulo(cont ->> 'unbound_expired'),
            interno.int_ou_nulo(cont ->> 'all'),
            CASE WHEN jsonb_typeof(cont -> 'binding_expire_soon') = 'array'
                 THEN (SELECT array_agg(interno.int_ou_nulo(v)) FROM (
                         SELECT v FROM jsonb_array_elements_text(cont -> 'binding_expire_soon') v LIMIT 10) vs) END,
            coalesce((SELECT jsonb_object_agg(k, v) FROM (SELECT k, v FROM jsonb_each(cont) e(k, v) LIMIT 40) kv),
                     '{}'::jsonb))
    ON CONFLICT (observado_em) DO NOTHING;
  END IF;

  INSERT INTO interno.agenciados_tiktok_coletas
    (observado_em, total_informado, recebidos, completa, entraram, sairam, ativos, saidas_aplicadas, fonte)
  VALUES (obs, n_total, n_recebidos, completa, n_novos, n_sairam,
          (SELECT count(*) FROM interno.agenciados_tiktok WHERE ativo), aplicar_saidas,
          coalesce(nullif(p ->> 'fonte', ''), 'ponte_agenciamento'));

  RETURN jsonb_build_object('status', 'registrada', 'recebidos', n_recebidos, 'entraram', n_novos,
                            'sairam', n_sairam, 'saidas_aplicadas', aplicar_saidas,
                            'com_detalhes', n_detalhes, 'eventos', n_eventos, 'desvinculando', n_desvinculando,
                            'pendentes', n_pendentes, 'convites_resolvidos', n_resolvidos);
END
$fn$;
REVOKE ALL ON FUNCTION public.registrar_coleta_agenciados_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_coleta_agenciados_v5(jsonb) TO service_role;

-- Histórico: p = {"observado_em", "itens": [{"relation_id", "arroba", "creator_name", "creator_id", "status",
--   "tipo_registro", "status_dados", "create_time_second", "vinculo_create_second", "start_second",
--   "effective_end_date_second", "expire_time_second"}]}. Só grava/atualiza; nunca apaga.
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
    creator_id = coalesce(excluded.creator_id, r.creator_id), status_tiktok = excluded.status_tiktok,
    tipo_registro = excluded.tipo_registro, status_dados = excluded.status_dados, criado_em = excluded.criado_em,
    vinculo_criado_em = coalesce(excluded.vinculo_criado_em, r.vinculo_criado_em),
    inicio_em = coalesce(excluded.inicio_em, r.inicio_em), fim_em = coalesce(excluded.fim_em, r.fim_em),
    expira_em = excluded.expira_em, ultima_vista_em = greatest(r.ultima_vista_em, excluded.ultima_vista_em);
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN jsonb_build_object('status', 'importada', 'gravados', n);
END
$fn$;
REVOKE ALL ON FUNCTION public.importar_parcerias_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.importar_parcerias_v5(jsonb) TO service_role;

-- Correção única: 11 pessoas em desvinculação marcadas como "saiu" por engano (levantamento de 23/11).
-- Voltam a ativas; a próxima coleta grava a desvinculação e o evento "pediu_desvinculo".
DELETE FROM interno.agenciados_eventos e USING interno.agenciados_tiktok a
WHERE e.relation_id = a.relation_id AND e.tipo = 'saiu' AND NOT a.ativo AND e.observado_em >= a.saiu_em
  AND a.relation_id IN ('8684773223254296338', '8689672014151911176', '8667692896062441237', '8689666227395790610',
    '8688360881183688455', '8689651098982844161', '8684913833815803655', '8689569458150147848', '8670727281028138773',
    '8689783154399151890', '8689771349254309650');
UPDATE interno.agenciados_tiktok SET ativo = true, saiu_em = NULL
WHERE NOT ativo AND relation_id IN ('8684773223254296338', '8689672014151911176', '8667692896062441237',
    '8689666227395790610', '8688360881183688455', '8689651098982844161', '8684913833815803655', '8689569458150147848',
    '8670727281028138773', '8689783154399151890', '8689771349254309650');

-- ---- Telas (horário de São Paulo; só o sistema lê) ----

-- Ficha: "situacao" ganha "Saindo" (desvinculação solicitada). Colunas novas no fim.
CREATE OR REPLACE VIEW public.agenciados_ficha AS
SELECT '@' || a.arroba AS tiktok, a.nome_tiktok AS nome,
       CASE WHEN NOT a.ativo THEN 'Saiu' WHEN a.situacao_tiktok = 'desvinculando' THEN 'Saindo' ELSE 'Ativo' END
         AS situacao,
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
       interno.categoria_amplify(a.gmv_nivel) AS categoria,
       interno.renovacao_rotulo(a.renovacao_status) AS renovacao,
       (a.renovacao_pedido_em AT TIME ZONE 'America/Sao_Paulo') AS renovacao_pedido_em,
       (a.renovacao_expira_em AT TIME ZONE 'America/Sao_Paulo') AS renovacao_expira_em,
       (a.renovacao_novo_fim AT TIME ZONE 'America/Sao_Paulo')::date AS renovacao_novo_fim,
       a.renovacao_pedidos_restantes,
       (a.desvinculo_pedido_em AT TIME ZONE 'America/Sao_Paulo') AS desvinculo_pedido_em,
       (a.desvinculo_conclui_em AT TIME ZONE 'America/Sao_Paulo') AS desvinculo_conclui_em
FROM interno.agenciados_tiktok a
LEFT JOIN LATERAL (
  SELECT c.telefone, c.fonte FROM interno.telefones_creators c WHERE c.arroba = a.arroba
  ORDER BY array_position(ARRAY['formulario', 'ficha_bia', 'chatwoot', 'base_amplify', 'notion'], c.fonte), c.visto_em DESC NULLS LAST
  LIMIT 1) t ON true
LEFT JOIN LATERAL (SELECT x.id, x.origem FROM public.creators x
                   WHERE lower(btrim(ltrim(x.tiktok, '@'))) = a.arroba LIMIT 1) f ON a.arroba IS NOT NULL;

CREATE OR REPLACE VIEW public.agenciados_a_vencer AS
SELECT f.tiktok, f.nome, f.contrato_fim, f.dias_para_vencer, f.nivel_nome, f.gmv_nivel, f.seguidores,
       f.telefone, f.fonte_telefone, f.renovacoes, f.relation_id, f.categoria,
       f.renovacao, f.renovacao_expira_em, f.renovacao_novo_fim
FROM public.agenciados_ficha f
WHERE f.situacao = 'Ativo' AND f.dias_para_vencer BETWEEN 0 AND 45;

CREATE OR REPLACE VIEW public.agenciados_movimento_por_categoria AS
SELECT (e.observado_em AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
       coalesce(interno.categoria_amplify(e.gmv_nivel), 'Sem GMV') AS categoria,
       count(*) FILTER (WHERE e.tipo IN ('entrou', 'voltou')) AS entraram,
       count(*) FILTER (WHERE e.tipo = 'saiu') AS sairam,
       count(*) FILTER (WHERE e.tipo = 'renovou') AS renovaram,
       coalesce(sum(e.gmv_nivel) FILTER (WHERE e.tipo = 'saiu'), 0) AS gmv_de_quem_saiu,
       count(*) FILTER (WHERE e.tipo = 'pediu_desvinculo') AS pediram_desvinculo,
       count(*) FILTER (WHERE e.tipo = 'cancelou_desvinculo') AS cancelaram_desvinculo,
       count(*) FILTER (WHERE e.tipo = 'pedido_renovacao') AS pedidos_de_renovacao
FROM interno.agenciados_eventos e
GROUP BY 1, 2;

-- Renovação: quem vence em até 60 dias ou tem pedido de renovação, com a situação do pedido.
CREATE OR REPLACE VIEW public.agenciados_renovacao AS
SELECT f.tiktok, f.nome, f.situacao, f.categoria, f.gmv_nivel, f.contrato_fim, f.dias_para_vencer,
       coalesce(f.renovacao, 'Sem pedido') AS renovacao, f.renovacao_pedido_em, f.renovacao_expira_em,
       f.renovacao_novo_fim, f.renovacao_pedidos_restantes, f.telefone, f.fonte_telefone, f.relation_id
FROM public.agenciados_ficha f
WHERE f.situacao IN ('Ativo', 'Saindo') AND (f.renovacao IS NOT NULL OR f.dias_para_vencer <= 60);

-- Quem pediu para sair e quando a saída conclui.
CREATE OR REPLACE VIEW public.agenciados_desvinculando AS
SELECT f.tiktok, f.nome, f.categoria, f.gmv_nivel, f.agenciado_em, f.contrato_fim,
       f.desvinculo_pedido_em, f.desvinculo_conclui_em,
       (f.desvinculo_conclui_em::date - (now() AT TIME ZONE 'America/Sao_Paulo')::date) AS dias_para_concluir,
       f.telefone, f.fonte_telefone, f.passou_pela_bia, f.relation_id
FROM public.agenciados_ficha f
WHERE f.situacao = 'Saindo';

CREATE OR REPLACE VIEW public.agenciados_convites_pendentes AS
SELECT '@' || v.arroba AS tiktok, v.nome,
       CASE WHEN v.pendente THEN 'Pendente' WHEN v.resultado = 'aceitou' THEN 'Aceitou' ELSE 'Não aceitou' END AS situacao,
       (v.convidado_em AT TIME ZONE 'America/Sao_Paulo') AS convidado_em,
       (v.convite_expira_em AT TIME ZONE 'America/Sao_Paulo') AS convite_expira_em,
       (v.contrato_fim_proposto AT TIME ZONE 'America/Sao_Paulo')::date AS contrato_fim_proposto,
       (v.resolvido_em AT TIME ZONE 'America/Sao_Paulo') AS resolvido_em,
       EXISTS (SELECT 1 FROM public.creators x WHERE lower(btrim(ltrim(x.tiktok, '@'))) = v.arroba) AS passou_pela_bia,
       v.relation_id
FROM interno.agenciados_convites v;

-- Conferência: a última foto oficial do Partner Center contra o banco.
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
       u.convite_recusado, u.convite_expirado, u.sairam, u.contrato_vencido, u.total, u.vencem_em_breve
FROM u CROSS JOIN b;

-- Histórico completo das parcerias (todas as que o Partner Center lista).
CREATE OR REPLACE VIEW public.parcerias_historico AS
SELECT '@' || r.arroba AS tiktok, r.nome, r.status_tiktok, r.tipo_registro, r.status_dados,
       CASE r.status_tiktok WHEN 1 THEN 'Vinculado' WHEN 2 THEN 'Convite pendente' WHEN 4 THEN 'Desvinculando'
                            WHEN 6 THEN 'Convite não aceito' WHEN 9 THEN 'Encerrado'
                            ELSE 'Outro (' || r.status_tiktok || ')' END AS estado,
       (r.vinculo_criado_em AT TIME ZONE 'America/Sao_Paulo') AS convidado_em,
       (r.criado_em AT TIME ZONE 'America/Sao_Paulo') AS ultimo_movimento_em,
       (r.inicio_em AT TIME ZONE 'America/Sao_Paulo')::date AS inicio,
       (r.fim_em AT TIME ZONE 'America/Sao_Paulo')::date AS fim,
       (r.ultima_vista_em AT TIME ZONE 'America/Sao_Paulo') AS visto_em,
       EXISTS (SELECT 1 FROM interno.agenciados_tiktok a WHERE a.relation_id = r.relation_id AND a.ativo) AS agenciado_hoje,
       r.relation_id, r.creator_id
FROM interno.parcerias_partner_center r;

GRANT EXECUTE ON FUNCTION interno.ts_de_segundos(text), interno.int_ou_nulo(text, integer),
  interno.renovacao_rotulo(smallint) TO PUBLIC;
REVOKE ALL ON public.agenciados_ficha, public.agenciados_a_vencer, public.agenciados_movimento_por_categoria,
  public.agenciados_renovacao, public.agenciados_desvinculando, public.agenciados_convites_pendentes,
  public.agenciados_conferencia, public.parcerias_historico FROM anon, authenticated;
GRANT SELECT ON public.agenciados_ficha, public.agenciados_a_vencer, public.agenciados_movimento_por_categoria,
  public.agenciados_renovacao, public.agenciados_desvinculando, public.agenciados_convites_pendentes,
  public.agenciados_conferencia, public.parcerias_historico TO service_role;
COMMIT;
