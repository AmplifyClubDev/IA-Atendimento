BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
DO $guard$
BEGIN
 IF current_user<>'postgres' THEN RAISE EXCEPTION 'summary_migration_requires_postgres'; END IF;
 IF md5(pg_get_functiondef('public.registrar_contato_v5(jsonb)'::regprocedure))<>'322adbe32bc3f36162ec2a87c44e6ee9'
  OR md5(pg_get_viewdef('public.atendimentos'::regclass,true))<>'3d282d03cf36e24b8219e520ec23511c'
  THEN RAISE EXCEPTION 'summary_baseline_changed'; END IF;
 IF EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid='interno.atendimentos'::regclass
  AND attname IN ('mensagens_recebidas','resumo','proximo_passo','marcos') AND NOT attisdropped)
  THEN RAISE EXCEPTION 'summary_already_present'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='interno.atendimentos'::regclass AND tgname='v5_10_datas' AND tgenabled='O')
  THEN RAISE EXCEPTION 'summary_dates_trigger_changed'; END IF;
END;
$guard$;
-- Schema lock is held until COMMIT; snapshot excludes no pre-existing business field.
LOCK TABLE interno.atendimentos IN ACCESS EXCLUSIVE MODE;
CREATE TEMP TABLE v5_summary_before ON COMMIT DROP AS
 SELECT 'atendimentos'::text AS tabela,id::text,md5(to_jsonb(x)::text) AS fingerprint FROM interno.atendimentos x
 UNION ALL SELECT 'creators',id::text,md5(to_jsonb(x)::text) FROM interno.creators x
 UNION ALL SELECT 'eventos',id::text,md5(to_jsonb(x)::text) FROM interno.eventos x
 UNION ALL SELECT 'agenciamentos',id::text,md5(to_jsonb(x)::text) FROM interno.agenciamentos x
 UNION ALL SELECT 'gmv',id::text,md5(to_jsonb(x)::text) FROM interno.gmv x;
ALTER TABLE interno.atendimentos
 ADD COLUMN mensagens_recebidas bigint NOT NULL DEFAULT 0 CHECK(mensagens_recebidas>=0),
 ADD COLUMN resumo text,
 ADD COLUMN proximo_passo text,
 ADD COLUMN marcos jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(marcos)='object'
  AND marcos-ARRAY['conhecer','qualificacao','validacao','convite','cadastro','encerramento']='{}'::jsonb);
-- Backfill derives only observed receipts. Unknown historical stage dates stay absent.
-- Disable this one date trigger inside the locked transaction, preserving original timestamps.
ALTER TABLE interno.atendimentos DISABLE TRIGGER v5_10_datas;
UPDATE interno.atendimentos a SET mensagens_recebidas=(SELECT count(DISTINCT e.referencia) FROM interno.eventos e
 WHERE e.atendimento_id=a.id AND e.tipo='atendimento_atualizado'),
 marcos=coalesce((SELECT jsonb_object_agg(x.etapa,x.data) FROM (
  SELECT q.etapa,min(q.data) AS data FROM (
   SELECT CASE e.dados->>'etapa'
    WHEN 'entrada' THEN 'conhecer' WHEN 'intro' THEN 'conhecer' WHEN 'menu' THEN 'conhecer' WHEN 'know' THEN 'conhecer'
    WHEN 'origin' THEN 'qualificacao' WHEN 'tiktok' THEN 'qualificacao' WHEN 'shop' THEN 'qualificacao' WHEN 'agency' THEN 'qualificacao'
    WHEN 'consent' THEN 'validacao' WHEN 'await_acceptance' THEN 'convite'
    WHEN 'form' THEN 'cadastro' WHEN 'cadastro_confirmado' THEN 'cadastro' END AS etapa,
    e.ocorrido_em AS data FROM interno.eventos e WHERE e.atendimento_id=a.id AND e.tipo='atendimento_atualizado'
   UNION ALL SELECT 'encerramento',e.ocorrido_em FROM interno.eventos e
    WHERE e.atendimento_id=a.id AND e.tipo='atendimento_atualizado' AND e.dados->>'situacao' IN ('encerrado','expirado')
  ) q WHERE q.etapa IS NOT NULL AND q.data IS NOT NULL GROUP BY q.etapa
 ) x),'{}'::jsonb);
