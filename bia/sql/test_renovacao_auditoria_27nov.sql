-- Testa renovacao_auditoria_27nov.sql numa subtransação desfeita no fim.
DO $test$
DECLARE r jsonb; id_venc bigint; id_env bigint; hoje date := (now() AT TIME ZONE 'America/Sao_Paulo')::date;
BEGIN
 BEGIN
  -- Linha prevista de um contrato que já venceu: a preparação cancela.
  INSERT INTO interno.renovacao_envios (relation_id, contrato_fim, etapa, template)
  SELECT relation_id, hoje - 1, 'convite', 'renovacao_contrato' FROM interno.agenciados_tiktok WHERE ativo LIMIT 1
  RETURNING id INTO id_venc;
  SET LOCAL ROLE service_role;
  r := public.preparar_fila_renovacao_v5();
  RESET ROLE;
  IF NOT EXISTS (SELECT 1 FROM interno.renovacao_envios WHERE id = id_venc AND situacao = 'cancelado') THEN RAISE EXCEPTION 'vencido_nao_cancelado'; END IF;
  IF EXISTS (SELECT 1 FROM interno.renovacao_envios WHERE situacao = 'previsto' AND contrato_fim <= hoje) THEN RAISE EXCEPTION 'sobrou_vencido'; END IF;
  -- Conversa que não é nossa e não é teste: não registra.
  SET LOCAL ROLE service_role;
  r := public.registrar_resposta_renovacao_v5(jsonb_build_object('mensagem', '777000001', 'conversa', '123456', 'resposta', 'outro'));
  IF r ->> 'status' <> 'fora' THEN RAISE EXCEPTION 'registrou_conversa_alheia %', r; END IF;
  r := public.registrar_resposta_renovacao_v5(jsonb_build_object('mensagem', '777000002', 'conversa', '123456', 'resposta', 'outro', 'teste', true));
  IF r ->> 'status' <> 'registrada' THEN RAISE EXCEPTION 'teste_nao_registrou %', r; END IF;
  RESET ROLE;
  -- Conversa enviada pelo serviço: registra e devolve o contrato.
  INSERT INTO interno.renovacao_envios (relation_id, contrato_fim, etapa, template, situacao, chatwoot_conversa, enviado_em)
  VALUES ('zzsinteticoA27', hoje + 3, 'convite', 'renovacao_contrato', 'enviado', '999999027', now()) RETURNING id INTO id_env;
  SET LOCAL ROLE service_role;
  r := public.registrar_resposta_renovacao_v5(jsonb_build_object('mensagem', '777000003', 'conversa', '999999027', 'resposta', 'quero'));
  IF r ->> 'status' <> 'registrada' OR (r -> 'envio' ->> 'id')::bigint <> id_env THEN RAISE EXCEPTION 'nossa %', r; END IF;
  RESET ROLE;
  RAISE EXCEPTION 'rollback_ok';
 EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'rollback_ok' THEN RAISE; END IF;
 END;
 RAISE NOTICE 'test_renovacao_auditoria_27nov: ok';
END
$test$;
