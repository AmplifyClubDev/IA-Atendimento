-- Formulário público único (https://amplify-cadastro.up.railway.app/cadastro)
-- grava no banco novo AmplifyOS-v5 (divlvdmsqbwplervsqwu).
--
-- Cria somente:
--   1. bucket privado de Storage `cadastro-privado` (foto de perfil e print de GMV);
--   2. função interna `interno.cadastro_publico_resolver` (acha a ficha por @/WhatsApp/e-mail);
--   3. função `public.consultar_cadastro_publico_v5` (pré-checagem sem gravar nada);
--   4. função `public.registrar_cadastro_publico_v5` (grava o cadastro final);
--   5. funções `public.preparar_entrega_circle_v5` / `confirmar_entrega_circle_v5` (acesso no Circle).
-- Não cria nem altera tabelas, colunas, constraints, triggers ou as funções da Bia.
-- Gerado por build_migration.py: a validação dos 63 campos e o upsert da ficha são
-- copiados literalmente de public.registrar_cadastro_ensaio_v5 (fonte aplicada em 28/10).
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
DO $guard$
BEGIN
 IF current_user<>'postgres' THEN RAISE EXCEPTION 'cadastro_publico_migration_requires_postgres'; END IF;
 IF to_regprocedure('public.registrar_cadastro_publico_v5(jsonb,jsonb)') IS NOT NULL
   OR to_regprocedure('public.consultar_cadastro_publico_v5(text,text,text)') IS NOT NULL
   OR to_regprocedure('interno.cadastro_publico_resolver(text,text,text)') IS NOT NULL
   OR to_regprocedure('public.preparar_entrega_circle_v5(uuid)') IS NOT NULL
   OR to_regprocedure('public.confirmar_entrega_circle_v5(uuid,text,text,bigint,text,text)') IS NOT NULL
   THEN RAISE EXCEPTION 'cadastro_publico_already_installed'; END IF;
 IF (SELECT count(*) FROM information_schema.columns WHERE table_schema='interno' AND table_name='creators')<>110
   THEN RAISE EXCEPTION 'cadastro_publico_catalog_changed:creators'; END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='gmv_periodo_unique' AND conrelid='interno.gmv'::regclass)
   OR NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conname='eventos_tipo_check' AND conrelid='interno.eventos'::regclass
     AND pg_get_constraintdef(oid) LIKE '%''cadastro_confirmado''::text%')
   OR NOT EXISTS(SELECT 1 FROM pg_indexes WHERE schemaname='interno' AND tablename='gmv'
     AND indexname='gmv_uma_entrada_por_natureza_idx' AND indexdef LIKE '%UNIQUE%(creator_id, natureza)%entrada%')
   THEN RAISE EXCEPTION 'cadastro_publico_catalog_changed:gmv_eventos'; END IF;
 IF EXISTS(SELECT 1 FROM storage.buckets WHERE id='cadastro-privado') THEN RAISE EXCEPTION 'cadastro_publico_bucket_exists'; END IF;
END;
$guard$;

-- Imagens privadas: sem política para anon/authenticated; só a chave de serviço lê e grava.
INSERT INTO storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
VALUES('cadastro-privado','cadastro-privado',false,5242880,ARRAY['image/jpeg']);