ALTER TABLE interno.atendimentos ENABLE TRIGGER v5_10_datas;
ALTER TABLE interno.atendimentos DISABLE TRIGGER v5_10_datas;
UPDATE interno.atendimentos a SET resumo=CASE
  WHEN a.etapa='cadastro_confirmado' THEN 'Cadastro recebido e atendimento encerrado.'
  WHEN a.situacao='expirado' THEN 'Atendimento encerrado por falta de resposta.'
  WHEN a.situacao='encerrado' THEN 'Atendimento encerrado nesta etapa.'
  WHEN a.etapa IN ('entrada','intro','menu','know') THEN 'Conhecendo a Amplify.'
  WHEN a.etapa IN ('origin','tiktok','shop','agency') THEN 'Qualificação em andamento.'
  WHEN a.etapa='consent' THEN 'Aguardando autorização para validar o perfil.'
  WHEN a.etapa='await_acceptance' THEN 'Aguardando informação sobre o aceite do convite.'
  WHEN a.etapa='form' THEN 'Formulário de cadastro pendente.'
  ELSE 'Atendimento em andamento.' END,
 proximo_passo=CASE
  WHEN a.etapa='cadastro_confirmado' THEN 'Conferir a entrega de acessos.'
  WHEN a.situacao<>'aberto' THEN 'Aguardar novo contato.'
  WHEN a.etapa IN ('entrada','intro','menu','know') THEN 'Entender o interesse da pessoa.'
  WHEN a.etapa='origin' THEN 'Identificar como conheceu a Amplify.'
  WHEN a.etapa='tiktok' THEN 'Receber o @ do TikTok.'
  WHEN a.etapa='shop' THEN 'Confirmar se o TikTok Shop está ativo.'
  WHEN a.etapa='agency' THEN 'Confirmar se possui agência.'
  WHEN a.etapa='consent' THEN 'Confirmar a autorização da pessoa.'
  WHEN a.etapa='await_acceptance' THEN 'Confirmar o vínculo antes do cadastro.'
  WHEN a.etapa='form' THEN 'Preencher e confirmar o formulário.'
  ELSE 'Conferir a pendência da etapa.' END;
ALTER TABLE interno.atendimentos ENABLE TRIGGER v5_10_datas;

CREATE OR REPLACE FUNCTION interno.atendimento_resumir()
RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $resumo$
DECLARE v_stage text; v_at timestamptz;
BEGIN
 -- Fixed keys, one first-entry timestamp per business stage; never message arrays.
 IF TG_OP='UPDATE' THEN NEW.marcos:=OLD.marcos;
 ELSE NEW.marcos:='{}'::jsonb; END IF;
 v_stage:=CASE NEW.etapa
  WHEN 'entrada' THEN 'conhecer' WHEN 'intro' THEN 'conhecer' WHEN 'menu' THEN 'conhecer' WHEN 'know' THEN 'conhecer'
  WHEN 'origin' THEN 'qualificacao' WHEN 'tiktok' THEN 'qualificacao' WHEN 'shop' THEN 'qualificacao' WHEN 'agency' THEN 'qualificacao'
  WHEN 'consent' THEN 'validacao' WHEN 'await_acceptance' THEN 'convite'
  WHEN 'form' THEN 'cadastro' WHEN 'cadastro_confirmado' THEN 'cadastro' END;
 IF TG_OP='INSERT' THEN v_at:=coalesce(NEW.primeira_mensagem_em,statement_timestamp());
 ELSE v_at:=statement_timestamp(); END IF;
 IF v_stage IS NOT NULL AND NOT NEW.marcos ? v_stage THEN
  NEW.marcos:=NEW.marcos||jsonb_build_object(v_stage,v_at); END IF;
 IF NEW.situacao<>'aberto' AND NOT NEW.marcos ? 'encerramento' THEN
  NEW.marcos:=NEW.marcos||jsonb_build_object('encerramento',statement_timestamp()); END IF;
 NEW.resumo:=CASE
  WHEN NEW.etapa='cadastro_confirmado' THEN 'Cadastro recebido e atendimento encerrado.'
  WHEN NEW.situacao='expirado' THEN 'Atendimento encerrado por falta de resposta.'
  WHEN NEW.situacao='encerrado' THEN 'Atendimento encerrado nesta etapa.'
  WHEN NEW.etapa IN ('entrada','intro','menu','know') THEN 'Conhecendo a Amplify.'
  WHEN NEW.etapa IN ('origin','tiktok','shop','agency') THEN 'Qualificação em andamento.'
  WHEN NEW.etapa='consent' THEN 'Aguardando autorização para validar o perfil.'
  WHEN NEW.etapa='await_acceptance' THEN 'Aguardando informação sobre o aceite do convite.'
  WHEN NEW.etapa='form' THEN 'Formulário de cadastro pendente.'
  ELSE 'Atendimento em andamento.' END;
 NEW.proximo_passo:=CASE
  WHEN NEW.etapa='cadastro_confirmado' THEN 'Conferir a entrega de acessos.'
  WHEN NEW.situacao<>'aberto' THEN 'Aguardar novo contato.'
  WHEN NEW.etapa IN ('entrada','intro','menu','know') THEN 'Entender o interesse da pessoa.'
  WHEN NEW.etapa='origin' THEN 'Identificar como conheceu a Amplify.'
  WHEN NEW.etapa='tiktok' THEN 'Receber o @ do TikTok.'
  WHEN NEW.etapa='shop' THEN 'Confirmar se o TikTok Shop está ativo.'
  WHEN NEW.etapa='agency' THEN 'Confirmar se possui agência.'
  WHEN NEW.etapa='consent' THEN 'Confirmar a autorização da pessoa.'
  WHEN NEW.etapa='await_acceptance' THEN 'Confirmar o vínculo antes do cadastro.'
  WHEN NEW.etapa='form' THEN 'Preencher e confirmar o formulário.'
  ELSE 'Conferir a pendência da etapa.' END;
 RETURN NEW;
