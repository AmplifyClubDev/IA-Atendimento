-- Testa agenciados_partner_completo.sql numa subtransação desfeita no fim; não deixa dado sintético.
-- A (vinculado, com pedido de renovação), B (pediu desvinculação), C (convite pendente).
DO $test$
DECLARE r jsonb; n integer; t0 timestamptz := now(); itens jsonb;
  s0 text := extract(epoch FROM now())::bigint::text;
  fim1 text := extract(epoch FROM now() + interval '5 days')::bigint::text;
  fim2 text := extract(epoch FROM now() + interval '370 days')::bigint::text;
  exp7 text := extract(epoch FROM now() + interval '7 days')::bigint::text;
BEGIN
 -- A correção única já deixou os 11 de volta como ativos.
 IF EXISTS (SELECT 1 FROM interno.agenciados_tiktok WHERE NOT ativo AND relation_id IN ('8684773223254296338',
     '8689672014151911176', '8689783154399151890', '8689771349254309650')) THEN RAISE EXCEPTION 'correcao_11'; END IF;
 IF interno.ts_de_segundos('abc') IS NOT NULL OR interno.ts_de_segundos('1795200000') IS NULL
    OR interno.int_ou_nulo('12') <> 12 OR interno.int_ou_nulo('-1') IS NOT NULL OR interno.int_ou_nulo('5', 3) IS NOT NULL
    OR interno.renovacao_rotulo(1::smallint) <> 'Aguardando aceite' OR interno.renovacao_rotulo(NULL) IS NOT NULL THEN
   RAISE EXCEPTION 'funcoes'; END IF;
 BEGIN
  DELETE FROM interno.agenciados_tiktok_coletas WHERE observado_em > t0 - interval '2 hours';
  SET LOCAL ROLE service_role;
  r := public.registrar_coleta_agenciados_v5(jsonb_build_object('observado_em', t0, 'total', 2, 'completa', false,
    'fonte', 'teste', 'itens', jsonb_build_array(
      jsonb_build_object('relation_id', 'zzsinteticoA', 'arroba', 'zz_a', 'estado', 'vinculado', 'com_detalhes', '1',
        'create_time_second', s0, 'effective_end_date_second', fim1, 'nivel', '1', 'gmv_nivel', '6000',
        'renovacao_status', '1', 'renovacao_pedido_second', s0, 'renovacao_expira_second', exp7,
        'renovacao_novo_fim_second', fim2, 'renovacao_restantes', '1'),
      jsonb_build_object('relation_id', 'zzsinteticoB', 'arroba', 'zz_b', 'estado', 'desvinculando', 'com_detalhes', '1',
        'create_time_second', s0, 'effective_end_date_second', fim2, 'desvinculo_pedido_second', s0,
        'desvinculo_conclui_second', exp7)),
    'pendentes', jsonb_build_object('completa', true, 'total', 1, 'itens', jsonb_build_array(
      jsonb_build_object('relation_id', 'zzsinteticoC', 'arroba', '@ZZ_C', 'create_time_second', s0,
        'expire_time_second', exp7, 'effective_end_date_second', fim2))),
    'contagens', jsonb_build_object('bound', 1551, 'pending', 99, 'unbinding', 46, 'unbound', 8718, 'all', 10414,
      'binding_failed_reject', 425, 'binding_expire_soon', jsonb_build_array(219, 139, 8))));
  IF r ->> 'status' <> 'registrada' OR (r ->> 'entraram')::int <> 1 OR (r ->> 'desvinculando')::int <> 1
     OR (r ->> 'pendentes')::int <> 1 THEN RAISE EXCEPTION 'coleta1 %', r; END IF;
  SELECT count(*) INTO n FROM interno.agenciados_eventos WHERE relation_id = 'zzsinteticoB';
  IF n <> 1 OR NOT EXISTS (SELECT 1 FROM interno.agenciados_eventos WHERE relation_id = 'zzsinteticoB' AND tipo = 'pediu_desvinculo')
    THEN RAISE EXCEPTION 'b_so_pediu_desvinculo'; END IF;
  IF NOT EXISTS (SELECT 1 FROM interno.agenciados_eventos WHERE relation_id = 'zzsinteticoA' AND tipo = 'entrou') THEN
    RAISE EXCEPTION 'a_entrou'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.agenciados_ficha WHERE tiktok = '@zz_b' AND situacao = 'Saindo'
                 AND desvinculo_conclui_em IS NOT NULL) THEN RAISE EXCEPTION 'ficha_saindo'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.agenciados_desvinculando WHERE tiktok = '@zz_b' AND dias_para_concluir BETWEEN 6 AND 7)
    THEN RAISE EXCEPTION 'tela_desvinculando'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.agenciados_renovacao WHERE tiktok = '@zz_a' AND renovacao = 'Aguardando aceite'
                 AND renovacao_pedidos_restantes = 1 AND categoria = 'Silver') THEN RAISE EXCEPTION 'tela_renovacao'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.agenciados_convites_pendentes WHERE tiktok = '@zz_c' AND situacao = 'Pendente') THEN
    RAISE EXCEPTION 'convite_pendente'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.agenciados_conferencia WHERE tiktok_vinculados = 1551 AND tiktok_desvinculando = 46) THEN
    RAISE EXCEPTION 'conferencia'; END IF;

  -- 2ª coleta: A sem pedido (com detalhes), B desistiu da saída, C sumiu dos pendentes.
  RESET ROLE;
  DELETE FROM interno.agenciados_tiktok_coletas WHERE observado_em >= t0;
  SET LOCAL ROLE service_role;
  r := public.registrar_coleta_agenciados_v5(jsonb_build_object('observado_em', t0 + interval '1 minute', 'total', 2,
    'completa', false, 'itens', jsonb_build_array(
      jsonb_build_object('relation_id', 'zzsinteticoA', 'arroba', 'zz_a', 'estado', 'vinculado', 'com_detalhes', '1',
        'effective_end_date_second', fim1),
      jsonb_build_object('relation_id', 'zzsinteticoB', 'arroba', 'zz_b', 'estado', 'vinculado',
        'effective_end_date_second', fim2)),
    'pendentes', jsonb_build_object('completa', true, 'total', 0, 'itens', '[]'::jsonb)));
  IF (r ->> 'convites_resolvidos')::int <> 1 THEN RAISE EXCEPTION 'convite_resolvido %', r; END IF;
  IF (SELECT renovacao_status FROM interno.agenciados_tiktok WHERE relation_id = 'zzsinteticoA') IS NOT NULL THEN
    RAISE EXCEPTION 'renovacao_nao_limpou'; END IF;
  IF NOT EXISTS (SELECT 1 FROM interno.agenciados_eventos WHERE relation_id = 'zzsinteticoB' AND tipo = 'cancelou_desvinculo')
    OR EXISTS (SELECT 1 FROM interno.agenciados_eventos WHERE relation_id = 'zzsinteticoB' AND tipo IN ('entrou', 'voltou'))
    THEN RAISE EXCEPTION 'b_cancelou'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.agenciados_convites_pendentes WHERE tiktok = '@zz_c' AND situacao = 'Não aceitou') THEN
    RAISE EXCEPTION 'convite_nao_aceitou'; END IF;

  -- 3ª coleta completa sem B: B sai. A continua.
  RESET ROLE;
  DELETE FROM interno.agenciados_tiktok_coletas WHERE observado_em >= t0;
  SELECT jsonb_agg(jsonb_build_object('relation_id', relation_id, 'arroba', arroba,
           'estado', coalesce(situacao_tiktok, 'vinculado'),
           'effective_end_date_second', extract(epoch FROM vigencia_fim)::bigint::text)), count(*)
    INTO itens, n FROM interno.agenciados_tiktok WHERE ativo AND relation_id <> 'zzsinteticoB';
  SET LOCAL ROLE service_role;
  r := public.registrar_coleta_agenciados_v5(jsonb_build_object('observado_em', t0 + interval '2 minutes',
    'total', n, 'completa', true, 'itens', itens));
  IF (r ->> 'sairam')::int <> 1 OR NOT EXISTS (SELECT 1 FROM interno.agenciados_eventos
       WHERE relation_id = 'zzsinteticoB' AND tipo = 'saiu') THEN RAISE EXCEPTION 'saida %', r; END IF;
  IF (SELECT count(*) FROM interno.agenciados_eventos WHERE observado_em >= t0 AND relation_id NOT LIKE 'zzsintetico%'
        AND tipo IN ('saiu', 'entrou', 'voltou', 'pediu_desvinculo', 'cancelou_desvinculo')) <> 0 THEN
    RAISE EXCEPTION 'evento_falso_nos_reais'; END IF;

  r := public.importar_parcerias_v5(jsonb_build_object('observado_em', t0, 'itens', jsonb_build_array(
    jsonb_build_object('relation_id', 'zzsinteticoD', 'arroba', 'zz_d', 'status', '9', 'tipo_registro', '13',
      'status_dados', '3', 'create_time_second', s0, 'effective_end_date_second', fim1))));
  IF (r ->> 'gravados')::int <> 1 OR NOT EXISTS (SELECT 1 FROM public.parcerias_historico
       WHERE tiktok = '@zz_d' AND estado = 'Encerrado') THEN RAISE EXCEPTION 'historico %', r; END IF;
  PERFORM 1 FROM public.agenciados_movimento_por_categoria LIMIT 1;
  PERFORM 1 FROM public.agenciados_a_vencer LIMIT 1;
  RESET ROLE;

  SET LOCAL ROLE anon;
  BEGIN
    PERFORM 1 FROM public.agenciados_renovacao LIMIT 1;
    RAISE EXCEPTION 'anon_le_renovacao';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RESET ROLE;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_agenciados_partner_completo: ok';
END
$test$;