CREATE FUNCTION interno.cadastro_publico_resolver(p_tiktok text,p_whatsapp text,p_email text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path='' AS $resolver$
DECLARE
 v_by_tiktok uuid[]; v_by_phone uuid[]; v_by_email uuid[]; v_ids uuid[]; c interno.creators%rowtype;
BEGIN
 IF p_tiktok IS NULL OR p_tiktok !~ '^[a-z0-9._]{2,24}$'
   OR p_whatsapp IS NULL OR p_whatsapp !~ '^55[0-9]{10,11}$'
   OR p_email IS NULL OR p_email<>lower(btrim(p_email)) OR p_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' THEN
  RAISE EXCEPTION 'cadastro_publico_identidade_invalida' USING ERRCODE='22023';
 END IF;
 SELECT coalesce(array_agg(id),'{}') INTO v_by_tiktok FROM interno.creators WHERE lower(ltrim(btrim(tiktok),'@'))=p_tiktok;
 SELECT coalesce(array_agg(id),'{}') INTO v_by_phone FROM interno.creators WHERE whatsapp=p_whatsapp OR telefone=p_whatsapp;
 SELECT coalesce(array_agg(id),'{}') INTO v_by_email FROM interno.creators WHERE lower(btrim(email))=p_email;
 IF cardinality(v_by_tiktok)>1 OR cardinality(v_by_phone)>1 OR cardinality(v_by_email)>1 THEN
  RETURN jsonb_build_object('status','conferencia','reason','identidade_ambigua');
 END IF;
 SELECT coalesce(array_agg(DISTINCT x),'{}') INTO v_ids FROM unnest(v_by_tiktok||v_by_phone) x;
 IF cardinality(v_ids)>1 THEN
  RETURN jsonb_build_object('status','conferencia','reason','perfil_e_whatsapp_em_fichas_diferentes');
 END IF;
 IF cardinality(v_ids)=0 THEN
  IF cardinality(v_by_email)=1 THEN RETURN jsonb_build_object('status','conferencia','reason','email_em_outra_ficha'); END IF;
  RETURN jsonb_build_object('status','nova');
 END IF;
 SELECT * INTO c FROM interno.creators WHERE id=v_ids[1];
 -- Achou pelo WhatsApp, mas a ficha já tem outro @: nunca troca o perfil sem conferência.
 IF nullif(btrim(c.tiktok),'') IS NOT NULL AND lower(ltrim(btrim(c.tiktok),'@'))<>p_tiktok THEN
  RETURN jsonb_build_object('status','conferencia','reason','perfil_divergente');
 END IF;
 -- Achou pelo @, mas a ficha é de outro WhatsApp: quem digita o @ de outra pessoa não assume a ficha.
 IF (c.whatsapp IS NOT NULL OR c.telefone IS NOT NULL)
   AND c.whatsapp IS DISTINCT FROM p_whatsapp AND c.telefone IS DISTINCT FROM p_whatsapp THEN
  RETURN jsonb_build_object('status','conferencia','reason','contato_divergente');
 END IF;
 IF cardinality(v_by_email)=1 AND v_by_email[1]<>c.id THEN
  RETURN jsonb_build_object('status','conferencia','reason','email_em_outra_ficha');
 END IF;
 IF c.cadastro_situacao='confirmado' THEN RETURN jsonb_build_object('status','ja_cadastrado'); END IF;
 RETURN jsonb_build_object('status','existente','creator_id',c.id);
END;
$resolver$;

-- Pré-checagem da primeira etapa. Não grava e não devolve o id da ficha.
CREATE FUNCTION public.consultar_cadastro_publico_v5(p_tiktok text,p_whatsapp text,p_email text)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER SET search_path='' AS $consulta$
BEGIN
 IF current_user<>'service_role' THEN RAISE EXCEPTION 'cadastro_publico_service_role_obrigatorio' USING ERRCODE='42501'; END IF;
 RETURN interno.cadastro_publico_resolver(p_tiktok,p_whatsapp,p_email)-'creator_id';
END;
$consulta$;

CREATE FUNCTION public.registrar_cadastro_publico_v5(p_payload jsonb, p_context jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $function$
declare
  v_map jsonb := $mapping${"version":"atendimento-v5-ensaio-data-1","form_version":"amplify-cadastro-v2","consent_version":"2026-09-09-v1","fields":[{"id":"nome","table":"creators","column":"nome","type":"text","conversion":"text"},{"id":"email","table":"creators","column":"email","type":"email","conversion":"email"},{"id":"whatsapp","table":"creators","column":"whatsapp","type":"phone_number","conversion":"phone_number"},{"id":"foto_perfil","table":"creators_perfil","column":"foto_perfil_referencia","type":"file","conversion":"private_file"},{"id":"mini_bio","table":"creators_perfil","column":"mini_bio","type":"textarea","conversion":"textarea"},{"id":"canal_origem","table":"creators_aquisicao","column":"origem_informada_formulario","type":"select","conversion":"select","options":["Conheci no instagram","Conheci no TikTok","Me indicaram","Entraram em contato comigo","Outro jeito"]},{"id":"origem_outro","table":"creators_aquisicao","column":"origem_outro","type":"text","conversion":"text","condition":{"field":"canal_origem","equals":"Outro jeito"}},{"id":"expectativas","table":"creators_perfil","column":"expectativas","type":"textarea","conversion":"textarea"},{"id":"meta_renda_mensal","table":"creators_perfil","column":"meta_renda_mensal","type":"number","conversion":"decimal"},{"id":"contexto_adicional","table":"creators_perfil","column":"contexto_adicional","type":"textarea","conversion":"textarea"},{"id":"plataformas","table":"creators_perfil","column":"plataformas","type":"multi_select","conversion":"multi_select","options":["TikTok","Instagram","YouTube","Shopee","Mercado Livre","Amazon","Shein","Outros"]},{"id":"instagram","table":"creators_perfil","column":"instagram","type":"text","conversion":"text","condition":{"field":"plataformas","includes":"Instagram"}},{"id":"plataformas_outros","table":"creators_perfil","column":"plataformas_outros","type":"text","conversion":"text","condition":{"field":"plataformas","includes":"Outros"}},{"id":"experiencia_live_shop","table":"creators_perfil","column":"experiencia_live_shop","type":"select","conversion":"select","options":["Nenhuma","Básico","Intermediário","Avançado"]},{"id":"agencia_anterior","table":"creators_perfil","column":"teve_agencia_anterior","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"nome_agencia_anterior","table":"creators_perfil","column":"nome_agencia_anterior","type":"text","conversion":"text","condition":{"field":"agencia_anterior","equals":"Sim"}},{"id":"experiencia_agencia","table":"creators_perfil","column":"experiencia_agencia","type":"textarea","conversion":"textarea","condition":{"field":"agencia_anterior","equals":"Sim"}},{"id":"produtos_excluidos","table":"creators_perfil","column":"produtos_excluidos","type":"textarea","conversion":"textarea"},{"id":"gmv_declarado","table":"creators_gmv","column":"valor","type":"number","conversion":"decimal"},{"id":"inicio_amplify_informado","table":"creators_perfil","column":"inicio_amplify_informado","type":"date","conversion":"date"},{"id":"cpf","table":"creators_pagamentos","column":"cpf","type":"text","conversion":"cpf"},{"id":"nascimento","table":"creators_perfil","column":"data_nascimento","type":"date","conversion":"date"},{"id":"genero","table":"creators_perfil","column":"genero","type":"select","conversion":"select","options":["Masculino","Feminino","Prefiro não responder"]},{"id":"estado_civil","table":"creators_perfil","column":"estado_civil","type":"select","conversion":"select","options":["Solteiro","Namorando","Casado","Prefiro não informar"]},{"id":"camiseta","table":"creators_perfil","column":"camiseta","type":"select","conversion":"select","options":["P","M","G","GG","Outro"]},{"id":"camiseta_outro","table":"creators_perfil","column":"camiseta_outro","type":"text","conversion":"text","condition":{"field":"camiseta","equals":"Outro"}},{"id":"estado","table":"creators_enderecos","column":"endereco_estado","type":"select","conversion":"select","options":["Acre","Alagoas","Amapá","Amazonas","Bahia","Ceará","Distrito Federal","Espírito Santo","Goiás","Maranhão","Mato Grosso","Mato Grosso do Sul","Minas Gerais","Pará","Paraíba","Paraná","Pernambuco","Piauí","Rio de Janeiro","Rio Grande do Norte","Rio Grande do Sul","Rondônia","Roraima","Santa Catarina","São Paulo","Sergipe","Tocantins"]},{"id":"cidade","table":"creators_enderecos","column":"endereco_cidade","type":"text","conversion":"text"},{"id":"logradouro","table":"creators_enderecos","column":"endereco_logradouro","type":"text","conversion":"text"},{"id":"bairro","table":"creators_enderecos","column":"endereco_bairro","type":"text","conversion":"text"},{"id":"numero","table":"creators_enderecos","column":"endereco_numero","type":"text","conversion":"text"},{"id":"complemento","table":"creators_enderecos","column":"endereco_complemento","type":"text","conversion":"text"},{"id":"cep","table":"creators_enderecos","column":"endereco_cep","type":"text","conversion":"cep"},{"id":"pix","table":"creators_pagamentos","column":"pix_chave","type":"text","conversion":"text"},{"id":"possui_cnpj","table":"creators_pagamentos","column":"possui_cnpj","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"cnpj","table":"creators_pagamentos","column":"cnpj","type":"text","conversion":"cnpj","condition":{"field":"possui_cnpj","equals":"Sim"}},{"id":"nichos","table":"creators_perfil","column":"nichos","type":"multi_select","conversion":"multi_select","options":["Lifestyle","Tecnologia","Moda","Beleza","Fitness & Saúde","Viagens","Culinária & Gastronomia","Educação & Conhecimento","Casa e Decoração","Gaming (Jogos)","Pets","Família & Parentalidade","Negócios & Empreendedorismo","Eletrônicos","Outros"]},{"id":"nichos_outros","table":"creators_perfil","column":"nichos_outros","type":"text","conversion":"text","condition":{"field":"nichos","includes":"Outros"}},{"id":"rotina","table":"creators_perfil","column":"rotina","type":"select","conversion":"select","options":["Tenho outro trabalho além de criar conteúdo","Me dedico 100% ao conteúdo","Outro"]},{"id":"rotina_outro","table":"creators_perfil","column":"rotina_outro","type":"textarea","conversion":"textarea","condition":{"field":"rotina","equals":"Outro"}},{"id":"tem_filhos","table":"creators_oportunidades","column":"tem_filhos","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"cabelo","table":"creators_perfil","column":"cabelo","type":"select","conversion":"select","options":["liso","Ondulado","Cacheado","Crespo","Sem cabelo","Prefiro não informar"]},{"id":"calcado","table":"creators_perfil","column":"calcado","type":"number","conversion":"decimal"},{"id":"cor_raca","table":"creators_oportunidades","column":"cor_raca","type":"select","conversion":"select","options":["Branca","Parda","Preta","Amarela (descendentes de asiáticos)","Indígena","Prefiro não informar"]},{"id":"alimentacao","table":"creators_oportunidades","column":"alimentacao","type":"select","conversion":"select","options":["Sem restrições (como de tudo)","Vegetariano/Vegano (não come carne)","Tenho restrições alimentares (especificar)"]},{"id":"restricao_alimentar","table":"creators_oportunidades","column":"restricao_alimentar","type":"text","conversion":"text","condition":{"field":"alimentacao","equals":"Tenho restrições alimentares (especificar)"}},{"id":"casa_praia_campo","table":"creators_oportunidades","column":"casa_praia_campo","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"carro","table":"creators_oportunidades","column":"carro","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"moto","table":"creators_oportunidades","column":"moto","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"celular","table":"creators_oportunidades","column":"celular","type":"select","conversion":"select","options":["iPhone","Android","Ambos","Outros"]},{"id":"computador","table":"creators_oportunidades","column":"computador","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"tripe","table":"creators_oportunidades","column":"tripe","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"microfone","table":"creators_oportunidades","column":"microfone","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"academia","table":"creators_oportunidades","column":"academia","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"tem_pet","table":"creators_oportunidades","column":"tem_pet","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"pets","table":"creators_oportunidades","column":"pets","type":"text","conversion":"text","condition":{"field":"tem_pet","equals":"Sim"}},{"id":"outro_idioma","table":"creators_oportunidades","column":"outro_idioma","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"video_idioma","table":"creators_oportunidades","column":"video_idioma","type":"url","conversion":"url","condition":{"field":"outro_idioma","equals":"Sim"}},{"id":"idiomas","table":"creators_oportunidades","column":"idiomas","type":"multi_select","conversion":"multi_select","options":["Inglês","Espanhol","Francês","Alemão","Italiano","Japonês","Mandarim (Chinês)","Coreano","Árabe","Russo","Hindi","Outros"],"condition":{"field":"outro_idioma","equals":"Sim"}},{"id":"idiomas_outros","table":"creators_oportunidades","column":"idiomas_outros","type":"text","conversion":"text","condition":{"field":"idiomas","includes":"Outros"}},{"id":"mais_2000_seguidores","table":"creators_perfil","column":"declarou_mais_2000_seguidores","type":"select","conversion":"boolean","options":["Sim","Não"]},{"id":"print_gmv","table":"creators_gmv","column":"comprovante_referencia","type":"file","conversion":"private_file"},{"id":"tiktok","table":"creators","column":"tiktok","type":"text","conversion":"tiktok"}]}$mapping$::jsonb;
  v_creator uuid; v_event uuid; v_form uuid; v_bytes bytea; v_expected uuid;
  v_received timestamptz; v_at timestamptz; v_day date;
  v_field jsonb; v_section jsonb; v_value jsonb; v_parent jsonb; v_condition jsonb;
  v_answers jsonb := '{}'::jsonb; v_context_item jsonb; v_visible boolean;
  v_name text; v_table text; v_column text; v_conversion text; v_text text;
  v_number numeric; v_cpf text; v_index integer; v_length integer; v_sum integer; v_digit integer;
  v_allowed text[]; v_expected_reference text;
  v_fingerprint text; v_saved interno.eventos%rowtype; v_flat jsonb; v_ref text;
  v_identity jsonb; v_atendimento uuid; v_email_confirmed timestamptz;
  v_rel jsonb; v_rel_ev jsonb; v_rel_at timestamptz; v_agency interno.agenciamentos%rowtype;
  v_print jsonb; v_print_value numeric; v_print_start date; v_print_end date; v_print_at timestamptz;
  v_gmv_id bigint; v_period text; v_result jsonb;
  v_tiktok text; v_phone text; v_email text;
  v_previous text := coalesce(current_setting('app.v5_explicit_event',true),'off');
begin
  if current_user <> 'service_role' then
    raise exception using errcode='42501',message='cadastro_publico_service_role_obrigatorio';
  end if;
  if jsonb_typeof(p_payload) is distinct from 'object'
     or (select count(*) from jsonb_object_keys(p_payload)) <> 6
     or not p_payload ?& array['mapping_version','form_version','identity','branches','gmv','consent']
     or p_payload->>'mapping_version' is distinct from v_map->>'version'
     or p_payload->>'form_version' is distinct from v_map->>'form_version' then
    raise exception using errcode='22023',message='cadastro_publico_payload_invalido';
  end if;
  if jsonb_typeof(p_context) is distinct from 'object'
     or (select count(*) from jsonb_object_keys(p_context)) <> 8
     or not p_context ?& array['event_id','form_instance_id','received_at','source','attachments',
       'email_confirmation','relationship','gmv_print'] then
    raise exception using errcode='22023',message='cadastro_publico_contexto_invalido';
  end if;
  v_event := (p_context->>'event_id')::uuid;
  v_form := (p_context->>'form_instance_id')::uuid;
  if v_event is null or v_form is null or v_form='00000000-0000-0000-0000-000000000000'::uuid
     or p_context->>'event_id' <> v_event::text or p_context->>'form_instance_id' <> v_form::text then
    raise exception using errcode='22023',message='cadastro_publico_identificadores_invalidos';
  end if;
  -- Um envio por formulário: o id do envio deriva só do formulário (UUID3), então
  -- repetir o mesmo envio devolve o recibo anterior em vez de criar outra ficha.
  v_bytes := decode(md5(convert_to('amplify-cadastro-publico-v5|'||v_form::text,'UTF8')),'hex');
  v_bytes := set_byte(v_bytes,6,(get_byte(v_bytes,6)&15)|48);
  v_bytes := set_byte(v_bytes,8,(get_byte(v_bytes,8)&63)|128);
  v_expected := encode(v_bytes,'hex')::uuid;
  if v_event <> v_expected then
    raise exception using errcode='22023',message='cadastro_publico_evento_nao_corresponde_ao_formulario';
  end if;
  if coalesce(p_context->>'received_at','') !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$' then
    raise exception using errcode='22023',message='cadastro_publico_data_recebimento_invalida';
  end if;
  v_received := (p_context->>'received_at')::timestamptz;
  if not isfinite(v_received) then
    raise exception using errcode='22023',message='cadastro_publico_data_recebimento_invalida';
  end if;
  v_day := (v_received at time zone 'UTC')::date;
  v_section := p_context->'source';
  if jsonb_typeof(v_section) is distinct from 'object'
     or (select count(*) from jsonb_object_keys(v_section))<>2
     or not v_section ?& array['kind','reference']
     or v_section->>'kind' is distinct from 'formulario_publico' then
    raise exception using errcode='22023',message='cadastro_publico_fonte_invalida';
  end if;
  v_text := v_section->>'reference';
  if v_text is null or v_text !~ '^[A-Za-z0-9][A-Za-z0-9:_./-]{0,239}$' or position('://' in v_text)>0 or position('..' in v_text)>0 then
    raise exception using errcode='22023',message='cadastro_publico_referencia_fonte_invalida';
  end if;
  if jsonb_typeof(p_payload->'consent') is distinct from 'object'
     or p_payload->'consent' <> jsonb_build_object('accepted',true,'version',v_map->>'consent_version') then
    raise exception using errcode='22023',message='cadastro_publico_consentimento_obrigatorio';
  end if;

  -- Cada chave de destino deve corresponder exatamente ao mapa de 63 campos.
  if jsonb_typeof(p_payload->'branches') is distinct from 'object'
     or (select count(*) from jsonb_object_keys(p_payload->'branches'))<>6
     or not (p_payload->'branches') ?& array['creators_aquisicao','creators_perfil','creators_oportunidades','creators_enderecos','creators_pagamentos','creators_circle'] then
    raise exception using errcode='22023',message='cadastro_publico_ramificacoes_invalidas';
  end if;
  foreach v_table in array array['creators','creators_aquisicao','creators_perfil','creators_oportunidades','creators_enderecos','creators_pagamentos','creators_circle','creators_gmv'] loop
    v_section := case v_table when 'creators' then p_payload->'identity'
      when 'creators_gmv' then p_payload->'gmv' else p_payload->'branches'->v_table end;
    select coalesce(array_agg(f->>'column'),'{}'::text[]) into v_allowed
      from jsonb_array_elements(v_map->'fields') f where f->>'table'=v_table;
    if jsonb_typeof(v_section) is distinct from 'object'
       or (select count(*) from jsonb_object_keys(v_section))<>cardinality(v_allowed)
       or not v_section ?& v_allowed then
      raise exception using errcode='22023',message='cadastro_publico_campos_de_destino_invalidos:'||v_table;
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
        raise exception using errcode='22023',message='cadastro_publico_campo_fora_da_condicao:'||v_name;
      end if;
      v_answers := v_answers||jsonb_build_object(v_name,null); continue;
    end if;
    if v_value is null or v_value='null'::jsonb then
      raise exception using errcode='22023',message='cadastro_publico_campo_obrigatorio:'||v_name;
    end if;
    if v_conversion='boolean' then
      if jsonb_typeof(v_value)<>'boolean' then
        raise exception using errcode='22023',message='cadastro_publico_booleano_invalido:'||v_name;
      end if;
      v_answers := v_answers||jsonb_build_object(v_name,case when v_value='true'::jsonb then 'Sim' else 'Não' end);
    elsif v_conversion='multi_select' then
      if jsonb_typeof(v_value)<>'array' then
        raise exception using errcode='22023',message='cadastro_publico_lista_invalida:'||v_name;
      end if;
      if jsonb_array_length(v_value)=0
         or exists(select 1 from jsonb_array_elements(v_value) x where jsonb_typeof(x)<>'string' or not (v_field->'options') @> jsonb_build_array(x))
         or (select count(*) from jsonb_array_elements(v_value))<>(select count(distinct x) from jsonb_array_elements(v_value) x) then
        raise exception using errcode='22023',message='cadastro_publico_opcoes_invalidas:'||v_name;
      end if;
      v_answers := v_answers||jsonb_build_object(v_name,v_value);
    else
      if jsonb_typeof(v_value)<>'string' then
        raise exception using errcode='22023',message='cadastro_publico_texto_invalido:'||v_name;
      end if;
      v_text := v_value#>>'{}';
      if v_text='' or v_text<>btrim(v_text) or length(v_text)>(case when v_conversion='textarea' then 2000 else 254 end) then
        raise exception using errcode='22023',message='cadastro_publico_texto_invalido:'||v_name;
      end if;
      if v_conversion='decimal' then
        if v_text !~ '^\d+(\.\d{1,2})?$' then
          raise exception using errcode='22023',message='cadastro_publico_numero_invalido:'||v_name;
        end if;
        v_number := v_text::numeric;
        if v_number<0 or v_number>1000000000
           or (v_name='calcado' and (v_number>999.9 or v_number<>round(v_number,1))) then
          raise exception using errcode='22023',message='cadastro_publico_numero_invalido:'||v_name;
        end if;
      elsif v_conversion='date' then
        if v_text !~ '^\d{4}-\d{2}-\d{2}$' or v_text::date<'1900-01-01'::date or v_text::date>v_day then
          raise exception using errcode='22023',message='cadastro_publico_data_invalida:'||v_name;
        end if;
      elsif v_conversion='email' then
        if v_text<>lower(v_text) or v_text !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' then
          raise exception using errcode='22023',message='cadastro_publico_email_invalido';
        end if;
      elsif v_conversion='phone_number' then
        if v_text !~ '^55[0-9]{10,11}$' then raise exception using errcode='22023',message='cadastro_publico_telefone_invalido'; end if;
      elsif v_conversion='tiktok' then
        if v_text !~ '^[a-z0-9._]{2,24}$' then raise exception using errcode='22023',message='cadastro_publico_tiktok_invalido'; end if;
      elsif v_conversion='cep' then
        if v_text !~ '^[0-9]{8}$' then raise exception using errcode='22023',message='cadastro_publico_cep_invalido'; end if;
      elsif v_conversion='cnpj' then
        if v_text !~ '^[A-Z0-9]{12}[0-9]{2}$' then raise exception using errcode='22023',message='cadastro_publico_cnpj_invalido'; end if;
      elsif v_conversion='cpf' then
        v_cpf := v_text;
        if v_cpf !~ '^[0-9]{11}$' or v_cpf=repeat(substr(v_cpf,1,1),11) then
          raise exception using errcode='22023',message='cadastro_publico_cpf_invalido';
        end if;
        for v_length in 9..10 loop
          v_sum := 0;
          for v_index in 1..v_length loop v_sum:=v_sum+substr(v_cpf,v_index,1)::integer*(v_length+2-v_index); end loop;
          v_digit := ((v_sum*10)%11)%10;
          if v_digit<>substr(v_cpf,v_length+1,1)::integer then raise exception using errcode='22023',message='cadastro_publico_cpf_invalido'; end if;
        end loop;
      elsif v_conversion='url' then
        if v_text !~ '^https://[^/@[:space:]]+(/[^[:space:]]*)?$' then raise exception using errcode='22023',message='cadastro_publico_url_invalida:'||v_name; end if;
      elsif v_conversion='private_file' then
        if v_text !~ '^[A-Za-z0-9][A-Za-z0-9:_./-]{0,239}$' or position('://' in v_text)>0 or position('..' in v_text)>0 then
          raise exception using errcode='22023',message='cadastro_publico_arquivo_invalido:'||v_name;
        end if;
      end if;
      if v_field->>'type'='select' and v_conversion<>'boolean' and not (v_field->'options') @> jsonb_build_array(v_text) then
        raise exception using errcode='22023',message='cadastro_publico_opcao_invalida:'||v_name;
      end if;
      v_answers := v_answers||jsonb_build_object(v_name,v_value);
    end if;
  end loop;

  -- Somente atestados de upload, sem o recibo/token original no argumento SQL.
  v_section := p_context->'attachments';
  if jsonb_typeof(v_section) is distinct from 'object' or (select count(*) from jsonb_object_keys(v_section))<>2 or not v_section ?& array['foto_perfil','print_gmv'] then
    raise exception using errcode='22023',message='cadastro_publico_anexos_invalidos';
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
      raise exception using errcode='22023',message='cadastro_publico_anexo_nao_validado:'||v_name;
    end if;
  end loop;

  v_tiktok := p_payload->'identity'->>'tiktok';
  v_phone := p_payload->'identity'->>'whatsapp';
  v_email := p_payload->'identity'->>'email';

  -- E-mail confirmado por código nesta sessão do formulário.
  v_context_item := p_context->'email_confirmation';
  if jsonb_typeof(v_context_item) is distinct from 'object'
     or (select count(*) from jsonb_object_keys(v_context_item))<>4
     or not v_context_item ?& array['at','source','reference','email_sha256']
     or v_context_item->>'source' is distinct from 'email_token_validado'
     or v_context_item->>'email_sha256' is distinct from encode(sha256(convert_to(v_email,'UTF8')),'hex')
     or coalesce(v_context_item->>'reference','') !~ '^[A-Za-z0-9][A-Za-z0-9:_./-]{0,239}$'
     or coalesce(v_context_item->>'at','') !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$' then
    raise exception using errcode='22023',message='cadastro_publico_email_nao_confirmado';
  end if;
  v_email_confirmed := (v_context_item->>'at')::timestamptz;
  if not isfinite(v_email_confirmed) or v_email_confirmed>v_received or v_email_confirmed<v_received-interval '7 days' then
    raise exception using errcode='22023',message='cadastro_publico_email_nao_confirmado';
  end if;

  -- Vínculo conferido AO VIVO no Partner Center pela ponte de agenciamento.
  -- Pendente, não encontrado, leitura parcial ou outro @ nunca passam.
  v_rel := p_context->'relationship';
  if jsonb_typeof(v_rel) is distinct from 'object'
     or (select count(*) from jsonb_object_keys(v_rel))<>7
     or not v_rel ?& array['operation','creator','observed_at','status','confirmed','job_id','evidence']
     or v_rel->'operation' is distinct from '"relationship"'::jsonb
     or v_rel->'status' is distinct from '"linked"'::jsonb
     or v_rel->'confirmed' is distinct from 'true'::jsonb
     or v_rel->'creator' is distinct from to_jsonb('@'||v_tiktok)
     or jsonb_typeof(v_rel->'job_id') is distinct from 'string'
     or coalesce(v_rel->>'job_id','') !~ '^[A-Za-z0-9][A-Za-z0-9:_./-]{0,239}$'
     or position('://' in v_rel->>'job_id')>0 or position('..' in v_rel->>'job_id')>0
     or jsonb_typeof(v_rel->'observed_at') is distinct from 'string'
     or coalesce(v_rel->>'observed_at','') !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$' then
    raise exception using errcode='22023',message='cadastro_publico_vinculo_obrigatorio';
  end if;
  v_rel_at := (v_rel->>'observed_at')::timestamptz;
  if not isfinite(v_rel_at) or v_rel_at>v_received or v_rel_at<v_received-interval '24 hours' then
    raise exception using errcode='22023',message='cadastro_publico_vinculo_vencido';
  end if;
  v_rel_ev := v_rel->'evidence';
  if jsonb_typeof(v_rel_ev) is distinct from 'object'
     or octet_length(v_rel_ev::text)>8192
     or v_rel_ev->'source' is distinct from '"partner_relations"'::jsonb
     or v_rel_ev->'status' is distinct from '"vinculado"'::jsonb
     or v_rel_ev->'fresh' is distinct from 'true'::jsonb
     or v_rel_ev->'complete' is distinct from 'true'::jsonb
     or v_rel_ev->'tiktok_status' is distinct from '1'::jsonb
     or jsonb_typeof(v_rel_ev->'relation_id') is distinct from 'string'
     or coalesce(v_rel_ev->>'relation_id','') !~ '^[A-Za-z0-9][A-Za-z0-9:_-]{0,199}$' then
    raise exception using errcode='22023',message='cadastro_publico_vinculo_evidencia_invalida';
  end if;

  -- Leitura automática do print de GMV: sempre "declarado" (nunca "verificado"),
  -- e indisponível fica sem valor (nunca vira zero).
  v_print := p_context->'gmv_print';
  if jsonb_typeof(v_print) is distinct from 'object'
     or (select count(*) from jsonb_object_keys(v_print))<>8
     or not v_print ?& array['situacao','valor','moeda','periodo_inicio','periodo_fim','leitor','lido_em','motivo']
     or coalesce(v_print->>'situacao','') not in ('lido','indisponivel')
     or coalesce(v_print->>'leitor','') !~ '^[A-Za-z0-9][A-Za-z0-9:_./-]{0,119}$'
     or coalesce(v_print->>'lido_em','') !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$' then
    raise exception using errcode='22023',message='cadastro_publico_leitura_print_invalida';
  end if;
  v_print_at := (v_print->>'lido_em')::timestamptz;
  if not isfinite(v_print_at) or v_print_at>v_received+interval '5 minutes' or v_print_at<v_received-interval '7 days' then
    raise exception using errcode='22023',message='cadastro_publico_leitura_print_invalida';
  end if;
  if v_print->>'situacao'='lido' then
    if jsonb_typeof(v_print->'valor') is distinct from 'string' or v_print->>'valor' !~ '^\d{1,10}(\.\d{1,2})?$'
       or jsonb_typeof(v_print->'moeda') is distinct from 'string' or v_print->>'moeda' !~ '^[A-Z]{3}$'
       or v_print->'motivo' is distinct from 'null'::jsonb then
      raise exception using errcode='22023',message='cadastro_publico_leitura_print_invalida';
    end if;
    v_print_value := (v_print->>'valor')::numeric;
    if v_print_value>1000000000 then raise exception using errcode='22023',message='cadastro_publico_leitura_print_invalida'; end if;
    if (v_print->'periodo_inicio'='null'::jsonb) <> (v_print->'periodo_fim'='null'::jsonb) then
      raise exception using errcode='22023',message='cadastro_publico_leitura_print_periodo_invalido';
    end if;
    if v_print->'periodo_inicio'<>'null'::jsonb then
      if coalesce(v_print->>'periodo_inicio','') !~ '^\d{4}-\d{2}-\d{2}$' or coalesce(v_print->>'periodo_fim','') !~ '^\d{4}-\d{2}-\d{2}$' then
        raise exception using errcode='22023',message='cadastro_publico_leitura_print_periodo_invalido';
      end if;
      v_print_start := (v_print->>'periodo_inicio')::date; v_print_end := (v_print->>'periodo_fim')::date;
      if v_print_end<v_print_start or v_print_end>v_day or v_print_end-v_print_start>366 then
        raise exception using errcode='22023',message='cadastro_publico_leitura_print_periodo_invalido';
      end if;
    end if;
  elsif v_print->'valor'<>'null'::jsonb or v_print->'periodo_inicio'<>'null'::jsonb or v_print->'periodo_fim'<>'null'::jsonb
        or coalesce(v_print->>'motivo','') !~ '^[a-z][a-z0-9_]{0,79}$' then
    raise exception using errcode='22023',message='cadastro_publico_leitura_print_invalida';
  end if;

  -- Mesmas travas das RPCs da Bia (ficha antes de atendimento); nenhuma chamada externa aqui.
  perform pg_advisory_xact_lock(hashtextextended('v5:cadastro',0));
  v_fingerprint := encode(sha256(convert_to(p_payload::text||E'\n'||p_context::text,'UTF8')),'hex');
  select * into v_saved from interno.eventos where submissao_id=v_event;
  if found then
    if v_saved.payload_sha256<>v_fingerprint then
      raise exception 'cadastro_publico_envio_conflitante' using errcode='23505'; end if;
    return v_saved.resultado||jsonb_build_object('replayed',true);
  end if;

  v_identity := interno.cadastro_publico_resolver(v_tiktok,v_phone,v_email);
  if v_identity->>'status'='conferencia' then
    raise exception using errcode='23505',message='cadastro_publico_conferencia:'||(v_identity->>'reason');
  elsif v_identity->>'status'='ja_cadastrado' then
    raise exception using errcode='23505',message='cadastro_publico_ja_cadastrado';
  elsif v_identity->>'status'='existente' then
    v_creator := (v_identity->>'creator_id')::uuid;
    perform 1 from interno.creators where id=v_creator and cadastro_situacao='pendente' for update;
    if not found then raise exception using errcode='23505',message='cadastro_publico_ja_cadastrado'; end if;
    -- Lead que veio da Bia: liga o envio ao atendimento aberto mais recente da mesma ficha.
    select id into v_atendimento from interno.atendimentos
      where creator_id=v_creator and situacao='aberto' order by atualizado_em desc limit 1;
  else
    v_creator := gen_random_uuid();
  end if;

  v_flat:=p_payload->'identity';
  for v_table in select jsonb_object_keys(p_payload->'branches') loop
    v_flat:=v_flat||(p_payload->'branches'->v_table);
  end loop;
  perform set_config('app.v5_explicit_event','on',true);
  insert into interno.creators(id,nome,email,whatsapp,foto_perfil_referencia,mini_bio,origem_informada_formulario,origem_outro,expectativas,meta_renda_mensal,contexto_adicional,plataformas,instagram,plataformas_outros,experiencia_live_shop,teve_agencia_anterior,nome_agencia_anterior,experiencia_agencia,produtos_excluidos,inicio_amplify_informado,cpf,data_nascimento,genero,estado_civil,camiseta,camiseta_outro,endereco_estado,endereco_cidade,endereco_logradouro,endereco_bairro,endereco_numero,endereco_complemento,endereco_cep,pix_chave,possui_cnpj,cnpj,nichos,nichos_outros,rotina,rotina_outro,tem_filhos,cabelo,calcado,cor_raca,alimentacao,restricao_alimentar,casa_praia_campo,carro,moto,celular,computador,tripe,microfone,academia,tem_pet,pets,outro_idioma,video_idioma,idiomas,idiomas_outros,declarou_mais_2000_seguidores,tiktok)
  select v_creator,r.nome,r.email,r.whatsapp,r.foto_perfil_referencia,r.mini_bio,r.origem_informada_formulario,r.origem_outro,r.expectativas,r.meta_renda_mensal,r.contexto_adicional,r.plataformas,r.instagram,r.plataformas_outros,r.experiencia_live_shop,r.teve_agencia_anterior,r.nome_agencia_anterior,r.experiencia_agencia,r.produtos_excluidos,r.inicio_amplify_informado,r.cpf,r.data_nascimento,r.genero,r.estado_civil,r.camiseta,r.camiseta_outro,r.endereco_estado,r.endereco_cidade,r.endereco_logradouro,r.endereco_bairro,r.endereco_numero,r.endereco_complemento,r.endereco_cep,r.pix_chave,r.possui_cnpj,r.cnpj,r.nichos,r.nichos_outros,r.rotina,r.rotina_outro,r.tem_filhos,r.cabelo,r.calcado,r.cor_raca,r.alimentacao,r.restricao_alimentar,r.casa_praia_campo,r.carro,r.moto,r.celular,r.computador,r.tripe,r.microfone,r.academia,r.tem_pet,r.pets,r.outro_idioma,r.video_idioma,r.idiomas,r.idiomas_outros,r.declarou_mais_2000_seguidores,r.tiktok
  from jsonb_populate_record(null::interno.creators,v_flat) r
  on conflict(id) do update set nome=excluded.nome,email=excluded.email,whatsapp=excluded.whatsapp,foto_perfil_referencia=excluded.foto_perfil_referencia,mini_bio=excluded.mini_bio,origem_informada_formulario=excluded.origem_informada_formulario,origem_outro=excluded.origem_outro,expectativas=excluded.expectativas,meta_renda_mensal=excluded.meta_renda_mensal,contexto_adicional=excluded.contexto_adicional,plataformas=excluded.plataformas,instagram=excluded.instagram,plataformas_outros=excluded.plataformas_outros,experiencia_live_shop=excluded.experiencia_live_shop,teve_agencia_anterior=excluded.teve_agencia_anterior,nome_agencia_anterior=excluded.nome_agencia_anterior,experiencia_agencia=excluded.experiencia_agencia,produtos_excluidos=excluded.produtos_excluidos,inicio_amplify_informado=excluded.inicio_amplify_informado,cpf=excluded.cpf,data_nascimento=excluded.data_nascimento,genero=excluded.genero,estado_civil=excluded.estado_civil,camiseta=excluded.camiseta,camiseta_outro=excluded.camiseta_outro,endereco_estado=excluded.endereco_estado,endereco_cidade=excluded.endereco_cidade,endereco_logradouro=excluded.endereco_logradouro,endereco_bairro=excluded.endereco_bairro,endereco_numero=excluded.endereco_numero,endereco_complemento=excluded.endereco_complemento,endereco_cep=excluded.endereco_cep,pix_chave=excluded.pix_chave,possui_cnpj=excluded.possui_cnpj,cnpj=excluded.cnpj,nichos=excluded.nichos,nichos_outros=excluded.nichos_outros,rotina=excluded.rotina,rotina_outro=excluded.rotina_outro,tem_filhos=excluded.tem_filhos,cabelo=excluded.cabelo,calcado=excluded.calcado,cor_raca=excluded.cor_raca,alimentacao=excluded.alimentacao,restricao_alimentar=excluded.restricao_alimentar,casa_praia_campo=excluded.casa_praia_campo,carro=excluded.carro,moto=excluded.moto,celular=excluded.celular,computador=excluded.computador,tripe=excluded.tripe,microfone=excluded.microfone,academia=excluded.academia,tem_pet=excluded.tem_pet,pets=excluded.pets,outro_idioma=excluded.outro_idioma,video_idioma=excluded.video_idioma,idiomas=excluded.idiomas,idiomas_outros=excluded.idiomas_outros,declarou_mais_2000_seguidores=excluded.declarou_mais_2000_seguidores,tiktok=excluded.tiktok;
  v_ref := 'cadastro-publico-v5:'||v_event::text||':'||v_fingerprint;
  update interno.creators c set canal_entrada=coalesce(c.canal_entrada,'formulario_publico'),
    formulario_situacao='recebido_formulario_publico',formulario_recebido_em=v_received,formulario_versao=p_payload->>'form_version',
    formulario_submissao_referencia=v_ref,consentimento_aceito_em=v_received,consentimento_versao=p_payload->'consent'->>'version',
    email_confirmado_em=v_email_confirmed,cadastro_situacao='confirmado',cadastro_revisao=c.cadastro_revisao+1,
    etapa_atual='cadastro_confirmado',situacao_atual='cadastro_confirmado'
    where c.id=v_creator;

  -- Agenciamento: mesma regra da RPC de contato (um vínculo ativo por pessoa).
  select * into v_agency from interno.agenciamentos where creator_id=v_creator and situacao='confirmado' for update;
  if found and v_agency.tiktok_observado is not null
     and lower(ltrim(v_agency.tiktok_observado,'@'))<>v_tiktok then
    raise exception using errcode='23505',message='cadastro_publico_vinculo_outro_perfil';
  end if;
  if found then
    update interno.agenciamentos set verificado_em=greatest(verificado_em,v_rel_at),
      tiktok_observado=coalesce(tiktok_observado,v_rel->>'creator') where id=v_agency.id;
  else
    insert into interno.agenciamentos(creator_id,fonte,confirmado_em,verificado_em,confirmacao_referencia,tiktok_observado,conta_referencia,situacao)
      values(v_creator,'tiktok_partner_center',v_rel_at,v_rel_at,v_rel->>'job_id',v_rel->>'creator','formulario_publico','confirmado');
  end if;

  -- GMV de entrada: o banco aceita UMA linha 'entrada' por natureza (índice
  -- gmv_uma_entrada_por_natureza_idx). valor = o que a pessoa digitou; comprovante = o print.
  -- creators.gmv_entrada_id NÃO é tocado: ele só aponta para GMV verificado (categoria do Circle).
  insert into interno.gmv(creator_id,atendimento_id,finalidade,natureza,periodicidade,periodo_inicio,periodo_fim,
    valor,moeda,situacao,fonte,observado_em,comprovante_referencia)
  values(v_creator,v_atendimento,'entrada','declarado','nao_informado',null,null,(p_payload->'gmv'->>'valor')::numeric,
    'BRL','registrado','formulario_publico:'||v_event::text,v_received,p_payload->'gmv'->>'comprovante_referencia')
  on conflict (creator_id,natureza) where finalidade='entrada' do update set
    periodicidade=excluded.periodicidade,periodo_inicio=null,periodo_fim=null,valor=excluded.valor,moeda=excluded.moeda,
    situacao=excluded.situacao,fonte=excluded.fonte,observado_em=excluded.observado_em,
    comprovante_referencia=excluded.comprovante_referencia,atendimento_id=coalesce(excluded.atendimento_id,gmv.atendimento_id),
    motivo_correcao='formulario_publico:'||v_event::text
  returning id into v_gmv_id;

  -- Leitura automática do print: evento próprio 'gmv_atualizado' ligado a essa linha
  -- (o histórico do modelo novo fica em eventos). Sempre natureza 'declarado', nunca
  -- verificado; ilegível fica sem valor (nunca zero).
  v_period := null;
  if v_print->>'situacao'='lido' then
    v_period := case when v_print_start is null then 'nao_informado'
      when v_print_end=v_print_start+27 then 'janela_28_dias' else 'periodo_personalizado' end;
  end if;
  insert into interno.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,gmv_id,dados)
  values(v_creator,v_atendimento,'gmv_atualizado','formulario_publico',v_event::text,1,v_print_at,v_gmv_id,jsonb_build_object(
    'origem','leitura_print_gmv','natureza','declarado','situacao',v_print->>'situacao',
    'valor',v_print->'valor','moeda',v_print->'moeda','periodicidade',v_period,
    'periodo_inicio',v_print->'periodo_inicio','periodo_fim',v_print->'periodo_fim',
    'motivo',v_print->'motivo','leitor',v_print->>'leitor','comprovante_referencia',p_payload->'gmv'->>'comprovante_referencia',
    'valor_digitado',p_payload->'gmv'->>'valor',
    -- Diferença acima de 10% entre o digitado e o lido fica marcada para conferência.
    'diverge_do_digitado',case when v_print_value is null then null
      else abs(v_print_value-(p_payload->'gmv'->>'valor')::numeric)>0.1*greatest(v_print_value,(p_payload->'gmv'->>'valor')::numeric) end));

  v_result := jsonb_build_object('creator_id',v_creator,'event_id',v_event,'gmv_id',v_gmv_id,
    'atendimento_id',v_atendimento,'ficha',case when v_identity->>'status'='existente' then 'existente' else 'nova' end,
    'status','cadastro_recebido','replayed',false);
  insert into interno.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,payload_sha256,
    formulario_id,submissao_id,gmv_id,dados,resultado)
  values(v_creator,v_atendimento,'cadastro_confirmado','formulario_publico',v_event::text,0,v_received,v_fingerprint,
    v_form,v_event,v_gmv_id,jsonb_build_object(
      'origem','formulario_publico',
      'vinculo',jsonb_build_object('job_id',v_rel->>'job_id','relation_id',v_rel_ev->>'relation_id','observado_em',v_rel->>'observed_at'),
      'leitura_print',jsonb_build_object('situacao',v_print->>'situacao','valor',v_print->'valor','motivo',v_print->'motivo','leitor',v_print->>'leitor')),
    v_result);
  perform set_config('app.v5_explicit_event',v_previous,true);
  return v_result;
