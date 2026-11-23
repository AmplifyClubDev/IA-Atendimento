-- Testa agenciados_categoria.sql (só leitura de funções e telas; nada é gravado).
DO $test$
DECLARE r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES (0::numeric, 'Start'), (4999.99, 'Start'), (5000, 'Silver'), (29999.99, 'Silver'),
                                  (30000, 'Gold'), (99999.99, 'Gold'), (100000, 'Diamond'), (5000000, 'Diamond')) v(g, c) LOOP
    IF interno.categoria_amplify(r.g) IS DISTINCT FROM r.c THEN RAISE EXCEPTION 'categoria % -> %', r.g, interno.categoria_amplify(r.g); END IF;
  END LOOP;
  IF interno.categoria_amplify(NULL) IS NOT NULL OR interno.categoria_amplify(-1) IS NOT NULL THEN RAISE EXCEPTION 'nulo_negativo'; END IF;
  IF interno.ordem_categoria('Diamond') <> 4 OR interno.ordem_categoria('x') IS NOT NULL THEN RAISE EXCEPTION 'ordem'; END IF;
  IF EXISTS (SELECT 1 FROM public.agenciados_ficha WHERE gmv_nivel IS NOT NULL AND categoria IS NULL) THEN RAISE EXCEPTION 'ficha_sem_categoria'; END IF;
  IF (SELECT sum(agenciados) FROM public.agenciados_por_categoria) <> (SELECT count(*) FROM interno.agenciados_tiktok WHERE ativo) THEN
    RAISE EXCEPTION 'soma_por_categoria'; END IF;
  PERFORM 1 FROM public.agenciados_movimento_por_categoria LIMIT 1;
  PERFORM categoria FROM public.agenciados_a_vencer LIMIT 1;
  RAISE NOTICE 'test_agenciados_categoria: ok';
END
$test$;
