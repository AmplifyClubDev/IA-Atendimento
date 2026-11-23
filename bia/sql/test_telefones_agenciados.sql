-- Testa telefones_agenciados.sql numa subtransação desfeita no fim; não deixa dado sintético.
DO $test$
DECLARE r jsonb; n integer;
BEGIN
 BEGIN
  IF interno.normalizar_arroba(' https://www.tiktok.com/@Teste.Um/video/1?x=2 ') IS DISTINCT FROM 'teste.um' THEN
    RAISE EXCEPTION 'arroba_url'; END IF;
  IF interno.normalizar_arroba('@@Teste_2') IS DISTINCT FROM 'teste_2' THEN RAISE EXCEPTION 'arroba_simples'; END IF;
  IF interno.normalizar_telefone('(47) 99999-0000') IS DISTINCT FROM '5547999990000' THEN RAISE EXCEPTION 'tel_11'; END IF;
  IF interno.normalizar_telefone('+55 47 9999-0000') IS DISTINCT FROM '554799990000' THEN RAISE EXCEPTION 'tel_12'; END IF;
  IF interno.normalizar_telefone('12345') IS NOT NULL THEN RAISE EXCEPTION 'tel_curto'; END IF;

  SET LOCAL ROLE service_role;
  r := public.importar_telefones_v5(jsonb_build_object('fonte', 'notion', 'itens', jsonb_build_array(
         jsonb_build_object('arroba', '@zz_sintetico_tel', 'telefone', '47 99999-0001', 'ref', 'a'),
         jsonb_build_object('arroba', 'ZZ_SINTETICO_TEL', 'telefone', '5547999990001', 'ref', 'b'),
         jsonb_build_object('arroba', '', 'telefone', '47999990002'),
         jsonb_build_object('arroba', 'zz_sintetico_tel', 'telefone', '123'))));
  IF (r ->> 'recebidos')::int <> 4 OR (r ->> 'validos')::int <> 1 OR (r ->> 'gravados')::int <> 1 THEN
    RAISE EXCEPTION 'import_contagem %', r; END IF;
  r := public.importar_telefones_v5(jsonb_build_object('fonte', 'base_amplify', 'itens', jsonb_build_array(
         jsonb_build_object('arroba', 'zz_sintetico_tel', 'telefone', '47999990003', 'visto_em', '2026-11-01T00:00:00Z'))));
  SELECT count(*) INTO n FROM interno.telefones_creators WHERE arroba = 'zz_sintetico_tel';
  IF n <> 2 THEN RAISE EXCEPTION 'import_linhas %', n; END IF;
  BEGIN
    PERFORM public.importar_telefones_v5('{"fonte": "formulario", "itens": []}');
    RAISE EXCEPTION 'fonte_interna_aceita';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  PERFORM public.atualizar_telefones_internos_v5();
  PERFORM 1 FROM public.agenciados_contato LIMIT 1;
  RESET ROLE;

  SET LOCAL ROLE anon;
  BEGIN
    PERFORM 1 FROM public.agenciados_contato LIMIT 1;
    RAISE EXCEPTION 'anon_le_telefones';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RESET ROLE;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_telefones_agenciados: ok';
END
$test$;
