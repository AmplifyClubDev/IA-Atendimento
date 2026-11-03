CREATE OR REPLACE FUNCTION public.registrar_cadastro_ensaio_v5(p_payload jsonb, p_context jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
  v_map jsonb := $mapping${"version":"atendimento-v5-ensaio-data-1","form_version":"amplify-cadastro-v2","consent_version":"2026-09-09-v1","fields":[{"id":"nome","table":"creators","column":"nome","type":"text","conversion":"text"},{"id":"email","table":"creators","column":"email","type":"email","conversion":"email"},{"id":"whatsapp","table":"creators","column":"whatsapp","type":"phone_number","conversion":"phone_number"},{"id":"foto_perfil","table":"creators_perfil","column":"foto_perfil_referencia","type":"file","conversion":"private_file"},{"id":"mini_bio","table":"creators_perfil","column":"mini_bio","type":"textarea","conversion":"textarea"},{"id":"canal_origem","table":"creators_aquisicao","column":"origem_informada_formulario","type":"select","conversion":"select","options":["Conheci no instagram","Conheci no TikTok","Me indicaram","Entraram em contato comigo","Outro jeito"]},{"id":"origem_outro","table":"creators_aquisicao","column":"origem_outro","type":"text","conversion":"text","condition":{"field":"canal_origem","equals":"Outro jeito"}},{"id":"expectativas","table":"creators_perfil","column":"expectativas","type":"textarea","conversion":"textarea"},{"id":"meta_renda_mensal","table":"creators_perfil","column":"meta_renda_mensal","type":"number","conversion":"decimal"},{"id":"contexto_adicional","table":"creators_perfil","column":"contexto_adicional","type":"textarea","conversion":"textarea"},{"id":"plataformas","table":"creators_perfil","column":"plataformas","type":"multi_select","conversion":"multi_select","options":["TikTok","Instagram","YouTube","Shopee","Mercado Livre","Amazon","Shein","Outros"]},{"id":"instagram","table":"creators_perfil","column":"instagram","type":"text","conversion":"text","condition":{"field":"plataformas","includes":"Instagram"}},{"id":"plataformas_outros","table":"creators_perfil","column":"plataformas_outros","type":"text","conversion":"text","condition":{"field":"plataformas","includes":"Outros"}},{"id":"experiencia_live_shop","table":"creators_perfil","column":"experiencia_live_shop","type":"select","conversion":"select","options":["Nenhuma","Básico","Intermediário","Avançado"]},{"id":"agencia_anterior","table":"creators_perfil","column":"teve_agencia_anterior","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"nome_agencia_anterior","table":"creators_perfil","column":"nome_agencia_anterior","type":"text","conversion":"text","condition":{"field":"agencia_anterior","equals":"Sim"}},{"id":"experiencia_agencia","table":"creators_perfil","column":"experiencia_agencia","type":"textarea","conversion":"textarea","condition":{"field":"agencia_anterior","equals":"Sim"}},{"id":"produtos_excluidos","table":"creators_perfil","column":"produtos_excluidos","type":"textarea","conversion":"textarea"},{"id":"gmv_declarado","table":"creators_gmv","column":"valor","type":"number","conversion":"decimal"},{"id":"inicio_amplify_informado","table":"creators_perfil","column":"inicio_amplify_informado","type":"date","conversion":"date"},{"id":"cpf","table":"creators_pagamentos","column":"cpf","type":"text","conversion":"cpf"},{"id":"nascimento","table":"creators_perfil","column":"data_nascimento","type":"date","conversion":"date"},{"id":"genero","table":"creators_perfil","column":"genero","type":"select","conversion":"select","options":["Masculino","Feminino","Prefiro não responder"]},{"id":"estado_civil","table":"creators_perfil","column":"estado_civil","type":"select","conversion":"select","options":["Solteiro","Namorando","Casado","Prefiro não informar"]},{"id":"camiseta","table":"creators_perfil","column":"camiseta","type":"select","conversion":"select","options":["P","M","G","GG","Outro"]},{"id":"camiseta_outro","table":"creators_perfil","column":"camiseta_outro","type":"text","conversion":"text","condition":{"field":"camiseta","equals":"Outro"}},{"id":"estado","table":"creators_enderecos","column":"endereco_estado","type":"select","conversion":"select","options":["Acre","Alagoas","Amapá","Amazonas","Bahia","Ceará","Distrito Federal","Espírito Santo","Goiás","Maranhão","Mato Grosso","Mato Grosso do Sul","Minas Gerais","Pará","Paraíba","Paraná","Pernambuco","Piauí","Rio de Janeiro","Rio Grande do Norte","Rio Grande do Sul","Rondônia","Roraima","Santa Catarina","São Paulo","Sergipe","Tocantins"]},{"id":"cidade","table":"creators_enderecos","column":"endereco_cidade","type":"text","conversion":"text"},{"id":"logradouro","table":"creators_enderecos","column":"endereco_logradouro","type":"text","conversion":"text"},{"id":"bairro","table":"creators_enderecos","column":"endereco_bairro","type":"text","conversion":"text"},{"id":"numero","table":"creators_enderecos","column":"endereco_numero","type":"text","conversion":"text"},{"id":"complemento","table":"creators_enderecos","column":"endereco_complemento","type":"text","conversion":"text"},{"id":"cep","table":"creators_enderecos","column":"endereco_cep","type":"text","conversion":"cep"},{"id":"pix","table":"creators_pagamentos","column":"pix_chave","type":"text","conversion":"text"},{"id":"possui_cnpj","table":"creators_pagamentos","column":"possui_cnpj","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"cnpj","table":"creators_pagamentos","column":"cnpj","type":"text","conversion":"cnpj","condition":{"field":"possui_cnpj","equals":"Sim"}},{"id":"nichos","table":"creators_perfil","column":"nichos","type":"multi_select","conversion":"multi_select","options":["Lifestyle","Tecnologia","Moda","Beleza","Fitness & Saúde","Viagens","Culinária & Gastronomia","Educação & Conhecimento","Casa e Decoração","Gaming (Jogos)","Pets","Família & Parentalidade","Negócios & Empreendedorismo","Eletrônicos","Outros"]},{"id":"nichos_outros","table":"creators_perfil","column":"nichos_outros","type":"text","conversion":"text","condition":{"field":"nichos","includes":"Outros"}},{"id":"rotina","table":"creators_perfil","column":"rotina","type":"select","conversion":"select","options":["Tenho outro trabalho além de criar conteúdo","Me dedico 100% ao conteúdo","Outro"]},{"id":"rotina_outro","table":"creators_perfil","column":"rotina_outro","type":"textarea","conversion":"textarea","condition":{"field":"rotina","equals":"Outro"}},{"id":"tem_filhos","table":"creators_oportunidades","column":"tem_filhos","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"cabelo","table":"creators_perfil","column":"cabelo","type":"select","conversion":"select","options":["liso","Ondulado","Cacheado","Crespo","Sem cabelo","Prefiro não informar"]},{"id":"calcado","table":"creators_perfil","column":"calcado","type":"number","conversion":"decimal"},{"id":"cor_raca","table":"creators_oportunidades","column":"cor_raca","type":"select","conversion":"select","options":["Branca","Parda","Preta","Amarela (descendentes de asiáticos)","Indígena","Prefiro não informar"]},{"id":"alimentacao","table":"creators_oportunidades","column":"alimentacao","type":"select","conversion":"select","options":["Sem restrições (como de tudo)","Vegetariano/Vegano (não come carne)","Tenho restrições alimentares (especificar)"]},{"id":"restricao_alimentar","table":"creators_oportunidades","column":"restricao_alimentar","type":"text","conversion":"text","condition":{"field":"alimentacao","equals":"Tenho restrições alimentares (especificar)"}},{"id":"casa_praia_campo","table":"creators_oportunidades","column":"casa_praia_campo","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"carro","table":"creators_oportunidades","column":"carro","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"moto","table":"creators_oportunidades","column":"moto","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"celular","table":"creators_oportunidades","column":"celular","type":"select","conversion":"select","options":["iPhone","Android","Ambos","Outros"]},{"id":"computador","table":"creators_oportunidades","column":"computador","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"tripe","table":"creators_oportunidades","column":"tripe","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"microfone","table":"creators_oportunidades","column":"microfone","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"academia","table":"creators_oportunidades","column":"academia","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"tem_pet","table":"creators_oportunidades","column":"tem_pet","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"pets","table":"creators_oportunidades","column":"pets","type":"text","conversion":"text","condition":{"field":"tem_pet","equals":"Sim"}},{"id":"outro_idioma","table":"creators_oportunidades","column":"outro_idioma","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"video_idioma","table":"creators_oportunidades","column":"video_idioma","type":"url","conversion":"url","condition":{"field":"outro_idioma","equals":"Sim"}},{"id":"idiomas","table":"creators_oportunidades","column":"idiomas","type":"multi_select","conversion":"multi_select","options":["Inglês","Espanhol","Francês","Alemão","Italiano","Japonês","Mandarim (Chinês)","Coreano","Árabe","Russo","Hindi","Outros"],"condition":{"field":"outro_idioma","equals":"Sim"}},{"id":"idiomas_outros","table":"creators_oportunidades","column":"idiomas_outros","type":"text","conversion":"text","condition":{"field":"idiomas","includes":"Outros"}},{"id":"mais_2000_seguidores","table":"creators_perfil","column":"declarou_mais_2000_seguidores","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"print_gmv","table":"creators_gmv","column":"comprovante_referencia","type":"file","conversion":"private_file"},{"id":"tiktok","table":"creators","column":"tiktok","type":"text","conversion":"tiktok"}]}$mapping$::jsonb;
  v_creator uuid; v_event uuid; v_form uuid; v_expected uuid; v_bytes bytea;
  v_received timestamptz; v_at timestamptz; v_day date; v_start date; v_end date;
  v_field jsonb; v_section jsonb; v_value jsonb; v_parent jsonb; v_condition jsonb;
  v_answers jsonb := '{}'::jsonb; v_context_item jsonb; v_visible boolean;
  v_name text; v_table text; v_column text; v_conversion text; v_text text;
  v_ref text; v_fingerprint text; v_existing_ref text; v_existing_id uuid;
  v_existing interno.creators%rowtype; v_number numeric; v_cpf text;
  v_index integer; v_length integer; v_sum integer; v_digit integer; v_gmv_id bigint;
  v_allowed text[]; v_observation text; v_origin text; v_origin_source text;
  v_origin_ref text; v_first timestamptz; v_channel text; v_email_confirmed timestamptz;
  v_expected_reference text; v_mode text; v_flat jsonb; v_saved interno.eventos%rowtype; v_atendimento uuid; v_result jsonb; v_previous text:=coalesce(current_setting('app.v5_explicit_event',true),'off');
begin
  if current_user <> 'service_role' then
    raise exception using errcode='42501',message='ensaio_service_role_obrigatorio';
  end if;
  if jsonb_typeof(p_payload) is distinct from 'object'
     or (select count(*) from jsonb_object_keys(p_payload)) <> 6
     or not p_payload ?& array['mapping_version','form_version','identity','branches','gmv','consent']
     or p_payload->>'mapping_version' is distinct from v_map->>'version'
     or p_payload->>'form_version' is distinct from v_map->>'form_version' then
    raise exception using errcode='22023',message='ensaio_payload_invalido';
  end if;
  if jsonb_typeof(p_context) is distinct from 'object'
     or not p_context ?& array['creator_id','event_id','form_instance_id','received_at','source','attachments']
     or exists(select 1 from jsonb_object_keys(p_context) k where k not in
       ('creator_id','event_id','form_instance_id','received_at','source','attachments','first_inbound','origin','email_confirmation','gmv_period','atendimento_id')) then
    raise exception using errcode='22023',message='ensaio_contexto_invalido';
  end if;
  v_creator := (p_context->>'creator_id')::uuid;
  v_event := (p_context->>'event_id')::uuid;
  v_form := (p_context->>'form_instance_id')::uuid;
  if v_creator is null or v_event is null or v_form is null
     or v_creator='00000000-0000-0000-0000-000000000000'::uuid
     or v_form='00000000-0000-0000-0000-000000000000'::uuid
     or p_context->>'creator_id' <> v_creator::text
     or p_context->>'event_id' <> v_event::text
     or p_context->>'form_instance_id' <> v_form::text then
    raise exception using errcode='22023',message='ensaio_identificadores_invalidos';
  end if;
  v_bytes := decode(md5(uuid_send(v_creator)||convert_to(
    'atendimento-v5-ensaio|amplify-cadastro-v2|'||v_form::text,'UTF8')),'hex');
  v_bytes := set_byte(v_bytes,6,(get_byte(v_bytes,6)&15)|48);
  v_bytes := set_byte(v_bytes,8,(get_byte(v_bytes,8)&63)|128);
  v_expected := encode(v_bytes,'hex')::uuid;
  if v_event <> v_expected then
    raise exception using errcode='22023',message='ensaio_evento_nao_corresponde_ao_formulario';
  end if;
  if coalesce(p_context->>'received_at','') !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$' then
    raise exception using errcode='22023',message='ensaio_data_recebimento_invalida';
  end if;
  v_received := (p_context->>'received_at')::timestamptz;
  if not isfinite(v_received) then
    raise exception using errcode='22023',message='ensaio_data_recebimento_invalida';
  end if;
  v_day := (v_received at time zone 'UTC')::date;
  v_section := p_context->'source';
  if jsonb_typeof(v_section) is distinct from 'object'
     or (select count(*) from jsonb_object_keys(v_section))<>2
     or not v_section ?& array['kind','reference']
     or v_section->>'kind' is distinct from 'formulario_ensaio' then
    raise exception using errcode='22023',message='ensaio_fonte_invalida';
  end if;
  v_text := v_section->>'reference';
  if v_text is null or v_text !~ '^[A-Za-z0-9][A-Za-z0-9:_./-]{0,239}$' or position('://' in v_text)>0 or position('..' in v_text)>0 then
    raise exception using errcode='22023',message='ensaio_referencia_fonte_invalida';
  end if;
  if jsonb_typeof(p_payload->'consent') is distinct from 'object'
     or p_payload->'consent' <> jsonb_build_object('accepted',true,'version',v_map->>'consent_version') then
    raise exception using errcode='22023',message='ensaio_consentimento_obrigatorio';
  end if;

  -- Cada chave de destino deve corresponder exatamente ao mapa de 63 campos.
  if jsonb_typeof(p_payload->'branches') is distinct from 'object'
     or (select count(*) from jsonb_object_keys(p_payload->'branches'))<>6
     or not (p_payload->'branches') ?& array['creators_aquisicao','creators_perfil','creators_oportunidades','creators_enderecos','creators_pagamentos','creators_circle'] then
    raise exception using errcode='22023',message='ensaio_ramificacoes_invalidas';
  end if;
  foreach v_table in array array['creators','creators_aquisicao','creators_perfil','creators_oportunidades','creators_enderecos','creators_pagamentos','creators_circle','creators_gmv'] loop
    v_section := case v_table when 'creators' then p_payload->'identity'
      when 'creators_gmv' then p_payload->'gmv' else p_payload->'branches'->v_table end;
    select coalesce(array_agg(f->>'column'),'{}'::text[]) into v_allowed
      from jsonb_array_elements(v_map->'fields') f where f->>'table'=v_table;
    if jsonb_typeof(v_section) is distinct from 'object'
       or (select count(*) from jsonb_object_keys(v_section))<>cardinality(v_allowed)
       or not v_section ?& v_allowed then
      raise exception using errcode='22023',message='ensaio_campos_de_destino_invalidos:'||v_table;
    end if;
  end loop;
  for v_field in select value from jsonb_array_elements(v_map->'fields') loop
    v_name := v_field->>'id'; v_table := v_field->>'table'; v_column := v_field->>'column';
    v_conversion := v_field->>'conversion';
    v_section := case v_table when 'creators' then p_payload->'identity'
      when 'creators_gmv' then p_payload->'gmv' else p_payload->'branches'->v_table end;
    v_value := v_section->v_column;
    -- Reconstrucao das respostas condicionantes, sem confiar em um flag do cliente.
    v_condition := v_field->'condition'; v_visible := true;
    if v_condition is not null then
      v_parent := v_answers->(v_condition->>'field');
      if v_condition ? 'equals' then
        v_visible := v_parent is not null and v_parent=v_condition->'equals';
      else
        v_visible := jsonb_typeof(v_parent)='array' and v_parent @> jsonb_build_array(v_condition->>'includes');
      end if;
    end if;
    if not coalesce(v_visible,false) then
      if v_value is distinct from 'null'::jsonb then
        raise exception using errcode='22023',message='ensaio_campo_fora_da_condicao:'||v_name;
      end if;
      v_answers := v_answers||jsonb_build_object(v_name,null); continue;
    end if;
    if v_value is null or v_value='null'::jsonb then
      raise exception using errcode='22023',message='ensaio_campo_obrigatorio:'||v_name;
    end if;
    if v_conversion='boolean' then
      if jsonb_typeof(v_value)<>'boolean' then
        raise exception using errcode='22023',message='ensaio_booleano_invalido:'||v_name;
      end if;
      v_answers := v_answers||jsonb_build_object(v_name,case when v_value='true'::jsonb then 'Sim' else 'Não' end);
    elsif v_conversion='multi_select' then
      if jsonb_typeof(v_value)<>'array' then
        raise exception using errcode='22023',message='ensaio_lista_invalida:'||v_name;
      end if;
      if jsonb_array_length(v_value)=0
         or exists(select 1 from jsonb_array_elements(v_value) x where jsonb_typeof(x)<>'string' or not (v_field->'options') @> jsonb_build_array(x))
         or (select count(*) from jsonb_array_elements(v_value))<>(select count(distinct x) from jsonb_array_elements(v_value) x) then
        raise exception using errcode='22023',message='ensaio_opcoes_invalidas:'||v_name;
      end if;
      v_answers := v_answers||jsonb_build_object(v_name,v_value);
    else
      if jsonb_typeof(v_value)<>'string' then
        raise exception using errcode='22023',message='ensaio_texto_invalido:'||v_name;
      end if;
      v_text := v_value#>>'{}';
      if v_text='' or v_text<>btrim(v_text) or length(v_text)>(case when v_conversion='textarea' then 2000 else 254 end) then
        raise exception using errcode='22023',message='ensaio_texto_invalido:'||v_name;
      end if;
      if v_conversion='decimal' then
        if v_text !~ '^\d+(\.\d{1,2})?$' then
          raise exception using errcode='22023',message='ensaio_numero_invalido:'||v_name;
        end if;
        v_number := v_text::numeric;
        if v_number<0 or v_number>1000000000
           or (v_name='calcado' and (v_number>999.9 or v_number<>round(v_number,1))) then
          raise exception using errcode='22023',message='ensaio_numero_invalido:'||v_name;
        end if;
      elsif v_conversion='date' then
        if v_text !~ '^\d{4}-\d{2}-\d{2}$' or v_text::date<'1900-01-01'::date or v_text::date>v_day then
          raise exception using errcode='22023',message='ensaio_data_invalida:'||v_name;
        end if;
      elsif v_conversion='email' then
        if v_text<>lower(v_text) or v_text !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' then
          raise exception using errcode='22023',message='ensaio_email_invalido';
        end if;
      elsif v_conversion='phone_number' then
        if v_text !~ '^55[0-9]{10,11}$' then raise exception using errcode='22023',message='ensaio_telefone_invalido'; end if;
      elsif v_conversion='tiktok' then
        if v_text !~ '^[a-z0-9._]{2,24}$' then raise exception using errcode='22023',message='ensaio_tiktok_invalido'; end if;
      elsif v_conversion='cep' then
        if v_text !~ '^[0-9]{8}$' then raise exception using errcode='22023',message='ensaio_cep_invalido'; end if;
      elsif v_conversion='cnpj' then
        if v_text !~ '^[A-Z0-9]{12}[0-9]{2}$' then raise exception using errcode='22023',message='ensaio_cnpj_invalido'; end if;
      elsif v_conversion='cpf' then
        v_cpf := v_text;
        if v_cpf !~ '^[0-9]{11}$' or v_cpf=repeat(substr(v_cpf,1,1),11) then
          raise exception using errcode='22023',message='ensaio_cpf_invalido';
        end if;
        for v_length in 9..10 loop
          v_sum := 0;
          for v_index in 1..v_length loop v_sum:=v_sum+substr(v_cpf,v_index,1)::integer*(v_length+2-v_index); end loop;
          v_digit := ((v_sum*10)%11)%10;
          if v_digit<>substr(v_cpf,v_length+1,1)::integer then raise exception using errcode='22023',message='ensaio_cpf_invalido'; end if;
        end loop;
      elsif v_conversion='url' then
        if v_text !~ '^https://[^/@[:space:]]+(/[^[:space:]]*)?$' then raise exception using errcode='22023',message='ensaio_url_invalida:'||v_name; end if;
      elsif v_conversion='private_file' then
        if v_text !~ '^[A-Za-z0-9][A-Za-z0-9:_./-]{0,239}$' or position('://' in v_text)>0 or position('..' in v_text)>0 then
          raise exception using errcode='22023',message='ensaio_arquivo_invalido:'||v_name;
        end if;
      end if;
      if v_field->>'type'='select' and v_conversion<>'boolean' and not (v_field->'options') @> jsonb_build_array(v_text) then
        raise exception using errcode='22023',message='ensaio_opcao_invalida:'||v_name;
      end if;
      v_answers := v_answers||jsonb_build_object(v_name,v_value);
    end if;
  end loop;

  -- Somente atestados de upload, sem o recibo/token original no argumento SQL.
  v_section := p_context->'attachments';
  if jsonb_typeof(v_section) is distinct from 'object' or (select count(*) from jsonb_object_keys(v_section))<>2 or not v_section ?& array['foto_perfil','print_gmv'] then
    raise exception using errcode='22023',message='ensaio_anexos_invalidos';
  end if;
  foreach v_name in array array['foto_perfil','print_gmv'] loop
    v_context_item := v_section->v_name;
    v_expected_reference := case when v_name='foto_perfil' then p_payload->'branches'->'creators_perfil'->>'foto_perfil_referencia' else p_payload->'gmv'->>'comprovante_referencia' end;
    if jsonb_typeof(v_context_item) is distinct from 'object'
       or (select count(*) from jsonb_object_keys(v_context_item))<>3
       or not v_context_item ?& array['reference','source','receipt_sha256']
       or v_context_item->>'source' is distinct from 'upload_validado'
       or v_context_item->>'reference' is distinct from v_expected_reference
       or coalesce(v_context_item->>'receipt_sha256','') !~ '^[0-9a-f]{64}$' then
      raise exception using errcode='22023',message='ensaio_anexo_nao_validado:'||v_name;
    end if;
  end loop;
  foreach v_observation in array array['first_inbound','origin','email_confirmation'] loop
    if not p_context ? v_observation then continue; end if;
    v_context_item := p_context->v_observation;
    v_allowed := array['at','source','reference'];
    if v_observation='origin' then v_allowed:=array_append(v_allowed,'value'); end if;
    if v_observation='email_confirmation' then v_allowed:=array_append(v_allowed,'email_sha256'); end if;
    if jsonb_typeof(v_context_item) is distinct from 'object'
       or (select count(*) from jsonb_object_keys(v_context_item))<>cardinality(v_allowed)
       or not v_context_item ?& v_allowed then
      raise exception using errcode='22023',message='ensaio_observacao_invalida:'||v_observation;
    end if;
    v_text := v_context_item->>'reference';
    if v_text is null or v_text !~ '^[A-Za-z0-9][A-Za-z0-9:_./-]{0,239}$' or position('://' in v_text)>0 or position('..' in v_text)>0
       or coalesce(v_context_item->>'at','') !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$' then
      raise exception using errcode='22023',message='ensaio_observacao_invalida:'||v_observation;
    end if;
    v_at := (v_context_item->>'at')::timestamptz;
    if not isfinite(v_at) or v_at>v_received then raise exception using errcode='22023',message='ensaio_observacao_futura'; end if;
    if v_observation='first_inbound' then
      if v_context_item->>'source' is distinct from 'chatwoot_webhook' then raise exception using errcode='22023',message='ensaio_fonte_mensagem_invalida'; end if;
      v_first:=v_at;v_channel:='whatsapp';
    elsif v_observation='origin' then
      if coalesce(v_context_item->>'source','') not in ('declaracao_pessoa','utm_observada','link_observado')
         or coalesce(btrim(v_context_item->>'value'),'')='' or length(v_context_item->>'value')>120 then
        raise exception using errcode='22023',message='ensaio_origem_invalida';
      end if;
      v_origin:=v_context_item->>'value';v_origin_source:=v_context_item->>'source';v_origin_ref:=v_context_item->>'reference';
    else
      if v_context_item->>'source' is distinct from 'email_token_validado'
         or v_context_item->>'email_sha256' is distinct from encode(sha256(convert_to(p_payload->'identity'->>'email','UTF8')),'hex') then
        raise exception using errcode='22023',message='ensaio_email_nao_confirmado';
      end if;
      v_email_confirmed:=v_at;
    end if;
  end loop;
  v_mode := 'nao_informado';
  if p_context ? 'gmv_period' then
    v_context_item:=p_context->'gmv_period';
    if jsonb_typeof(v_context_item) is distinct from 'object'
       or (select count(*) from jsonb_object_keys(v_context_item))<>4
       or not v_context_item ?& array['start','end','source','reference']
       or v_context_item->>'source' is distinct from 'periodo_declarado'
       or coalesce(v_context_item->>'start','') !~ '^\d{4}-\d{2}-\d{2}$'
       or coalesce(v_context_item->>'end','') !~ '^\d{4}-\d{2}-\d{2}$' then
      raise exception using errcode='22023',message='ensaio_periodo_invalido';
    end if;
    v_text:=v_context_item->>'reference';
    if v_text is null or v_text !~ '^[A-Za-z0-9][A-Za-z0-9:_./-]{0,239}$' or position('://' in v_text)>0 or position('..' in v_text)>0 then raise exception using errcode='22023',message='ensaio_periodo_fonte_invalida'; end if;
    v_start:=(v_context_item->>'start')::date;v_end:=(v_context_item->>'end')::date;
    if not isfinite(v_start) or not isfinite(v_end) or v_end<>v_start+27 or v_end>v_day then raise exception using errcode='22023',message='ensaio_periodo_invalido'; end if;
    v_mode:='janela_28_dias';
  end if;


  if v_email_confirmed is null then raise exception 'cadastro_email_confirmation_required' using errcode='22023'; end if;
  if p_context ? 'atendimento_id' then
    v_atendimento:=(p_context->>'atendimento_id')::uuid;
    if v_atendimento is null or not exists(select 1 from interno.atendimentos where id=v_atendimento and creator_id=v_creator) then
      raise exception 'cadastro_atendimento_invalid' using errcode='22023'; end if;
  end if;
  perform pg_advisory_xact_lock(hashtextextended('v5:cadastro',0));
  v_fingerprint:=encode(sha256(convert_to(p_payload::text||E'\n'||p_context::text,'UTF8')),'hex');
  select * into v_saved from interno.eventos where submissao_id=v_event;
  if found then
    if v_saved.creator_id<>v_creator or v_saved.payload_sha256<>v_fingerprint then
      raise exception 'cadastro_submission_conflict' using errcode='23505'; end if;
    return v_saved.resultado||jsonb_build_object('replayed',true);
  end if;
  if v_atendimento is not null and not exists(select 1 from interno.atendimentos where id=v_atendimento and creator_id=v_creator
      and situacao='aberto' and etapa='form' and (expires_at is null or expires_at>v_received)) then
    raise exception 'cadastro_atendimento_inactive' using errcode='22023'; end if;
  select * into v_existing from interno.creators where id=v_creator for update;
  if found and v_existing.cadastro_situacao='confirmado' then
    raise exception 'cadastro_already_confirmed_requires_revision_confirmation' using errcode='23505'; end if;
  -- A different stable person is never merged by a phone/name match.
  if exists(select 1 from interno.creators c where c.id<>v_creator and
    (lower(btrim(c.email))=p_payload->'identity'->>'email' or c.whatsapp=p_payload->'identity'->>'whatsapp'
     or c.telefone=p_payload->'identity'->>'whatsapp' or lower(ltrim(c.tiktok,'@'))=p_payload->'identity'->>'tiktok')) then
    raise exception 'cadastro_identity_requires_review' using errcode='23505'; end if;
  v_flat:=p_payload->'identity';
  for v_table in select jsonb_object_keys(p_payload->'branches') loop
    v_flat:=v_flat||(p_payload->'branches'->v_table);
  end loop;
  perform set_config('app.v5_explicit_event','on',true);
  insert into interno.creators(id,nome,email,whatsapp,foto_perfil_referencia,mini_bio,origem_informada_formulario,origem_outro,expectativas,meta_renda_mensal,contexto_adicional,plataformas,instagram,plataformas_outros,experiencia_live_shop,teve_agencia_anterior,nome_agencia_anterior,experiencia_agencia,produtos_excluidos,inicio_amplify_informado,cpf,data_nascimento,genero,estado_civil,camiseta,camiseta_outro,endereco_estado,endereco_cidade,endereco_logradouro,endereco_bairro,endereco_numero,endereco_complemento,endereco_cep,pix_chave,possui_cnpj,cnpj,nichos,nichos_outros,rotina,rotina_outro,tem_filhos,cabelo,calcado,cor_raca,alimentacao,restricao_alimentar,casa_praia_campo,carro,moto,celular,computador,tripe,microfone,academia,tem_pet,pets,outro_idioma,video_idioma,idiomas,idiomas_outros,declarou_mais_2000_seguidores,tiktok)
  select v_creator,r.nome,r.email,r.whatsapp,r.foto_perfil_referencia,r.mini_bio,r.origem_informada_formulario,r.origem_outro,r.expectativas,r.meta_renda_mensal,r.contexto_adicional,r.plataformas,r.instagram,r.plataformas_outros,r.experiencia_live_shop,r.teve_agencia_anterior,r.nome_agencia_anterior,r.experiencia_agencia,r.produtos_excluidos,r.inicio_amplify_informado,r.cpf,r.data_nascimento,r.genero,r.estado_civil,r.camiseta,r.camiseta_outro,r.endereco_estado,r.endereco_cidade,r.endereco_logradouro,r.endereco_bairro,r.endereco_numero,r.endereco_complemento,r.endereco_cep,r.pix_chave,r.possui_cnpj,r.cnpj,r.nichos,r.nichos_outros,r.rotina,r.rotina_outro,r.tem_filhos,r.cabelo,r.calcado,r.cor_raca,r.alimentacao,r.restricao_alimentar,r.casa_praia_campo,r.carro,r.moto,r.celular,r.computador,r.tripe,r.microfone,r.academia,r.tem_pet,r.pets,r.outro_idioma,r.video_idioma,r.idiomas,r.idiomas_outros,r.declarou_mais_2000_seguidores,r.tiktok
  from jsonb_populate_record(null::interno.creators,v_flat) r
  on conflict(id) do update set nome=excluded.nome,email=excluded.email,whatsapp=excluded.whatsapp,foto_perfil_referencia=excluded.foto_perfil_referencia,mini_bio=excluded.mini_bio,origem_informada_formulario=excluded.origem_informada_formulario,origem_outro=excluded.origem_outro,expectativas=excluded.expectativas,meta_renda_mensal=excluded.meta_renda_mensal,contexto_adicional=excluded.contexto_adicional,plataformas=excluded.plataformas,instagram=excluded.instagram,plataformas_outros=excluded.plataformas_outros,experiencia_live_shop=excluded.experiencia_live_shop,teve_agencia_anterior=excluded.teve_agencia_anterior,nome_agencia_anterior=excluded.nome_agencia_anterior,experiencia_agencia=excluded.experiencia_agencia,produtos_excluidos=excluded.produtos_excluidos,inicio_amplify_informado=excluded.inicio_amplify_informado,cpf=excluded.cpf,data_nascimento=excluded.data_nascimento,genero=excluded.genero,estado_civil=excluded.estado_civil,camiseta=excluded.camiseta,camiseta_outro=excluded.camiseta_outro,endereco_estado=excluded.endereco_estado,endereco_cidade=excluded.endereco_cidade,endereco_logradouro=excluded.endereco_logradouro,endereco_bairro=excluded.endereco_bairro,endereco_numero=excluded.endereco_numero,endereco_complemento=excluded.endereco_complemento,endereco_cep=excluded.endereco_cep,pix_chave=excluded.pix_chave,possui_cnpj=excluded.possui_cnpj,cnpj=excluded.cnpj,nichos=excluded.nichos,nichos_outros=excluded.nichos_outros,rotina=excluded.rotina,rotina_outro=excluded.rotina_outro,tem_filhos=excluded.tem_filhos,cabelo=excluded.cabelo,calcado=excluded.calcado,cor_raca=excluded.cor_raca,alimentacao=excluded.alimentacao,restricao_alimentar=excluded.restricao_alimentar,casa_praia_campo=excluded.casa_praia_campo,carro=excluded.carro,moto=excluded.moto,celular=excluded.celular,computador=excluded.computador,tripe=excluded.tripe,microfone=excluded.microfone,academia=excluded.academia,tem_pet=excluded.tem_pet,pets=excluded.pets,outro_idioma=excluded.outro_idioma,video_idioma=excluded.video_idioma,idiomas=excluded.idiomas,idiomas_outros=excluded.idiomas_outros,declarou_mais_2000_seguidores=excluded.declarou_mais_2000_seguidores,tiktok=excluded.tiktok;
  v_ref:='ensaio-v5:'||v_event::text||':'||v_fingerprint;
  update interno.creators c set canal_entrada=coalesce(c.canal_entrada,v_channel),
    primeira_mensagem_em=coalesce(c.primeira_mensagem_em,v_first),
    origem_fonte=case when c.origem_entrada is null then coalesce(v_origin_source,c.origem_fonte) else c.origem_fonte end,
    origem_detalhe=case when c.origem_entrada is null then coalesce(v_origin_ref,c.origem_detalhe) else c.origem_detalhe end,
    origem_entrada=coalesce(c.origem_entrada,v_origin),
    formulario_situacao='recebido_ensaio_whatsapp',formulario_recebido_em=v_received,formulario_versao=p_payload->>'form_version',
    formulario_submissao_referencia=v_ref,consentimento_aceito_em=v_received,consentimento_versao=p_payload->'consent'->>'version',
    email_confirmado_em=v_email_confirmed,cadastro_situacao='confirmado',cadastro_revisao=c.cadastro_revisao+1,
    etapa_atual='cadastro_confirmado',situacao_atual='cadastro_confirmado'
    where c.id=v_creator;
  insert into interno.gmv(creator_id,atendimento_id,finalidade,natureza,periodicidade,periodo_inicio,periodo_fim,
    valor,moeda,situacao,fonte,observado_em,comprovante_referencia)
  values(v_creator,v_atendimento,'entrada','declarado',v_mode,v_start,v_end,(p_payload->'gmv'->>'valor')::numeric,
    'BRL','registrado','formulario_ensaio:'||v_event::text,v_received,p_payload->'gmv'->>'comprovante_referencia') returning id into v_gmv_id;
  v_result:=jsonb_build_object('creator_id',v_creator,'event_id',v_event,'gmv_id',v_gmv_id,'replayed',false,'status','cadastro_recebido_ensaio');
  insert into interno.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,payload_sha256,
    formulario_id,submissao_id,gmv_id,resultado)
  values(v_creator,v_atendimento,'cadastro_confirmado_ensaio','formulario_ensaio',v_event::text,0,v_received,v_fingerprint,
    v_form,v_event,v_gmv_id,v_result);
  if v_atendimento is not null then update interno.atendimentos set situacao='encerrado',motivo_encerramento='cadastro_confirmado'
    where id=v_atendimento and creator_id=v_creator; end if;
  perform set_config('app.v5_explicit_event',v_previous,true);
  return v_result;
end;
$function$