end;
$function$;

-- Entrega do acesso no Circle (mesmo código do worker antigo, agora lendo o V5).
-- Estado da entrega em colunas e eventos que já existem: creators.circle_* e
-- eventos acesso_solicitado / acesso_entregue / email_aceito_provedor / email_falha.
-- Uma tentativa por cadastro: resultado incerto nunca é repetido sozinho (revisão manual).
CREATE FUNCTION public.preparar_entrega_circle_v5(p_evento uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $preparar$
DECLARE e interno.eventos%rowtype; c interno.creators%rowtype; v_gmv numeric; v_previous text:=coalesce(current_setting('app.v5_explicit_event',true),'off');
BEGIN
 IF current_user<>'service_role' THEN RAISE EXCEPTION 'cadastro_publico_service_role_obrigatorio' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('v5:cadastro',0));
 SELECT * INTO e FROM interno.eventos WHERE submissao_id=p_evento AND tipo='cadastro_confirmado' AND instancia='formulario_publico';
 IF NOT FOUND THEN RETURN jsonb_build_object('ready',false,'reason','cadastro_nao_encontrado'); END IF;
 IF EXISTS(SELECT 1 FROM interno.eventos WHERE instancia='formulario_publico' AND referencia=p_evento::text AND tipo='acesso_solicitado') THEN
  RETURN jsonb_build_object('ready',false,'reason','entrega_ja_iniciada');
 END IF;
 SELECT * INTO c FROM interno.creators WHERE id=e.creator_id FOR UPDATE;
 IF c.cadastro_situacao<>'confirmado' OR c.email IS NULL OR c.nome IS NULL THEN
  RETURN jsonb_build_object('ready',false,'reason','cadastro_incompleto'); END IF;
 -- Categoria: GMV de entrada VERIFICADO quando existir; senão o worker usa Start.
 SELECT valor INTO v_gmv FROM interno.gmv WHERE creator_id=c.id AND finalidade='entrada' AND natureza='verificado'
   AND situacao='registrado' AND valor IS NOT NULL;
 PERFORM set_config('app.v5_explicit_event','on',true);
 INSERT INTO interno.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,dados)
 VALUES(c.id,e.atendimento_id,'acesso_solicitado','formulario_publico',p_evento::text,2,statement_timestamp(),
   jsonb_build_object('origem','formulario_publico','gmv_verificado',v_gmv));
 UPDATE interno.creators SET circle_situacao='entrega_em_andamento' WHERE id=c.id;
 PERFORM set_config('app.v5_explicit_event',v_previous,true);
 RETURN jsonb_build_object('ready',true,'creator_id',c.id,'name',c.nome,'email',c.email,'gmv_verificado',v_gmv);
