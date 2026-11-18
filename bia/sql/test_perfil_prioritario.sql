-- Test all effects in a rolled-back subtransaction; leave no synthetic data.
DO $test$
DECLARE a interno.atendimentos%rowtype; p jsonb; profile jsonb; r jsonb; stamp text; original_gmv jsonb;
BEGIN
 BEGIN
  SELECT * INTO a FROM interno.atendimentos WHERE account_id='1' AND situacao='aberto'
    ORDER BY ultima_mensagem_em DESC LIMIT 1;
  IF NOT FOUND THEN RAISE EXCEPTION 'requires_open_attendance'; END IF;
  original_gmv:=a.qualificacao->'declaracoes_chat';
  stamp:=to_char(statement_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"');
  profile:=jsonb_build_object('handle','@synthetic_profile','url','https://www.tiktok.com/@synthetic_profile',
    'origem','chat_declarado','declarado_em',stamp,'mensagem_id','999999999999999997','verificado',false);
  p:=jsonb_build_object('instancia',a.instancia,'account_id',a.account_id,'contact_id',a.contact_id,
    'conversation_id',a.conversation_id,'message_id','999999999999999997',
    'event_id','chatwoot:1:999999999999999997','revision',a.revisao+1,'atendimento_id',a.id,
    'creator_id',a.creator_id,'etapa',a.etapa,'situacao','aberto','observado_em',stamp,
    'ultima_mensagem_em',stamp,'expires_at',to_char((statement_timestamp()+interval '24 hours') AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
    'qualificacao',jsonb_build_object('tiktok_declarado','@synthetic_profile','perfil_tiktok',profile));
  SET LOCAL ROLE service_role;
  r:=public.registrar_contato_v5(p);
  IF (SELECT qualificacao->'perfil_tiktok' FROM interno.atendimentos WHERE id=a.id) IS DISTINCT FROM profile THEN
   RAISE EXCEPTION 'profile_projection_failed'; END IF;
  IF (SELECT qualificacao->'declaracoes_chat' FROM interno.atendimentos WHERE id=a.id) IS DISTINCT FROM original_gmv THEN
   RAISE EXCEPTION 'declarations_changed'; END IF;
  r:=public.registrar_contato_v5(p);
  IF r->>'replayed' IS DISTINCT FROM 'true' THEN RAISE EXCEPTION 'profile_replay_failed'; END IF;
  BEGIN
   PERFORM public.registrar_contato_v5(jsonb_set(p,'{qualificacao,perfil_tiktok,verificado}','true'));
   RAISE EXCEPTION 'false_verification_accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL;
  END;
  BEGIN
   PERFORM public.registrar_contato_v5(jsonb_set(p,'{qualificacao,perfil_tiktok,url}','"https://evil.test"'));
   RAISE EXCEPTION 'invalid_link_accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL;
  END;
  BEGIN
   PERFORM public.registrar_contato_v5(jsonb_set(p,'{qualificacao,perfil_tiktok,origem}','"contexto_anterior"'));
   RAISE EXCEPTION 'invented_prior_evidence_accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL;
  END;
  -- A legacy caller must not erase the profile or the existing declarations.
  p:=p||jsonb_build_object('message_id','999999999999999996','event_id','chatwoot:1:999999999999999996','revision',a.revisao+2,
    'qualificacao',jsonb_build_object('tiktok_declarado','@synthetic_profile'));
  r:=public.registrar_contato_v5(p);
  IF (SELECT qualificacao->'perfil_tiktok' FROM interno.atendimentos WHERE id=a.id) IS DISTINCT FROM profile THEN
   RAISE EXCEPTION 'profile_rollback_protection_failed'; END IF;
  RESET ROLE;
  RAISE EXCEPTION USING ERRCODE='P7777',MESSAGE='rollback_synthetic_profile_test';
 EXCEPTION WHEN SQLSTATE 'P7777' THEN NULL;
 END;
END;
$test$;
