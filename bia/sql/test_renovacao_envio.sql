-- Testa renovacao_envio.sql numa subtransação desfeita no fim.
DO $test$
DECLARE r jsonb; id_teste bigint;
BEGIN
 BEGIN
  INSERT INTO interno.renovacao_envios (relation_id, contrato_fim, etapa, template)
  VALUES ('zzsinteticoR', current_date, 'semana', 'primeiro_contato_contrato') RETURNING id INTO id_teste;
  SET LOCAL ROLE service_role;
  r := public.marcar_envio_renovacao_v5(jsonb_build_object('id', id_teste::text, 'situacao', 'enviado', 'chatwoot_conversa', '123'));
  IF (r ->> 'alterados')::int <> 1 THEN RAISE EXCEPTION 'marcou %', r; END IF;
  -- Já enviado não volta a mudar.
  r := public.marcar_envio_renovacao_v5(jsonb_build_object('id', id_teste::text, 'situacao', 'falhou'));
  IF (r ->> 'alterados')::int <> 0 THEN RAISE EXCEPTION 'mudou_enviado'; END IF;
  RESET ROLE;
  IF NOT EXISTS (SELECT 1 FROM interno.renovacao_envios WHERE id = id_teste AND situacao = 'enviado'
                 AND enviado_em IS NOT NULL AND chatwoot_conversa = '123') THEN RAISE EXCEPTION 'gravado'; END IF;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_renovacao_envio: ok';
END
$test$;
