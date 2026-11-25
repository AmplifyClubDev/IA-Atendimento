-- Testa creators_foto.sql (só leitura).
DO $test$
BEGIN
  IF (SELECT count(*) FROM public.creators_foto) <> (SELECT count(*) FROM interno.creators WHERE foto_perfil_referencia LIKE 'publico/%') THEN
    RAISE EXCEPTION 'contagem'; END IF;
  IF EXISTS (SELECT 1 FROM public.creators_foto WHERE foto_ref NOT LIKE 'publico/%') THEN RAISE EXCEPTION 'caminho'; END IF;
  SET LOCAL ROLE anon;
  BEGIN
    PERFORM 1 FROM public.creators_foto LIMIT 1;
    RAISE EXCEPTION 'anon_le_foto';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RESET ROLE;
  RAISE NOTICE 'test_creators_foto: ok';
END
$test$;