END;
$resumo$;
REVOKE ALL ON FUNCTION interno.atendimento_resumir() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION interno.atendimento_resumir() TO service_role;
CREATE OR REPLACE FUNCTION public.registrar_contato_v5(p_entrada jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c interno.creators%rowtype; a interno.atendimentos%rowtype; e interno.eventos%rowtype;
 v_creator uuid; v_atendimento uuid; v_revision bigint; v_hash text; v_result jsonb; k text; v_observed timestamptz;
 v_last timestamptz; v_expiry timestamptz; v_source text; v_input jsonb; v_origin jsonb; v_expired jsonb:='[]'; v_closed jsonb:='[]'; v_new_cycle boolean;
 v_compact boolean; v_message_increment bigint:=0;
 v_previous text:=coalesce(current_setting('app.v5_explicit_event',true),'off');
begin
 if current_user<>'service_role' then raise exception 'service_role_required' using errcode='42501'; end if;
 if jsonb_typeof(p_entrada) is distinct from 'object' or not p_entrada ?& array[
   'instancia','account_id','contact_id','conversation_id','message_id','event_id','revision','etapa','situacao']
   or exists(select 1 from jsonb_object_keys(p_entrada) x where x not in
   ('instancia','account_id','contact_id','conversation_id','message_id','event_id','creator_id','atendimento_id','revision',
    'etapa','situacao','observado_em','ultima_mensagem_em','expires_at','origem','qualificacao','rascunho','whatsapp','modo_identidade')) then
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
   or p_entrada ?| array['qualificacao','rascunho','origem','ultima_mensagem_em','expires_at']) then
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
     'possui_agencia_declarada','consentimento_ensaio','aceite_no_ensaio') then raise exception 'contato_qualification_invalid' using errcode='22023'; end if;
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
  if found and (a.creator_id<>v_creator or a.instancia<>p_entrada->>'instancia' or a.account_id<>p_entrada->>'account_id'
    or a.contact_id<>p_entrada->>'contact_id' or a.conversation_id<>p_entrada->>'conversation_id') then
   raise exception 'contato_cycle_identity_conflict' using errcode='23505'; end if;
  if found and v_revision<=a.revisao then raise exception 'contato_stale_revision' using errcode='23505'; end if;
  if found and ((a.situacao<>'aberto' and p_entrada->>'situacao'='aberto')
    or (a.ultima_mensagem_em is not null and v_last is not null and v_last<a.ultima_mensagem_em)
    or (a.expires_at is not null and v_expiry is not null and v_expiry<a.expires_at)) then
   raise exception 'contato_terminal_or_clock_regression' using errcode='23505'; end if;
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
   coalesce(p_entrada->'qualificacao','{}'),coalesce(p_entrada->'rascunho','{}'),v_origin,v_message_increment)
  on conflict(id) do update set revisao=excluded.revisao,etapa=excluded.etapa,situacao=excluded.situacao,
    mensagens_recebidas=atendimentos.mensagens_recebidas+excluded.mensagens_recebidas,
    ultima_mensagem_em=coalesce(excluded.ultima_mensagem_em,atendimentos.ultima_mensagem_em),
    expires_at=coalesce(excluded.expires_at,atendimentos.expires_at),
    qualificacao=excluded.qualificacao,rascunho=atendimentos.rascunho||excluded.rascunho,origem=coalesce(atendimentos.origem,excluded.origem);
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
$function$;
CREATE OR REPLACE VIEW public.atendimentos WITH (security_invoker=true) AS
SELECT a.id,
    a.creator_id,
    c.nome,
    c.tiktok,
        CASE a.etapa
            WHEN 'entrada'::text THEN 'Entrada'::text
            WHEN 'intro'::text THEN 'Apresentação'::text
            WHEN 'menu'::text THEN 'Início'::text
            WHEN 'know'::text THEN 'Conhecer a Amplify'::text
            WHEN 'origin'::text THEN 'Origem'::text
            WHEN 'tiktok'::text THEN 'Perfil do TikTok'::text
            WHEN 'shop'::text THEN 'TikTok Shop'::text
            WHEN 'agency'::text THEN 'Agenciamento'::text
            WHEN 'consent'::text THEN 'Validação'::text
            WHEN 'await_acceptance'::text THEN 'Aceite do convite'::text
            WHEN 'form'::text THEN 'Formulário'::text
            WHEN 'cadastro_confirmado'::text THEN 'Cadastro'::text
            WHEN 'closed'::text THEN 'Encerramento'::text
            ELSE 'A confirmar'::text
        END AS etapa,
        CASE
            WHEN a.situacao = 'aberto'::text AND a.expires_at <= statement_timestamp() THEN 'Prazo encerrado'::text
            WHEN a.situacao = 'aberto'::text THEN 'Em atendimento'::text
            WHEN a.situacao = 'encerrado'::text THEN 'Encerrado'::text
            WHEN a.situacao = 'expirado'::text THEN 'Prazo encerrado'::text
            ELSE 'A confirmar'::text
        END AS situacao,
    a.primeira_mensagem_em AS inicio_em,
    a.ultima_mensagem_em,
    a.expires_at AS prazo_em,
        CASE a.motivo_encerramento
            WHEN '24h_sem_mensagem'::text THEN '24 horas sem mensagem'::text
            ELSE initcap(replace(a.motivo_encerramento, '_'::text, ' '::text))
        END AS encerramento,
        CASE COALESCE(a.origem ->> 'value'::text, a.qualificacao ->> 'origem_declarada'::text)
            WHEN 'anuncio'::text THEN 'Anúncio'::text
            WHEN 'indicacao'::text THEN 'Indicação'::text
            WHEN 'outro'::text THEN 'Outro'::text
            WHEN 'nao_informado'::text THEN 'Não informado'::text
            ELSE COALESCE(NULLIF(COALESCE(a.origem ->> 'value'::text, a.qualificacao ->> 'origem_declarada'::text), ''::text), 'Não informado'::text)
        END AS origem,
    a.atualizado_em,
    a.mensagens_recebidas AS mensagens,
    CASE WHEN a.situacao='aberto' AND a.expires_at<=statement_timestamp() THEN 'Prazo encerrado sem nova mensagem.' ELSE a.resumo END AS resumo,
    CASE WHEN a.situacao='aberto' AND a.expires_at<=statement_timestamp() THEN 'Aguardar novo contato.' ELSE a.proximo_passo END AS proximo_passo
   FROM interno.atendimentos a
     JOIN interno.creators c ON c.id = a.creator_id;

