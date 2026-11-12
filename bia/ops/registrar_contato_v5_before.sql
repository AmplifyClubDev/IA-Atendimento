CREATE OR REPLACE FUNCTION public.registrar_contato_v5(p_entrada jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c interno.creators%rowtype; a interno.atendimentos%rowtype; e interno.eventos%rowtype;
 v_creator uuid; v_atendimento uuid; v_revision bigint; v_hash text; v_result jsonb; k text; v_observed timestamptz;
 v_last timestamptz; v_expiry timestamptz; v_source text; v_input jsonb; v_origin jsonb; v_expired jsonb:='[]'; v_closed jsonb:='[]'; v_new_cycle boolean;
 v_compact boolean; v_message_increment bigint:=0;
 v_checks jsonb:='{}'; v_receipt jsonb; v_evidence jsonb; v_qualification jsonb;
 v_key text; v_receipt_at timestamptz; v_agency interno.agenciamentos%rowtype;
 v_previous text:=coalesce(current_setting('app.v5_explicit_event',true),'off');
begin
 if current_user<>'service_role' then raise exception 'service_role_required' using errcode='42501'; end if;
 if jsonb_typeof(p_entrada) is distinct from 'object' or not p_entrada ?& array[
   'instancia','account_id','contact_id','conversation_id','message_id','event_id','revision','etapa','situacao']
   or exists(select 1 from jsonb_object_keys(p_entrada) x where x not in
   ('instancia','account_id','contact_id','conversation_id','message_id','event_id','creator_id','atendimento_id','revision',
    'etapa','situacao','observado_em','ultima_mensagem_em','expires_at','origem','qualificacao','rascunho','whatsapp','modo_identidade','verificacoes_tiktok')) then
  raise exception 'contato_input_invalid' using errcode='22023'; end if;
 foreach k in array array['account_id','contact_id','conversation_id','message_id'] loop
  if jsonb_typeof(p_entrada->k) is distinct from 'string' or p_entrada->>k !~ '^[1-9][0-9]{0,19}$' then
   raise exception 'contato_source_id_invalid' using errcode='22023'; end if;
 end loop;
 if coalesce(p_entrada->>'instancia','') !~ '^[A-Za-z0-9_.:-]{1,80}$'
  or p_entrada->>'event_id' is distinct from 'chatwoot:'||(p_entrada->>'account_id')||':'||(p_entrada->>'message_id')
  or jsonb_typeof(p_entrada->'revision') is distinct from 'number'
  or p_entrada->>'revision' !~ '^[0-9]{1,15}$'
  or coalesce(p_entrada->>'etapa','') !~ '^[a-z_]{1,50}$'
  or p_entrada->>'situacao' not in ('aberto','encerrado','expirado') then
  raise exception 'contato_contract_invalid' using errcode='22023'; end if;
 v_revision:=(p_entrada->>'revision')::bigint;
 v_atendimento:=nullif(p_entrada->>'atendimento_id','')::uuid;
 if (v_atendimento is null and (v_revision<>0 or p_entrada->>'etapa'<>'entrada'))
   or v_atendimento='00000000-0000-0000-0000-000000000000'::uuid then
  raise exception 'contato_cycle_required' using errcode='22023'; end if;
 -- Opt-in identity lookup has no per-message receipt and no journey mutation.
 -- Legacy callers retain their exact payload-hash/replay contract.
 v_compact:=p_entrada ? 'modo_identidade';
 if v_compact and (p_entrada->>'modo_identidade' is distinct from 'consulta'
   or v_revision<>0 or v_atendimento is not null or p_entrada->>'etapa'<>'entrada'
   or p_entrada->>'situacao'<>'aberto'
   or p_entrada ?| array['qualificacao','rascunho','origem','ultima_mensagem_em','expires_at','verificacoes_tiktok']) then
  raise exception 'contato_identity_mode_invalid' using errcode='22023'; end if;
 foreach k in array array['observado_em','ultima_mensagem_em','expires_at'] loop
  if p_entrada->>k is not null and (p_entrada->>k !~ '^\d{4}-\d{2}-\d{2}T.*(Z|[+]00:00)$'
     or not isfinite((p_entrada->>k)::timestamptz)) then raise exception 'contato_clock_invalid' using errcode='22023'; end if;
 end loop;
 v_observed:=(p_entrada->>'observado_em')::timestamptz; v_last:=(p_entrada->>'ultima_mensagem_em')::timestamptz;
 v_expiry:=(p_entrada->>'expires_at')::timestamptz;
 if v_observed>statement_timestamp()+interval '5 minutes' or v_last>statement_timestamp()+interval '5 minutes'
   or (v_expiry is not null and (v_last is null or v_expiry<>v_last+interval '24 hours')) then
  raise exception 'contato_clock_invalid' using errcode='22023'; end if;
 if p_entrada ? 'whatsapp' and p_entrada->>'whatsapp' !~ '^\+?55[1-9][0-9]{9,10}$' then
  raise exception 'contato_phone_invalid' using errcode='22023'; end if;
 if p_entrada ? 'qualificacao' then
  if jsonb_typeof(p_entrada->'qualificacao') is distinct from 'object' then raise exception 'contato_qualification_invalid' using errcode='22023'; end if;
  for k in select jsonb_object_keys(p_entrada->'qualificacao') loop
   if k not in ('interesse_agenciamento','origem_declarada','tiktok_declarado','shop_ativo_declarado',
     'possui_agencia_declarada','consentimento_ensaio','aceite_no_ensaio','consentimento_convite','aceite_declarado') then raise exception 'contato_qualification_invalid' using errcode='22023'; end if;
   if k not in ('origem_declarada','tiktok_declarado') and jsonb_typeof(p_entrada->'qualificacao'->k) not in ('boolean','null') then
    raise exception 'contato_qualification_invalid' using errcode='22023'; end if;
   if k='origem_declarada' and p_entrada->'qualificacao'->k<>'null'::jsonb and
      (jsonb_typeof(p_entrada->'qualificacao'->k)<>'string' or p_entrada->'qualificacao'->>k not in ('anuncio','indicacao','outro','nao_informado')) then
    raise exception 'contato_qualification_invalid' using errcode='22023'; end if;
   if k='tiktok_declarado' and p_entrada->'qualificacao'->k<>'null'::jsonb and
      (jsonb_typeof(p_entrada->'qualificacao'->k)<>'string' or p_entrada->'qualificacao'->>k !~ '^@[A-Za-z0-9_][A-Za-z0-9_.]{1,23}$') then
    raise exception 'contato_qualification_invalid' using errcode='22023'; end if;
  end loop;
 end if;
 if p_entrada ? 'rascunho' then
  if jsonb_typeof(p_entrada->'rascunho') is distinct from 'object' then raise exception 'contato_draft_invalid' using errcode='22023'; end if;
  for k in select jsonb_object_keys(p_entrada->'rascunho') loop
   if k not in ('nome','email','whatsapp','mini_bio','canal_origem','origem_outro','expectativas','meta_renda_mensal','contexto_adicional','plataformas','instagram','plataformas_outros','experiencia_live_shop','agencia_anterior','nome_agencia_anterior','experiencia_agencia','produtos_excluidos','gmv_declarado','inicio_amplify_informado','cpf','nascimento','genero','estado_civil','camiseta','camiseta_outro','estado','cidade','logradouro','bairro','numero','complemento','cep','pix','possui_cnpj','cnpj','nichos','nichos_outros','rotina','rotina_outro','tem_filhos','cabelo','calcado','cor_raca','alimentacao','restricao_alimentar','casa_praia_campo','carro','moto','celular','computador','tripe','microfone','academia','tem_pet','pets','outro_idioma','video_idioma','idiomas','idiomas_outros','mais_2000_seguidores','tiktok') or jsonb_typeof(p_entrada->'rascunho'->k) not in ('string','boolean','number','array','null')
      or octet_length((p_entrada->'rascunho'->k)::text)>10000 then raise exception 'contato_draft_invalid' using errcode='22023'; end if;
   if jsonb_typeof(p_entrada->'rascunho'->k)='array' and
      (jsonb_array_length(p_entrada->'rascunho'->k)>30 or exists(select 1 from jsonb_array_elements(p_entrada->'rascunho'->k) x where jsonb_typeof(x)<>'string')) then
    raise exception 'contato_draft_invalid' using errcode='22023'; end if;
  end loop;
 end if;
 -- Fixed latest operational receipts, not a transcript or a growing event array.
 v_qualification:=coalesce(p_entrada->'qualificacao','{}'::jsonb);
 if p_entrada ? 'verificacoes_tiktok' then
  v_checks:=p_entrada->'verificacoes_tiktok';
  if v_atendimento is null or jsonb_typeof(v_checks) is distinct from 'object'
    or octet_length(v_checks::text)>24000
    or exists(select 1 from jsonb_object_keys(v_checks) x where x not in ('precheck','invite','relationship','lookup','gmv_report')) then
   raise exception 'tiktok_receipts_invalid' using errcode='22023'; end if;
  for k,v_receipt in select key,value from jsonb_each(v_checks) loop
   if jsonb_typeof(v_receipt) is distinct from 'object' or (select count(*) from jsonb_object_keys(v_receipt))<>8
     or not v_receipt ?& array['operation','creator','observed_at','status','confirmed','job_id','cycle_id','evidence']
     or v_receipt->>'operation' is distinct from k
     or v_receipt->>'cycle_id' is distinct from v_atendimento::text
     or coalesce(v_receipt->>'creator','') !~ '^@[a-z0-9_][a-z0-9_.]{1,23}$'
     or v_receipt->>'creator' is distinct from lower(v_qualification->>'tiktok_declarado')
     or jsonb_typeof(v_receipt->'confirmed') is distinct from 'boolean'
     or coalesce(v_receipt->>'job_id','') !~ '^[A-Za-z0-9@_.:-]{1,240}$'
     or coalesce(v_receipt->>'observed_at','') !~ '^\d{4}-\d{2}-\d{2}T.*(Z|[+]00:00)$'
     or jsonb_typeof(v_receipt->'evidence') is distinct from 'object'
     or octet_length((v_receipt->'evidence')::text)>4096 then
    raise exception 'tiktok_receipt_invalid' using errcode='22023'; end if;
   if (k='precheck' and v_receipt->>'status' not in ('eligible','ineligible','verification_pending','failed','outcome_unknown'))
     or (k='relationship' and v_receipt->>'status' not in ('linked','pending','not_found','verification_pending','failed','outcome_unknown'))
     or (k='invite' and v_receipt->>'status' not in ('sent','linked','pending','pending_verification','verification_pending','failed','outcome_unknown','eligible','ineligible'))
     or (k in ('lookup','gmv_report') and v_receipt->>'status' not in ('observed','not_found','verification_pending','failed','outcome_unknown'))
     or v_receipt->>'status' is null then
    raise exception 'tiktok_status_invalid' using errcode='22023'; end if;
   v_evidence:=v_receipt->'evidence';
   for v_key in select jsonb_object_keys(v_evidence) loop
    if v_key not in ('source','relation_id','status','tiktok_status','fresh','complete','shop_account_status','shop_status',
      'post_attempted','http_status','create_accepted','period_and_unit_require_validation','metrics','period_labels',
      'start_date','end_date_exclusive','gmv_observed','gmv_formatted','date_range') then
     raise exception 'tiktok_evidence_invalid' using errcode='22023'; end if;
   end loop;
   if v_receipt->>'status'='linked' and (v_receipt->'confirmed'<>'true'::jsonb
     or v_evidence->>'source' is distinct from 'partner_relations'
     or v_evidence->'fresh' is distinct from 'true'::jsonb or v_evidence->'complete' is distinct from 'true'::jsonb
     or v_evidence->>'status' is distinct from 'vinculado'
     or v_evidence->'tiktok_status' is distinct from '1'::jsonb
     or coalesce(v_evidence->>'relation_id','') !~ '^[A-Za-z0-9_.:-]{1,120}$') then
    raise exception 'tiktok_linkage_proof_invalid' using errcode='22023'; end if;
  end loop;
  v_qualification:=v_qualification||jsonb_build_object('verificacoes_tiktok',v_checks);
 end if;
 v_origin:=p_entrada->'origem';
 if v_origin is not null and (jsonb_typeof(v_origin) is distinct from 'object' or not v_origin ?& array['at','source','reference','value']
   or (select count(*) from jsonb_object_keys(v_origin))<>4
   or v_origin->>'source'<>'declaracao_pessoa' or v_origin->>'value' not in ('anuncio','indicacao','outro')
   or coalesce(v_origin->>'at','') !~ '^\d{4}-\d{2}-\d{2}T.*(Z|[+]00:00)$'
   or not isfinite((v_origin->>'at')::timestamptz) or (v_origin->>'at')::timestamptz>statement_timestamp()+interval '5 minutes'
   or v_origin->>'reference' !~ ('^chatwoot:'||(p_entrada->>'account_id')||':[1-9][0-9]{0,19}$')) then
  raise exception 'contato_origin_invalid' using errcode='22023'; end if;
 -- One short transaction serializes identity assignment and both stages of each message.
 perform pg_advisory_xact_lock(hashtextextended('v5:contato',0));
 v_hash:=encode(sha256(convert_to(p_entrada::text,'UTF8')),'hex');
 if not v_compact then
  select * into e from interno.eventos where instancia=p_entrada->>'instancia' and referencia=p_entrada->>'event_id' and revisao=v_revision;
  if found then
   if e.payload_sha256<>v_hash then raise exception 'contato_replay_conflict' using errcode='23505'; end if;
   return e.resultado||jsonb_build_object('replayed',true);
  end if;
 end if;
 -- A discarded cycle must never be recreated by an old or undated webhook.
 -- Existing exact receipts return above, including their original result.
 if not v_compact and v_atendimento is not null
   and not exists(select 1 from interno.atendimentos where id=v_atendimento)
   and (v_observed is null or v_observed<statement_timestamp()-interval '30 days') then
  raise exception 'contato_new_cycle_source_expired' using errcode='22023'; end if;
 select * into c from interno.creators where origem_instancia=p_entrada->>'instancia'
    and origem_account_id=p_entrada->>'account_id' and origem_contact_id=p_entrada->>'contact_id' for update;
 if found then
  v_creator:=c.id;
  if p_entrada->>'creator_id' is not null and (p_entrada->>'creator_id')::uuid<>v_creator then
   raise exception 'contato_preferred_creator_conflict' using errcode='23505'; end if;
 else
  v_creator:=coalesce((p_entrada->>'creator_id')::uuid,gen_random_uuid());
  if v_creator='00000000-0000-0000-0000-000000000000'::uuid then raise exception 'contato_creator_invalid' using errcode='22023'; end if;
  select * into c from interno.creators where id=v_creator for update;
  if found and c.origem_instancia is not null then raise exception 'contato_creator_bound_elsewhere' using errcode='23505'; end if;
  perform set_config('app.v5_explicit_event','on',true);
  insert into interno.creators(id,origem_instancia,origem_account_id,origem_contact_id,whatsapp,primeira_mensagem_em,canal_entrada,etapa_atual,situacao_atual)
   values(v_creator,p_entrada->>'instancia',p_entrada->>'account_id',p_entrada->>'contact_id',
     replace(p_entrada->>'whatsapp','+',''),v_observed,case when v_observed is not null then 'whatsapp' end,'entrada','em_atendimento')
   on conflict(id) do update set origem_instancia=excluded.origem_instancia,origem_account_id=excluded.origem_account_id,
     origem_contact_id=excluded.origem_contact_id;
 end if;
 perform set_config('app.v5_explicit_event','on',true);
 update interno.creators set primeira_mensagem_em=coalesce(primeira_mensagem_em,v_observed),
   canal_entrada=case when primeira_mensagem_em is null and v_observed is not null then coalesce(canal_entrada,'whatsapp') else canal_entrada end,
   whatsapp=case when cadastro_situacao='pendente' and whatsapp is null then replace(p_entrada->>'whatsapp','+','') else whatsapp end
   where id=v_creator and ((primeira_mensagem_em is null and v_observed is not null)
     or (cadastro_situacao='pendente' and whatsapp is null and p_entrada->>'whatsapp' is not null));
 if v_compact then
  select cadastro_situacao into v_source from interno.creators where id=v_creator;
  perform set_config('app.v5_explicit_event',v_previous,true);
  return jsonb_build_object('creator_id',v_creator,'atendimento_id',null,
    'event_id',p_entrada->>'event_id','revision',0,'replayed',false,'cadastro_situacao',v_source);
 end if;
 if v_atendimento is not null then
  select * into a from interno.atendimentos where id=v_atendimento for update;
  v_new_cycle:=not found;
  -- After the receipt window a closed summary is a watermark, not mutable
  -- input. Kept exact milestone receipts may still replay before this guard.
  if not v_new_cycle and a.situacao<>'aberto'
    and coalesce((a.marcos->>'encerramento')::timestamptz,a.atualizado_em)
        <statement_timestamp()-interval '30 days' then
   raise exception 'contato_cycle_archived' using errcode='23505'; end if;
  if found and (a.creator_id<>v_creator or a.instancia<>p_entrada->>'instancia' or a.account_id<>p_entrada->>'account_id'
    or a.contact_id<>p_entrada->>'contact_id' or a.conversation_id<>p_entrada->>'conversation_id') then
   raise exception 'contato_cycle_identity_conflict' using errcode='23505'; end if;
  if found and v_revision<=a.revisao then raise exception 'contato_stale_revision' using errcode='23505'; end if;
  if found and ((a.situacao<>'aberto' and p_entrada->>'situacao'='aberto')
    or (a.ultima_mensagem_em is not null and v_last is not null and v_last<a.ultima_mensagem_em)
    or (a.expires_at is not null and v_expiry is not null and v_expiry<a.expires_at)) then
   raise exception 'contato_terminal_or_clock_regression' using errcode='23505'; end if;
  -- Replay returned above before age checks; fresh mutations stay in their cycle.
  for k,v_receipt in select key,value from jsonb_each(v_checks) loop
   v_receipt_at:=(v_receipt->>'observed_at')::timestamptz;
   if not isfinite(v_receipt_at) or v_receipt_at>statement_timestamp()+interval '5 minutes'
     or v_receipt_at<coalesce(a.primeira_mensagem_em,v_observed,statement_timestamp())
     or (p_entrada->>'situacao'='aberto' and v_expiry<=statement_timestamp()) then
    raise exception 'tiktok_receipt_clock_invalid' using errcode='22023'; end if;
  end loop;
  if v_new_cycle and exists(select 1 from interno.atendimentos prior
   where prior.id<>v_atendimento and prior.creator_id=v_creator and prior.instancia=p_entrada->>'instancia'
    and prior.account_id=p_entrada->>'account_id' and prior.contact_id=p_entrada->>'contact_id'
    and prior.conversation_id=p_entrada->>'conversation_id' and prior.situacao='aberto'
    and (prior.expires_at is null or prior.expires_at>coalesce(v_last,statement_timestamp()))
    and (v_last is null or prior.ultima_mensagem_em>v_last or v_revision<=prior.revisao)) then
   raise exception 'contato_new_cycle_stale' using errcode='23505';end if;
  with changed as (update interno.atendimentos set situacao='expirado',motivo_encerramento='24h_sem_mensagem'
   where id<>v_atendimento and instancia=p_entrada->>'instancia' and account_id=p_entrada->>'account_id'
   and contact_id=p_entrada->>'contact_id' and conversation_id=p_entrada->>'conversation_id' and situacao='aberto'
   and expires_at<=coalesce(v_last,statement_timestamp()) returning id)
   select coalesce(jsonb_agg(id),'[]') into v_expired from changed;
  if v_new_cycle then
   with changed as (update interno.atendimentos set situacao='encerrado',motivo_encerramento='novo_ciclo_solicitado'
    where id<>v_atendimento and creator_id=v_creator and instancia=p_entrada->>'instancia'
     and account_id=p_entrada->>'account_id' and contact_id=p_entrada->>'contact_id'
     and conversation_id=p_entrada->>'conversation_id' and situacao='aberto'
     and (expires_at is null or expires_at>coalesce(v_last,statement_timestamp()))
    returning id)
    select coalesce(jsonb_agg(id),'[]') into v_closed from changed;
  end if;

  select case when exists(select 1 from interno.eventos prior_event
   where prior_event.instancia=p_entrada->>'instancia' and prior_event.referencia=p_entrada->>'event_id'
     and prior_event.atendimento_id=v_atendimento and prior_event.tipo='atendimento_atualizado')
   then 0 else 1 end into v_message_increment;
  insert into interno.atendimentos(id,creator_id,instancia,account_id,contact_id,conversation_id,revisao,etapa,situacao,
   primeira_mensagem_em,ultima_mensagem_em,expires_at,qualificacao,rascunho,origem,mensagens_recebidas)
  values(v_atendimento,v_creator,p_entrada->>'instancia',p_entrada->>'account_id',p_entrada->>'contact_id',p_entrada->>'conversation_id',
   v_revision,p_entrada->>'etapa',p_entrada->>'situacao',v_observed,v_last,v_expiry,
   v_qualification,coalesce(p_entrada->'rascunho','{}'),v_origin,v_message_increment)
  on conflict(id) do update set revisao=excluded.revisao,etapa=excluded.etapa,situacao=excluded.situacao,
    mensagens_recebidas=atendimentos.mensagens_recebidas+excluded.mensagens_recebidas,
    ultima_mensagem_em=coalesce(excluded.ultima_mensagem_em,atendimentos.ultima_mensagem_em),
    expires_at=coalesce(excluded.expires_at,atendimentos.expires_at),
    qualificacao=excluded.qualificacao,rascunho=atendimentos.rascunho||excluded.rascunho,origem=coalesce(atendimentos.origem,excluded.origem);
  -- Only a fresh exact-profile relationship observation can register agency.
  -- Pending/missing/partial reads never close or create an agency record.
  v_receipt:=v_checks->'relationship';
  if v_receipt->>'status'='linked' and v_receipt->'confirmed'='true'::jsonb then
   v_receipt_at:=(v_receipt->>'observed_at')::timestamptz;
   if statement_timestamp()-v_receipt_at>interval '24 hours' then
    raise exception 'tiktok_linkage_proof_expired' using errcode='22023'; end if;
   select * into v_agency from interno.agenciamentos where creator_id=v_creator and situacao='confirmado' for update;
   if found and v_agency.tiktok_observado is not null
     and lower(ltrim(v_agency.tiktok_observado,'@'))<>ltrim(v_receipt->>'creator','@') then
    raise exception 'tiktok_existing_linkage_profile_conflict' using errcode='23505'; end if;
   if found then
    update interno.agenciamentos set verificado_em=greatest(verificado_em,v_receipt_at),
      tiktok_observado=coalesce(tiktok_observado,v_receipt->>'creator') where id=v_agency.id;
   else
    insert into interno.agenciamentos(creator_id,fonte,confirmado_em,verificado_em,confirmacao_referencia,tiktok_observado,conta_referencia,situacao)
     values(v_creator,'tiktok_partner_center',v_receipt_at,v_receipt_at,
       v_receipt->>'job_id',v_receipt->>'creator','chatwoot:'||(p_entrada->>'account_id'),'confirmado');
   end if;
   update interno.creators set tiktok=ltrim(v_receipt->>'creator','@')
    where id=v_creator and cadastro_situacao='pendente' and tiktok is null;
  end if;
  update interno.creators set etapa_atual=p_entrada->>'etapa',
    situacao_atual=case p_entrada->>'situacao' when 'aberto' then 'em_atendimento' when 'encerrado' then 'atendimento_encerrado' else 'atendimento_expirado' end
   where id=v_creator and cadastro_situacao='pendente' and (v_last is null or not exists(
    select 1 from interno.atendimentos other where other.creator_id=v_creator and other.id<>v_atendimento and other.ultima_mensagem_em>v_last));
 end if;
 select cadastro_situacao into v_source from interno.creators where id=v_creator;
 v_result:=jsonb_build_object('creator_id',v_creator,'atendimento_id',v_atendimento,'event_id',p_entrada->>'event_id',
    'revision',v_revision,'replayed',false,'cadastro_situacao',v_source);
 insert into interno.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,payload_sha256,dados,resultado)
  values(v_creator,v_atendimento,case when v_atendimento is null then 'contato_recebido' else 'atendimento_atualizado' end,
   p_entrada->>'instancia',p_entrada->>'event_id',v_revision,v_observed,v_hash,
   jsonb_build_object('etapa',p_entrada->>'etapa','situacao',p_entrada->>'situacao','atendimentos_expirados',v_expired,'atendimentos_encerrados',v_closed),v_result);
 perform set_config('app.v5_explicit_event',v_previous,true);
 return v_result;
end;
$function$

