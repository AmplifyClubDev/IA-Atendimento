-- Testa telefones_chatwoot.sql numa subtransação desfeita no fim.
DO $test$
DECLARE r jsonb; a text;
BEGIN
 BEGIN
  SELECT arroba INTO a FROM interno.agenciados_tiktok
   WHERE ativo AND arroba IS NOT NULL AND NOT EXISTS (SELECT 1 FROM interno.telefones_creators t WHERE t.arroba = agenciados_tiktok.arroba)
   LIMIT 1;
  SET LOCAL ROLE service_role;
  r := public.importar_telefones_v5(jsonb_build_object('fonte', 'chatwoot', 'itens', jsonb_build_array(
         jsonb_build_object('arroba', a, 'telefone', '+55 47 99999-0009', 'ref', 'chatwoot:1'))));
  IF (r ->> 'gravados')::int <> 1 THEN RAISE EXCEPTION 'import %', r; END IF;
  IF (SELECT fonte_telefone FROM public.agenciados_ficha WHERE tiktok = '@' || a) <> 'chatwoot' THEN RAISE EXCEPTION 'ficha'; END IF;
  IF (SELECT fonte_telefone FROM public.agenciados_contato WHERE tiktok = '@' || a) <> 'chatwoot' THEN RAISE EXCEPTION 'contato'; END IF;
  -- Notion não passa na frente do Chatwoot
  r := public.importar_telefones_v5(jsonb_build_object('fonte', 'notion', 'itens', jsonb_build_array(
         jsonb_build_object('arroba', a, 'telefone', '5547999990010'))));
  IF (SELECT fonte_telefone FROM public.agenciados_ficha WHERE tiktok = '@' || a) <> 'chatwoot' THEN RAISE EXCEPTION 'prioridade'; END IF;
  BEGIN
    PERFORM public.importar_telefones_v5('{"fonte": "outra", "itens": []}');
    RAISE EXCEPTION 'fonte_estranha_aceita';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
  RESET ROLE;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_telefones_chatwoot: ok';
END
$test$;