CREATE TRIGGER v5_05_resumo BEFORE INSERT OR UPDATE ON interno.atendimentos
 FOR EACH ROW EXECUTE FUNCTION interno.atendimento_resumir();
COMMENT ON COLUMN interno.atendimentos.mensagens_recebidas IS 'Quantidade de mensagens distintas com processamento final confirmado; mensagens no Chatwoot não processadas não são inventadas. Replay não incrementa.';
COMMENT ON COLUMN interno.atendimentos.marcos IS 'Primeiro ingresso observado em até seis marcos fixos. Não contém mensagens. Datas anteriores desconhecidas permanecem ausentes.';
COMMENT ON COLUMN interno.atendimentos.resumo IS 'Resumo curto calculado pela etapa, sem transcrição nem geração por IA.';
COMMENT ON COLUMN interno.atendimentos.proximo_passo IS 'Próxima pendência calculada pela etapa. Não executa nem comprova efeitos externos.';
DO $preserve$
BEGIN
 IF EXISTS(SELECT 1 FROM v5_summary_before b FULL JOIN (
 SELECT 'atendimentos'::text AS tabela,id::text,md5((to_jsonb(x)-ARRAY['mensagens_recebidas','resumo','proximo_passo','marcos'])::text) AS fingerprint FROM interno.atendimentos x
 UNION ALL SELECT 'creators',id::text,md5(to_jsonb(x)::text) FROM interno.creators x
 UNION ALL SELECT 'eventos',id::text,md5(to_jsonb(x)::text) FROM interno.eventos x
 UNION ALL SELECT 'agenciamentos',id::text,md5(to_jsonb(x)::text) FROM interno.agenciamentos x
 UNION ALL SELECT 'gmv',id::text,md5(to_jsonb(x)::text) FROM interno.gmv x) a USING(tabela,id)
 WHERE b.id IS NULL OR a.id IS NULL OR b.fingerprint IS DISTINCT FROM a.fingerprint)
 THEN RAISE EXCEPTION 'summary_existing_data_changed'; END IF;
 IF EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='interno.atendimentos'::regclass AND tgname='v5_10_datas' AND tgenabled<>'O')
 THEN RAISE EXCEPTION 'summary_dates_trigger_not_restored'; END IF;
END;
$preserve$;
NOTIFY pgrst,'reload schema';
COMMIT;
