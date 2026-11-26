-- Testa renovacao_respostas.sql numa subtransação desfeita no fim.
DO $test$
DECLARE r jsonb; id_envio bigint;
BEGIN
 BEGIN
  INSERT INTO interno.renovacao_envios (relation_id, contrato_fim, etapa, template, situacao, chatwoot_conversa, enviado_em)
  VALUES ('zzsinteticoQ', current_date + 3, 'convite', 'renovacao_contrato', 'enviado', '999999001', now()) RETURNING id INTO id_envio;
  SET LOCAL ROLE service_role;
  r := public.registrar_resposta_renovacao_v5(jsonb_build_object('mensagem', '888000001', 'conversa', '999999001',
         'telefone', '+55 47 99999-0000', 'resposta', 'nao_quero', 'texto', 'Não quero renovar'));
  IF r ->> 'status' <> 'registrada' OR (r -> 'envio' ->> 'id')::bigint <> id_envio THEN RAISE EXCEPTION 'ligou_envio %', r; END IF;
  r := public.registrar_resposta_renovacao_v5(jsonb_build_object('mensagem', '888000001', 'conversa', '999999001', 'resposta', 'nao_quero'));
  IF r ->> 'status' <> 'repetida' THEN RAISE EXCEPTION 'duplicou'; END IF;
  r := public.registrar_resposta_renovacao_v5(jsonb_build_object('mensagem', '888000002', 'conversa', '123', 'resposta', 'duvida'));
  IF r ->> 'status' <> 'registrada' OR r -> 'envio' <> 'null'::jsonb THEN RAISE EXCEPTION 'sem_envio %', r; END IF;
  RESET ROLE;
  IF NOT EXISTS (SELECT 1 FROM interno.renovacao_respostas WHERE chatwoot_mensagem = '888000001' AND telefone = '5547999990000') THEN
    RAISE EXCEPTION 'telefone_normalizado'; END IF;
  PERFORM 1 FROM public.renovacao_respostas LIMIT 1;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_renovacao_respostas: ok';
END
$test$;
