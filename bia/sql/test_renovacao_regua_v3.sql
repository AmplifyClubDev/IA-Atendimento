-- Testa renovacao_regua_v3.sql numa subtransação desfeita no fim.
DO $test$
DECLARE r jsonb; n integer;
BEGIN
 BEGIN
  IF interno.primeiro_nome('ana paula 💙') <> 'Ana' OR interno.primeiro_nome('Prof Aline Sakura') <> 'Aline' OR interno.primeiro_nome('A Ponte Cidadã') <> 'Ponte' OR interno.primeiro_nome('🌸') IS NOT NULL OR interno.primeiro_nome(NULL) IS NOT NULL THEN
    RAISE EXCEPTION 'primeiro_nome'; END IF;
  IF EXISTS (SELECT 1 FROM public.renovacao_regua WHERE motivo IS NULL AND (dias NOT BETWEEN 1 AND 7
             OR template <> 'renovacao_contrato' OR parametros <> jsonb_build_array(to_char(contrato_fim, 'DD/MM'))
             OR telefone IS NULL OR renovacao = 'Aceita')) THEN RAISE EXCEPTION 'regra'; END IF;
  IF EXISTS (SELECT 1 FROM interno.renovacao_envios WHERE situacao = 'previsto' AND etapa IN ('semana', 'lembrete', 'hoje')) THEN
    RAISE EXCEPTION 'fila_antiga'; END IF;
  SELECT count(*) INTO n FROM public.renovacao_regua WHERE motivo IS NULL;
  SET LOCAL ROLE service_role;
  r := public.preparar_fila_renovacao_v5();
  IF (r ->> 'novos')::int <> n THEN RAISE EXCEPTION 'fila % <> %', r, n; END IF;
  r := public.preparar_fila_renovacao_v5();
  IF (r ->> 'novos')::int <> 0 THEN RAISE EXCEPTION 'duplicou %', r; END IF;
  RESET ROLE;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_renovacao_regua_v3: ok';
END
$test$;
