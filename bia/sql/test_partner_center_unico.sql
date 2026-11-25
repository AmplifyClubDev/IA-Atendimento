-- Testa partner_center_unico.sql numa subtransação desfeita no fim; não deixa dado sintético.
DO $test$
DECLARE r jsonb; n integer; t0 timestamptz := now(); s0 text := extract(epoch FROM now())::bigint::text;
BEGIN
 BEGIN
  -- 1 linha por ID de parceria.
  IF (SELECT count(*) FROM public.partner_center) <> (SELECT count(DISTINCT id_parceria) FROM public.partner_center) THEN
    RAISE EXCEPTION 'id_repetido'; END IF;
  -- Todos os agenciados e todos os convites aparecem.
  IF (SELECT count(*) FROM public.partner_center WHERE origem = 'agenciados') <> (SELECT count(*) FROM interno.agenciados_tiktok)
    THEN RAISE EXCEPTION 'faltam_agenciados'; END IF;
  IF (SELECT count(*) FROM public.partner_center WHERE estado IN ('Vinculado', 'Saindo'))
     <> (SELECT count(*) FROM interno.agenciados_tiktok WHERE ativo) THEN RAISE EXCEPTION 'ativos'; END IF;

  SET LOCAL ROLE service_role;
  -- Atualização sem detalhes não apaga o que já existe.
  r := public.importar_parcerias_v5(jsonb_build_object('observado_em', t0, 'itens', jsonb_build_array(
    jsonb_build_object('relation_id', 'zzsinteticoH', 'arroba', 'zz_h', 'status', '7', 'tipo_registro', '1',
      'vinculo_create_second', s0, 'create_time_second', s0))));
  r := public.importar_parcerias_v5(jsonb_build_object('observado_em', t0 + interval '1 minute', 'itens', jsonb_build_array(
    jsonb_build_object('relation_id', 'zzsinteticoH', 'arroba', 'zz_h', 'status', '9'))));
  SELECT count(*) INTO n FROM interno.parcerias_partner_center
   WHERE relation_id = 'zzsinteticoH' AND status_tiktok = 9 AND tipo_registro = 1 AND vinculo_criado_em IS NOT NULL;
  IF n <> 1 THEN RAISE EXCEPTION 'historico_apagou_dado'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.partner_center WHERE id_parceria = 'zzsinteticoH' AND estado = 'Saiu (desvinculou)'
                 AND origem = 'historico') THEN RAISE EXCEPTION 'linha_historico'; END IF;
  PERFORM 1 FROM public.partner_center_resumo;
  PERFORM diferenca_vinculados FROM public.agenciados_conferencia;
  RESET ROLE;

  SET LOCAL ROLE anon;
  BEGIN
    PERFORM 1 FROM public.partner_center LIMIT 1;
    RAISE EXCEPTION 'anon_le_partner_center';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RESET ROLE;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_partner_center_unico: ok';
END
$test$;
