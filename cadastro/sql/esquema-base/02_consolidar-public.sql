-- Alvo exclusivo: AmplifyOS-v5 / divlvdmsqbwplervsqwu.
-- Catalogo remoto capturado em 2026-10-28T05:12:26.18849+00:00; nenhuma linha e descartada.
-- SHA256 catalog-before.json: 9949cde4dd891898b4eed00c153845f4be97c49fdf0d147d6ed3f78bb6dc4208
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path=public,extensions,pg_catalog;
do $guard$
declare atual jsonb; t text; tem_linha boolean;
begin
 if current_user<>'postgres' then raise exception 'migration_requires_postgres' using errcode='42501'; end if;
 if (select array_agg(c.relname::text order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='public' and c.relkind in ('r','p')) is distinct from array['creators','creators_aquisicao','creators_circle','creators_conferencias','creators_contratos','creators_enderecos','creators_gmv','creators_oportunidades','creators_pagamentos','creators_perfil','creators_vinculos'] then
   raise exception 'public_table_catalog_changed' using errcode='55000'; end if;
 select jsonb_agg(jsonb_build_object('table',c.relname,'column',a.attname,'type_sql',format_type(a.atttypid,a.atttypmod),
       'not_null',a.attnotnull,'identity',a.attidentity::text) order by c.relname,a.attname) into atual
 from pg_class c join pg_namespace n on n.oid=c.relnamespace join pg_attribute a on a.attrelid=c.oid
 where n.nspname='public' and c.relkind in ('r','p') and a.attnum>0 and not a.attisdropped;
 if atual is distinct from '[{"table": "creators", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators", "column": "email", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators", "column": "id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators", "column": "nome", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators", "column": "telefone", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators", "column": "tiktok", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators", "column": "whatsapp", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_aquisicao", "column": "canal_entrada", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "consentimento_aceito_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "consentimento_versao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "convite_aceito_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "convite_criado_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "convite_enviado_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "convite_referencia", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "convite_situacao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_aquisicao", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_aquisicao", "column": "deseja_sair_agencia", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "email_confirmado_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "etapa_atual", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "formulario_disponibilizado_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "formulario_iniciado_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "formulario_recebido_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "formulario_situacao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "formulario_submissao_referencia", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "formulario_versao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_aquisicao", "column": "interesse_agenciamento", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "origem_detalhe", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "origem_entrada", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "origem_fonte", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "origem_informada_formulario", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "origem_outro", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "pendencia_atual", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "possui_agencia_atual", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "primeira_mensagem_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "proxima_acao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "quer_convite", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "saida_agencia_confirmada_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "situacao_atual", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "validacao_confirmada_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "validacao_motivo", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_aquisicao", "column": "validacao_situacao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_circle", "column": "acesso_referencia", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_circle", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_circle", "column": "circle_acesso_criado_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_circle", "column": "circle_cargos_atribuidos_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_circle", "column": "circle_cargos_entrada", "type_sql": "text[]", "not_null": false, "identity": ""}, {"table": "creators_circle", "column": "circle_categoria_entrada", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_circle", "column": "circle_situacao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_circle", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_circle", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_circle", "column": "gmv_entrada_id", "type_sql": "bigint", "not_null": false, "identity": ""}, {"table": "creators_circle", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_conferencias", "column": "acesso_encontrado", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_conferencias", "column": "acesso_esperado", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_conferencias", "column": "assunto", "type_sql": "text", "not_null": true, "identity": ""}, {"table": "creators_conferencias", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_conferencias", "column": "cargos_encontrados", "type_sql": "text[]", "not_null": false, "identity": ""}, {"table": "creators_conferencias", "column": "cargos_esperados", "type_sql": "text[]", "not_null": false, "identity": ""}, {"table": "creators_conferencias", "column": "competencia", "type_sql": "date", "not_null": true, "identity": ""}, {"table": "creators_conferencias", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_conferencias", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_conferencias", "column": "fonte", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_conferencias", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_conferencias", "column": "id", "type_sql": "bigint", "not_null": true, "identity": "a"}, {"table": "creators_conferencias", "column": "observacao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_conferencias", "column": "referencia", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_conferencias", "column": "responsavel", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_conferencias", "column": "situacao", "type_sql": "text", "not_null": true, "identity": ""}, {"table": "creators_conferencias", "column": "verificado_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_contratos", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_contratos", "column": "confirmado_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_contratos", "column": "contrato_percentual", "type_sql": "numeric(5,2)", "not_null": false, "identity": ""}, {"table": "creators_contratos", "column": "contrato_prazo_meses", "type_sql": "integer", "not_null": false, "identity": ""}, {"table": "creators_contratos", "column": "contrato_renovacao_prevista_em", "type_sql": "date", "not_null": false, "identity": ""}, {"table": "creators_contratos", "column": "contrato_ultima_renovacao_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_contratos", "column": "contrato_vigencia_fim", "type_sql": "date", "not_null": false, "identity": ""}, {"table": "creators_contratos", "column": "contrato_vigencia_inicio", "type_sql": "date", "not_null": false, "identity": ""}, {"table": "creators_contratos", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_contratos", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_contratos", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_contratos", "column": "id", "type_sql": "bigint", "not_null": true, "identity": "a"}, {"table": "creators_contratos", "column": "numero_renovacao", "type_sql": "integer", "not_null": true, "identity": ""}, {"table": "creators_contratos", "column": "situacao", "type_sql": "text", "not_null": true, "identity": ""}, {"table": "creators_contratos", "column": "vinculo_id", "type_sql": "bigint", "not_null": true, "identity": ""}, {"table": "creators_enderecos", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_enderecos", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_enderecos", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_enderecos", "column": "endereco_bairro", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_enderecos", "column": "endereco_cep", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_enderecos", "column": "endereco_cidade", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_enderecos", "column": "endereco_complemento", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_enderecos", "column": "endereco_estado", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_enderecos", "column": "endereco_logradouro", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_enderecos", "column": "endereco_numero", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_enderecos", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "comprovante_referencia", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_gmv", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "finalidade", "type_sql": "text", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "fonte", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_gmv", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "id", "type_sql": "bigint", "not_null": true, "identity": "a"}, {"table": "creators_gmv", "column": "moeda", "type_sql": "text", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "motivo_correcao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_gmv", "column": "natureza", "type_sql": "text", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "observado_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_gmv", "column": "periodicidade", "type_sql": "text", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "periodo_fim", "type_sql": "date", "not_null": false, "identity": ""}, {"table": "creators_gmv", "column": "periodo_inicio", "type_sql": "date", "not_null": false, "identity": ""}, {"table": "creators_gmv", "column": "responsavel", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_gmv", "column": "situacao", "type_sql": "text", "not_null": true, "identity": ""}, {"table": "creators_gmv", "column": "valor", "type_sql": "numeric(18,2)", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "academia", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "alimentacao", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_oportunidades", "column": "carro", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "casa_praia_campo", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "celular", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "computador", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "cor_raca", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_oportunidades", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_oportunidades", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_oportunidades", "column": "idiomas", "type_sql": "text[]", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "idiomas_outros", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "microfone", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "moto", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "outro_idioma", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "pets", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "restricao_alimentar", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "tem_filhos", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "tem_pet", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "tripe", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_oportunidades", "column": "video_idioma", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_pagamentos", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_pagamentos", "column": "cnpj", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_pagamentos", "column": "cpf", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_pagamentos", "column": "cpf_validado", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_pagamentos", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_pagamentos", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_pagamentos", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_pagamentos", "column": "pix_chave", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_pagamentos", "column": "possui_cnpj", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_perfil", "column": "cabelo", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "calcado", "type_sql": "numeric(4,1)", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "camiseta", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "camiseta_outro", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "contexto_adicional", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_perfil", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_perfil", "column": "data_nascimento", "type_sql": "date", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "declarou_mais_2000_seguidores", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "estado_civil", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "expectativas", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "experiencia_agencia", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "experiencia_live_shop", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "foto_perfil_referencia", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "genero", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_perfil", "column": "inicio_amplify_informado", "type_sql": "date", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "instagram", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "meta_renda_mensal", "type_sql": "numeric(18,2)", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "mini_bio", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "nichos", "type_sql": "text[]", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "nichos_outros", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "nome_agencia_anterior", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "plataformas", "type_sql": "text[]", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "plataformas_outros", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "produtos_excluidos", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "rotina", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "rotina_outro", "type_sql": "text", "not_null": false, "identity": ""}, {"table": "creators_perfil", "column": "teve_agencia_anterior", "type_sql": "boolean", "not_null": false, "identity": ""}, {"table": "creators_vinculos", "column": "atualizado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_vinculos", "column": "confirmado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_vinculos", "column": "creator_id", "type_sql": "uuid", "not_null": true, "identity": ""}, {"table": "creators_vinculos", "column": "criado_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_vinculos", "column": "fim_em", "type_sql": "timestamp with time zone", "not_null": false, "identity": ""}, {"table": "creators_vinculos", "column": "fonte", "type_sql": "text", "not_null": true, "identity": ""}, {"table": "creators_vinculos", "column": "historico_jornada", "type_sql": "jsonb", "not_null": true, "identity": ""}, {"table": "creators_vinculos", "column": "id", "type_sql": "bigint", "not_null": true, "identity": "a"}, {"table": "creators_vinculos", "column": "inicio_em", "type_sql": "timestamp with time zone", "not_null": true, "identity": ""}, {"table": "creators_vinculos", "column": "motivo_saida", "type_sql": "text", "not_null": false, "identity": ""}]'::jsonb then
   raise exception 'public_column_catalog_changed' using errcode='55000'; end if;
end;
$guard$;
lock table public.creators,public.creators_aquisicao,public.creators_circle,public.creators_conferencias,public.creators_contratos,public.creators_enderecos,public.creators_gmv,public.creators_oportunidades,public.creators_pagamentos,public.creators_perfil,public.creators_vinculos in access exclusive mode;
do $empty$
declare t text; existe boolean;
begin
 foreach t in array array['creators','creators_aquisicao','creators_circle','creators_conferencias','creators_contratos','creators_enderecos','creators_gmv','creators_oportunidades','creators_pagamentos','creators_perfil','creators_vinculos'] loop
  execute format('select exists(select 1 from public.%I limit 1)',t) into existe;
  if existe then raise exception 'migration_aborted_nonempty_table:%',t using errcode='55000'; end if;
 end loop;
end;
$empty$;
drop view public.creators_retencao;
drop view public.creators_marketing;
drop view public.creators_conferencia_mensal;
drop view public.creators_ficha_completa;
drop view public.creators_linha_tempo;
drop view public.creators_visao_geral;
drop view public.creators_gmv_mensal;
drop trigger creators_10_controlar on public.creators;
drop trigger creators_30_inicializar on public.creators;
drop trigger creators_10_controlar on public.creators_aquisicao;
drop trigger creators_10_controlar on public.creators_circle;
drop trigger creators_20_validar on public.creators_circle;
drop trigger creators_10_controlar on public.creators_conferencias;
drop trigger creators_10_controlar on public.creators_contratos;
drop trigger creators_10_controlar on public.creators_enderecos;
drop trigger creators_10_controlar on public.creators_gmv;
drop trigger creators_20_validar on public.creators_gmv;
drop trigger creators_10_controlar on public.creators_oportunidades;
drop trigger creators_10_controlar on public.creators_pagamentos;
drop trigger creators_10_controlar on public.creators_perfil;
drop trigger creators_10_controlar on public.creators_vinculos;
drop trigger creators_20_validar on public.creators_vinculos;
drop function public.creators_controlar_ficha();
drop function public.creators_inicializar_fichas();
drop function public.creators_validar_relacoes();
drop function public.registrar_cadastro_ensaio_v5(jsonb,jsonb);
drop function public.registrar_gmv_mensal(uuid,date,numeric,text,timestamp with time zone,text,text);
drop table public.creators_contratos;
drop table public.creators_circle;
drop table public.creators_conferencias;
drop table public.creators_gmv;
drop table public.creators_vinculos;
drop table public.creators_aquisicao;
drop table public.creators_perfil;
drop table public.creators_oportunidades;
drop table public.creators_enderecos;
drop table public.creators_pagamentos;
drop table public.creators;
create table public.creators (
  id uuid default gen_random_uuid() not null,
  nome text,
  telefone text,
  email text,
  tiktok text,
  whatsapp text,
  criado_em timestamp with time zone default statement_timestamp() not null,
  atualizado_em timestamp with time zone default statement_timestamp() not null,
  historico_jornada jsonb default '[]'::jsonb not null,
  canal_entrada text,
  origem_entrada text,
  origem_detalhe text,
  origem_fonte text,
  primeira_mensagem_em timestamp with time zone,
  etapa_atual text default 'primeiro_contato'::text,
  situacao_atual text default 'em_andamento'::text,
  pendencia_atual text,
  proxima_acao text,
  possui_agencia_atual boolean,
  deseja_sair_agencia boolean,
  saida_agencia_confirmada_em timestamp with time zone,
  interesse_agenciamento boolean,
  validacao_situacao text,
  validacao_confirmada_em timestamp with time zone,
  validacao_motivo text,
  quer_convite boolean,
  convite_referencia text,
  convite_criado_em timestamp with time zone,
  convite_enviado_em timestamp with time zone,
  convite_situacao text,
  convite_aceito_em timestamp with time zone,
  formulario_situacao text,
  formulario_disponibilizado_em timestamp with time zone,
  formulario_iniciado_em timestamp with time zone,
  formulario_recebido_em timestamp with time zone,
  formulario_versao text,
  formulario_submissao_referencia text,
  origem_informada_formulario text,
  origem_outro text,
  consentimento_aceito_em timestamp with time zone,
  consentimento_versao text,
  email_confirmado_em timestamp with time zone,
  foto_perfil_referencia text,
  mini_bio text,
  data_nascimento date,
  genero text,
  estado_civil text,
  camiseta text,
  camiseta_outro text,
  nichos text[],
  nichos_outros text,
  cabelo text,
  calcado numeric(4,1),
  expectativas text,
  meta_renda_mensal numeric(18,2),
  contexto_adicional text,
  plataformas text[],
  instagram text,
  plataformas_outros text,
  experiencia_live_shop text,
  teve_agencia_anterior boolean,
  nome_agencia_anterior text,
  experiencia_agencia text,
  produtos_excluidos text,
  inicio_amplify_informado date,
  rotina text,
  rotina_outro text,
  declarou_mais_2000_seguidores boolean,
  cor_raca text,
  tem_filhos boolean,
  alimentacao text,
  restricao_alimentar text,
  casa_praia_campo boolean,
  carro boolean,
  moto boolean,
  celular text,
  computador boolean,
  tripe boolean,
  microfone boolean,
  academia boolean,
  tem_pet boolean,
  pets text,
  outro_idioma boolean,
  video_idioma text,
  idiomas text[],
  idiomas_outros text,
  endereco_estado text,
  endereco_cidade text,
  endereco_logradouro text,
  endereco_bairro text,
  endereco_numero text,
  endereco_complemento text,
  endereco_cep text,
  cpf text,
  cpf_validado boolean,
  pix_chave text,
  possui_cnpj boolean,
  cnpj text,
  circle_categoria_entrada text,
  circle_cargos_entrada text[],
  circle_situacao text,
  circle_acesso_criado_em timestamp with time zone,
  circle_cargos_atribuidos_em timestamp with time zone,
  acesso_referencia text,
  gmv_entrada_id bigint,
  cadastro_situacao text not null default 'pendente' check(cadastro_situacao in ('pendente','confirmado')),
  cadastro_revisao bigint not null default 0 check(cadastro_revisao>=0),
  origem_instancia text, origem_account_id text, origem_contact_id text,
  primary key(id),
  check(jsonb_typeof(historico_jornada)='array'),
  check((origem_instancia is null and origem_account_id is null and origem_contact_id is null)
    or (origem_instancia ~ '^[A-Za-z0-9_.:-]{1,80}$' and origem_account_id ~ '^[1-9][0-9]{0,19}$' and origem_contact_id ~ '^[1-9][0-9]{0,19}$')),
  check(cadastro_situacao<>'confirmado' or (formulario_recebido_em is not null and email_confirmado_em is not null
    and consentimento_aceito_em is not null and formulario_submissao_referencia is not null)),
  constraint creators_circle_datas_finitas CHECK ((circle_acesso_criado_em IS NULL OR isfinite(circle_acesso_criado_em)) AND (circle_cargos_atribuidos_em IS NULL OR isfinite(circle_cargos_atribuidos_em)))
);
create unique index creators_origem_identidade_idx on public.creators(origem_instancia,origem_account_id,origem_contact_id)
 where origem_instancia is not null;
create index creators_cadastro_idx on public.creators(cadastro_situacao,criado_em);
create table public.atendimentos (
 id uuid primary key, creator_id uuid not null references public.creators(id) on delete restrict,
 instancia text not null, account_id text not null, contact_id text not null, conversation_id text not null,
 revisao bigint not null default 0 check(revisao>=0), etapa text not null default 'entrada',
 situacao text not null default 'aberto' check(situacao in ('aberto','encerrado','expirado')),
 motivo_encerramento text, primeira_mensagem_em timestamptz, ultima_mensagem_em timestamptz, expires_at timestamptz,
 qualificacao jsonb not null default '{}' check(jsonb_typeof(qualificacao)='object'),
 rascunho jsonb not null default '{}' check(jsonb_typeof(rascunho)='object'),
 origem jsonb check(origem is null or jsonb_typeof(origem)='object'),
 criado_em timestamptz not null default statement_timestamp(), atualizado_em timestamptz not null default statement_timestamp(),
 unique(creator_id,id),
 check(account_id ~ '^[1-9][0-9]{0,19}$' and contact_id ~ '^[1-9][0-9]{0,19}$' and conversation_id ~ '^[1-9][0-9]{0,19}$'),
 check(expires_at is null or ultima_mensagem_em is null or expires_at>=ultima_mensagem_em)
);
create index atendimentos_pessoa_data_idx on public.atendimentos(creator_id,criado_em desc);
create index atendimentos_conversa_idx on public.atendimentos(instancia,account_id,conversation_id,criado_em desc);
create table public.agenciamentos (
 id bigint generated always as identity primary key,
 creator_id uuid not null references public.creators(id) on delete restrict,
 inicio_em timestamptz, fim_em timestamptz, fonte text not null, confirmado_em timestamptz not null, verificado_em timestamptz not null,
 confirmacao_referencia text not null, motivo_saida text,
 tiktok_observado text, conta_referencia text,
 numero_renovacao integer not null default 0 check(numero_renovacao>=0),
 situacao text not null default 'confirmado' check(situacao in ('confirmado','encerrado')),
 contrato_percentual numeric(7,4), contrato_prazo_meses integer,
 contrato_vigencia_inicio date, contrato_vigencia_fim date, contrato_renovacao_prevista_em date,
 contrato_ultima_renovacao_em timestamptz,
 renovacoes jsonb not null default '[]' check(jsonb_typeof(renovacoes)='array'),
 criado_em timestamptz not null default statement_timestamp(), atualizado_em timestamptz not null default statement_timestamp(),
 check(fim_em is null or inicio_em is null or fim_em>inicio_em),
 check(situacao<>'encerrado' or fim_em is not null),
 check(btrim(fonte)<>'' and btrim(confirmacao_referencia)<>'' and fonte !~* '(simulad|ensaio|mock)'),
 check(tiktok_observado is null or tiktok_observado ~ '^@?[A-Za-z0-9_][A-Za-z0-9_.]{1,23}$'),
 check(conta_referencia is null or conta_referencia ~ '^[A-Za-z0-9][A-Za-z0-9:_-]{0,199}$'),
 check(contrato_percentual is null or contrato_percentual between 0 and 100),
 check(contrato_prazo_meses is null or contrato_prazo_meses>0),
 exclude using gist(creator_id extensions.gist_uuid_ops with =,tstzrange(inicio_em,fim_em,'[)') with &&) where(inicio_em is not null)
);
create index agenciamentos_pessoa_data_idx on public.agenciamentos(creator_id,inicio_em desc);
create unique index agenciamentos_um_confirmado_idx on public.agenciamentos(creator_id) where situacao='confirmado';
create table public.gmv (
 id bigint generated always as identity not null,
 creator_id uuid not null,
 finalidade text not null,
 natureza text not null,
 periodicidade text not null,
 periodo_inicio date,
 periodo_fim date,
 valor numeric(18,2),
 moeda text default 'BRL'::text not null,
 situacao text default 'pendente'::text not null,
 fonte text,
 observado_em timestamp with time zone,
 responsavel text,
 comprovante_referencia text,
 motivo_correcao text,
 criado_em timestamp with time zone default statement_timestamp() not null,
 atualizado_em timestamp with time zone default statement_timestamp() not null,
 historico_jornada jsonb default '[]'::jsonb not null,
 atendimento_id uuid,
 constraint gmv_ausencia_sem_zero CHECK ((situacao <> ALL (ARRAY['pendente'::text, 'indisponivel'::text])) OR valor IS NULL),
 constraint gmv_creator_id_fkey FOREIGN KEY (creator_id) REFERENCES public.creators(id) ON UPDATE RESTRICT ON DELETE RESTRICT,
 constraint gmv_datas_finitas CHECK ((periodo_inicio IS NULL OR isfinite(periodo_inicio)) AND (periodo_fim IS NULL OR isfinite(periodo_fim)) AND (observado_em IS NULL OR isfinite(observado_em))),
 constraint gmv_finalidade_valida CHECK (finalidade = ANY (ARRAY['entrada'::text, 'acompanhamento'::text])),
 constraint gmv_fonte_nao_vazia CHECK (fonte IS NULL OR btrim(fonte) <> ''::text),
 constraint gmv_historico_lista CHECK (jsonb_typeof(historico_jornada) = 'array'::text),
 constraint gmv_janela_28_dias CHECK (periodicidade <> 'janela_28_dias'::text OR periodo_fim = (periodo_inicio + 27)),
 constraint gmv_mes_completo CHECK (periodicidade <> 'mes_calendario'::text OR EXTRACT(day FROM periodo_inicio) = 1::numeric AND periodo_fim = (periodo_inicio + '1 mon'::interval - '1 day'::interval)::date),
 constraint gmv_moeda_valida CHECK (moeda ~ '^[A-Z]{3}$'::text),
 constraint gmv_natureza_valida CHECK (natureza = ANY (ARRAY['declarado'::text, 'verificado'::text])),
 constraint gmv_periodicidade_valida CHECK (periodicidade = ANY (ARRAY['mes_calendario'::text, 'janela_28_dias'::text, 'periodo_personalizado'::text, 'nao_informado'::text])),
 constraint gmv_periodo_completo CHECK (periodicidade = 'nao_informado'::text AND finalidade = 'entrada'::text AND periodo_inicio IS NULL AND periodo_fim IS NULL OR periodicidade <> 'nao_informado'::text AND periodo_inicio IS NOT NULL AND periodo_fim IS NOT NULL),
 constraint gmv_periodo_unique UNIQUE NULLS NOT DISTINCT (creator_id, finalidade, natureza, periodicidade, periodo_inicio, periodo_fim, moeda),
 constraint gmv_periodo_valido CHECK (periodo_fim >= periodo_inicio),
 constraint gmv_pessoa_registro_unique UNIQUE (creator_id, id),
 constraint gmv_pkey PRIMARY KEY (id),
 constraint gmv_registro_completo CHECK (situacao <> 'registrado'::text OR valor IS NOT NULL AND fonte IS NOT NULL AND btrim(fonte) <> ''::text AND observado_em IS NOT NULL),
 constraint gmv_situacao_valida CHECK (situacao = ANY (ARRAY['pendente'::text, 'parcial'::text, 'registrado'::text, 'indisponivel'::text])),
 constraint gmv_valor_valido CHECK (valor >= 0::numeric AND (valor <> ALL (ARRAY['NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric]))),
 foreign key(creator_id,atendimento_id) references public.atendimentos(creator_id,id) on delete restrict
);
CREATE INDEX gmv_acompanhamento_pendente_idx ON public.gmv USING btree (periodo_inicio, creator_id) WHERE ((finalidade = 'acompanhamento'::text) AND (situacao = ANY (ARRAY['pendente'::text, 'parcial'::text, 'indisponivel'::text])));
CREATE INDEX gmv_pessoa_periodo_idx ON public.gmv USING btree (creator_id, periodo_inicio DESC, periodo_fim DESC);
CREATE UNIQUE INDEX gmv_uma_entrada_por_natureza_idx ON public.gmv USING btree (creator_id, natureza) WHERE (finalidade = 'entrada'::text);
alter table public.creators add constraint creators_gmv_entrada_fk foreign key(id,gmv_entrada_id)
 references public.gmv(creator_id,id) on delete restrict;
create table public.eventos (
 id bigint generated always as identity primary key,
 creator_id uuid not null references public.creators(id) on delete restrict,
 atendimento_id uuid, tipo text not null,
 instancia text not null, referencia text not null, revisao bigint not null default 0 check(revisao>=0),
 ocorrido_em timestamptz, registrado_em timestamptz not null default statement_timestamp(),
 payload_sha256 text check(payload_sha256 is null or payload_sha256 ~ '^[0-9a-f]{64}$'),
 formulario_id uuid, submissao_id uuid, gmv_id bigint,
 dados jsonb not null default '{}' check(jsonb_typeof(dados)='object'),
 resultado jsonb check(resultado is null or jsonb_typeof(resultado)='object'),
 unique(instancia,referencia,revisao),
 foreign key(creator_id,atendimento_id) references public.atendimentos(creator_id,id) on delete restrict,
 foreign key(creator_id,gmv_id) references public.gmv(creator_id,id) on delete restrict,
 check(tipo in ('contato_recebido','atendimento_atualizado','cadastro_confirmado_ensaio','cadastro_confirmado',
   'registro_criado','registro_alterado','agenciamento_confirmado','agenciamento_encerrado','renovacao_contrato','gmv_atualizado','conferencia_mensal',
   'convite_solicitado','convite_enviado','aceite_informado','convite_a_confirmar','acesso_solicitado','acesso_entregue',
   'email_aceito_provedor','email_entregue','email_falha','cadastro_alteracao_confirmada')),
 check(tipo not in ('cadastro_confirmado_ensaio','cadastro_confirmado') or
   (formulario_id is not null and submissao_id is not null and gmv_id is not null and payload_sha256 is not null and resultado is not null))
);
create unique index eventos_submissao_idx on public.eventos(submissao_id) where submissao_id is not null;
create index eventos_pessoa_data_idx on public.eventos(creator_id,registrado_em desc);
create index eventos_atendimento_idx on public.eventos(atendimento_id,registrado_em desc) where atendimento_id is not null;
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
  v_existing public.creators%rowtype; v_number numeric; v_cpf text;
  v_index integer; v_length integer; v_sum integer; v_digit integer; v_gmv_id bigint;
  v_allowed text[]; v_observation text; v_origin text; v_origin_source text;
  v_origin_ref text; v_first timestamptz; v_channel text; v_email_confirmed timestamptz;
  v_expected_reference text; v_mode text; v_flat jsonb; v_saved public.eventos%rowtype; v_atendimento uuid; v_result jsonb; v_previous text:=coalesce(current_setting('app.v5_explicit_event',true),'off');
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
    if v_atendimento is null or not exists(select 1 from public.atendimentos where id=v_atendimento and creator_id=v_creator) then
      raise exception 'cadastro_atendimento_invalid' using errcode='22023'; end if;
  end if;
  perform pg_advisory_xact_lock(hashtextextended('v5:cadastro',0));
  v_fingerprint:=encode(sha256(convert_to(p_payload::text||E'\n'||p_context::text,'UTF8')),'hex');
  select * into v_saved from public.eventos where submissao_id=v_event;
  if found then
    if v_saved.creator_id<>v_creator or v_saved.payload_sha256<>v_fingerprint then
      raise exception 'cadastro_submission_conflict' using errcode='23505'; end if;
    return v_saved.resultado||jsonb_build_object('replayed',true);
  end if;
  if v_atendimento is not null and not exists(select 1 from public.atendimentos where id=v_atendimento and creator_id=v_creator
      and situacao='aberto' and etapa='form' and (expires_at is null or expires_at>v_received)) then
    raise exception 'cadastro_atendimento_inactive' using errcode='22023'; end if;
  select * into v_existing from public.creators where id=v_creator for update;
  if found and v_existing.cadastro_situacao='confirmado' then
    raise exception 'cadastro_already_confirmed_requires_revision_confirmation' using errcode='23505'; end if;
  -- A different stable person is never merged by a phone/name match.
  if exists(select 1 from public.creators c where c.id<>v_creator and
    (lower(btrim(c.email))=p_payload->'identity'->>'email' or c.whatsapp=p_payload->'identity'->>'whatsapp'
     or c.telefone=p_payload->'identity'->>'whatsapp' or lower(ltrim(c.tiktok,'@'))=p_payload->'identity'->>'tiktok')) then
    raise exception 'cadastro_identity_requires_review' using errcode='23505'; end if;
  v_flat:=p_payload->'identity';
  for v_table in select jsonb_object_keys(p_payload->'branches') loop
    v_flat:=v_flat||(p_payload->'branches'->v_table);
  end loop;
  perform set_config('app.v5_explicit_event','on',true);
  insert into public.creators(id,nome,email,whatsapp,foto_perfil_referencia,mini_bio,origem_informada_formulario,origem_outro,expectativas,meta_renda_mensal,contexto_adicional,plataformas,instagram,plataformas_outros,experiencia_live_shop,teve_agencia_anterior,nome_agencia_anterior,experiencia_agencia,produtos_excluidos,inicio_amplify_informado,cpf,data_nascimento,genero,estado_civil,camiseta,camiseta_outro,endereco_estado,endereco_cidade,endereco_logradouro,endereco_bairro,endereco_numero,endereco_complemento,endereco_cep,pix_chave,possui_cnpj,cnpj,nichos,nichos_outros,rotina,rotina_outro,tem_filhos,cabelo,calcado,cor_raca,alimentacao,restricao_alimentar,casa_praia_campo,carro,moto,celular,computador,tripe,microfone,academia,tem_pet,pets,outro_idioma,video_idioma,idiomas,idiomas_outros,declarou_mais_2000_seguidores,tiktok)
  select v_creator,r.nome,r.email,r.whatsapp,r.foto_perfil_referencia,r.mini_bio,r.origem_informada_formulario,r.origem_outro,r.expectativas,r.meta_renda_mensal,r.contexto_adicional,r.plataformas,r.instagram,r.plataformas_outros,r.experiencia_live_shop,r.teve_agencia_anterior,r.nome_agencia_anterior,r.experiencia_agencia,r.produtos_excluidos,r.inicio_amplify_informado,r.cpf,r.data_nascimento,r.genero,r.estado_civil,r.camiseta,r.camiseta_outro,r.endereco_estado,r.endereco_cidade,r.endereco_logradouro,r.endereco_bairro,r.endereco_numero,r.endereco_complemento,r.endereco_cep,r.pix_chave,r.possui_cnpj,r.cnpj,r.nichos,r.nichos_outros,r.rotina,r.rotina_outro,r.tem_filhos,r.cabelo,r.calcado,r.cor_raca,r.alimentacao,r.restricao_alimentar,r.casa_praia_campo,r.carro,r.moto,r.celular,r.computador,r.tripe,r.microfone,r.academia,r.tem_pet,r.pets,r.outro_idioma,r.video_idioma,r.idiomas,r.idiomas_outros,r.declarou_mais_2000_seguidores,r.tiktok
  from jsonb_populate_record(null::public.creators,v_flat) r
  on conflict(id) do update set nome=excluded.nome,email=excluded.email,whatsapp=excluded.whatsapp,foto_perfil_referencia=excluded.foto_perfil_referencia,mini_bio=excluded.mini_bio,origem_informada_formulario=excluded.origem_informada_formulario,origem_outro=excluded.origem_outro,expectativas=excluded.expectativas,meta_renda_mensal=excluded.meta_renda_mensal,contexto_adicional=excluded.contexto_adicional,plataformas=excluded.plataformas,instagram=excluded.instagram,plataformas_outros=excluded.plataformas_outros,experiencia_live_shop=excluded.experiencia_live_shop,teve_agencia_anterior=excluded.teve_agencia_anterior,nome_agencia_anterior=excluded.nome_agencia_anterior,experiencia_agencia=excluded.experiencia_agencia,produtos_excluidos=excluded.produtos_excluidos,inicio_amplify_informado=excluded.inicio_amplify_informado,cpf=excluded.cpf,data_nascimento=excluded.data_nascimento,genero=excluded.genero,estado_civil=excluded.estado_civil,camiseta=excluded.camiseta,camiseta_outro=excluded.camiseta_outro,endereco_estado=excluded.endereco_estado,endereco_cidade=excluded.endereco_cidade,endereco_logradouro=excluded.endereco_logradouro,endereco_bairro=excluded.endereco_bairro,endereco_numero=excluded.endereco_numero,endereco_complemento=excluded.endereco_complemento,endereco_cep=excluded.endereco_cep,pix_chave=excluded.pix_chave,possui_cnpj=excluded.possui_cnpj,cnpj=excluded.cnpj,nichos=excluded.nichos,nichos_outros=excluded.nichos_outros,rotina=excluded.rotina,rotina_outro=excluded.rotina_outro,tem_filhos=excluded.tem_filhos,cabelo=excluded.cabelo,calcado=excluded.calcado,cor_raca=excluded.cor_raca,alimentacao=excluded.alimentacao,restricao_alimentar=excluded.restricao_alimentar,casa_praia_campo=excluded.casa_praia_campo,carro=excluded.carro,moto=excluded.moto,celular=excluded.celular,computador=excluded.computador,tripe=excluded.tripe,microfone=excluded.microfone,academia=excluded.academia,tem_pet=excluded.tem_pet,pets=excluded.pets,outro_idioma=excluded.outro_idioma,video_idioma=excluded.video_idioma,idiomas=excluded.idiomas,idiomas_outros=excluded.idiomas_outros,declarou_mais_2000_seguidores=excluded.declarou_mais_2000_seguidores,tiktok=excluded.tiktok;
  v_ref:='ensaio-v5:'||v_event::text||':'||v_fingerprint;
  update public.creators c set canal_entrada=coalesce(c.canal_entrada,v_channel),
    primeira_mensagem_em=coalesce(c.primeira_mensagem_em,v_first),
    origem_fonte=case when c.origem_entrada is null then coalesce(v_origin_source,c.origem_fonte) else c.origem_fonte end,
    origem_detalhe=case when c.origem_entrada is null then coalesce(v_origin_ref,c.origem_detalhe) else c.origem_detalhe end,
    origem_entrada=coalesce(c.origem_entrada,v_origin),
    formulario_situacao='recebido_ensaio_whatsapp',formulario_recebido_em=v_received,formulario_versao=p_payload->>'form_version',
    formulario_submissao_referencia=v_ref,consentimento_aceito_em=v_received,consentimento_versao=p_payload->'consent'->>'version',
    email_confirmado_em=v_email_confirmed,cadastro_situacao='confirmado',cadastro_revisao=c.cadastro_revisao+1,
    etapa_atual='cadastro_confirmado',situacao_atual='cadastro_confirmado'
    where c.id=v_creator;
  insert into public.gmv(creator_id,atendimento_id,finalidade,natureza,periodicidade,periodo_inicio,periodo_fim,
    valor,moeda,situacao,fonte,observado_em,comprovante_referencia)
  values(v_creator,v_atendimento,'entrada','declarado',v_mode,v_start,v_end,(p_payload->'gmv'->>'valor')::numeric,
    'BRL','registrado','formulario_ensaio:'||v_event::text,v_received,p_payload->'gmv'->>'comprovante_referencia') returning id into v_gmv_id;
  v_result:=jsonb_build_object('creator_id',v_creator,'event_id',v_event,'gmv_id',v_gmv_id,'replayed',false,'status','cadastro_recebido_ensaio');
  insert into public.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,payload_sha256,
    formulario_id,submissao_id,gmv_id,resultado)
  values(v_creator,v_atendimento,'cadastro_confirmado_ensaio','formulario_ensaio',v_event::text,0,v_received,v_fingerprint,
    v_form,v_event,v_gmv_id,v_result);
  if v_atendimento is not null then update public.atendimentos set situacao='encerrado',motivo_encerramento='cadastro_confirmado'
    where id=v_atendimento and creator_id=v_creator; end if;
  perform set_config('app.v5_explicit_event',v_previous,true);
  return v_result;
end;
$function$;

create function public.registrar_contato_v5(p_entrada jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $fn$
declare c public.creators%rowtype; a public.atendimentos%rowtype; e public.eventos%rowtype;
 v_creator uuid; v_atendimento uuid; v_revision bigint; v_hash text; v_result jsonb; k text; v_observed timestamptz;
 v_last timestamptz; v_expiry timestamptz; v_source text; v_input jsonb; v_origin jsonb; v_expired jsonb:='[]';
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
 select * into e from public.eventos where instancia=p_entrada->>'instancia' and referencia=p_entrada->>'event_id' and revisao=v_revision;
 if found then
  if e.payload_sha256<>v_hash then raise exception 'contato_replay_conflict' using errcode='23505'; end if;
  return e.resultado||jsonb_build_object('replayed',true);
 end if;
 select * into c from public.creators where origem_instancia=p_entrada->>'instancia'
    and origem_account_id=p_entrada->>'account_id' and origem_contact_id=p_entrada->>'contact_id' for update;
 if found then
  v_creator:=c.id;
  if p_entrada->>'creator_id' is not null and (p_entrada->>'creator_id')::uuid<>v_creator then
   raise exception 'contato_preferred_creator_conflict' using errcode='23505'; end if;
 else
  v_creator:=coalesce((p_entrada->>'creator_id')::uuid,gen_random_uuid());
  if v_creator='00000000-0000-0000-0000-000000000000'::uuid then raise exception 'contato_creator_invalid' using errcode='22023'; end if;
  select * into c from public.creators where id=v_creator for update;
  if found and c.origem_instancia is not null then raise exception 'contato_creator_bound_elsewhere' using errcode='23505'; end if;
  perform set_config('app.v5_explicit_event','on',true);
  insert into public.creators(id,origem_instancia,origem_account_id,origem_contact_id,whatsapp,primeira_mensagem_em,canal_entrada,etapa_atual,situacao_atual)
   values(v_creator,p_entrada->>'instancia',p_entrada->>'account_id',p_entrada->>'contact_id',
     replace(p_entrada->>'whatsapp','+',''),v_observed,case when v_observed is not null then 'whatsapp' end,'entrada','em_atendimento')
   on conflict(id) do update set origem_instancia=excluded.origem_instancia,origem_account_id=excluded.origem_account_id,
     origem_contact_id=excluded.origem_contact_id;
 end if;
 perform set_config('app.v5_explicit_event','on',true);
 update public.creators set primeira_mensagem_em=coalesce(primeira_mensagem_em,v_observed),
   canal_entrada=case when primeira_mensagem_em is null and v_observed is not null then coalesce(canal_entrada,'whatsapp') else canal_entrada end,
   whatsapp=case when cadastro_situacao='pendente' and whatsapp is null then replace(p_entrada->>'whatsapp','+','') else whatsapp end
   where id=v_creator;
 if v_atendimento is not null then
  select * into a from public.atendimentos where id=v_atendimento for update;
  if found and (a.creator_id<>v_creator or a.instancia<>p_entrada->>'instancia' or a.account_id<>p_entrada->>'account_id'
    or a.contact_id<>p_entrada->>'contact_id' or a.conversation_id<>p_entrada->>'conversation_id') then
   raise exception 'contato_cycle_identity_conflict' using errcode='23505'; end if;
  if found and v_revision<=a.revisao then raise exception 'contato_stale_revision' using errcode='23505'; end if;
  if found and ((a.situacao<>'aberto' and p_entrada->>'situacao'='aberto')
    or (a.ultima_mensagem_em is not null and v_last is not null and v_last<a.ultima_mensagem_em)
    or (a.expires_at is not null and v_expiry is not null and v_expiry<a.expires_at)) then
   raise exception 'contato_terminal_or_clock_regression' using errcode='23505'; end if;
  with changed as (update public.atendimentos set situacao='expirado',motivo_encerramento='24h_sem_mensagem'
   where id<>v_atendimento and instancia=p_entrada->>'instancia' and account_id=p_entrada->>'account_id'
   and contact_id=p_entrada->>'contact_id' and conversation_id=p_entrada->>'conversation_id' and situacao='aberto'
   and expires_at<=coalesce(v_last,statement_timestamp()) returning id)
   select coalesce(jsonb_agg(id),'[]') into v_expired from changed;
  insert into public.atendimentos(id,creator_id,instancia,account_id,contact_id,conversation_id,revisao,etapa,situacao,
   primeira_mensagem_em,ultima_mensagem_em,expires_at,qualificacao,rascunho,origem)
  values(v_atendimento,v_creator,p_entrada->>'instancia',p_entrada->>'account_id',p_entrada->>'contact_id',p_entrada->>'conversation_id',
   v_revision,p_entrada->>'etapa',p_entrada->>'situacao',v_observed,v_last,v_expiry,
   coalesce(p_entrada->'qualificacao','{}'),coalesce(p_entrada->'rascunho','{}'),v_origin)
  on conflict(id) do update set revisao=excluded.revisao,etapa=excluded.etapa,situacao=excluded.situacao,
    ultima_mensagem_em=coalesce(excluded.ultima_mensagem_em,atendimentos.ultima_mensagem_em),
    expires_at=coalesce(excluded.expires_at,atendimentos.expires_at),
    qualificacao=excluded.qualificacao,rascunho=atendimentos.rascunho||excluded.rascunho,origem=coalesce(atendimentos.origem,excluded.origem);
  update public.creators set etapa_atual=p_entrada->>'etapa',
    situacao_atual=case p_entrada->>'situacao' when 'aberto' then 'em_atendimento' when 'encerrado' then 'atendimento_encerrado' else 'atendimento_expirado' end
   where id=v_creator and cadastro_situacao='pendente' and (v_last is null or not exists(
    select 1 from public.atendimentos other where other.creator_id=v_creator and other.id<>v_atendimento and other.ultima_mensagem_em>v_last));
 end if;
 select cadastro_situacao into v_source from public.creators where id=v_creator;
 v_result:=jsonb_build_object('creator_id',v_creator,'atendimento_id',v_atendimento,'event_id',p_entrada->>'event_id',
    'revision',v_revision,'replayed',false,'cadastro_situacao',v_source);
 insert into public.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,payload_sha256,dados,resultado)
  values(v_creator,v_atendimento,case when v_atendimento is null then 'contato_recebido' else 'atendimento_atualizado' end,
   p_entrada->>'instancia',p_entrada->>'event_id',v_revision,v_observed,v_hash,
   jsonb_build_object('etapa',p_entrada->>'etapa','situacao',p_entrada->>'situacao','atendimentos_expirados',v_expired),v_result);
 perform set_config('app.v5_explicit_event',v_previous,true);
 return v_result;
end;
$fn$;
CREATE OR REPLACE FUNCTION public.registrar_gmv_mensal(p_creator_id uuid, p_competencia date, p_valor numeric, p_fonte text, p_observado_em timestamp with time zone, p_responsavel text DEFAULT NULL::text, p_motivo_correcao text DEFAULT NULL::text)
 RETURNS bigint
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare primeiro date; ultimo date; resultado bigint;
begin
  if p_competencia is null or p_valor is null or p_observado_em is null or nullif(btrim(p_fonte),'') is null then
    raise exception using errcode='23514',message='Informe pessoa, mês, valor, fonte e data da observação. Ausência de informação não é GMV zero.';
  end if;
  primeiro := date_trunc('month',p_competencia::timestamp)::date;
  ultimo := (primeiro+interval '1 month'-interval '1 day')::date;
  if (p_observado_em at time zone 'America/Sao_Paulo')::date < primeiro then
    raise exception using errcode='23514',message='A observação não pode ser anterior ao início do mês medido.';
  end if;
  insert into public.gmv(creator_id,finalidade,natureza,periodicidade,periodo_inicio,periodo_fim,
    valor,moeda,situacao,fonte,observado_em,responsavel,motivo_correcao)
  values(p_creator_id,'acompanhamento','verificado','mes_calendario',primeiro,ultimo,p_valor,'BRL',
    case when (p_observado_em at time zone 'America/Sao_Paulo')::date>ultimo then 'registrado' else 'parcial' end,
    p_fonte,p_observado_em,p_responsavel,p_motivo_correcao)
  on conflict(creator_id,finalidade,natureza,periodicidade,periodo_inicio,periodo_fim,moeda)
  do update set valor=excluded.valor,situacao=excluded.situacao,fonte=excluded.fonte,
    observado_em=excluded.observado_em,responsavel=excluded.responsavel,motivo_correcao=excluded.motivo_correcao
  returning id into resultado;
  return resultado;
end;
$function$
;

create function public.v5_controlar_datas() returns trigger language plpgsql security invoker set search_path='' as $fn$
begin
 if to_jsonb(new) ? 'historico_jornada' and (to_jsonb(new)->'historico_jornada'<>'[]'::jsonb
    or (tg_op='UPDATE' and to_jsonb(new)->'historico_jornada' is distinct from to_jsonb(old)->'historico_jornada')) then
  raise exception 'legacy_history_is_read_only_use_events' using errcode='23514';end if;
 if tg_op='INSERT' then new.criado_em:=statement_timestamp();new.atualizado_em:=new.criado_em;
 else
  if new.id is distinct from old.id or new.criado_em is distinct from old.criado_em then raise exception 'record_identity_immutable' using errcode='23514'; end if;
  if to_jsonb(new)-'atualizado_em' is not distinct from to_jsonb(old)-'atualizado_em' then new.atualizado_em:=old.atualizado_em;
  else new.atualizado_em:=statement_timestamp(); end if;
 end if;
 return new;
end;
$fn$;
create function public.v5_registrar_alteracao() returns trigger language plpgsql security invoker set search_path='' as $fn$
declare changes jsonb; person uuid; value jsonb;
begin
 if current_setting('app.v5_explicit_event',true)='on' then return new; end if;
 if tg_op='UPDATE' and to_jsonb(new)-'atualizado_em' is not distinct from to_jsonb(old)-'atualizado_em' then return new; end if;
 value:=to_jsonb(new);
 select coalesce(jsonb_agg(x.key order by x.key),'[]') into changes from jsonb_each(value) x
  where x.key not in ('criado_em','atualizado_em','historico_jornada') and
   (tg_op='INSERT' and x.value<>'null'::jsonb or tg_op='UPDATE' and x.value is distinct from to_jsonb(old)->x.key);
 person:=case when tg_table_name='creators' then (value->>'id')::uuid else (value->>'creator_id')::uuid end;
 insert into public.eventos(creator_id,tipo,instancia,referencia,dados)
  values(person,case when tg_op='INSERT' then 'registro_criado' else 'registro_alterado' end,'banco',
   tg_table_name||':'||new.id::text||':'||gen_random_uuid()::text,jsonb_build_object('tabela',tg_table_name,'campos',changes));
 return new;
end;
$fn$;
create function public.v5_proteger_evento() returns trigger language plpgsql security invoker set search_path='' as $fn$
begin raise exception 'event_is_append_only' using errcode='23514';end;
$fn$;
create function public.v5_validar_gmv() returns trigger language plpgsql security invoker set search_path='' as $fn$
begin
 if tg_op='UPDATE' then
  if new.creator_id<>old.creator_id then raise exception 'gmv_identity_immutable' using errcode='23514';end if;
  if old.observado_em is not null and new.observado_em<old.observado_em then raise exception 'gmv_stale_observation' using errcode='23514';end if;
  if old.valor is not null and (new.valor is distinct from old.valor or new.periodo_inicio is distinct from old.periodo_inicio
      or new.periodo_fim is distinct from old.periodo_fim or new.periodicidade is distinct from old.periodicidade or new.moeda is distinct from old.moeda)
     and nullif(btrim(new.motivo_correcao),'') is null then raise exception 'gmv_correction_reason_required' using errcode='23514';end if;
 end if;
 if exists(select 1 from public.creators where gmv_entrada_id=new.id) and
    (new.finalidade<>'entrada' or new.natureza<>'verificado' or new.situacao<>'registrado') then
  raise exception 'gmv_circle_reference_must_stay_verified' using errcode='23514';end if;
 return new;
end;
$fn$;
do $triggers$
declare t text;
begin
 foreach t in array array['creators','atendimentos','agenciamentos','gmv'] loop
  execute format('create trigger v5_10_datas before insert or update on public.%I for each row execute function public.v5_controlar_datas()',t);
  if t<>'atendimentos' then execute format('create trigger v5_90_evento after insert or update on public.%I for each row execute function public.v5_registrar_alteracao()',t); end if;
 end loop;
end;
$triggers$;
create trigger v5_20_validar before insert or update on public.gmv for each row execute function public.v5_validar_gmv();
create trigger v5_10_append_only before update or delete on public.eventos for each row execute function public.v5_proteger_evento();
alter table public.creators enable row level security;
revoke all on public.creators from public,anon,authenticated,service_role;
grant select,insert,update on public.creators to service_role;
create policy service_only on public.creators to service_role using(true) with check(true);
alter table public.atendimentos enable row level security;
revoke all on public.atendimentos from public,anon,authenticated,service_role;
grant select,insert,update on public.atendimentos to service_role;
create policy service_only on public.atendimentos to service_role using(true) with check(true);
alter table public.agenciamentos enable row level security;
revoke all on public.agenciamentos from public,anon,authenticated,service_role;
grant select,insert,update on public.agenciamentos to service_role;
create policy service_only on public.agenciamentos to service_role using(true) with check(true);
alter table public.gmv enable row level security;
revoke all on public.gmv from public,anon,authenticated,service_role;
grant select,insert,update on public.gmv to service_role;
create policy service_only on public.gmv to service_role using(true) with check(true);
alter table public.eventos enable row level security;
revoke all on public.eventos from public,anon,authenticated,service_role;
grant select,insert on public.eventos to service_role;
create policy service_only on public.eventos to service_role using(true) with check(true);
grant usage on schema public to service_role;
revoke all on sequence public.agenciamentos_id_seq from public,anon,authenticated,service_role;
grant usage on sequence public.agenciamentos_id_seq to service_role;
revoke all on sequence public.gmv_id_seq from public,anon,authenticated,service_role;
grant usage on sequence public.gmv_id_seq to service_role;
revoke all on sequence public.eventos_id_seq from public,anon,authenticated,service_role;
grant usage on sequence public.eventos_id_seq to service_role;
revoke all on function public.v5_controlar_datas() from public,anon,authenticated;
grant execute on function public.v5_controlar_datas() to service_role;
revoke all on function public.v5_registrar_alteracao() from public,anon,authenticated;
grant execute on function public.v5_registrar_alteracao() to service_role;
revoke all on function public.v5_proteger_evento() from public,anon,authenticated;
grant execute on function public.v5_proteger_evento() to service_role;
revoke all on function public.v5_validar_gmv() from public,anon,authenticated;
grant execute on function public.v5_validar_gmv() to service_role;
revoke all on function public.registrar_contato_v5(jsonb) from public,anon,authenticated;
grant execute on function public.registrar_contato_v5(jsonb) to service_role;
revoke all on function public.registrar_cadastro_ensaio_v5(jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.registrar_cadastro_ensaio_v5(jsonb,jsonb) to service_role;
revoke all on function public.registrar_gmv_mensal(uuid,date,numeric,text,timestamp with time zone,text,text) from public,anon,authenticated;
grant execute on function public.registrar_gmv_mensal(uuid,date,numeric,text,timestamp with time zone,text,text) to service_role;
comment on column public.creators.id is 'Identidade única e permanente da pessoa, criada no primeiro contato. Continua igual ao se tornar creator. Não é CPF, telefone, perfil social nem identidade de login.';
comment on column public.creators.nome is 'Identificação / Nome conhecido da pessoa; pode ser completado pelo nome completo informado no formulário (campo nome). Vazio enquanto desconhecido.';
comment on column public.creators.telefone is 'Identificação / Número que iniciou o contato, incluindo país e DDD quando conhecidos. É diferente do WhatsApp informado posteriormente no formulário; não é chave única da pessoa.';
comment on column public.creators.email is 'Identificação / E-mail informado para o Club (campo email do formulário). Não cria acesso ao AmplifyOS nem confirma entrega de acesso ao Circle.';
comment on column public.creators.tiktok is 'Identificação / Perfil TikTok informado na conversa ou no formulário (campo tiktok). Pode mudar; não substitui o ID da pessoa.';
comment on column public.creators.whatsapp is 'Formulário / Contato / WhatsApp com DDD. Referência original: whatsapp. Opcional nesta ficha incremental. Número informado no formulário; pode diferir do telefone que iniciou a conversa.';
comment on column public.creators.criado_em is 'Controle / Momento em que a ficha foi criada neste banco. Definido pelo banco e protegido contra alteração normal.';
comment on column public.creators.atualizado_em is 'Controle / Última alteração efetiva da ficha, calculada automaticamente pelo banco.';
comment on column public.creators.historico_jornada is 'Histórico / Lista automática de acontecimentos e mudanças. Preserva o antes e o depois de marcos, estados, decisões, GMV de entrada com períodos declarados e verificados, categoria e cargos de ingresso no Circle e condições comerciais. Não copia as colunas de nome, contato, CPF, PIX, respostas pessoais, referências externas ou observações livres. Permite correções sem apagar os fatos operacionais anteriores. Não é imutável contra administradores nem reconstitui valores pessoais anteriores.';
comment on column public.creators.canal_entrada is 'Entrada / Meio da primeira conversa, por exemplo WhatsApp. Canal de contato é diferente da origem de aquisição.';
comment on column public.creators.origem_entrada is 'Entrada / Origem identificada desde a primeira mensagem: anúncio, indicação, contato direto ou outra origem confirmada. Nulo significa ainda não identificada.';
comment on column public.creators.origem_detalhe is 'Entrada / Detalhe conhecido da origem: campanha, anúncio ou referência da indicação. Não inventar uma origem quando ausente.';
comment on column public.creators.origem_fonte is 'Entrada / De onde veio a informação de origem: metadado da mensagem, declaração da pessoa ou confirmação da equipe.';
comment on column public.creators.primeira_mensagem_em is 'Entrada / Data e horário reais da primeira mensagem conhecida. Pode ser anterior à criação da ficha.';
comment on column public.creators.etapa_atual is 'Jornada / Etapa atual: primeiro_contato, validacao, convite, agenciado, formulario, gmv_e_categoria, entrada_circle ou concluido. Não confirma automaticamente acontecimentos externos.';
comment on column public.creators.situacao_atual is 'Jornada / Situação operacional: em_andamento, aguardando_lead, aguardando_equipe, pendente, pausado, recusado, desistente ou concluido.';
comment on column public.creators.pendencia_atual is 'Jornada / O que falta resolver agora. Texto operacional da ficha; seu conteúdo não é copiado para o histórico automático.';
comment on column public.creators.proxima_acao is 'Jornada / Próxima ação esperada para acompanhar a pessoa. Não executa automações.';
comment on column public.creators.possui_agencia_atual is 'Validação / A pessoa informou vínculo atual com outra agência. Nulo significa que ainda não sabemos; falso não é o mesmo que desconhecido.';
comment on column public.creators.deseja_sair_agencia is 'Validação / Intenção declarada de sair da agência atual. A intenção não confirma que a saída aconteceu.';
comment on column public.creators.saida_agencia_confirmada_em is 'Validação / Quando foi confirmada a saída da agência anterior, se aplicável. Não preencher somente por intenção declarada.';
comment on column public.creators.interesse_agenciamento is 'Validação / Interesse declarado em se agenciar com a Amplify. Nulo significa ainda não respondido.';
comment on column public.creators.validacao_situacao is 'Validação / pendente, em_andamento, aprovado ou reprovado. Os critérios comerciais não são impostos por esta estrutura.';
comment on column public.creators.validacao_confirmada_em is 'Validação / Quando a equipe ou a fonte responsável confirmou o resultado da validação.';
comment on column public.creators.validacao_motivo is 'Validação / Motivo do resultado ou impedimento identificado. Não é copiado para o histórico automático.';
comment on column public.creators.quer_convite is 'Convite / A pessoa quer receber o convite. Interesse não comprova criação, envio nem aceite.';
comment on column public.creators.convite_referencia is 'Convite / Referência do convite no serviço de origem, quando existir. É referência externa ligada ao mesmo ID central, não uma nova identidade da pessoa.';
comment on column public.creators.convite_criado_em is 'Convite / Quando o convite vigente foi criado. Ao substituir um convite, o histórico preserva os marcos e a situação anteriores, sem copiar a referência externa.';
comment on column public.creators.convite_enviado_em is 'Convite / Quando o envio do convite vigente foi confirmado. Criar o convite não confirma seu envio.';
comment on column public.creators.convite_situacao is 'Convite / nao_criado, criado, enviado, aceito, recusado, expirado ou cancelado. Registrar o que foi confirmado, sem presumir sucesso por tentativa de envio.';
comment on column public.creators.convite_aceito_em is 'Convite / Quando o aceite do convite vigente foi confirmado pela fonte responsável.';
comment on column public.creators.formulario_situacao is 'Formulário / nao_disponibilizado, disponibilizado, em_preenchimento ou recebido. Recebido significa respostas persistidas e recebimento confirmado.';
comment on column public.creators.formulario_disponibilizado_em is 'Formulário / Quando o formulário foi disponibilizado à pessoa agenciada.';
comment on column public.creators.formulario_iniciado_em is 'Formulário / Quando o preenchimento foi iniciado, se esse acontecimento for observado.';
comment on column public.creators.formulario_recebido_em is 'Formulário / Quando as respostas foram recebidas e sua persistência confirmada. Tela exibida ou link enviado não são confirmação de recebimento.';
comment on column public.creators.formulario_versao is 'Formulário / Versão que a pessoa respondeu. O catálogo de referência observado foi amplify-cadastro-v2; não é valor presumido para novos cadastros.';
comment on column public.creators.formulario_submissao_referencia is 'Formulário / Protocolo ou referência externa de recebimento, quando disponível. Vinculado ao mesmo ID central.';
comment on column public.creators.origem_informada_formulario is 'Formulário / Cadastro e jornada / Como você conheceu a Amplify?. Referência original: canal_origem. Opcional nesta ficha incremental. Resposta declarada no formulário, separada da origem identificada na primeira mensagem.';
comment on column public.creators.origem_outro is 'Formulário / Cadastro e jornada / Como?. Referência original: origem_outro. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.consentimento_aceito_em is 'Cadastro / Data de aceite efetivo do termo de tratamento de dados. Não preencher automaticamente com a criação da ficha.';
comment on column public.creators.consentimento_versao is 'Cadastro / Versão do termo efetivamente aceito. Sem valor padrão presumido.';
comment on column public.creators.email_confirmado_em is 'Quando a confirmação do e-mail informado foi efetivamente observada pelo processo de cadastro. Nulo significa não confirmada. Não cria login nem acesso; não preencher só por receber um endereço de e-mail.';
comment on column public.creators.foto_perfil_referencia is 'Formulário / Perfil / Sua foto de perfil. Referência original: foto_perfil. Opcional nesta ficha incremental. Guardar apenas referência ao arquivo privado; não binário, URL assinada, token ou conteúdo do arquivo.';
comment on column public.creators.mini_bio is 'Formulário / Perfil / Apresente você e seu conteúdo. Referência original: mini_bio. Opcional nesta ficha incremental.';
comment on column public.creators.data_nascimento is 'Formulário / Perfil / Data de nascimento. Referência original: nascimento. Opcional nesta ficha incremental.';
comment on column public.creators.genero is 'Formulário / Perfil / Com qual gênero você se identifica?. Referência original: genero. Opcional nesta ficha incremental.';
comment on column public.creators.estado_civil is 'Formulário / Perfil / Estado civil. Referência original: estado_civil. Opcional nesta ficha incremental.';
comment on column public.creators.camiseta is 'Formulário / Perfil / Qual tamanho de camiseta você usa?. Referência original: camiseta. Opcional nesta ficha incremental.';
comment on column public.creators.camiseta_outro is 'Formulário / Perfil / Informe o tamanho da camiseta. Referência original: camiseta_outro. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.nichos is 'Formulário / Perfil / Quais são seus nichos de conteúdo?. Referência original: nichos. Opcional nesta ficha incremental.';
comment on column public.creators.nichos_outros is 'Formulário / Perfil / Quais outros nichos?. Referência original: nichos_outros. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.cabelo is 'Formulário / Perfil / Qual o tipo do seu cabelo?. Referência original: cabelo. Opcional nesta ficha incremental.';
comment on column public.creators.calcado is 'Formulário / Perfil / Qual seu número de calçado?. Referência original: calcado. Opcional nesta ficha incremental.';
comment on column public.creators.expectativas is 'Formulário / Cadastro e jornada / Que tipo de apoio você espera da Amplify?. Referência original: expectativas. Opcional nesta ficha incremental.';
comment on column public.creators.meta_renda_mensal is 'Formulário / Cadastro e jornada / Qual é sua meta de renda mensal com conteúdo? (R$). Referência original: meta_renda_mensal. Opcional nesta ficha incremental.';
comment on column public.creators.contexto_adicional is 'Formulário / Cadastro e jornada / Há algo mais que o time precisa saber sobre você?. Referência original: contexto_adicional. Opcional nesta ficha incremental.';
comment on column public.creators.plataformas is 'Formulário / Cadastro e jornada / Plataformas de atuação. Referência original: plataformas. Opcional nesta ficha incremental.';
comment on column public.creators.instagram is 'Formulário / Cadastro e jornada / Qual seu @ do Instagram?. Referência original: instagram. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.plataformas_outros is 'Formulário / Cadastro e jornada / Quais outras plataformas?. Referência original: plataformas_outros. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.experiencia_live_shop is 'Formulário / Cadastro e jornada / Você tem experiência com Live Shop?. Referência original: experiencia_live_shop. Opcional nesta ficha incremental.';
comment on column public.creators.teve_agencia_anterior is 'Formulário / Cadastro e jornada / Já fez parte de outra agência?. Referência original: agencia_anterior. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.nome_agencia_anterior is 'Formulário / Cadastro e jornada / Agência anterior. Referência original: nome_agencia_anterior. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.experiencia_agencia is 'Formulário / Cadastro e jornada / Qual sua experiência e opinião com a última agência. Referência original: experiencia_agencia. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.produtos_excluidos is 'Formulário / Cadastro e jornada / Tipos de produto que NÃO trabalha. Referência original: produtos_excluidos. Opcional nesta ficha incremental.';
comment on column public.creators.inicio_amplify_informado is 'Formulário / Cadastro e jornada / Quando você começou na Amplify?. Referência original: inicio_amplify_informado. Opcional nesta ficha incremental.';
comment on column public.creators.rotina is 'Formulário / Cadastro e jornada / Qual sua rotina?. Referência original: rotina. Opcional nesta ficha incremental.';
comment on column public.creators.rotina_outro is 'Formulário / Cadastro e jornada / Como é sua rotina?. Referência original: rotina_outro. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.declarou_mais_2000_seguidores is 'Formulário / Cadastro e jornada / Você tem +2.000 seguidores no TikTok?. Referência original: mais_2000_seguidores. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.cor_raca is 'Formulário / Perfil / Como você se autodeclara em relação à sua cor/raça?. Referência original: cor_raca. Opcional nesta ficha incremental.';
comment on column public.creators.tem_filhos is 'Formulário / Oportunidades / Tem filhos?. Referência original: tem_filhos. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.alimentacao is 'Formulário / Oportunidades / Qual o seu tipo de dieta/alimentação?. Referência original: alimentacao. Opcional nesta ficha incremental.';
comment on column public.creators.restricao_alimentar is 'Formulário / Oportunidades / Qual restrição alimentar. Referência original: restricao_alimentar. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.casa_praia_campo is 'Formulário / Oportunidades / Tem casa de praia/campo?. Referência original: casa_praia_campo. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.carro is 'Formulário / Oportunidades / Tem carro?. Referência original: carro. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.moto is 'Formulário / Oportunidades / Tem moto?. Referência original: moto. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.celular is 'Formulário / Oportunidades / Tipo de celular. Referência original: celular. Opcional nesta ficha incremental.';
comment on column public.creators.computador is 'Formulário / Oportunidades / Tem computador?. Referência original: computador. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.tripe is 'Formulário / Oportunidades / Tem tripé. Referência original: tripe. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.microfone is 'Formulário / Oportunidades / Tem microfone de lapela?. Referência original: microfone. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.academia is 'Formulário / Oportunidades / Tem acesso a academia?. Referência original: academia. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.tem_pet is 'Formulário / Oportunidades / Tem pet de estimação?. Referência original: tem_pet. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.pets is 'Formulário / Oportunidades / Pets (quais). Referência original: pets. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.outro_idioma is 'Formulário / Oportunidades / Você fala outro idioma?. Referência original: outro_idioma. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.video_idioma is 'Formulário / Oportunidades / Link vídeo falando outro idioma. Referência original: video_idioma. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.idiomas is 'Formulário / Oportunidades / Idiomas. Referência original: idiomas. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.idiomas_outros is 'Formulário / Oportunidades / Quais outros idiomas?. Referência original: idiomas_outros. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';
comment on column public.creators.endereco_estado is 'Formulário / Endereço / Em qual estado você mora?. Referência original: estado. Opcional nesta ficha incremental.';
comment on column public.creators.endereco_cidade is 'Formulário / Endereço / Cidade. Referência original: cidade. Opcional nesta ficha incremental.';
comment on column public.creators.endereco_logradouro is 'Formulário / Endereço / Endereço para receber as amostras/produtos. Referência original: logradouro. Opcional nesta ficha incremental.';
comment on column public.creators.endereco_bairro is 'Formulário / Endereço / Bairro. Referência original: bairro. Opcional nesta ficha incremental.';
comment on column public.creators.endereco_numero is 'Formulário / Endereço / Número. Referência original: numero. Opcional nesta ficha incremental.';
comment on column public.creators.endereco_complemento is 'Formulário / Endereço / Complemento do endereço (ou “Sem complemento”). Referência original: complemento. Opcional nesta ficha incremental.';
comment on column public.creators.endereco_cep is 'Formulário / Endereço / CEP para receber amostras/produtos. Referência original: cep. Opcional nesta ficha incremental.';
comment on column public.creators.cpf is 'Formulário / Pagamentos / CPF. Referência original: cpf. Opcional nesta ficha incremental. Identificador textual; não usar como número, senha, chave de login ou prova automática de titularidade.';
comment on column public.creators.cpf_validado is 'Formulário / Resultado da validação do CPF pelo processo responsável. Nulo significa não validado; este SQL não realiza consulta nem validação de CPF.';
comment on column public.creators.pix_chave is 'Formulário / Pagamentos / Chave PIX. Referência original: pix. Opcional nesta ficha incremental.';
comment on column public.creators.possui_cnpj is 'Formulário / Pagamentos / Você possui CNPJ?. Referência original: possui_cnpj. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';
comment on column public.creators.cnpj is 'Formulário / Pagamentos / CNPJ. Referência original: cnpj. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável. Identificador textual; não usar como número, senha, chave de login ou prova automática de titularidade.';
comment on column public.creators.circle_categoria_entrada is 'Categoria efetivamente definida no ingresso. Evolução de GMV posterior não deve substituir silenciosamente esta referência inicial.';
comment on column public.creators.circle_cargos_entrada is 'Cargos efetivamente atribuídos no primeiro ingresso, após confirmação pelo processo responsável. Cargos apenas esperados ficam em creators_conferencias.cargos_esperados; não presumir atribuição pela criação da ficha.';
comment on column public.creators.circle_situacao is 'Situação de ingresso ou acesso observada no processo responsável; não pressupõe criação pela simples gravação da ficha.';
comment on column public.creators.circle_acesso_criado_em is 'Momento em que a criação do acesso foi confirmada na fonte responsável; link enviado não comprova este marco.';
comment on column public.creators.circle_cargos_atribuidos_em is 'Momento em que a atribuição dos cargos de ingresso foi confirmada no Circle.';
comment on column public.creators.acesso_referencia is 'Referência estável do membro ou acesso no Circle; não é senha, token, cookie ou autorização para entrar.';
comment on column public.creators.gmv_entrada_id is 'Medição de entrada da mesma pessoa usada na classificação, quando aplicável; não aponta para uma medição posterior de acompanhamento.';
comment on table public.creators is 'Uma ficha UUID por pessoa desde o primeiro contato. Cadastro pendente e confirmado sao estados distintos; respostas da IA ficam no rascunho do atendimento ate confirmacao do formulario.';
comment on table public.atendimentos is 'Um ciclo de conversa por UUID do motor, ligado a pessoa por origem estavel. Encerramento ou expiracao da conversa nao encerra agenciamento.';
comment on table public.agenciamentos is 'Somente periodos de vinculo real confirmado com fonte e referencia. Formulario e simulacao nao criam linhas aqui. Renovacoes conservam os campos de contrato e historico de eventos.';
comment on column public.agenciamentos.tiktok_observado is 'Conta TikTok observada pela fonte que confirmou o agenciamento. Pode existir antes do formulario e nao substitui silenciosamente creators.tiktok.';
comment on column public.agenciamentos.conta_referencia is 'Identificador estavel da conta no provedor, quando conhecido. Nao e URL, credencial, cookie ou token; pode ser informado sem arroba conhecido.';
comment on table public.gmv is 'Medicoes por pessoa, finalidade, natureza, periodo e moeda; declarado nao vira verificado. Ausencia nao e zero.';
comment on table public.eventos is 'Historico central tipado e append-only para o servico, com referencias e recibos idempotentes. Eventos tecnicos guardam nomes de campos, sem copiar dados pessoais.';
comment on column public.creators.historico_jornada is 'Campo legado de compatibilidade mantido vazio. O historico operacional novo e consultado em public.eventos.';
comment on column public.gmv.historico_jornada is 'Campo legado de compatibilidade mantido vazio. Correcoes e alteracoes novas sao registradas em public.eventos.';
do $verify$
begin
 if (select array_agg(c.relname::text order by c.relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace
     where n.nspname='public' and c.relkind in ('r','p')) is distinct from array['agenciamentos','atendimentos','creators','eventos','gmv'] then
   raise exception 'unexpected_final_public_tables'; end if;
 if exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('v','m')) then
   raise exception 'unexpected_final_public_views'; end if;
end;
$verify$;
commit;
