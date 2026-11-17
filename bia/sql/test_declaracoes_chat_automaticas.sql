-- Execute after migration DDL in the SAME transaction, then ROLLBACK.
DO $test$
DECLARE a interno.atendimentos%rowtype; p jsonb; d jsonb; result jsonb; n bigint; stamp text;
BEGIN
 SELECT * INTO a FROM interno.atendimentos WHERE account_id='1' AND situacao='aberto'
   ORDER BY ultima_mensagem_em DESC LIMIT 1;
 IF NOT FOUND THEN RAISE EXCEPTION 'test_requires_existing_open_attendance'; END IF;
 stamp:=to_char(statement_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"');
 p:=jsonb_build_object('instancia',a.instancia,'account_id',a.account_id,'contact_id',a.contact_id,
   'conversation_id',a.conversation_id,'message_id','999999999999999999',
   'event_id','chatwoot:1:999999999999999999','revision',a.revisao+1,'atendimento_id',a.id,
   'creator_id',a.creator_id,'etapa',a.etapa,'situacao','aberto','observado_em',stamp,
   'ultima_mensagem_em',stamp,'expires_at',to_char((statement_timestamp()+interval '24 hours') AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 d:=jsonb_build_array(jsonb_build_object('campo','gmv','valor',9000000,'moeda','BRL','periodo_dias',30,
   'declarado_em',stamp,'mensagem_id','999999999999999999','evidencia','90 mil'));
 SET LOCAL ROLE service_role;
 result:=public.registrar_contato_declaracoes_v5(p,d);
 result:=public.registrar_contato_declaracoes_v5(p,d);
 IF result->>'replayed' IS DISTINCT FROM 'true' THEN RAISE EXCEPTION 'replay_failed'; END IF;
 SELECT count(*) INTO n FROM interno.declaracoes_chat WHERE account_id='1' AND mensagem_id='999999999999999999';
 IF n<>1 THEN RAISE EXCEPTION 'dedup_failed'; END IF;
 IF (SELECT qualificacao#>>'{declaracoes_chat,gmv,valor}' FROM interno.atendimentos WHERE id=a.id)<>'9000000' THEN
  RAISE EXCEPTION 'projection_failed'; END IF;
 BEGIN
  PERFORM public.registrar_contato_declaracoes_v5(p,jsonb_set(d,'{0,valor}','8000000'));
  RAISE EXCEPTION 'conflict_was_accepted';
 EXCEPTION WHEN unique_violation THEN NULL;
 END;
 BEGIN
  PERFORM public.registrar_contato_declaracoes_v5(p,jsonb_set(d,'{0,valor}','-1'));
  RAISE EXCEPTION 'negative_was_accepted';
 EXCEPTION WHEN invalid_parameter_value THEN NULL;
 END;
 -- Normalized unknown is stored as zero but cannot erase an informed amount.
 p:=p||jsonb_build_object('message_id','999999999999999998','event_id','chatwoot:1:999999999999999998','revision',a.revisao+2);
 d:=jsonb_set(jsonb_set(d,'{0,mensagem_id}','"999999999999999998"'),'{0,valor}','0');
 d:=jsonb_set(d,'{0,criterio_normalizacao}','"nao_sabe"');
 d:=jsonb_set(d,'{0,evidencia}','"Não sei"');
 result:=public.registrar_contato_declaracoes_v5(p,d);
 IF (SELECT criterio_normalizacao FROM interno.declaracoes_chat WHERE account_id='1' AND mensagem_id='999999999999999998') IS DISTINCT FROM 'nao_sabe' THEN
  RAISE EXCEPTION 'normalization_metadata_missing'; END IF;
 IF (SELECT qualificacao#>>'{declaracoes_chat,gmv,valor}' FROM interno.atendimentos WHERE id=a.id) IS DISTINCT FROM '9000000' THEN
  RAISE EXCEPTION 'unknown_overwrote_informed_amount'; END IF;
 RESET ROLE;
END;
$test$;
SELECT 'atomic_contact_history_projection_replay_conflict_and_invalid_value_passed' AS test_result;
