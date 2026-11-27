-- Testa renovacao_liberar.sql numa subtransação desfeita no fim.
DO $test$
DECLARE r jsonb; id_v bigint; id_a bigint; hoje date := (now() AT TIME ZONE 'America/Sao_Paulo')::date; rel text;
BEGIN
 BEGIN
  SELECT relation_id INTO rel FROM interno.agenciados_tiktok WHERE ativo AND vigencia_fim > now() + interval '30 days' LIMIT 1;
  -- Envio antigo de um contrato que terminou ontem e não foi renovado (a ficha mostra o mesmo fim): "venceu".
  INSERT INTO interno.renovacao_envios (relation_id, contrato_fim, etapa, template, situacao, chatwoot_conversa, enviado_em)
  VALUES ('zzsinteticoL1', hoje - 1, 'convite', 'renovacao_contrato', 'enviado', '999999101', now()) RETURNING id INTO id_v;
  -- Envio de alguém cujo contrato hoje vai além do enviado: "renovou".
  INSERT INTO interno.renovacao_envios (relation_id, contrato_fim, etapa, template, situacao, chatwoot_conversa, enviado_em)
  VALUES (rel, hoje + 2, 'convite', 'renovacao_contrato', 'enviado', '999999102', now()) RETURNING id INTO id_a;
  IF (SELECT ciclo_fim FROM public.renovacao_para_liberar WHERE id = id_v) <> 'saiu' THEN RAISE EXCEPTION 'sem_ficha_saiu'; END IF;
  IF (SELECT ciclo_fim FROM public.renovacao_para_liberar WHERE id = id_a) <> 'renovou' THEN RAISE EXCEPTION 'renovou'; END IF;
  SET LOCAL ROLE service_role;
  r := public.fechar_ciclo_renovacao_v5(jsonb_build_object('id', id_a::text, 'ciclo_fim', 'renovou', 'confirmacao', true));
  IF (r ->> 'fechados')::int <> 1 THEN RAISE EXCEPTION 'fechou %', r; END IF;
  r := public.fechar_ciclo_renovacao_v5(jsonb_build_object('id', id_a::text, 'ciclo_fim', 'renovou'));
  IF (r ->> 'fechados')::int <> 0 THEN RAISE EXCEPTION 'fechou_2x'; END IF;
  RESET ROLE;
  IF EXISTS (SELECT 1 FROM public.renovacao_para_liberar WHERE id = id_a) THEN RAISE EXCEPTION 'continua_na_lista'; END IF;
  IF (SELECT confirmacao_enviada_em FROM interno.renovacao_envios WHERE id = id_a) IS NULL THEN RAISE EXCEPTION 'confirmacao'; END IF;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_renovacao_liberar: ok';
END
$test$;
