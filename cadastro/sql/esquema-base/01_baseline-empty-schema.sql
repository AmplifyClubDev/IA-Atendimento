-- Target: AmplifyOS-v5 / divlvdmsqbwplervsqwu

-- Reconstructs the verified EMPTY schema captured before consolidation.

-- Not a data restore and not safe after new records have been received.

SET client_encoding = 'UTF8';

SET search_path = public, extensions;

CREATE TABLE public."creators" (
  "id" uuid DEFAULT gen_random_uuid() NOT NULL,
  "nome" text,
  "telefone" text,
  "email" text,
  "tiktok" text,
  "whatsapp" text,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators" IS 'Base mae: identidade unica e permanente, contatos e controle da pessoa. Os detalhes e acontecimentos ficam nas ramificacoes. Sair do agenciamento nao exclui a pessoa. As seis fichas individuais nascem junto com a pessoa, com o mesmo ID.';

CREATE TABLE public."creators_aquisicao" (
  "creator_id" uuid NOT NULL,
  "canal_entrada" text,
  "origem_entrada" text,
  "origem_detalhe" text,
  "origem_fonte" text,
  "primeira_mensagem_em" timestamp with time zone,
  "etapa_atual" text DEFAULT 'primeiro_contato'::text,
  "situacao_atual" text DEFAULT 'em_andamento'::text,
  "pendencia_atual" text,
  "proxima_acao" text,
  "possui_agencia_atual" boolean,
  "deseja_sair_agencia" boolean,
  "saida_agencia_confirmada_em" timestamp with time zone,
  "interesse_agenciamento" boolean,
  "validacao_situacao" text,
  "validacao_confirmada_em" timestamp with time zone,
  "validacao_motivo" text,
  "quer_convite" boolean,
  "convite_referencia" text,
  "convite_criado_em" timestamp with time zone,
  "convite_enviado_em" timestamp with time zone,
  "convite_situacao" text,
  "convite_aceito_em" timestamp with time zone,
  "formulario_situacao" text,
  "formulario_disponibilizado_em" timestamp with time zone,
  "formulario_iniciado_em" timestamp with time zone,
  "formulario_recebido_em" timestamp with time zone,
  "formulario_versao" text,
  "formulario_submissao_referencia" text,
  "origem_informada_formulario" text,
  "origem_outro" text,
  "consentimento_aceito_em" timestamp with time zone,
  "consentimento_versao" text,
  "email_confirmado_em" timestamp with time zone,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_aquisicao" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_aquisicao" IS 'Entrada e acompanhamento do lead no AmplifyOS V5. Uma ficha por pessoa ligada pelo mesmo creator_id. Mantém origem observada e origem declarada separadas, validação, convite e recebimento do formulário. Estados abertos e dados incrementais; não executa automações nem confirma fatos externos por preenchimento.';

CREATE TABLE public."creators_circle" (
  "creator_id" uuid NOT NULL,
  "circle_categoria_entrada" text,
  "circle_cargos_entrada" text[],
  "circle_situacao" text,
  "circle_acesso_criado_em" timestamp with time zone,
  "circle_cargos_atribuidos_em" timestamp with time zone,
  "acesso_referencia" text,
  "gmv_entrada_id" bigint,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_circle" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_circle" IS 'Ficha de ingresso e acesso no Circle, ligada à mesma pessoa. Guarda a categoria e os cargos de entrada separados das conferências periódicas. Não cria acesso, não atribui cargos e não infere sucesso de uma tentativa externa. Uma validação adicional da migração restringe a referência de GMV à finalidade de entrada.';

CREATE TABLE public."creators_conferencias" (
  "id" bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  "creator_id" uuid NOT NULL,
  "competencia" date NOT NULL,
  "assunto" text NOT NULL,
  "situacao" text DEFAULT 'pendente'::text NOT NULL,
  "verificado_em" timestamp with time zone,
  "fonte" text,
  "responsavel" text,
  "referencia" text,
  "acesso_esperado" boolean,
  "acesso_encontrado" boolean,
  "cargos_esperados" text[],
  "cargos_encontrados" text[],
  "observacao" text,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_conferencias" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_conferencias" IS 'Resultado do acompanhamento mensal por pessoa e assunto, separado dos fatos de vínculo, GMV e acesso. Uma linha por mês e assunto permite acompanhar pendências e correções com histórico. Não gera linhas, não consulta fontes e não infere saída pelo silêncio ou por dados faltantes.';

CREATE TABLE public."creators_contratos" (
  "id" bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  "creator_id" uuid NOT NULL,
  "vinculo_id" bigint NOT NULL,
  "numero_renovacao" integer DEFAULT 0 NOT NULL,
  "situacao" text DEFAULT 'previsto'::text NOT NULL,
  "confirmado_em" timestamp with time zone,
  "contrato_percentual" numeric(5,2),
  "contrato_prazo_meses" integer,
  "contrato_vigencia_inicio" date,
  "contrato_vigencia_fim" date,
  "contrato_renovacao_prevista_em" date,
  "contrato_ultima_renovacao_em" timestamp with time zone,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_contratos" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_contratos" IS 'Ciclos de contrato e renovação dentro de um período confirmado de vínculo. Ciclo zero identifica o contrato inicial; cada renovação recebe seu próprio registro. Previsão não confirma conclusão. Prazo, percentual, datas e regra de acompanhamento não são presumidos.';

CREATE TABLE public."creators_enderecos" (
  "creator_id" uuid NOT NULL,
  "endereco_estado" text,
  "endereco_cidade" text,
  "endereco_logradouro" text,
  "endereco_bairro" text,
  "endereco_numero" text,
  "endereco_complemento" text,
  "endereco_cep" text,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_enderecos" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_enderecos" IS 'Endereço atual informado para receber amostras e produtos. Uma ficha por pessoa ligada pelo mesmo creator_id. Não é histórico de envios nem prova de recebimento; dados opcionais e de uso interno autorizado.';

CREATE TABLE public."creators_gmv" (
  "id" bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  "creator_id" uuid NOT NULL,
  "finalidade" text NOT NULL,
  "natureza" text NOT NULL,
  "periodicidade" text NOT NULL,
  "periodo_inicio" date,
  "periodo_fim" date,
  "valor" numeric(18,2),
  "moeda" text DEFAULT 'BRL'::text NOT NULL,
  "situacao" text DEFAULT 'pendente'::text NOT NULL,
  "fonte" text,
  "observado_em" timestamp with time zone,
  "responsavel" text,
  "comprovante_referencia" text,
  "motivo_correcao" text,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_gmv" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_gmv" IS 'Uma medição de GMV por pessoa, finalidade, natureza, período e moeda. A entrada mantém seu valor declarado e seu valor verificado em linhas distintas. Cada mês de acompanhamento cria outra linha; correções atualizam a medição existente com histórico, sem duplicar períodos. Zero registrado é diferente de informação pendente ou indisponível. Não há colunas para cada mês nem somas automáticas entre períodos sobrepostos.';

CREATE TABLE public."creators_oportunidades" (
  "creator_id" uuid NOT NULL,
  "cor_raca" text,
  "tem_filhos" boolean,
  "alimentacao" text,
  "restricao_alimentar" text,
  "casa_praia_campo" boolean,
  "carro" boolean,
  "moto" boolean,
  "celular" text,
  "computador" boolean,
  "tripe" boolean,
  "microfone" boolean,
  "academia" boolean,
  "tem_pet" boolean,
  "pets" text,
  "outro_idioma" boolean,
  "video_idioma" text,
  "idiomas" text[],
  "idiomas_outros" text,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_oportunidades" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_oportunidades" IS 'Informações opcionais fornecidas pelo creator para seleção de oportunidades. Uma ficha por pessoa ligada pelo mesmo creator_id. Contém informações pessoais e autodeclarações; a futura aplicação deve limitar sua consulta à finalidade e aos usuários autorizados.';

CREATE TABLE public."creators_pagamentos" (
  "creator_id" uuid NOT NULL,
  "cpf" text,
  "cpf_validado" boolean,
  "pix_chave" text,
  "possui_cnpj" boolean,
  "cnpj" text,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_pagamentos" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_pagamentos" IS 'Dados de pagamento declarados pelo creator. Uma ficha por pessoa ligada pelo mesmo creator_id. Contém dados pessoais financeiros; consulta reservada à finalidade financeira autorizada. CPF informado e CPF validado são informações distintas; não inicia pagamentos.';

CREATE TABLE public."creators_perfil" (
  "creator_id" uuid NOT NULL,
  "foto_perfil_referencia" text,
  "mini_bio" text,
  "data_nascimento" date,
  "genero" text,
  "estado_civil" text,
  "camiseta" text,
  "camiseta_outro" text,
  "nichos" text[],
  "nichos_outros" text,
  "cabelo" text,
  "calcado" numeric(4,1),
  "expectativas" text,
  "meta_renda_mensal" numeric(18,2),
  "contexto_adicional" text,
  "plataformas" text[],
  "instagram" text,
  "plataformas_outros" text,
  "experiencia_live_shop" text,
  "teve_agencia_anterior" boolean,
  "nome_agencia_anterior" text,
  "experiencia_agencia" text,
  "produtos_excluidos" text,
  "inicio_amplify_informado" date,
  "rotina" text,
  "rotina_outro" text,
  "declarou_mais_2000_seguidores" boolean,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_perfil" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_perfil" IS 'Perfil e contexto de trabalho do creator no AmplifyOS V5. Uma ficha por pessoa ligada pelo mesmo creator_id. Respostas opcionais do formulário; a data de início declarada não substitui o início confirmado do vínculo.';

CREATE TABLE public."creators_vinculos" (
  "id" bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  "creator_id" uuid NOT NULL,
  "inicio_em" timestamp with time zone NOT NULL,
  "fim_em" timestamp with time zone,
  "fonte" text NOT NULL,
  "confirmado_em" timestamp with time zone NOT NULL,
  "motivo_saida" text,
  "criado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "atualizado_em" timestamp with time zone DEFAULT statement_timestamp() NOT NULL,
  "historico_jornada" jsonb DEFAULT '[]'::jsonb NOT NULL
);

ALTER TABLE public."creators_vinculos" ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public."creators_vinculos" IS 'Períodos confirmados de agenciamento da mesma pessoa. A saída encerra um período e preserva a ficha; o retorno abre outro período. Ausência de uma fonte ou lista parcial não confirma saída. Uma restrição adicional da migração impede sobreposição entre períodos.';

ALTER TABLE public."creators" ADD CONSTRAINT "creators_pkey" PRIMARY KEY (id);

ALTER TABLE public."creators_aquisicao" ADD CONSTRAINT "creators_aquisicao_pkey" PRIMARY KEY (creator_id);

ALTER TABLE public."creators_circle" ADD CONSTRAINT "creators_circle_pkey" PRIMARY KEY (creator_id);

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_competencia_assunto_unique" UNIQUE (creator_id, competencia, assunto);

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_pkey" PRIMARY KEY (id);

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_ciclo_unique" UNIQUE (vinculo_id, numero_renovacao);

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_pkey" PRIMARY KEY (id);

ALTER TABLE public."creators_enderecos" ADD CONSTRAINT "creators_enderecos_pkey" PRIMARY KEY (creator_id);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_periodo_unique" UNIQUE NULLS NOT DISTINCT (creator_id, finalidade, natureza, periodicidade, periodo_inicio, periodo_fim, moeda);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_pessoa_registro_unique" UNIQUE (creator_id, id);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_pkey" PRIMARY KEY (id);

ALTER TABLE public."creators_oportunidades" ADD CONSTRAINT "creators_oportunidades_pkey" PRIMARY KEY (creator_id);

ALTER TABLE public."creators_pagamentos" ADD CONSTRAINT "creators_pagamentos_pkey" PRIMARY KEY (creator_id);

ALTER TABLE public."creators_perfil" ADD CONSTRAINT "creators_perfil_pkey" PRIMARY KEY (creator_id);

ALTER TABLE public."creators_vinculos" ADD CONSTRAINT "creators_vinculos_pessoa_registro_unique" UNIQUE (creator_id, id);

ALTER TABLE public."creators_vinculos" ADD CONSTRAINT "creators_vinculos_pkey" PRIMARY KEY (id);

ALTER TABLE public."creators_vinculos" ADD CONSTRAINT "creators_vinculos_sem_sobreposicao" EXCLUDE USING gist (creator_id WITH =, tstzrange(inicio_em, fim_em, '[)'::text) WITH &&);

ALTER TABLE public."creators" ADD CONSTRAINT "creators_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_aquisicao" ADD CONSTRAINT "creators_aquisicao_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE RESTRICT;

ALTER TABLE public."creators_aquisicao" ADD CONSTRAINT "creators_aquisicao_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_circle" ADD CONSTRAINT "creators_circle_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON UPDATE RESTRICT ON DELETE RESTRICT;

ALTER TABLE public."creators_circle" ADD CONSTRAINT "creators_circle_datas_finitas" CHECK ((circle_acesso_criado_em IS NULL OR isfinite(circle_acesso_criado_em)) AND (circle_cargos_atribuidos_em IS NULL OR isfinite(circle_cargos_atribuidos_em)));

ALTER TABLE public."creators_circle" ADD CONSTRAINT "creators_circle_gmv_mesma_pessoa_fk" FOREIGN KEY (creator_id, gmv_entrada_id) REFERENCES creators_gmv(creator_id, id) ON UPDATE RESTRICT ON DELETE RESTRICT;

ALTER TABLE public."creators_circle" ADD CONSTRAINT "creators_circle_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_assunto_valido" CHECK (assunto = ANY (ARRAY['vinculo'::text, 'gmv'::text, 'acesso'::text]));

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON UPDATE RESTRICT ON DELETE RESTRICT;

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_data_finita" CHECK (verificado_em IS NULL OR isfinite(verificado_em));

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_fonte_nao_vazia" CHECK (fonte IS NULL OR btrim(fonte) <> ''::text);

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_mes_valido" CHECK (isfinite(competencia) AND EXTRACT(day FROM competencia) = 1::numeric);

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_resultado_com_fonte" CHECK (situacao = 'pendente'::text OR verificado_em IS NOT NULL AND fonte IS NOT NULL AND btrim(fonte) <> ''::text);

ALTER TABLE public."creators_conferencias" ADD CONSTRAINT "creators_conferencias_situacao_valida" CHECK (situacao = ANY (ARRAY['pendente'::text, 'conferido'::text, 'divergente'::text, 'indisponivel'::text]));

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_confirmacao_presente" CHECK (situacao <> 'confirmado'::text OR confirmado_em IS NOT NULL);

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON UPDATE RESTRICT ON DELETE RESTRICT;

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_datas_finitas" CHECK ((confirmado_em IS NULL OR isfinite(confirmado_em)) AND (contrato_vigencia_inicio IS NULL OR isfinite(contrato_vigencia_inicio)) AND (contrato_vigencia_fim IS NULL OR isfinite(contrato_vigencia_fim)) AND (contrato_renovacao_prevista_em IS NULL OR isfinite(contrato_renovacao_prevista_em)) AND (contrato_ultima_renovacao_em IS NULL OR isfinite(contrato_ultima_renovacao_em)));

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_numero_valido" CHECK (numero_renovacao >= 0);

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_percentual_valido" CHECK (contrato_percentual >= 0::numeric AND contrato_percentual <= 100::numeric AND (contrato_percentual <> ALL (ARRAY['NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric])));

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_pessoa_vinculo_fk" FOREIGN KEY (creator_id, vinculo_id) REFERENCES creators_vinculos(creator_id, id) ON UPDATE RESTRICT ON DELETE RESTRICT;

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_prazo_valido" CHECK (contrato_prazo_meses > 0);

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_situacao_valida" CHECK (situacao = ANY (ARRAY['previsto'::text, 'confirmado'::text, 'encerrado'::text, 'cancelado'::text]));

ALTER TABLE public."creators_contratos" ADD CONSTRAINT "creators_contratos_vigencia_valida" CHECK (contrato_vigencia_fim >= contrato_vigencia_inicio);

ALTER TABLE public."creators_enderecos" ADD CONSTRAINT "creators_enderecos_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE RESTRICT;

ALTER TABLE public."creators_enderecos" ADD CONSTRAINT "creators_enderecos_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_ausencia_sem_zero" CHECK ((situacao <> ALL (ARRAY['pendente'::text, 'indisponivel'::text])) OR valor IS NULL);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON UPDATE RESTRICT ON DELETE RESTRICT;

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_datas_finitas" CHECK ((periodo_inicio IS NULL OR isfinite(periodo_inicio)) AND (periodo_fim IS NULL OR isfinite(periodo_fim)) AND (observado_em IS NULL OR isfinite(observado_em)));

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_finalidade_valida" CHECK (finalidade = ANY (ARRAY['entrada'::text, 'acompanhamento'::text]));

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_fonte_nao_vazia" CHECK (fonte IS NULL OR btrim(fonte) <> ''::text);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_janela_28_dias" CHECK (periodicidade <> 'janela_28_dias'::text OR periodo_fim = (periodo_inicio + 27));

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_mes_completo" CHECK (periodicidade <> 'mes_calendario'::text OR EXTRACT(day FROM periodo_inicio) = 1::numeric AND periodo_fim = (periodo_inicio + '1 mon'::interval - '1 day'::interval)::date);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_moeda_valida" CHECK (moeda ~ '^[A-Z]{3}$'::text);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_natureza_valida" CHECK (natureza = ANY (ARRAY['declarado'::text, 'verificado'::text]));

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_periodicidade_valida" CHECK (periodicidade = ANY (ARRAY['mes_calendario'::text, 'janela_28_dias'::text, 'periodo_personalizado'::text, 'nao_informado'::text]));

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_periodo_completo" CHECK (periodicidade = 'nao_informado'::text AND finalidade = 'entrada'::text AND periodo_inicio IS NULL AND periodo_fim IS NULL OR periodicidade <> 'nao_informado'::text AND periodo_inicio IS NOT NULL AND periodo_fim IS NOT NULL);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_periodo_valido" CHECK (periodo_fim >= periodo_inicio);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_registro_completo" CHECK (situacao <> 'registrado'::text OR valor IS NOT NULL AND fonte IS NOT NULL AND btrim(fonte) <> ''::text AND observado_em IS NOT NULL);

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_situacao_valida" CHECK (situacao = ANY (ARRAY['pendente'::text, 'parcial'::text, 'registrado'::text, 'indisponivel'::text]));

ALTER TABLE public."creators_gmv" ADD CONSTRAINT "creators_gmv_valor_valido" CHECK (valor >= 0::numeric AND (valor <> ALL (ARRAY['NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric])));

ALTER TABLE public."creators_oportunidades" ADD CONSTRAINT "creators_oportunidades_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE RESTRICT;

ALTER TABLE public."creators_oportunidades" ADD CONSTRAINT "creators_oportunidades_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_pagamentos" ADD CONSTRAINT "creators_pagamentos_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE RESTRICT;

ALTER TABLE public."creators_pagamentos" ADD CONSTRAINT "creators_pagamentos_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_perfil" ADD CONSTRAINT "creators_perfil_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE RESTRICT;

ALTER TABLE public."creators_perfil" ADD CONSTRAINT "creators_perfil_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_vinculos" ADD CONSTRAINT "creators_vinculos_creator_id_fkey" FOREIGN KEY (creator_id) REFERENCES creators(id) ON UPDATE RESTRICT ON DELETE RESTRICT;

ALTER TABLE public."creators_vinculos" ADD CONSTRAINT "creators_vinculos_datas_finitas" CHECK (isfinite(inicio_em) AND isfinite(confirmado_em) AND (fim_em IS NULL OR isfinite(fim_em)));

ALTER TABLE public."creators_vinculos" ADD CONSTRAINT "creators_vinculos_fonte_presente" CHECK (btrim(fonte) <> ''::text);

ALTER TABLE public."creators_vinculos" ADD CONSTRAINT "creators_vinculos_historico_lista" CHECK (jsonb_typeof(historico_jornada) = 'array'::text);

ALTER TABLE public."creators_vinculos" ADD CONSTRAINT "creators_vinculos_periodo_valido" CHECK (fim_em > inicio_em);

CREATE INDEX creators_telefone_idx ON public.creators USING btree (telefone) WHERE (telefone IS NOT NULL);

CREATE INDEX creators_aquisicao_entrada_idx ON public.creators_aquisicao USING btree (primeira_mensagem_em DESC);

CREATE INDEX creators_aquisicao_etapa_idx ON public.creators_aquisicao USING btree (etapa_atual, situacao_atual);

CREATE INDEX creators_circle_gmv_entrada_idx ON public.creators_circle USING btree (gmv_entrada_id) WHERE (gmv_entrada_id IS NOT NULL);

CREATE INDEX creators_circle_pessoa_gmv_idx ON public.creators_circle USING btree (creator_id, gmv_entrada_id);

CREATE INDEX creators_conferencias_pendencias_idx ON public.creators_conferencias USING btree (competencia, assunto, situacao, creator_id) WHERE (situacao <> 'conferido'::text);

CREATE INDEX creators_contratos_pessoa_vinculo_idx ON public.creators_contratos USING btree (creator_id, vinculo_id);

CREATE INDEX creators_contratos_proxima_renovacao_idx ON public.creators_contratos USING btree (contrato_renovacao_prevista_em) WHERE ((situacao = ANY (ARRAY['previsto'::text, 'confirmado'::text])) AND (contrato_renovacao_prevista_em IS NOT NULL));

CREATE INDEX creators_gmv_acompanhamento_pendente_idx ON public.creators_gmv USING btree (periodo_inicio, creator_id) WHERE ((finalidade = 'acompanhamento'::text) AND (situacao = ANY (ARRAY['pendente'::text, 'parcial'::text, 'indisponivel'::text])));

CREATE INDEX creators_gmv_pessoa_periodo_idx ON public.creators_gmv USING btree (creator_id, periodo_inicio DESC, periodo_fim DESC);

CREATE UNIQUE INDEX creators_gmv_uma_entrada_por_natureza_idx ON public.creators_gmv USING btree (creator_id, natureza) WHERE (finalidade = 'entrada'::text);

CREATE INDEX creators_vinculos_periodo_idx ON public.creators_vinculos USING btree (creator_id, inicio_em DESC, fim_em);

CREATE UNIQUE INDEX creators_vinculos_um_aberto_idx ON public.creators_vinculos USING btree (creator_id) WHERE (fim_em IS NULL);

CREATE OR REPLACE FUNCTION public.creators_controlar_ficha()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
declare
  antes jsonb := '{}'::jsonb; depois jsonb; alterados jsonb; chave text;
  marcos text[] := array[
    'etapa_atual','situacao_atual','possui_agencia_atual','deseja_sair_agencia',
    'saida_agencia_confirmada_em','interesse_agenciamento','validacao_situacao',
    'validacao_confirmada_em','quer_convite','convite_criado_em','convite_enviado_em',
    'convite_situacao','convite_aceito_em','formulario_situacao',
    'formulario_disponibilizado_em','formulario_iniciado_em','formulario_recebido_em',
    'email_confirmado_em','consentimento_aceito_em','consentimento_versao',
    'inicio_em','fim_em','confirmado_em','numero_renovacao','situacao',
    'contrato_percentual','contrato_prazo_meses','contrato_vigencia_inicio',
    'contrato_vigencia_fim','contrato_renovacao_prevista_em','contrato_ultima_renovacao_em',
    'finalidade','natureza','periodicidade','periodo_inicio','periodo_fim','valor','moeda',
    'observado_em','circle_categoria_entrada','circle_cargos_entrada','circle_situacao',
    'circle_acesso_criado_em','circle_cargos_atribuidos_em','competencia','assunto',
    'verificado_em','acesso_esperado','acesso_encontrado','cargos_esperados','cargos_encontrados',
    'vinculo_id','gmv_entrada_id'
  ];
  antes_marcos jsonb; depois_marcos jsonb; evento jsonb;
begin
  if tg_op = 'INSERT' then
    if new.historico_jornada is distinct from '[]'::jsonb then
      raise exception using errcode='23514', message='O histórico é gerado pelo banco.';
    end if;
    new.criado_em := statement_timestamp(); new.atualizado_em := new.criado_em;
  else
    foreach chave in array tg_argv loop
      if to_jsonb(new)->chave is distinct from to_jsonb(old)->chave then
        raise exception using errcode='23514', message='A identidade do registro é permanente: '||chave;
      end if;
    end loop;
    if new.criado_em is distinct from old.criado_em or new.historico_jornada is distinct from old.historico_jornada then
      raise exception using errcode='23514', message='Data de criação e histórico são controlados pelo banco.';
    end if;
    antes := to_jsonb(old) - array['id','creator_id','criado_em','atualizado_em','historico_jornada'];
  end if;
  depois := to_jsonb(new) - array['id','creator_id','criado_em','atualizado_em','historico_jornada'];
  select coalesce(jsonb_agg(x.key order by x.key),'[]'::jsonb) into alterados
  from jsonb_each(depois) x where x.value is distinct from antes->x.key
    and (tg_op <> 'INSERT' or x.value <> 'null'::jsonb);
  if tg_op='UPDATE' and alterados='[]'::jsonb then
    new.atualizado_em := old.atualizado_em; return new;
  end if;
  new.atualizado_em := statement_timestamp();
  select coalesce(jsonb_object_agg(x.key,x.value),'{}'::jsonb) into antes_marcos
    from jsonb_each(antes) x where x.key=any(marcos);
  select coalesce(jsonb_object_agg(x.key,x.value),'{}'::jsonb) into depois_marcos
    from jsonb_each(depois) x where x.key=any(marcos);
  evento := jsonb_build_object('registrado_em',statement_timestamp(),'operacao',tg_op,
    'tabela',tg_table_name,'papel_banco',current_user,'campos_alterados',alterados,
    'antes',antes_marcos,'depois',depois_marcos);
  new.historico_jornada := case when tg_op='INSERT' then jsonb_build_array(evento)
    else old.historico_jornada || jsonb_build_array(evento) end;
  return new;
end;
$function$
;

REVOKE ALL ON FUNCTION public.creators_controlar_ficha() FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.creators_controlar_ficha() TO service_role;

CREATE OR REPLACE FUNCTION public.creators_inicializar_fichas()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  insert into public.creators_aquisicao(creator_id) values(new.id);
  insert into public.creators_perfil(creator_id) values(new.id);
  insert into public.creators_oportunidades(creator_id) values(new.id);
  insert into public.creators_enderecos(creator_id) values(new.id);
  insert into public.creators_pagamentos(creator_id) values(new.id);
  insert into public.creators_circle(creator_id) values(new.id);
  return new;
end;
$function$
;

REVOKE ALL ON FUNCTION public.creators_inicializar_fichas() FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.creators_inicializar_fichas() TO service_role;

CREATE OR REPLACE FUNCTION public.creators_validar_relacoes()
 RETURNS trigger
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
begin
  if tg_table_name='creators_vinculos' then
    -- Serializa alterações de períodos para a mesma pessoa.
    perform 1 from public.creators where id=new.creator_id for update;
    if new.fim_em is not null and new.fim_em <= new.inicio_em then
      raise exception using errcode='23514',message='O fim do vínculo deve ser posterior ao início.';
    end if;
    if exists(select 1 from public.creators_vinculos v
      where v.creator_id=new.creator_id and v.id is distinct from new.id
        and tstzrange(v.inicio_em,v.fim_em,'[)') && tstzrange(new.inicio_em,new.fim_em,'[)')) then
      raise exception using errcode='23514',message='Os períodos de vínculo da mesma pessoa não podem se sobrepor.';
    end if;
  elsif tg_table_name='creators_circle' then
    if new.gmv_entrada_id is not null then
    perform 1 from public.creators_gmv g where g.id=new.gmv_entrada_id and g.creator_id=new.creator_id
      and g.finalidade='entrada' and g.natureza='verificado' and g.situacao='registrado' for share;
    if not found then
      raise exception using errcode='23514',message='A categoria de entrada precisa referenciar GMV verificado e registrado de entrada da mesma pessoa.';
    end if;
    end if;
  elsif tg_table_name='creators_gmv' and tg_op='UPDATE' then
    if old.observado_em is not null and new.observado_em < old.observado_em then
      raise exception using errcode='23514',message='Observação atrasada não pode substituir uma medição mais recente.';
    end if;
    if old.valor is not null and (new.valor is distinct from old.valor
      or new.periodicidade is distinct from old.periodicidade
      or new.periodo_inicio is distinct from old.periodo_inicio
      or new.periodo_fim is distinct from old.periodo_fim or new.moeda is distinct from old.moeda)
      and nullif(btrim(new.motivo_correcao),'') is null then
      raise exception using errcode='23514',message='Uma correção de valor ou período precisa de motivo; o histórico preservará o antes e o depois.';
    end if;
    if exists(select 1 from public.creators_circle c where c.gmv_entrada_id=new.id)
      and (new.finalidade<>'entrada' or new.natureza<>'verificado' or new.situacao<>'registrado') then
      raise exception using errcode='23514',message='GMV usado no ingresso do Circle precisa continuar verificado e registrado.';
    end if;
  end if;
  return new;
end;
$function$
;

REVOKE ALL ON FUNCTION public.creators_validar_relacoes() FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.creators_validar_relacoes() TO service_role;

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
  v_expected_reference text; v_mode text;
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
       ('creator_id','event_id','form_instance_id','received_at','source','attachments','first_inbound','origin','email_confirmation','gmv_period')) then
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

  -- Lock curto do ensaio protege evento, pessoa e identidade entre chamadas desta
  -- funcao. Nao ha chamadas externas dentro da transacao.
  perform pg_advisory_xact_lock(hashtextextended('atendimento-v5-ensaio:cadastro',0));
  v_fingerprint:=md5(p_payload::text||E'\n'||p_context::text);
  v_ref:='ensaio-v5:'||v_event::text||':'||v_fingerprint;
  select creator_id,formulario_submissao_referencia into v_existing_id,v_existing_ref
    from public.creators_aquisicao where formulario_submissao_referencia like 'ensaio-v5:'||v_event::text||':%' limit 1;
  if v_existing_id is not null then
    if v_existing_id<>v_creator or v_existing_ref<>v_ref then raise exception using errcode='23505',message='ensaio_evento_reutilizado_com_outro_conteudo'; end if;
    select id into v_gmv_id from public.creators_gmv where creator_id=v_creator and finalidade='entrada' and natureza='declarado';
    return jsonb_build_object('creator_id',v_creator,'event_id',v_event,'gmv_id',v_gmv_id,'replayed',true,'status','cadastro_recebido_ensaio');
  end if;
  select formulario_submissao_referencia into v_existing_ref from public.creators_aquisicao where creator_id=v_creator for update;
  if v_existing_ref is not null then raise exception using errcode='23505',message='ensaio_pessoa_ja_tem_formulario_final'; end if;
  select * into v_existing from public.creators where id=v_creator for update;
  if v_existing.id is not null and (
       (v_existing.email is not null and lower(btrim(v_existing.email))<>p_payload->'identity'->>'email')
       or (v_existing.whatsapp is not null and v_existing.whatsapp<>p_payload->'identity'->>'whatsapp')
       or (v_existing.tiktok is not null and lower(ltrim(v_existing.tiktok,'@'))<>p_payload->'identity'->>'tiktok')) then
    raise exception using errcode='23505',message='ensaio_identidade_existente_exige_conferencia';
  end if;
  if exists(select 1 from public.creators c where c.id<>v_creator and (
       lower(btrim(c.email))=p_payload->'identity'->>'email'
       or c.whatsapp=p_payload->'identity'->>'whatsapp'
       or c.telefone=p_payload->'identity'->>'whatsapp'
       or lower(ltrim(c.tiktok,'@'))=p_payload->'identity'->>'tiktok')) then
    raise exception using errcode='23505',message='ensaio_identidade_ambigua';
  end if;

  insert into public.creators(id,nome,email,whatsapp,tiktok)
  values(v_creator,p_payload->'identity'->>'nome',p_payload->'identity'->>'email',p_payload->'identity'->>'whatsapp',p_payload->'identity'->>'tiktok')
  on conflict(id) do update set nome=excluded.nome,email=excluded.email,whatsapp=excluded.whatsapp,tiktok=excluded.tiktok;
  -- O trigger existente inicializa as seis fichas no INSERT da pessoa.
  -- As atualizacoes abaixo nunca escrevem id, criado_em ou historico_jornada.
  insert into public.creators_aquisicao(creator_id) values(v_creator) on conflict(creator_id) do nothing;

  insert into public.creators_perfil(creator_id,foto_perfil_referencia,mini_bio,expectativas,meta_renda_mensal,contexto_adicional,plataformas,instagram,plataformas_outros,experiencia_live_shop,teve_agencia_anterior,nome_agencia_anterior,experiencia_agencia,produtos_excluidos,inicio_amplify_informado,data_nascimento,genero,estado_civil,camiseta,camiseta_outro,nichos,nichos_outros,rotina,rotina_outro,cabelo,calcado,declarou_mais_2000_seguidores)
  select v_creator,r.foto_perfil_referencia,r.mini_bio,r.expectativas,r.meta_renda_mensal,r.contexto_adicional,r.plataformas,r.instagram,r.plataformas_outros,r.experiencia_live_shop,r.teve_agencia_anterior,r.nome_agencia_anterior,r.experiencia_agencia,r.produtos_excluidos,r.inicio_amplify_informado,r.data_nascimento,r.genero,r.estado_civil,r.camiseta,r.camiseta_outro,r.nichos,r.nichos_outros,r.rotina,r.rotina_outro,r.cabelo,r.calcado,r.declarou_mais_2000_seguidores
  from jsonb_populate_record(null::public.creators_perfil,p_payload->'branches'->'creators_perfil') r
  on conflict(creator_id) do update set foto_perfil_referencia=excluded.foto_perfil_referencia,
    mini_bio=excluded.mini_bio,
    expectativas=excluded.expectativas,
    meta_renda_mensal=excluded.meta_renda_mensal,
    contexto_adicional=excluded.contexto_adicional,
    plataformas=excluded.plataformas,
    instagram=excluded.instagram,
    plataformas_outros=excluded.plataformas_outros,
    experiencia_live_shop=excluded.experiencia_live_shop,
    teve_agencia_anterior=excluded.teve_agencia_anterior,
    nome_agencia_anterior=excluded.nome_agencia_anterior,
    experiencia_agencia=excluded.experiencia_agencia,
    produtos_excluidos=excluded.produtos_excluidos,
    inicio_amplify_informado=excluded.inicio_amplify_informado,
    data_nascimento=excluded.data_nascimento,
    genero=excluded.genero,
    estado_civil=excluded.estado_civil,
    camiseta=excluded.camiseta,
    camiseta_outro=excluded.camiseta_outro,
    nichos=excluded.nichos,
    nichos_outros=excluded.nichos_outros,
    rotina=excluded.rotina,
    rotina_outro=excluded.rotina_outro,
    cabelo=excluded.cabelo,
    calcado=excluded.calcado,
    declarou_mais_2000_seguidores=excluded.declarou_mais_2000_seguidores;

  insert into public.creators_oportunidades(creator_id,tem_filhos,cor_raca,alimentacao,restricao_alimentar,casa_praia_campo,carro,moto,celular,computador,tripe,microfone,academia,tem_pet,pets,outro_idioma,video_idioma,idiomas,idiomas_outros)
  select v_creator,r.tem_filhos,r.cor_raca,r.alimentacao,r.restricao_alimentar,r.casa_praia_campo,r.carro,r.moto,r.celular,r.computador,r.tripe,r.microfone,r.academia,r.tem_pet,r.pets,r.outro_idioma,r.video_idioma,r.idiomas,r.idiomas_outros
  from jsonb_populate_record(null::public.creators_oportunidades,p_payload->'branches'->'creators_oportunidades') r
  on conflict(creator_id) do update set tem_filhos=excluded.tem_filhos,
    cor_raca=excluded.cor_raca,
    alimentacao=excluded.alimentacao,
    restricao_alimentar=excluded.restricao_alimentar,
    casa_praia_campo=excluded.casa_praia_campo,
    carro=excluded.carro,
    moto=excluded.moto,
    celular=excluded.celular,
    computador=excluded.computador,
    tripe=excluded.tripe,
    microfone=excluded.microfone,
    academia=excluded.academia,
    tem_pet=excluded.tem_pet,
    pets=excluded.pets,
    outro_idioma=excluded.outro_idioma,
    video_idioma=excluded.video_idioma,
    idiomas=excluded.idiomas,
    idiomas_outros=excluded.idiomas_outros;

  insert into public.creators_enderecos(creator_id,endereco_estado,endereco_cidade,endereco_logradouro,endereco_bairro,endereco_numero,endereco_complemento,endereco_cep)
  select v_creator,r.endereco_estado,r.endereco_cidade,r.endereco_logradouro,r.endereco_bairro,r.endereco_numero,r.endereco_complemento,r.endereco_cep
  from jsonb_populate_record(null::public.creators_enderecos,p_payload->'branches'->'creators_enderecos') r
  on conflict(creator_id) do update set endereco_estado=excluded.endereco_estado,
    endereco_cidade=excluded.endereco_cidade,
    endereco_logradouro=excluded.endereco_logradouro,
    endereco_bairro=excluded.endereco_bairro,
    endereco_numero=excluded.endereco_numero,
    endereco_complemento=excluded.endereco_complemento,
    endereco_cep=excluded.endereco_cep;

  insert into public.creators_pagamentos(creator_id,cpf,pix_chave,possui_cnpj,cnpj)
  select v_creator,r.cpf,r.pix_chave,r.possui_cnpj,r.cnpj
  from jsonb_populate_record(null::public.creators_pagamentos,p_payload->'branches'->'creators_pagamentos') r
  on conflict(creator_id) do update set cpf=excluded.cpf,
    pix_chave=excluded.pix_chave,
    possui_cnpj=excluded.possui_cnpj,
    cnpj=excluded.cnpj;

  insert into public.creators_circle(creator_id) values(v_creator) on conflict(creator_id) do nothing;

  update public.creators_aquisicao a set
    origem_informada_formulario=p_payload->'branches'->'creators_aquisicao'->>'origem_informada_formulario',
    origem_outro=p_payload->'branches'->'creators_aquisicao'->>'origem_outro',
    canal_entrada=coalesce(a.canal_entrada,v_channel),
    primeira_mensagem_em=coalesce(a.primeira_mensagem_em,v_first),
    origem_fonte=case when a.origem_entrada is null then coalesce(v_origin_source,a.origem_fonte) else a.origem_fonte end,
    origem_detalhe=case when a.origem_entrada is null then coalesce(v_origin_ref,a.origem_detalhe) else a.origem_detalhe end,
    origem_entrada=coalesce(a.origem_entrada,v_origin),
    formulario_situacao='recebido_ensaio_whatsapp',formulario_recebido_em=v_received,
    formulario_versao=p_payload->>'form_version',formulario_submissao_referencia=v_ref,
    consentimento_aceito_em=v_received,consentimento_versao=p_payload->'consent'->>'version',
    email_confirmado_em=coalesce(v_email_confirmed,a.email_confirmado_em)
  where a.creator_id=v_creator;
  -- Nao inventar o intervalo real dos 28 dias; sem fonte do periodo, registrar
  -- entrada com periodicidade nao_informado, mantendo o valor declarado.
  insert into public.creators_gmv(creator_id,finalidade,natureza,periodicidade,periodo_inicio,periodo_fim,
    valor,moeda,situacao,fonte,observado_em,comprovante_referencia,motivo_correcao)
  values(v_creator,'entrada','declarado',v_mode,v_start,v_end,(p_payload->'gmv'->>'valor')::numeric,
    'BRL','registrado','formulario_ensaio:'||v_event::text,v_received,p_payload->'gmv'->>'comprovante_referencia',null)
  on conflict(creator_id,natureza) where finalidade='entrada' do update set
    periodicidade=excluded.periodicidade,periodo_inicio=excluded.periodo_inicio,periodo_fim=excluded.periodo_fim,
    valor=excluded.valor,moeda=excluded.moeda,situacao=excluded.situacao,fonte=excluded.fonte,
    observado_em=excluded.observado_em,comprovante_referencia=excluded.comprovante_referencia,
    motivo_correcao='Atualizacao pelo formulario de ensaio '||v_event::text
  returning id into v_gmv_id;
  return jsonb_build_object('creator_id',v_creator,'event_id',v_event,'gmv_id',v_gmv_id,
    'replayed',false,'status','cadastro_recebido_ensaio');
end;
$function$
;

REVOKE ALL ON FUNCTION public.registrar_cadastro_ensaio_v5(jsonb,jsonb) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.registrar_cadastro_ensaio_v5(jsonb,jsonb) TO service_role;

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
  insert into public.creators_gmv(creator_id,finalidade,natureza,periodicidade,periodo_inicio,periodo_fim,
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

REVOKE ALL ON FUNCTION public.registrar_gmv_mensal(uuid,date,numeric,text,timestamp with time zone,text,text) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.registrar_gmv_mensal(uuid,date,numeric,text,timestamp with time zone,text,text) TO service_role;

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('id');

CREATE TRIGGER creators_30_inicializar AFTER INSERT ON creators FOR EACH ROW EXECUTE FUNCTION creators_inicializar_fichas();

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_aquisicao FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('creator_id');

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_circle FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('creator_id');

CREATE TRIGGER creators_20_validar BEFORE INSERT OR UPDATE ON creators_circle FOR EACH ROW EXECUTE FUNCTION creators_validar_relacoes();

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_conferencias FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('id', 'creator_id');

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_contratos FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('id', 'creator_id', 'vinculo_id');

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_enderecos FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('creator_id');

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_gmv FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('id', 'creator_id');

CREATE TRIGGER creators_20_validar BEFORE INSERT OR UPDATE ON creators_gmv FOR EACH ROW EXECUTE FUNCTION creators_validar_relacoes();

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_oportunidades FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('creator_id');

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_pagamentos FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('creator_id');

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_perfil FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('creator_id');

CREATE TRIGGER creators_10_controlar BEFORE INSERT OR UPDATE ON creators_vinculos FOR EACH ROW EXECUTE FUNCTION creators_controlar_ficha('id', 'creator_id');

CREATE TRIGGER creators_20_validar BEFORE INSERT OR UPDATE ON creators_vinculos FOR EACH ROW EXECUTE FUNCTION creators_validar_relacoes();

CREATE VIEW public."creators_conferencia_mensal" WITH (security_invoker=true) AS
 WITH meses AS (
         SELECT DISTINCT v.creator_id,
            m_1.m::date AS competencia
           FROM creators_vinculos v
             CROSS JOIN LATERAL generate_series(date_trunc('month'::text, (v.inicio_em AT TIME ZONE 'America/Sao_Paulo'::text)), date_trunc('month'::text, (LEAST(COALESCE(v.fim_em - '00:00:00.000001'::interval, statement_timestamp()), statement_timestamp()) AT TIME ZONE 'America/Sao_Paulo'::text)), '1 mon'::interval) m_1(m)
          WHERE v.inicio_em <= statement_timestamp()
        )
 SELECT c.id AS creator_id,
    c.nome,
    m.competencia,
    COALESCE(g.situacao, 'nao_atualizado'::text) AS gmv_situacao,
    g.valor AS gmv_valor,
    g.observado_em AS gmv_observado_em,
    COALESCE(cv.situacao, 'pendente'::text) AS vinculo_conferencia,
    COALESCE(cg.situacao, 'pendente'::text) AS gmv_conferencia,
    COALESCE(ca.situacao, 'pendente'::text) AS acesso_conferencia,
    ca.verificado_em AS acesso_conferido_em,
    ca.acesso_esperado,
    ca.acesso_encontrado,
    ca.cargos_esperados,
    ca.cargos_encontrados,
        CASE
            WHEN ca.id IS NULL OR ca.situacao = 'pendente'::text THEN 'pendente'::text
            WHEN ca.situacao = 'indisponivel'::text THEN 'indisponivel'::text
            WHEN ca.situacao = 'divergente'::text THEN 'divergente'::text
            WHEN ca.acesso_esperado IS NULL OR ca.acesso_encontrado IS NULL THEN 'incompleto'::text
            WHEN ca.acesso_esperado IS DISTINCT FROM ca.acesso_encontrado THEN 'divergente'::text
            WHEN ca.acesso_esperado = false THEN 'conforme_sem_acesso'::text
            WHEN ca.cargos_esperados IS NULL OR ca.cargos_encontrados IS NULL THEN 'incompleto'::text
            WHEN ca.cargos_esperados <@ ca.cargos_encontrados AND ca.cargos_encontrados <@ ca.cargos_esperados THEN 'conforme'::text
            ELSE 'divergente'::text
        END AS acesso_resultado,
    ca.responsavel AS acesso_responsavel
   FROM meses m
     JOIN creators c ON c.id = m.creator_id
     LEFT JOIN creators_gmv g ON g.creator_id = m.creator_id AND g.finalidade = 'acompanhamento'::text AND g.natureza = 'verificado'::text AND g.periodicidade = 'mes_calendario'::text AND g.moeda = 'BRL'::text AND g.periodo_inicio = m.competencia
     LEFT JOIN creators_conferencias cv ON cv.creator_id = m.creator_id AND cv.competencia = m.competencia AND cv.assunto = 'vinculo'::text
     LEFT JOIN creators_conferencias cg ON cg.creator_id = m.creator_id AND cg.competencia = m.competencia AND cg.assunto = 'gmv'::text
     LEFT JOIN creators_conferencias ca ON ca.creator_id = m.creator_id AND ca.competencia = m.competencia AND ca.assunto = 'acesso'::text;

REVOKE ALL ON public."creators_conferencia_mensal" FROM PUBLIC, anon, authenticated;

CREATE VIEW public."creators_ficha_completa" WITH (security_invoker=true) AS
 SELECT c.id AS creator_id,
    c.nome,
    c.telefone,
    c.whatsapp,
    c.email,
    c.tiktok,
    c.criado_em,
    c.atualizado_em,
    to_jsonb(a.*) - ARRAY['creator_id'::text, 'criado_em'::text, 'atualizado_em'::text, 'historico_jornada'::text] AS aquisicao,
    to_jsonb(p.*) - ARRAY['creator_id'::text, 'criado_em'::text, 'atualizado_em'::text, 'historico_jornada'::text] AS perfil,
    to_jsonb(o.*) - ARRAY['creator_id'::text, 'criado_em'::text, 'atualizado_em'::text, 'historico_jornada'::text] AS oportunidades,
    to_jsonb(e.*) - ARRAY['creator_id'::text, 'criado_em'::text, 'atualizado_em'::text, 'historico_jornada'::text] AS endereco,
    to_jsonb(f.*) - ARRAY['creator_id'::text, 'criado_em'::text, 'atualizado_em'::text, 'historico_jornada'::text] AS pagamentos,
    to_jsonb(ci.*) - ARRAY['creator_id'::text, 'criado_em'::text, 'atualizado_em'::text, 'historico_jornada'::text] AS circle
   FROM creators c
     JOIN creators_aquisicao a ON a.creator_id = c.id
     JOIN creators_perfil p ON p.creator_id = c.id
     JOIN creators_oportunidades o ON o.creator_id = c.id
     JOIN creators_enderecos e ON e.creator_id = c.id
     JOIN creators_pagamentos f ON f.creator_id = c.id
     JOIN creators_circle ci ON ci.creator_id = c.id;

REVOKE ALL ON public."creators_ficha_completa" FROM PUBLIC, anon, authenticated;

CREATE VIEW public."creators_gmv_mensal" WITH (security_invoker=true) AS
 WITH sequencia AS (
         SELECT g.id,
            g.creator_id,
            g.finalidade,
            g.natureza,
            g.periodicidade,
            g.periodo_inicio,
            g.periodo_fim,
            g.valor,
            g.moeda,
            g.situacao,
            g.fonte,
            g.observado_em,
            g.responsavel,
            g.comprovante_referencia,
            g.motivo_correcao,
            g.criado_em,
            g.atualizado_em,
            g.historico_jornada,
            lag(g.valor) OVER w AS valor_anterior,
            lag(g.periodo_inicio) OVER w AS inicio_anterior,
            lag(g.situacao) OVER w AS situacao_anterior
           FROM creators_gmv g
          WHERE g.finalidade = 'acompanhamento'::text AND g.natureza = 'verificado'::text AND g.periodicidade = 'mes_calendario'::text
          WINDOW w AS (PARTITION BY g.creator_id, g.moeda ORDER BY g.periodo_inicio)
        ), classificacao AS (
         SELECT s.id,
            s.creator_id,
            s.finalidade,
            s.natureza,
            s.periodicidade,
            s.periodo_inicio,
            s.periodo_fim,
            s.valor,
            s.moeda,
            s.situacao,
            s.fonte,
            s.observado_em,
            s.responsavel,
            s.comprovante_referencia,
            s.motivo_correcao,
            s.criado_em,
            s.atualizado_em,
            s.historico_jornada,
            s.valor_anterior,
            s.inicio_anterior,
            s.situacao_anterior,
                CASE
                    WHEN s.periodo_fim >= (statement_timestamp() AT TIME ZONE 'America/Sao_Paulo'::text)::date THEN 'mes_em_andamento'::text
                    WHEN s.situacao <> 'registrado'::text THEN 'dado_incompleto'::text
                    WHEN s.inicio_anterior IS NULL OR s.inicio_anterior <> (s.periodo_inicio - '1 mon'::interval)::date THEN 'mes_anterior_sem_registro'::text
                    WHEN s.situacao_anterior <> 'registrado'::text THEN 'mes_anterior_incompleto'::text
                    WHEN s.valor_anterior = 0::numeric THEN 'base_anterior_zero'::text
                    ELSE 'comparavel'::text
                END AS comparacao_situacao
           FROM sequencia s
        )
 SELECT id,
    creator_id,
    periodo_inicio,
    periodo_fim,
    valor,
    moeda,
    situacao,
    fonte,
    observado_em,
    valor_anterior,
    inicio_anterior,
    comparacao_situacao,
        CASE
            WHEN comparacao_situacao = ANY (ARRAY['comparavel'::text, 'base_anterior_zero'::text]) THEN valor - valor_anterior
            ELSE NULL::numeric
        END AS variacao_valor,
        CASE
            WHEN comparacao_situacao = 'comparavel'::text THEN round((valor - valor_anterior) * 100::numeric / NULLIF(valor_anterior, 0::numeric), 2)
            ELSE NULL::numeric
        END AS variacao_percentual
   FROM classificacao;

REVOKE ALL ON public."creators_gmv_mensal" FROM PUBLIC, anon, authenticated;

CREATE VIEW public."creators_linha_tempo" WITH (security_invoker=true) AS
 SELECT t.id AS creator_id,
    'creators'::text AS tabela,
    t.id::text AS registro_id,
    e.evento
   FROM creators t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_aquisicao'::text AS tabela,
    t.creator_id::text AS registro_id,
    e.evento
   FROM creators_aquisicao t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_perfil'::text AS tabela,
    t.creator_id::text AS registro_id,
    e.evento
   FROM creators_perfil t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_oportunidades'::text AS tabela,
    t.creator_id::text AS registro_id,
    e.evento
   FROM creators_oportunidades t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_enderecos'::text AS tabela,
    t.creator_id::text AS registro_id,
    e.evento
   FROM creators_enderecos t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_pagamentos'::text AS tabela,
    t.creator_id::text AS registro_id,
    e.evento
   FROM creators_pagamentos t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_vinculos'::text AS tabela,
    t.id::text AS registro_id,
    e.evento
   FROM creators_vinculos t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_contratos'::text AS tabela,
    t.id::text AS registro_id,
    e.evento
   FROM creators_contratos t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_gmv'::text AS tabela,
    t.id::text AS registro_id,
    e.evento
   FROM creators_gmv t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_circle'::text AS tabela,
    t.creator_id::text AS registro_id,
    e.evento
   FROM creators_circle t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento)
UNION ALL
 SELECT t.creator_id,
    'creators_conferencias'::text AS tabela,
    t.id::text AS registro_id,
    e.evento
   FROM creators_conferencias t
     CROSS JOIN LATERAL jsonb_array_elements(t.historico_jornada) e(evento);

REVOKE ALL ON public."creators_linha_tempo" FROM PUBLIC, anon, authenticated;

CREATE VIEW public."creators_visao_geral" WITH (security_invoker=true) AS
 SELECT c.id AS creator_id,
    c.nome,
    c.telefone,
    c.whatsapp,
    c.email,
    c.tiktok,
    c.criado_em,
    a.canal_entrada,
    a.origem_entrada,
    a.origem_detalhe,
    a.origem_fonte,
    a.primeira_mensagem_em,
    a.origem_informada_formulario,
    a.etapa_atual,
    a.situacao_atual,
    a.pendencia_atual,
    a.proxima_acao,
    a.formulario_situacao,
    a.formulario_recebido_em,
    v.id AS vinculo_id,
    v.inicio_em AS agenciamento_inicio_em,
    v.fim_em AS agenciamento_fim_em,
    v.confirmado_em AS vinculo_confirmado_em,
        CASE
            WHEN v.id IS NULL THEN 'sem_vinculo_confirmado'::text
            WHEN v.inicio_em > statement_timestamp() THEN 'inicio_futuro'::text
            WHEN v.fim_em IS NULL OR v.fim_em > statement_timestamp() THEN 'ativo'::text
            ELSE 'encerrado'::text
        END AS situacao_vinculo,
    ct.contrato_percentual,
    ct.contrato_prazo_meses,
    ct.contrato_vigencia_inicio,
    ct.contrato_renovacao_prevista_em,
    ct.numero_renovacao AS ultimo_ciclo_confirmado,
    ( SELECT count(*) AS count
           FROM creators_contratos rc
          WHERE rc.creator_id = c.id AND rc.vinculo_id = v.id AND rc.confirmado_em IS NOT NULL AND (rc.situacao = ANY (ARRAY['confirmado'::text, 'encerrado'::text])) AND rc.numero_renovacao > 0) AS renovacoes_confirmadas,
    gd.valor AS gmv_declarado_entrada,
    gd.moeda AS gmv_declarado_moeda,
    ge.valor AS gmv_verificado_entrada,
    ge.moeda AS gmv_verificado_moeda,
    gm.valor AS ultimo_gmv_mensal,
    gm.periodo_inicio AS ultimo_gmv_mes,
    gm.situacao AS ultimo_gmv_situacao,
    ci.circle_categoria_entrada,
    ci.circle_cargos_entrada,
    ci.circle_situacao,
    ci.circle_acesso_criado_em,
    ci.circle_cargos_atribuidos_em
   FROM creators c
     JOIN creators_aquisicao a ON a.creator_id = c.id
     JOIN creators_circle ci ON ci.creator_id = c.id
     LEFT JOIN LATERAL ( SELECT x.id,
            x.creator_id,
            x.inicio_em,
            x.fim_em,
            x.fonte,
            x.confirmado_em,
            x.motivo_saida,
            x.criado_em,
            x.atualizado_em,
            x.historico_jornada
           FROM creators_vinculos x
          WHERE x.creator_id = c.id
          ORDER BY (
                CASE
                    WHEN x.inicio_em <= statement_timestamp() AND (x.fim_em IS NULL OR x.fim_em > statement_timestamp()) THEN 0
                    WHEN x.inicio_em <= statement_timestamp() THEN 1
                    ELSE 2
                END), (
                CASE
                    WHEN x.inicio_em > statement_timestamp() THEN x.inicio_em
                    ELSE NULL::timestamp with time zone
                END), x.inicio_em DESC, x.id DESC
         LIMIT 1) v ON true
     LEFT JOIN LATERAL ( SELECT x.id,
            x.creator_id,
            x.vinculo_id,
            x.numero_renovacao,
            x.situacao,
            x.confirmado_em,
            x.contrato_percentual,
            x.contrato_prazo_meses,
            x.contrato_vigencia_inicio,
            x.contrato_vigencia_fim,
            x.contrato_renovacao_prevista_em,
            x.contrato_ultima_renovacao_em,
            x.criado_em,
            x.atualizado_em,
            x.historico_jornada
           FROM creators_contratos x
          WHERE x.creator_id = c.id AND x.vinculo_id = v.id AND x.confirmado_em IS NOT NULL AND (x.situacao = ANY (ARRAY['confirmado'::text, 'encerrado'::text]))
          ORDER BY x.numero_renovacao DESC
         LIMIT 1) ct ON true
     LEFT JOIN creators_gmv gd ON gd.creator_id = c.id AND gd.finalidade = 'entrada'::text AND gd.natureza = 'declarado'::text
     LEFT JOIN creators_gmv ge ON ge.creator_id = c.id AND ge.finalidade = 'entrada'::text AND ge.natureza = 'verificado'::text
     LEFT JOIN LATERAL ( SELECT x.id,
            x.creator_id,
            x.finalidade,
            x.natureza,
            x.periodicidade,
            x.periodo_inicio,
            x.periodo_fim,
            x.valor,
            x.moeda,
            x.situacao,
            x.fonte,
            x.observado_em,
            x.responsavel,
            x.comprovante_referencia,
            x.motivo_correcao,
            x.criado_em,
            x.atualizado_em,
            x.historico_jornada
           FROM creators_gmv x
          WHERE x.creator_id = c.id AND x.finalidade = 'acompanhamento'::text AND x.natureza = 'verificado'::text AND x.periodicidade = 'mes_calendario'::text AND x.moeda = 'BRL'::text
          ORDER BY x.periodo_inicio DESC
         LIMIT 1) gm ON true;

REVOKE ALL ON public."creators_visao_geral" FROM PUBLIC, anon, authenticated;

CREATE VIEW public."creators_marketing" WITH (security_invoker=true) AS
 SELECT creator_id,
    canal_entrada,
    origem_entrada,
    origem_detalhe,
    origem_fonte,
    origem_informada_formulario,
    primeira_mensagem_em,
    criado_em,
    etapa_atual,
    formulario_recebido_em,
    agenciamento_inicio_em,
    agenciamento_fim_em,
    situacao_vinculo
   FROM creators_visao_geral;

REVOKE ALL ON public."creators_marketing" FROM PUBLIC, anon, authenticated;

CREATE VIEW public."creators_retencao" WITH (security_invoker=true) AS
 SELECT creator_id,
    nome,
    telefone,
    whatsapp,
    tiktok,
    situacao_vinculo,
    agenciamento_inicio_em,
    agenciamento_fim_em,
    vinculo_confirmado_em,
    contrato_renovacao_prevista_em,
    contrato_percentual,
    contrato_prazo_meses,
    ultimo_ciclo_confirmado,
    renovacoes_confirmadas,
    gmv_declarado_entrada,
    gmv_verificado_entrada,
    ultimo_gmv_mensal,
    ultimo_gmv_mes,
    ultimo_gmv_situacao,
    circle_categoria_entrada,
    circle_situacao,
    pendencia_atual,
    proxima_acao
   FROM creators_visao_geral;

REVOKE ALL ON public."creators_retencao" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_aquisicao" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_circle" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_conferencias" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_contratos" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_enderecos" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_gmv" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_oportunidades" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_pagamentos" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_perfil" FROM PUBLIC, anon, authenticated;

REVOKE ALL ON public."creators_vinculos" FROM PUBLIC, anon, authenticated;

GRANT INSERT ON public."creators" TO "service_role";

GRANT SELECT ON public."creators" TO "service_role";

GRANT UPDATE ON public."creators" TO "service_role";

GRANT INSERT ON public."creators_aquisicao" TO "service_role";

GRANT SELECT ON public."creators_aquisicao" TO "service_role";

GRANT UPDATE ON public."creators_aquisicao" TO "service_role";

GRANT INSERT ON public."creators_circle" TO "service_role";

GRANT SELECT ON public."creators_circle" TO "service_role";

GRANT UPDATE ON public."creators_circle" TO "service_role";

GRANT SELECT ON public."creators_conferencia_mensal" TO "service_role";

GRANT INSERT ON public."creators_conferencias" TO "service_role";

GRANT SELECT ON public."creators_conferencias" TO "service_role";

GRANT UPDATE ON public."creators_conferencias" TO "service_role";

GRANT INSERT ON public."creators_contratos" TO "service_role";

GRANT SELECT ON public."creators_contratos" TO "service_role";

GRANT UPDATE ON public."creators_contratos" TO "service_role";

GRANT INSERT ON public."creators_enderecos" TO "service_role";

GRANT SELECT ON public."creators_enderecos" TO "service_role";

GRANT UPDATE ON public."creators_enderecos" TO "service_role";

GRANT SELECT ON public."creators_ficha_completa" TO "service_role";

GRANT INSERT ON public."creators_gmv" TO "service_role";

GRANT SELECT ON public."creators_gmv" TO "service_role";

GRANT UPDATE ON public."creators_gmv" TO "service_role";

GRANT SELECT ON public."creators_gmv_mensal" TO "service_role";

GRANT SELECT ON public."creators_linha_tempo" TO "service_role";

GRANT SELECT ON public."creators_marketing" TO "service_role";

GRANT INSERT ON public."creators_oportunidades" TO "service_role";

GRANT SELECT ON public."creators_oportunidades" TO "service_role";

GRANT UPDATE ON public."creators_oportunidades" TO "service_role";

GRANT INSERT ON public."creators_pagamentos" TO "service_role";

GRANT SELECT ON public."creators_pagamentos" TO "service_role";

GRANT UPDATE ON public."creators_pagamentos" TO "service_role";

GRANT INSERT ON public."creators_perfil" TO "service_role";

GRANT SELECT ON public."creators_perfil" TO "service_role";

GRANT UPDATE ON public."creators_perfil" TO "service_role";

GRANT SELECT ON public."creators_retencao" TO "service_role";

GRANT INSERT ON public."creators_vinculos" TO "service_role";

GRANT SELECT ON public."creators_vinculos" TO "service_role";

GRANT UPDATE ON public."creators_vinculos" TO "service_role";

GRANT SELECT ON public."creators_visao_geral" TO "service_role";

GRANT USAGE ON SEQUENCE "public"."creators_vinculos_id_seq" TO service_role;

SELECT pg_catalog.setval('"public"."creators_vinculos_id_seq"', 9, true);

GRANT USAGE ON SEQUENCE "public"."creators_contratos_id_seq" TO service_role;

SELECT pg_catalog.setval('"public"."creators_contratos_id_seq"', 5, true);

GRANT USAGE ON SEQUENCE "public"."creators_gmv_id_seq" TO service_role;

SELECT pg_catalog.setval('"public"."creators_gmv_id_seq"', 24, true);

GRANT USAGE ON SEQUENCE "public"."creators_conferencias_id_seq" TO service_role;

SELECT pg_catalog.setval('"public"."creators_conferencias_id_seq"', 2, true);

COMMENT ON COLUMN public."creators"."id" IS 'Identidade única e permanente da pessoa, criada no primeiro contato. Continua igual ao se tornar creator. Não é CPF, telefone, perfil social nem identidade de login.';

COMMENT ON COLUMN public."creators"."nome" IS 'Identificação / Nome conhecido da pessoa; pode ser completado pelo nome completo informado no formulário (campo nome). Vazio enquanto desconhecido.';

COMMENT ON COLUMN public."creators"."telefone" IS 'Identificação / Número que iniciou o contato, incluindo país e DDD quando conhecidos. É diferente do WhatsApp informado posteriormente no formulário; não é chave única da pessoa.';

COMMENT ON COLUMN public."creators"."email" IS 'Identificação / E-mail informado para o Club (campo email do formulário). Não cria acesso ao AmplifyOS nem confirma entrega de acesso ao Circle.';

COMMENT ON COLUMN public."creators"."tiktok" IS 'Identificação / Perfil TikTok informado na conversa ou no formulário (campo tiktok). Pode mudar; não substitui o ID da pessoa.';

COMMENT ON COLUMN public."creators"."whatsapp" IS 'Formulário / Contato / WhatsApp com DDD. Referência original: whatsapp. Opcional nesta ficha incremental. Número informado no formulário; pode diferir do telefone que iniciou a conversa.';

COMMENT ON COLUMN public."creators"."criado_em" IS 'Controle / Momento em que a ficha foi criada neste banco. Definido pelo banco e protegido contra alteração normal.';

COMMENT ON COLUMN public."creators"."atualizado_em" IS 'Controle / Última alteração efetiva da ficha, calculada automaticamente pelo banco.';

COMMENT ON COLUMN public."creators"."historico_jornada" IS 'Histórico / Lista automática de acontecimentos e mudanças. Preserva o antes e o depois de marcos, estados, decisões, GMV de entrada com períodos declarados e verificados, categoria e cargos de ingresso no Circle e condições comerciais. Não copia as colunas de nome, contato, CPF, PIX, respostas pessoais, referências externas ou observações livres. Permite correções sem apagar os fatos operacionais anteriores. Não é imutável contra administradores nem reconstitui valores pessoais anteriores.';

COMMENT ON COLUMN public."creators_aquisicao"."creator_id" IS 'Mesmo ID permanente de public.creators.id. Identifica e liga a ficha à pessoa; não gera nova identidade nem exige religações mensais.';

COMMENT ON COLUMN public."creators_aquisicao"."canal_entrada" IS 'Entrada / Meio da primeira conversa, por exemplo WhatsApp. Canal de contato é diferente da origem de aquisição.';

COMMENT ON COLUMN public."creators_aquisicao"."origem_entrada" IS 'Entrada / Origem identificada desde a primeira mensagem: anúncio, indicação, contato direto ou outra origem confirmada. Nulo significa ainda não identificada.';

COMMENT ON COLUMN public."creators_aquisicao"."origem_detalhe" IS 'Entrada / Detalhe conhecido da origem: campanha, anúncio ou referência da indicação. Não inventar uma origem quando ausente.';

COMMENT ON COLUMN public."creators_aquisicao"."origem_fonte" IS 'Entrada / De onde veio a informação de origem: metadado da mensagem, declaração da pessoa ou confirmação da equipe.';

COMMENT ON COLUMN public."creators_aquisicao"."primeira_mensagem_em" IS 'Entrada / Data e horário reais da primeira mensagem conhecida. Pode ser anterior à criação da ficha.';

COMMENT ON COLUMN public."creators_aquisicao"."etapa_atual" IS 'Jornada / Etapa atual: primeiro_contato, validacao, convite, agenciado, formulario, gmv_e_categoria, entrada_circle ou concluido. Não confirma automaticamente acontecimentos externos.';

COMMENT ON COLUMN public."creators_aquisicao"."situacao_atual" IS 'Jornada / Situação operacional: em_andamento, aguardando_lead, aguardando_equipe, pendente, pausado, recusado, desistente ou concluido.';

COMMENT ON COLUMN public."creators_aquisicao"."pendencia_atual" IS 'Jornada / O que falta resolver agora. Texto operacional da ficha; seu conteúdo não é copiado para o histórico automático.';

COMMENT ON COLUMN public."creators_aquisicao"."proxima_acao" IS 'Jornada / Próxima ação esperada para acompanhar a pessoa. Não executa automações.';

COMMENT ON COLUMN public."creators_aquisicao"."possui_agencia_atual" IS 'Validação / A pessoa informou vínculo atual com outra agência. Nulo significa que ainda não sabemos; falso não é o mesmo que desconhecido.';

COMMENT ON COLUMN public."creators_aquisicao"."deseja_sair_agencia" IS 'Validação / Intenção declarada de sair da agência atual. A intenção não confirma que a saída aconteceu.';

COMMENT ON COLUMN public."creators_aquisicao"."saida_agencia_confirmada_em" IS 'Validação / Quando foi confirmada a saída da agência anterior, se aplicável. Não preencher somente por intenção declarada.';

COMMENT ON COLUMN public."creators_aquisicao"."interesse_agenciamento" IS 'Validação / Interesse declarado em se agenciar com a Amplify. Nulo significa ainda não respondido.';

COMMENT ON COLUMN public."creators_aquisicao"."validacao_situacao" IS 'Validação / pendente, em_andamento, aprovado ou reprovado. Os critérios comerciais não são impostos por esta estrutura.';

COMMENT ON COLUMN public."creators_aquisicao"."validacao_confirmada_em" IS 'Validação / Quando a equipe ou a fonte responsável confirmou o resultado da validação.';

COMMENT ON COLUMN public."creators_aquisicao"."validacao_motivo" IS 'Validação / Motivo do resultado ou impedimento identificado. Não é copiado para o histórico automático.';

COMMENT ON COLUMN public."creators_aquisicao"."quer_convite" IS 'Convite / A pessoa quer receber o convite. Interesse não comprova criação, envio nem aceite.';

COMMENT ON COLUMN public."creators_aquisicao"."convite_referencia" IS 'Convite / Referência do convite no serviço de origem, quando existir. É referência externa ligada ao mesmo ID central, não uma nova identidade da pessoa.';

COMMENT ON COLUMN public."creators_aquisicao"."convite_criado_em" IS 'Convite / Quando o convite vigente foi criado. Ao substituir um convite, o histórico preserva os marcos e a situação anteriores, sem copiar a referência externa.';

COMMENT ON COLUMN public."creators_aquisicao"."convite_enviado_em" IS 'Convite / Quando o envio do convite vigente foi confirmado. Criar o convite não confirma seu envio.';

COMMENT ON COLUMN public."creators_aquisicao"."convite_situacao" IS 'Convite / nao_criado, criado, enviado, aceito, recusado, expirado ou cancelado. Registrar o que foi confirmado, sem presumir sucesso por tentativa de envio.';

COMMENT ON COLUMN public."creators_aquisicao"."convite_aceito_em" IS 'Convite / Quando o aceite do convite vigente foi confirmado pela fonte responsável.';

COMMENT ON COLUMN public."creators_aquisicao"."formulario_situacao" IS 'Formulário / nao_disponibilizado, disponibilizado, em_preenchimento ou recebido. Recebido significa respostas persistidas e recebimento confirmado.';

COMMENT ON COLUMN public."creators_aquisicao"."formulario_disponibilizado_em" IS 'Formulário / Quando o formulário foi disponibilizado à pessoa agenciada.';

COMMENT ON COLUMN public."creators_aquisicao"."formulario_iniciado_em" IS 'Formulário / Quando o preenchimento foi iniciado, se esse acontecimento for observado.';

COMMENT ON COLUMN public."creators_aquisicao"."formulario_recebido_em" IS 'Formulário / Quando as respostas foram recebidas e sua persistência confirmada. Tela exibida ou link enviado não são confirmação de recebimento.';

COMMENT ON COLUMN public."creators_aquisicao"."formulario_versao" IS 'Formulário / Versão que a pessoa respondeu. O catálogo de referência observado foi amplify-cadastro-v2; não é valor presumido para novos cadastros.';

COMMENT ON COLUMN public."creators_aquisicao"."formulario_submissao_referencia" IS 'Formulário / Protocolo ou referência externa de recebimento, quando disponível. Vinculado ao mesmo ID central.';

COMMENT ON COLUMN public."creators_aquisicao"."origem_informada_formulario" IS 'Formulário / Cadastro e jornada / Como você conheceu a Amplify?. Referência original: canal_origem. Opcional nesta ficha incremental. Resposta declarada no formulário, separada da origem identificada na primeira mensagem.';

COMMENT ON COLUMN public."creators_aquisicao"."origem_outro" IS 'Formulário / Cadastro e jornada / Como?. Referência original: origem_outro. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_aquisicao"."consentimento_aceito_em" IS 'Cadastro / Data de aceite efetivo do termo de tratamento de dados. Não preencher automaticamente com a criação da ficha.';

COMMENT ON COLUMN public."creators_aquisicao"."consentimento_versao" IS 'Cadastro / Versão do termo efetivamente aceito. Sem valor padrão presumido.';

COMMENT ON COLUMN public."creators_aquisicao"."email_confirmado_em" IS 'Quando a confirmação do e-mail informado foi efetivamente observada pelo processo de cadastro. Nulo significa não confirmada. Não cria login nem acesso; não preencher só por receber um endereço de e-mail.';

COMMENT ON COLUMN public."creators_aquisicao"."criado_em" IS 'Quando esta ficha de assunto foi criada. Não substitui a criação da pessoa nem a data de um acontecimento de negócio.';

COMMENT ON COLUMN public."creators_aquisicao"."atualizado_em" IS 'Última alteração da ficha controlada pelo trigger interno do pacote principal. Não equivale à conferência dos dados pela fonte.';

COMMENT ON COLUMN public."creators_aquisicao"."historico_jornada" IS 'Histórico interno resumido de criação e alterações da ficha, controlado pelo trigger do pacote principal. Não aceitar histórico arbitrário do cliente nem copiar dados pessoais, credenciais, arquivos ou respostas brutas.';

COMMENT ON COLUMN public."creators_circle"."creator_id" IS 'ID permanente da pessoa; uma ficha de ingresso no Circle por pessoa.';

COMMENT ON COLUMN public."creators_circle"."circle_categoria_entrada" IS 'Categoria efetivamente definida no ingresso. Evolução de GMV posterior não deve substituir silenciosamente esta referência inicial.';

COMMENT ON COLUMN public."creators_circle"."circle_cargos_entrada" IS 'Cargos efetivamente atribuídos no primeiro ingresso, após confirmação pelo processo responsável. Cargos apenas esperados ficam em creators_conferencias.cargos_esperados; não presumir atribuição pela criação da ficha.';

COMMENT ON COLUMN public."creators_circle"."circle_situacao" IS 'Situação de ingresso ou acesso observada no processo responsável; não pressupõe criação pela simples gravação da ficha.';

COMMENT ON COLUMN public."creators_circle"."circle_acesso_criado_em" IS 'Momento em que a criação do acesso foi confirmada na fonte responsável; link enviado não comprova este marco.';

COMMENT ON COLUMN public."creators_circle"."circle_cargos_atribuidos_em" IS 'Momento em que a atribuição dos cargos de ingresso foi confirmada no Circle.';

COMMENT ON COLUMN public."creators_circle"."acesso_referencia" IS 'Referência estável do membro ou acesso no Circle; não é senha, token, cookie ou autorização para entrar.';

COMMENT ON COLUMN public."creators_circle"."gmv_entrada_id" IS 'Medição de entrada da mesma pessoa usada na classificação, quando aplicável; não aponta para uma medição posterior de acompanhamento.';

COMMENT ON COLUMN public."creators_circle"."criado_em" IS 'Momento da criação do registro neste banco, controlado pelo banco.';

COMMENT ON COLUMN public."creators_circle"."atualizado_em" IS 'Momento da última mudança efetiva, controlado pelo banco.';

COMMENT ON COLUMN public."creators_circle"."historico_jornada" IS 'Lista automática das categorias, cargos e marcos do ingresso, preservando correções sem copiar referências externas.';

COMMENT ON COLUMN public."creators_conferencias"."id" IS 'Identificador da conferência mensal por assunto.';

COMMENT ON COLUMN public."creators_conferencias"."creator_id" IS 'ID permanente da pessoa acompanhada; a mesma identidade usada em todos os setores.';

COMMENT ON COLUMN public."creators_conferencias"."competencia" IS 'Mês da conferência, representado pelo primeiro dia do mês. Não substitui o período próprio de uma medição de GMV.';

COMMENT ON COLUMN public."creators_conferencias"."assunto" IS 'Assunto conferido: vínculo de agenciamento, GMV ou acesso.';

COMMENT ON COLUMN public."creators_conferencias"."situacao" IS 'Pendente aguarda conferência; conferido, divergente e indisponível registram um resultado com fonte e data. Indisponível não significa GMV zero, ausência de vínculo ou acesso removido.';

COMMENT ON COLUMN public."creators_conferencias"."verificado_em" IS 'Momento em que a fonte foi conferida e o resultado foi conhecido; obrigatório para resultados concluídos.';

COMMENT ON COLUMN public."creators_conferencias"."fonte" IS 'Fonte efetivamente consultada para esta conferência; obrigatória para resultados concluídos.';

COMMENT ON COLUMN public."creators_conferencias"."responsavel" IS 'Referência interna do responsável pela conferência ou pendência; opcional e sem efeito de autorização.';

COMMENT ON COLUMN public."creators_conferencias"."referencia" IS 'Referência externa da conferência, lote ou evidência; sem segredo, dados brutos ou URL assinada.';

COMMENT ON COLUMN public."creators_conferencias"."acesso_esperado" IS 'Se a pessoa deveria ter acesso segundo a regra vigente, quando conhecido. Nulo significa expectativa ainda não definida.';

COMMENT ON COLUMN public."creators_conferencias"."acesso_encontrado" IS 'Se o acesso foi encontrado na fonte consultada. Nulo significa que a existência não foi estabelecida.';

COMMENT ON COLUMN public."creators_conferencias"."cargos_esperados" IS 'Cargos esperados na conferência do mês, quando conhecidos. Não altera os cargos registrados no ingresso.';

COMMENT ON COLUMN public."creators_conferencias"."cargos_encontrados" IS 'Cargos efetivamente encontrados na fonte consultada. Lista vazia difere de informação desconhecida.';

COMMENT ON COLUMN public."creators_conferencias"."observacao" IS 'Descrição livre da pendência ou resultado; não é copiada para o histórico automático.';

COMMENT ON COLUMN public."creators_conferencias"."criado_em" IS 'Momento da criação do registro neste banco, controlado pelo banco.';

COMMENT ON COLUMN public."creators_conferencias"."atualizado_em" IS 'Momento da última mudança efetiva, controlado pelo banco.';

COMMENT ON COLUMN public."creators_conferencias"."historico_jornada" IS 'Lista automática dos resultados e mudanças efetivas da conferência; sem copiar observações, responsáveis ou referências externas.';

COMMENT ON COLUMN public."creators_contratos"."id" IS 'Identificador deste ciclo contratual.';

COMMENT ON COLUMN public."creators_contratos"."creator_id" IS 'Mesma pessoa do vínculo informado; chave composta impede vincular contrato ao vínculo de outra pessoa.';

COMMENT ON COLUMN public."creators_contratos"."vinculo_id" IS 'Período confirmado de agenciamento ao qual o contrato pertence.';

COMMENT ON COLUMN public."creators_contratos"."numero_renovacao" IS 'Zero para contrato inicial; um, dois e seguintes identificam as renovações deste vínculo. Não dispara acompanhamento ou automação.';

COMMENT ON COLUMN public."creators_contratos"."situacao" IS 'Estado registrado do ciclo: previsto, confirmado, encerrado ou cancelado. A previsão de uma data não muda este estado automaticamente.';

COMMENT ON COLUMN public."creators_contratos"."confirmado_em" IS 'Momento conhecido da confirmação deste ciclo; obrigatório para situação confirmado. Não preencher pela simples criação da linha.';

COMMENT ON COLUMN public."creators_contratos"."contrato_percentual" IS 'Percentual efetivamente combinado para este ciclo; opcional, entre zero e cem. Nenhum percentual comercial é presumido.';

COMMENT ON COLUMN public."creators_contratos"."contrato_prazo_meses" IS 'Prazo em meses efetivamente combinado, se houver. Não assume duração padrão nem calcula renovação automaticamente.';

COMMENT ON COLUMN public."creators_contratos"."contrato_vigencia_inicio" IS 'Primeiro dia de vigência conhecido deste ciclo.';

COMMENT ON COLUMN public."creators_contratos"."contrato_vigencia_fim" IS 'Último dia de vigência conhecido deste ciclo, inclusivo; pode coincidir com o início em um ciclo de um dia.';

COMMENT ON COLUMN public."creators_contratos"."contrato_renovacao_prevista_em" IS 'Data prevista para a próxima renovação conforme condições conhecidas; não comprova que ela ocorreu.';

COMMENT ON COLUMN public."creators_contratos"."contrato_ultima_renovacao_em" IS 'Marco efetivamente confirmado de renovação associado a este ciclo, quando conhecido; preservado para rastrear o campo original.';

COMMENT ON COLUMN public."creators_contratos"."criado_em" IS 'Momento da criação do registro neste banco, controlado pelo banco.';

COMMENT ON COLUMN public."creators_contratos"."atualizado_em" IS 'Momento da última mudança efetiva, controlado pelo banco.';

COMMENT ON COLUMN public."creators_contratos"."historico_jornada" IS 'Lista automática dos marcos e correções contratuais; preserva condições anteriores sem copiar textos livres ou referências externas.';

COMMENT ON COLUMN public."creators_enderecos"."creator_id" IS 'Mesmo ID permanente de public.creators.id. Identifica e liga a ficha à pessoa; não gera nova identidade nem exige religações mensais.';

COMMENT ON COLUMN public."creators_enderecos"."endereco_estado" IS 'Formulário / Endereço / Em qual estado você mora?. Referência original: estado. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_enderecos"."endereco_cidade" IS 'Formulário / Endereço / Cidade. Referência original: cidade. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_enderecos"."endereco_logradouro" IS 'Formulário / Endereço / Endereço para receber as amostras/produtos. Referência original: logradouro. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_enderecos"."endereco_bairro" IS 'Formulário / Endereço / Bairro. Referência original: bairro. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_enderecos"."endereco_numero" IS 'Formulário / Endereço / Número. Referência original: numero. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_enderecos"."endereco_complemento" IS 'Formulário / Endereço / Complemento do endereço (ou “Sem complemento”). Referência original: complemento. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_enderecos"."endereco_cep" IS 'Formulário / Endereço / CEP para receber amostras/produtos. Referência original: cep. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_enderecos"."criado_em" IS 'Quando esta ficha de assunto foi criada. Não substitui a criação da pessoa nem a data de um acontecimento de negócio.';

COMMENT ON COLUMN public."creators_enderecos"."atualizado_em" IS 'Última alteração da ficha controlada pelo trigger interno do pacote principal. Não equivale à conferência dos dados pela fonte.';

COMMENT ON COLUMN public."creators_enderecos"."historico_jornada" IS 'Histórico interno resumido de criação e alterações da ficha, controlado pelo trigger do pacote principal. Não aceitar histórico arbitrário do cliente nem copiar dados pessoais, credenciais, arquivos ou respostas brutas.';

COMMENT ON COLUMN public."creators_gmv"."id" IS 'Identificador da medição; permanece o mesmo quando um valor do próprio período é corrigido.';

COMMENT ON COLUMN public."creators_gmv"."creator_id" IS 'ID permanente da pessoa, preenchido pelo processo de gravação ao registrar a medição; não exige vinculação manual mensal.';

COMMENT ON COLUMN public."creators_gmv"."finalidade" IS 'Entrada preserva a referência inicial; acompanhamento registra evolução posterior. Uma linha de cada natureza pode representar a entrada.';

COMMENT ON COLUMN public."creators_gmv"."natureza" IS 'Declarado é informado pela pessoa; verificado é conferido em fonte responsável. Natureza não equivale à situação de preenchimento.';

COMMENT ON COLUMN public."creators_gmv"."periodicidade" IS 'Mês calendário, janela de 28 dias, período personalizado ou período ainda não informado na entrada. Janelas e meses não são tratados como equivalentes.';

COMMENT ON COLUMN public."creators_gmv"."periodo_inicio" IS 'Primeiro dia incluído na medição. Obrigatório no acompanhamento; pode faltar apenas na entrada com periodicidade não informada.';

COMMENT ON COLUMN public."creators_gmv"."periodo_fim" IS 'Último dia incluído na medição. Mês calendário vai do primeiro ao último dia do mês; janela de 28 dias termina 27 dias após o início.';

COMMENT ON COLUMN public."creators_gmv"."valor" IS 'GMV exato na moeda indicada, com duas casas decimais. Nulo significa valor não registrado; zero é permitido quando efetivamente informado ou conferido.';

COMMENT ON COLUMN public."creators_gmv"."moeda" IS 'Código da moeda em três letras maiúsculas. BRL é a moeda operacional padrão; comparar somente medições da mesma moeda.';

COMMENT ON COLUMN public."creators_gmv"."situacao" IS 'Pendente ou indisponível exige valor nulo; parcial permite informação incompleta; registrado exige valor, fonte e data de observação. Não indica sozinho que a natureza é verificada.';

COMMENT ON COLUMN public."creators_gmv"."fonte" IS 'Origem efetiva da informação, como declaração, relatório ou conferência identificada; obrigatória para uma medição registrada.';

COMMENT ON COLUMN public."creators_gmv"."observado_em" IS 'Momento em que a informação foi observada na fonte, separado do período medido e do momento de gravação.';

COMMENT ON COLUMN public."creators_gmv"."responsavel" IS 'Referência interna do responsável pela atualização ou conferência; opcional. Não concede permissões de acesso.';

COMMENT ON COLUMN public."creators_gmv"."comprovante_referencia" IS 'Referência estável a comprovante privado, quando houver. Não guardar arquivo binário, segredo ou URL assinada nesta coluna.';

COMMENT ON COLUMN public."creators_gmv"."motivo_correcao" IS 'Explicação operacional da última correção, quando aplicável. Texto livre não é copiado para o histórico automático.';

COMMENT ON COLUMN public."creators_gmv"."criado_em" IS 'Momento da criação do registro neste banco, controlado pelo banco.';

COMMENT ON COLUMN public."creators_gmv"."atualizado_em" IS 'Momento da última mudança efetiva, controlado pelo banco.';

COMMENT ON COLUMN public."creators_gmv"."historico_jornada" IS 'Lista automática dos estados, períodos, valores e correções da medição; preserva antes e depois, sem duplicar comprovantes nem textos livres.';

COMMENT ON COLUMN public."creators_oportunidades"."creator_id" IS 'Mesmo ID permanente de public.creators.id. Identifica e liga a ficha à pessoa; não gera nova identidade nem exige religações mensais.';

COMMENT ON COLUMN public."creators_oportunidades"."cor_raca" IS 'Formulário / Perfil / Como você se autodeclara em relação à sua cor/raça?. Referência original: cor_raca. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_oportunidades"."tem_filhos" IS 'Formulário / Oportunidades / Tem filhos?. Referência original: tem_filhos. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."alimentacao" IS 'Formulário / Oportunidades / Qual o seu tipo de dieta/alimentação?. Referência original: alimentacao. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_oportunidades"."restricao_alimentar" IS 'Formulário / Oportunidades / Qual restrição alimentar. Referência original: restricao_alimentar. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_oportunidades"."casa_praia_campo" IS 'Formulário / Oportunidades / Tem casa de praia/campo?. Referência original: casa_praia_campo. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."carro" IS 'Formulário / Oportunidades / Tem carro?. Referência original: carro. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."moto" IS 'Formulário / Oportunidades / Tem moto?. Referência original: moto. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."celular" IS 'Formulário / Oportunidades / Tipo de celular. Referência original: celular. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_oportunidades"."computador" IS 'Formulário / Oportunidades / Tem computador?. Referência original: computador. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."tripe" IS 'Formulário / Oportunidades / Tem tripé. Referência original: tripe. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."microfone" IS 'Formulário / Oportunidades / Tem microfone de lapela?. Referência original: microfone. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."academia" IS 'Formulário / Oportunidades / Tem acesso a academia?. Referência original: academia. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."tem_pet" IS 'Formulário / Oportunidades / Tem pet de estimação?. Referência original: tem_pet. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."pets" IS 'Formulário / Oportunidades / Pets (quais). Referência original: pets. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_oportunidades"."outro_idioma" IS 'Formulário / Oportunidades / Você fala outro idioma?. Referência original: outro_idioma. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_oportunidades"."video_idioma" IS 'Formulário / Oportunidades / Link vídeo falando outro idioma. Referência original: video_idioma. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_oportunidades"."idiomas" IS 'Formulário / Oportunidades / Idiomas. Referência original: idiomas. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_oportunidades"."idiomas_outros" IS 'Formulário / Oportunidades / Quais outros idiomas?. Referência original: idiomas_outros. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_oportunidades"."criado_em" IS 'Quando esta ficha de assunto foi criada. Não substitui a criação da pessoa nem a data de um acontecimento de negócio.';

COMMENT ON COLUMN public."creators_oportunidades"."atualizado_em" IS 'Última alteração da ficha controlada pelo trigger interno do pacote principal. Não equivale à conferência dos dados pela fonte.';

COMMENT ON COLUMN public."creators_oportunidades"."historico_jornada" IS 'Histórico interno resumido de criação e alterações da ficha, controlado pelo trigger do pacote principal. Não aceitar histórico arbitrário do cliente nem copiar dados pessoais, credenciais, arquivos ou respostas brutas.';

COMMENT ON COLUMN public."creators_pagamentos"."creator_id" IS 'Mesmo ID permanente de public.creators.id. Identifica e liga a ficha à pessoa; não gera nova identidade nem exige religações mensais.';

COMMENT ON COLUMN public."creators_pagamentos"."cpf" IS 'Formulário / Pagamentos / CPF. Referência original: cpf. Opcional nesta ficha incremental. Identificador textual; não usar como número, senha, chave de login ou prova automática de titularidade.';

COMMENT ON COLUMN public."creators_pagamentos"."cpf_validado" IS 'Formulário / Resultado da validação do CPF pelo processo responsável. Nulo significa não validado; este SQL não realiza consulta nem validação de CPF.';

COMMENT ON COLUMN public."creators_pagamentos"."pix_chave" IS 'Formulário / Pagamentos / Chave PIX. Referência original: pix. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_pagamentos"."possui_cnpj" IS 'Formulário / Pagamentos / Você possui CNPJ?. Referência original: possui_cnpj. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_pagamentos"."cnpj" IS 'Formulário / Pagamentos / CNPJ. Referência original: cnpj. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável. Identificador textual; não usar como número, senha, chave de login ou prova automática de titularidade.';

COMMENT ON COLUMN public."creators_pagamentos"."criado_em" IS 'Quando esta ficha de assunto foi criada. Não substitui a criação da pessoa nem a data de um acontecimento de negócio.';

COMMENT ON COLUMN public."creators_pagamentos"."atualizado_em" IS 'Última alteração da ficha controlada pelo trigger interno do pacote principal. Não equivale à conferência dos dados pela fonte.';

COMMENT ON COLUMN public."creators_pagamentos"."historico_jornada" IS 'Histórico interno resumido de criação e alterações da ficha, controlado pelo trigger do pacote principal. Não aceitar histórico arbitrário do cliente nem copiar dados pessoais, credenciais, arquivos ou respostas brutas.';

COMMENT ON COLUMN public."creators_perfil"."creator_id" IS 'Mesmo ID permanente de public.creators.id. Identifica e liga a ficha à pessoa; não gera nova identidade nem exige religações mensais.';

COMMENT ON COLUMN public."creators_perfil"."foto_perfil_referencia" IS 'Formulário / Perfil / Sua foto de perfil. Referência original: foto_perfil. Opcional nesta ficha incremental. Guardar apenas referência ao arquivo privado; não binário, URL assinada, token ou conteúdo do arquivo.';

COMMENT ON COLUMN public."creators_perfil"."mini_bio" IS 'Formulário / Perfil / Apresente você e seu conteúdo. Referência original: mini_bio. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."data_nascimento" IS 'Formulário / Perfil / Data de nascimento. Referência original: nascimento. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."genero" IS 'Formulário / Perfil / Com qual gênero você se identifica?. Referência original: genero. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."estado_civil" IS 'Formulário / Perfil / Estado civil. Referência original: estado_civil. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."camiseta" IS 'Formulário / Perfil / Qual tamanho de camiseta você usa?. Referência original: camiseta. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."camiseta_outro" IS 'Formulário / Perfil / Informe o tamanho da camiseta. Referência original: camiseta_outro. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_perfil"."nichos" IS 'Formulário / Perfil / Quais são seus nichos de conteúdo?. Referência original: nichos. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."nichos_outros" IS 'Formulário / Perfil / Quais outros nichos?. Referência original: nichos_outros. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_perfil"."cabelo" IS 'Formulário / Perfil / Qual o tipo do seu cabelo?. Referência original: cabelo. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."calcado" IS 'Formulário / Perfil / Qual seu número de calçado?. Referência original: calcado. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."expectativas" IS 'Formulário / Cadastro e jornada / Que tipo de apoio você espera da Amplify?. Referência original: expectativas. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."meta_renda_mensal" IS 'Formulário / Cadastro e jornada / Qual é sua meta de renda mensal com conteúdo? (R$). Referência original: meta_renda_mensal. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."contexto_adicional" IS 'Formulário / Cadastro e jornada / Há algo mais que o time precisa saber sobre você?. Referência original: contexto_adicional. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."plataformas" IS 'Formulário / Cadastro e jornada / Plataformas de atuação. Referência original: plataformas. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."instagram" IS 'Formulário / Cadastro e jornada / Qual seu @ do Instagram?. Referência original: instagram. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_perfil"."plataformas_outros" IS 'Formulário / Cadastro e jornada / Quais outras plataformas?. Referência original: plataformas_outros. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_perfil"."experiencia_live_shop" IS 'Formulário / Cadastro e jornada / Você tem experiência com Live Shop?. Referência original: experiencia_live_shop. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."teve_agencia_anterior" IS 'Formulário / Cadastro e jornada / Já fez parte de outra agência?. Referência original: agencia_anterior. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_perfil"."nome_agencia_anterior" IS 'Formulário / Cadastro e jornada / Agência anterior. Referência original: nome_agencia_anterior. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_perfil"."experiencia_agencia" IS 'Formulário / Cadastro e jornada / Qual sua experiência e opinião com a última agência. Referência original: experiencia_agencia. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_perfil"."produtos_excluidos" IS 'Formulário / Cadastro e jornada / Tipos de produto que NÃO trabalha. Referência original: produtos_excluidos. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."inicio_amplify_informado" IS 'Formulário / Cadastro e jornada / Quando você começou na Amplify?. Referência original: inicio_amplify_informado. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."rotina" IS 'Formulário / Cadastro e jornada / Qual sua rotina?. Referência original: rotina. Opcional nesta ficha incremental.';

COMMENT ON COLUMN public."creators_perfil"."rotina_outro" IS 'Formulário / Cadastro e jornada / Como é sua rotina?. Referência original: rotina_outro. Opcional nesta ficha incremental. Pergunta condicional no catálogo de referência; não exigir antes de a condição ser aplicável.';

COMMENT ON COLUMN public."creators_perfil"."declarou_mais_2000_seguidores" IS 'Formulário / Cadastro e jornada / Você tem +2.000 seguidores no TikTok?. Referência original: mais_2000_seguidores. Opcional nesta ficha incremental. Verdadeiro corresponde a Sim, falso a Não e nulo a ainda não informado.';

COMMENT ON COLUMN public."creators_perfil"."criado_em" IS 'Quando esta ficha de assunto foi criada. Não substitui a criação da pessoa nem a data de um acontecimento de negócio.';

COMMENT ON COLUMN public."creators_perfil"."atualizado_em" IS 'Última alteração da ficha controlada pelo trigger interno do pacote principal. Não equivale à conferência dos dados pela fonte.';

COMMENT ON COLUMN public."creators_perfil"."historico_jornada" IS 'Histórico interno resumido de criação e alterações da ficha, controlado pelo trigger do pacote principal. Não aceitar histórico arbitrário do cliente nem copiar dados pessoais, credenciais, arquivos ou respostas brutas.';

COMMENT ON COLUMN public."creators_vinculos"."id" IS 'Identificador do período de vínculo; não substitui a identidade permanente da pessoa.';

COMMENT ON COLUMN public."creators_vinculos"."creator_id" IS 'ID permanente da pessoa na base mãe; vínculo obrigatório e protegido contra exclusão em cascata.';

COMMENT ON COLUMN public."creators_vinculos"."inicio_em" IS 'Início efetivo e confirmado deste período de agenciamento; distinto da criação da ficha e da data em que a informação foi conferida.';

COMMENT ON COLUMN public."creators_vinculos"."fim_em" IS 'Encerramento efetivo deste período, quando confirmado. Nulo indica período aberto; não preencher com a data de uma importação ou pela ausência em lista parcial.';

COMMENT ON COLUMN public."creators_vinculos"."fonte" IS 'Origem responsável pela confirmação do vínculo; rótulo ou referência operacional, sem segredo ou documento embutido.';

COMMENT ON COLUMN public."creators_vinculos"."confirmado_em" IS 'Momento em que o estado do vínculo foi confirmado pela fonte responsável; não usar automaticamente a data de criação do registro.';

COMMENT ON COLUMN public."creators_vinculos"."motivo_saida" IS 'Motivo conhecido do encerramento; opcional e não copiado para o histórico automático.';

COMMENT ON COLUMN public."creators_vinculos"."criado_em" IS 'Momento da criação do registro neste banco, controlado pelo banco.';

COMMENT ON COLUMN public."creators_vinculos"."atualizado_em" IS 'Momento da última mudança efetiva, controlado pelo banco.';

COMMENT ON COLUMN public."creators_vinculos"."historico_jornada" IS 'Lista automática dos marcos e correções operacionais; não substituir pelo cliente. Não inclui textos livres nem referências externas.';
