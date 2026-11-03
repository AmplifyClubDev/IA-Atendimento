BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
CREATE OR REPLACE FUNCTION public.registrar_contato_v5(p_entrada jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare c interno.creators%rowtype; a interno.atendimentos%rowtype; e interno.eventos%rowtype;
 v_creator uuid; v_atendimento uuid; v_revision bigint; v_hash text; v_result jsonb; k text; v_observed timestamptz;
 v_last timestamptz; v_expiry timestamptz; v_source text; v_input jsonb; v_origin jsonb; v_expired jsonb:='[]'; v_closed jsonb:='[]'; v_new_cycle boolean;
 v_previous text:=coalesce(current_setting('app.v5_explicit_event',true),'off');
begin
 if current_user<>'service_role' then raise exception 'service_role_required' using errcode='42501'; end if;
 if jsonb_typeof(p_entrada) is distinct from 'object' or not p_entrada ?& array[
   'instancia','account_id','contact_id','conversation_id','message_id','event_id','revision','etapa','situacao']
   or exists(select 1 from jsonb_object_keys(p_entrada) x where x not in
   ('instancia','account_id','contact_id','conversation_id','message_id','event_id','creator_id','atendimento_id','revision',
    'etapa','situacao','observado_em','ultima_mensagem_em','expires_at','origem','qualificacao','rascunho','whatsapp')) then
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
 select * into e from interno.eventos where instancia=p_entrada->>'instancia' and referencia=p_entrada->>'event_id' and revisao=v_revision;
 if found then
  if e.payload_sha256<>v_hash then raise exception 'contato_replay_conflict' using errcode='23505'; end if;
  return e.resultado||jsonb_build_object('replayed',true);
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
   where id=v_creator;
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

  insert into interno.atendimentos(id,creator_id,instancia,account_id,contact_id,conversation_id,revisao,etapa,situacao,
   primeira_mensagem_em,ultima_mensagem_em,expires_at,qualificacao,rascunho,origem)
  values(v_atendimento,v_creator,p_entrada->>'instancia',p_entrada->>'account_id',p_entrada->>'contact_id',p_entrada->>'conversation_id',
   v_revision,p_entrada->>'etapa',p_entrada->>'situacao',v_observed,v_last,v_expiry,
   coalesce(p_entrada->'qualificacao','{}'),coalesce(p_entrada->'rascunho','{}'),v_origin)
  on conflict(id) do update set revisao=excluded.revisao,etapa=excluded.etapa,situacao=excluded.situacao,
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
$function$
;
CREATE OR REPLACE VIEW public.eventos WITH (security_invoker=true) AS
WITH etapas AS (
 SELECT e.id,
 row_number() over (partition by e.creator_id,e.atendimento_id order by e.revisao,e.id) AS ordem,
 lag(jsonb_build_array(e.dados->>'etapa',e.dados->>'situacao'))
  over (partition by e.creator_id,e.atendimento_id order by e.revisao,e.id) AS anterior
 FROM interno.eventos e WHERE e.tipo='atendimento_atualizado'
), marcos AS (
 SELECT e.*, s.ordem, case e.dados->>'etapa'
 when 'entrada' then 'Entrada' when 'intro' then 'Apresentação' when 'menu' then 'Início'
 when 'know' then 'Conhecer a Amplify' when 'origin' then 'Origem'
 when 'tiktok' then 'Perfil do TikTok' when 'shop' then 'TikTok Shop'
 when 'agency' then 'Agenciamento' when 'await_acceptance' then 'Aceite do convite'
 when 'form' then 'Formulário' when 'cadastro_confirmado' then 'Cadastro'
 when 'closed' then 'Encerramento' else 'A confirmar' end AS nome_etapa
 FROM interno.eventos e LEFT JOIN etapas s ON s.id=e.id
 WHERE (e.tipo<>'contato_recebido' OR NOT EXISTS(
  SELECT 1 FROM interno.eventos p WHERE p.tipo='atendimento_atualizado'
   AND p.instancia=e.instancia AND p.referencia=e.referencia AND p.creator_id=e.creator_id))
 AND (e.tipo<>'atendimento_atualizado' OR s.ordem=1
  OR jsonb_build_array(e.dados->>'etapa',e.dados->>'situacao') IS DISTINCT FROM s.anterior)
)
SELECT e.id, e.creator_id, coalesce(e.ocorrido_em,e.registrado_em) AS data,
 case
 when e.tipo='atendimento_atualizado' then case
  when e.dados->>'situacao'='expirado' then 'Atendimento expirado'
  when e.dados->>'situacao'='encerrado' then 'Atendimento encerrado'
  when e.ordem=1 and jsonb_array_length(case when jsonb_typeof(e.dados->'atendimentos_encerrados')='array' then e.dados->'atendimentos_encerrados' else '[]'::jsonb end)>0 then 'Atendimento reiniciado'
  when e.ordem=1 then 'Atendimento registrado' else 'Etapa atualizada' end
 when e.tipo in ('registro_criado','registro_alterado') then case e.dados->>'tabela'
  when 'creators' then 'Ficha atualizada' when 'gmv' then 'GMV atualizado'
  when 'agenciamentos' then 'Agenciamento atualizado' when 'atendimentos' then 'Atendimento atualizado'
  else 'Dados atualizados' end
 when e.tipo='contato_recebido' then 'Mensagem recebida'
 when e.tipo='cadastro_confirmado_ensaio' then 'Cadastro confirmado no teste'
 when e.tipo='cadastro_confirmado' then 'Cadastro confirmado'
 when e.tipo='agenciamento_confirmado' then 'Agenciamento confirmado'
 when e.tipo='agenciamento_encerrado' then 'Agenciamento encerrado'
 when e.tipo='renovacao_contrato' then 'Contrato renovado'
 when e.tipo='gmv_atualizado' then 'GMV atualizado'
 when e.tipo='conferencia_mensal' then 'Conferência mensal'
 when e.tipo='convite_solicitado' then 'Convite solicitado'
 when e.tipo='convite_enviado' then 'Convite enviado'
 when e.tipo='aceite_informado' then 'Aceite informado'
 when e.tipo='convite_a_confirmar' then 'Convite pendente'
 when e.tipo='acesso_solicitado' then 'Acesso solicitado'
 when e.tipo='acesso_entregue' then 'Acesso entregue'
 when e.tipo='email_aceito_provedor' then 'E-mail aceito para envio'
 when e.tipo='email_entregue' then 'E-mail entregue'
 when e.tipo='email_falha' then 'Falha no e-mail'
 when e.tipo='cadastro_alteracao_confirmada' then 'Alteração confirmada'
 else 'Registro de acompanhamento' end AS evento,
 case
 when e.tipo in ('contato_recebido','atendimento_atualizado') then e.nome_etapa
 when e.tipo like 'cadastro_%' OR e.dados->>'tabela'='creators' then 'Cadastro'
 when e.tipo like 'agenciamento_%' OR e.tipo like 'convite_%' OR e.tipo='aceite_informado' OR e.dados->>'tabela'='agenciamentos' then 'Agenciamento'
 when e.tipo like 'gmv_%' OR e.dados->>'tabela'='gmv' then 'GMV'
 when e.tipo like 'acesso_%' then 'Acessos'
 when e.tipo like 'email_%' then 'E-mail'
 when e.tipo='renovacao_contrato' then 'Contrato'
 when e.tipo='conferencia_mensal' then 'Conferência'
 else 'Acompanhamento' end AS etapa,
 case
 when e.tipo='atendimento_atualizado' then case e.dados->>'situacao'
  when 'expirado' then 'Prazo deste atendimento encerrado.'
  when 'encerrado' then 'Este atendimento foi encerrado.'
  else 'Etapa atual: '||e.nome_etapa||'.' end
 when e.tipo in ('registro_criado','registro_alterado') then case e.dados->>'tabela'
  when 'creators' then 'Dados da ficha atualizados.' when 'gmv' then 'Histórico de GMV atualizado.'
  when 'agenciamentos' then 'Dados do agenciamento atualizados.' when 'atendimentos' then 'Dados do atendimento atualizados.'
  else 'Dados de acompanhamento atualizados.' end
 when e.tipo='contato_recebido' then 'Mensagem recebida. A atualização da etapa ainda está pendente.'
 when e.tipo='cadastro_confirmado_ensaio' then 'Formulário recebido e cadastro confirmado no teste.'
 when e.tipo='cadastro_confirmado' then 'Formulário recebido e cadastro confirmado.'
 when e.tipo='agenciamento_confirmado' then 'Vínculo de agenciamento confirmado.'
 when e.tipo='agenciamento_encerrado' then 'Vínculo de agenciamento encerrado.'
 when e.tipo='renovacao_contrato' then 'Renovação do contrato registrada.'
 when e.tipo='gmv_atualizado' then 'Valor de GMV registrado no histórico.'
 when e.tipo='conferencia_mensal' then 'Conferência do mês registrada.'
 when e.tipo='convite_solicitado' then 'Envio do convite solicitado.'
 when e.tipo='convite_enviado' then 'Envio do convite registrado.'
 when e.tipo='aceite_informado' then 'A pessoa informou o aceite. A confirmação do vínculo é uma etapa separada.'
 when e.tipo='convite_a_confirmar' then 'Convite aguardando confirmação.'
 when e.tipo='acesso_solicitado' then 'Criação ou atualização do acesso solicitada.'
 when e.tipo='acesso_entregue' then 'Entrega do acesso registrada.'
 when e.tipo='email_aceito_provedor' then 'O serviço de e-mail aceitou o envio. Isso ainda não confirma a entrega.'
 when e.tipo='email_entregue' then 'Entrega do e-mail confirmada.'
 when e.tipo='email_falha' then 'Falha registrada no processo de envio do e-mail.'
 when e.tipo='cadastro_alteracao_confirmada' then 'Alteração dos dados confirmada pela pessoa.'
 else 'Registro de acompanhamento.' end AS resumo,
 e.atendimento_id
FROM marcos e;
REVOKE ALL ON public.eventos FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.eventos TO service_role;
COMMENT ON VIEW public.eventos IS 'Linha do tempo para consulta: somente marcos e mudanças de etapa, com nomes simples. Os comprovantes técnicos permanecem em interno.eventos, sem duplicar dados.';
COMMENT ON COLUMN public.eventos.creator_id IS 'ID permanente da pessoa; o mesmo de creators.id.';
COMMENT ON COLUMN public.eventos.data IS 'Data do acontecimento; na ausência, data de registro. O fuso é definido na consulta.';
COMMENT ON COLUMN public.eventos.evento IS 'Nome simples do acontecimento.';
COMMENT ON COLUMN public.eventos.etapa IS 'Momento da jornada, sem códigos internos.';
COMMENT ON COLUMN public.eventos.resumo IS 'Explicação curta do acontecimento.';
COMMENT ON COLUMN public.eventos.atendimento_id IS 'Atendimento relacionado, quando houver.';

NOTIFY pgrst,'reload schema';
COMMIT;

