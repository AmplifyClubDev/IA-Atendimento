-- Testa agenciados_ficha.sql numa subtransação desfeita no fim; não deixa dado sintético.
-- Um agenciado sintético entra (nível 2), renova e sobe de nível, e sai; os reais não mudam (rollback).
DO $test$
DECLARE r jsonb; n integer; ev record; itens jsonb; t0 timestamptz := now();
  fim1 bigint := extract(epoch FROM now() + interval '60 days')::bigint;
  fim2 bigint := extract(epoch FROM now() + interval '425 days')::bigint;
BEGIN
 BEGIN
  DELETE FROM interno.agenciados_tiktok_coletas WHERE observado_em > t0 - interval '2 hours';
  SET LOCAL ROLE service_role;
  r := public.registrar_coleta_agenciados_v5(jsonb_build_object('observado_em', t0, 'total', 1, 'completa', false,
    'fonte', 'teste', 'itens', jsonb_build_array(jsonb_build_object(
      'relation_id', 'zzsintetico1', 'arroba', '@ZZ_Sintetico', 'creator_name', 'Teste', 'status', 'vinculado',
      'create_time_second', extract(epoch FROM t0)::bigint::text, 'effective_end_date_second', fim1::text,
      'creator_id', '123', 'start_second', extract(epoch FROM t0)::bigint::text, 'nivel', '2', 'nivel_nome', 'Level 2',
      'nivel_proximo', '3', 'gmv_nivel', '3030.50', 'gmv_meta', '5000', 'progresso_pct', '6', 'seguidores', '2170',
      'categorias', jsonb_build_array('Beleza', 'Casa', ''), 'comissao_pct', '10', 'desvinculos_recusados', '0'))));
  IF r ->> 'status' <> 'registrada' OR (r ->> 'entraram')::int <> 1 OR (r ->> 'com_detalhes')::int <> 1 THEN
    RAISE EXCEPTION 'coleta1 %', r; END IF;
  SELECT * INTO ev FROM interno.agenciados_eventos WHERE relation_id = 'zzsintetico1';
  IF ev.tipo <> 'entrou' OR ev.nivel <> 2 OR ev.gmv_nivel <> 3030.50 THEN RAISE EXCEPTION 'evento_entrou %', row_to_json(ev); END IF;
  SELECT count(*) INTO n FROM interno.agenciados_tiktok
   WHERE relation_id = 'zzsintetico1' AND arroba = 'zz_sintetico' AND categorias = ARRAY['Beleza', 'Casa']
     AND seguidores = 2170 AND comissao_pct = 10 AND detalhes_em = t0;
  IF n <> 1 THEN RAISE EXCEPTION 'ficha_gravada'; END IF;

  RESET ROLE;
  DELETE FROM interno.agenciados_tiktok_coletas WHERE observado_em >= t0;
  SET LOCAL ROLE service_role;
  r := public.registrar_coleta_agenciados_v5(jsonb_build_object('observado_em', t0 + interval '1 minute', 'total', 1,
    'completa', false, 'itens', jsonb_build_array(jsonb_build_object(
      'relation_id', 'zzsintetico1', 'arroba', 'zz_sintetico', 'effective_end_date_second', fim2::text,
      'nivel', '3', 'nivel_nome', 'Level 3'))));
  SELECT count(*) INTO n FROM interno.agenciados_eventos WHERE relation_id = 'zzsintetico1' AND tipo IN ('renovou', 'mudou_nivel');
  IF n <> 2 OR (r ->> 'eventos')::int <> 2 THEN RAISE EXCEPTION 'renovou_mudou %', r; END IF;
  IF (SELECT seguidores FROM interno.agenciados_tiktok WHERE relation_id = 'zzsintetico1') <> 2170 THEN
    RAISE EXCEPTION 'detalhe_apagado_sem_motivo'; END IF;

  -- Lista completa sem o sintético: ele sai, com o nível do momento.
  RESET ROLE;
  DELETE FROM interno.agenciados_tiktok_coletas WHERE observado_em >= t0;
  SELECT jsonb_agg(jsonb_build_object('relation_id', relation_id, 'arroba', arroba,
           'effective_end_date_second', extract(epoch FROM vigencia_fim)::bigint::text)), count(*)
    INTO itens, n FROM interno.agenciados_tiktok WHERE ativo AND relation_id <> 'zzsintetico1';
  SET LOCAL ROLE service_role;
  r := public.registrar_coleta_agenciados_v5(jsonb_build_object('observado_em', t0 + interval '2 minutes',
    'total', n, 'completa', true, 'itens', itens));
  IF (r ->> 'sairam')::int <> 1 THEN RAISE EXCEPTION 'saida %', r; END IF;
  SELECT * INTO ev FROM interno.agenciados_eventos WHERE relation_id = 'zzsintetico1' AND tipo = 'saiu';
  IF ev.nivel <> 3 OR ev.nivel_nome <> 'Level 3' THEN RAISE EXCEPTION 'saida_sem_nivel'; END IF;
  SELECT count(*) INTO n FROM interno.agenciados_eventos WHERE tipo = 'renovou' AND relation_id <> 'zzsintetico1'
    AND observado_em >= t0;
  IF n <> 0 THEN RAISE EXCEPTION 'renovacao_falsa_nos_reais %', n; END IF;

  PERFORM 1 FROM public.agenciados_ficha LIMIT 1;
  PERFORM 1 FROM public.agenciados_movimento_por_nivel LIMIT 1;
  PERFORM 1 FROM public.agenciados_a_vencer LIMIT 1;
  IF NOT EXISTS (SELECT 1 FROM public.agenciados_movimento WHERE tiktok = '@zz_sintetico' AND tipo = 'saiu') THEN
    RAISE EXCEPTION 'tela_movimento'; END IF;
  RESET ROLE;

  SET LOCAL ROLE anon;
  BEGIN
    PERFORM 1 FROM public.agenciados_ficha LIMIT 1;
    RAISE EXCEPTION 'anon_le_ficha';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RESET ROLE;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_agenciados_ficha: ok';
END
$test$;
