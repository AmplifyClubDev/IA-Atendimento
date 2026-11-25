-- Testa renovacao_regua.sql numa subtransação desfeita no fim (não deixa fila).
DO $test$
DECLARE r jsonb; n integer;
BEGIN
 BEGIN
  -- Regras: só "pode enviar" quem está ativo, com pedido aguardando aceite e telefone.
  IF EXISTS (SELECT 1 FROM public.renovacao_regua WHERE motivo IS NULL
             AND (renovacao <> 'Aguardando aceite' OR telefone IS NULL OR template IS NULL)) THEN RAISE EXCEPTION 'regra'; END IF;
  IF EXISTS (SELECT 1 FROM public.renovacao_regua WHERE etapa = 'lembrete' AND parametros <> jsonb_build_array(dias::text)) THEN
    RAISE EXCEPTION 'parametro_dias'; END IF;
  SELECT count(*) INTO n FROM public.renovacao_regua WHERE motivo IS NULL;
  SET LOCAL ROLE service_role;
  r := public.preparar_fila_renovacao_v5();
  IF (r ->> 'novos')::int <> n THEN RAISE EXCEPTION 'fila % <> %', r, n; END IF;
  -- Rodar de novo não duplica.
  r := public.preparar_fila_renovacao_v5();
  IF (r ->> 'novos')::int <> 0 THEN RAISE EXCEPTION 'duplicou %', r; END IF;
  IF EXISTS (SELECT 1 FROM public.renovacao_regua WHERE motivo IS NULL) THEN RAISE EXCEPTION 'regua_nao_viu_fila'; END IF;
  PERFORM 1 FROM public.renovacao_fila LIMIT 1;
  RESET ROLE;
  SET LOCAL ROLE anon;
  BEGIN
    PERFORM 1 FROM public.renovacao_regua LIMIT 1;
    RAISE EXCEPTION 'anon_le_regua';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RESET ROLE;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_renovacao_regua: ok';
END
$test$;