END;
$preparar$;

CREATE FUNCTION public.confirmar_entrega_circle_v5(p_evento uuid,p_etapa text,p_categoria text,p_circle_member_id bigint,
  p_email_message_id text,p_motivo text)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $confirmar$
DECLARE e interno.eventos%rowtype; v_rev integer; v_previous text:=coalesce(current_setting('app.v5_explicit_event',true),'off');
BEGIN
 IF current_user<>'service_role' THEN RAISE EXCEPTION 'cadastro_publico_service_role_obrigatorio' USING ERRCODE='42501'; END IF;
 IF p_etapa NOT IN ('circle_confirmado','email_confirmado','revisao_manual')
   OR (p_categoria IS NOT NULL AND p_categoria NOT IN ('Start','Silver','Gold','Diamond'))
   OR (p_etapa='circle_confirmado' AND (p_circle_member_id IS NULL OR p_circle_member_id<=0 OR p_categoria IS NULL))
   OR (p_motivo IS NOT NULL AND p_motivo !~ '^[A-Za-z][A-Za-z0-9_]{0,79}$')
   OR (p_email_message_id IS NOT NULL AND length(p_email_message_id)>200) THEN
  RAISE EXCEPTION 'entrega_circle_parametros_invalidos' USING ERRCODE='22023'; END IF;
 SELECT * INTO e FROM interno.eventos WHERE submissao_id=p_evento AND tipo='cadastro_confirmado' AND instancia='formulario_publico';
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM interno.eventos WHERE instancia='formulario_publico' AND referencia=p_evento::text AND tipo='acesso_solicitado') THEN
  RAISE EXCEPTION 'entrega_circle_nao_iniciada' USING ERRCODE='22023'; END IF;
 v_rev := CASE p_etapa WHEN 'circle_confirmado' THEN 3 WHEN 'email_confirmado' THEN 4 ELSE 5 END;
 PERFORM set_config('app.v5_explicit_event','on',true);
 INSERT INTO interno.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,dados)
 VALUES(e.creator_id,e.atendimento_id,
   CASE p_etapa WHEN 'circle_confirmado' THEN 'acesso_entregue' WHEN 'email_confirmado' THEN 'email_aceito_provedor' ELSE 'email_falha' END,
   'formulario_publico',p_evento::text,v_rev,statement_timestamp(),
   jsonb_strip_nulls(jsonb_build_object('etapa',p_etapa,'categoria',p_categoria,'circle_member_id',p_circle_member_id,
     'email_message_id',p_email_message_id,'motivo',p_motivo)))
 ON CONFLICT (instancia,referencia,revisao) DO NOTHING;
 IF p_etapa='circle_confirmado' THEN
  UPDATE interno.creators SET circle_situacao='acesso_criado',circle_categoria_entrada=p_categoria,
    circle_acesso_criado_em=coalesce(circle_acesso_criado_em,statement_timestamp()),circle_cargos_atribuidos_em=statement_timestamp(),
    acesso_referencia='circle:'||p_circle_member_id WHERE id=e.creator_id;
 ELSIF p_etapa='email_confirmado' THEN
  UPDATE interno.creators SET circle_situacao='acessos_liberados' WHERE id=e.creator_id;
 ELSE
  UPDATE interno.creators SET circle_situacao='revisao_manual' WHERE id=e.creator_id;
 END IF;
 PERFORM set_config('app.v5_explicit_event',v_previous,true);
 RETURN jsonb_build_object('ok',true,'etapa',p_etapa);
END;
$confirmar$;

REVOKE ALL ON FUNCTION public.preparar_entrega_circle_v5(uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.confirmar_entrega_circle_v5(uuid,text,text,bigint,text,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.preparar_entrega_circle_v5(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.confirmar_entrega_circle_v5(uuid,text,text,bigint,text,text) TO service_role;
REVOKE ALL ON FUNCTION interno.cadastro_publico_resolver(text,text,text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.consultar_cadastro_publico_v5(text,text,text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.registrar_cadastro_publico_v5(jsonb,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION interno.cadastro_publico_resolver(text,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.consultar_cadastro_publico_v5(text,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.registrar_cadastro_publico_v5(jsonb,jsonb) TO service_role;
COMMIT;
