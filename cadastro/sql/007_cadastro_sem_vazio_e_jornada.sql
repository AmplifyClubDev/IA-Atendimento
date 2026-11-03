-- Cadastro público v5, 007: cadastro sem vazio + jornada com histórico (MODELO-CADASTRO-PLANILHA.md).
--  * interno.jornada: um marco por linha (contato, validação, convite, cadastro, acesso, categoria,
--    agenciamento, renovação), só acrescenta. Gravada por gatilho nas fichas e nos vínculos; nada
--    no código da Bia ou do Cadastro muda. Os marcos que já existem são copiados das datas guardadas.
--  * interno.creators.observacoes: campo do time (vazio vira "Sem observações" na planilha).
--  * creators_cadastro_completo: cadastro confirmado precisa de todas as respostas obrigatórias e
--    das condicionais que se aplicam (o formulário já exige; a trava fica no banco).
--  * interno.cadastro_planilha: as 71 colunas da planilha "Principal", na ordem, só em texto,
--    + 4 colunas de origem e situação. Nenhuma célula vazia: a migration falha se aparecer uma.
-- Não apaga nem altera dados existentes.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';
DO $guard$
BEGIN
 IF to_regclass('interno.creators') IS NULL OR to_regclass('interno.agenciamentos') IS NULL
   OR to_regclass('interno.gmv') IS NULL
   OR to_regclass('interno.jornada') IS NOT NULL OR to_regclass('interno.cadastro_planilha') IS NOT NULL
   OR EXISTS(SELECT 1 FROM information_schema.columns
     WHERE table_schema='interno' AND table_name='creators' AND column_name='observacoes')
   THEN RAISE EXCEPTION 'cadastro_publico_007_estado_inesperado'; END IF;
END;
$guard$;

-- 1. Observações do time ------------------------------------------------------------------------
ALTER TABLE interno.creators ADD COLUMN observacoes text NOT NULL DEFAULT ''
 CONSTRAINT creators_observacoes_tamanho CHECK (length(observacoes)<=4000);
COMMENT ON COLUMN interno.creators.observacoes IS 'Anotações do time sobre a pessoa. Vazio aparece como "Sem observações".';

-- 2. Cadastro confirmado completo ---------------------------------------------------------------
ALTER TABLE interno.creators ADD CONSTRAINT creators_cadastro_completo CHECK (cadastro_situacao<>'confirmado' OR (
 num_nulls(nome,email,whatsapp,tiktok,foto_perfil_referencia,mini_bio,origem_informada_formulario,expectativas,
   meta_renda_mensal,contexto_adicional,plataformas,experiencia_live_shop,teve_agencia_anterior,produtos_excluidos,
   inicio_amplify_informado,cpf,data_nascimento,genero,estado_civil,camiseta,endereco_estado,endereco_cidade,
   endereco_logradouro,endereco_bairro,endereco_numero,endereco_complemento,endereco_cep,pix_chave,possui_cnpj,
   nichos,rotina,tem_filhos,cabelo,calcado,cor_raca,alimentacao,casa_praia_campo,carro,moto,celular,computador,
   tripe,microfone,academia,tem_pet,outro_idioma,declarou_mais_2000_seguidores)=0
 AND cardinality(plataformas)>0 AND cardinality(nichos)>0
 AND (possui_cnpj=(cnpj IS NOT NULL))
 AND (teve_agencia_anterior OR (nome_agencia_anterior IS NULL AND experiencia_agencia IS NULL))
 AND (NOT teve_agencia_anterior OR num_nulls(nome_agencia_anterior,experiencia_agencia)=0)
 AND (tem_pet=(pets IS NOT NULL))
 AND (outro_idioma OR num_nonnulls(video_idioma,idiomas,idiomas_outros)=0)
 AND (NOT outro_idioma OR num_nulls(video_idioma,idiomas)=0)
)) NOT VALID;
ALTER TABLE interno.creators VALIDATE CONSTRAINT creators_cadastro_completo;

-- 3. Jornada --------------------------------------------------------------------------------------
CREATE TABLE interno.jornada(
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 creator_id uuid NOT NULL REFERENCES interno.creators(id) ON DELETE CASCADE,
 marco text NOT NULL CHECK (marco IN ('primeiro_contato','validacao_elegivel','validacao_inelegivel','convite_enviado',
   'convite_aceito','cadastro_recebido','acesso_liberado','categoria_definida','agenciamento_iniciado',
   'agenciamento_encerrado','contrato_renovado')),
 ocorrido_em timestamptz NOT NULL CHECK (isfinite(ocorrido_em)),
 fonte text NOT NULL CHECK (btrim(fonte)<>''),
 referencia text NOT NULL CHECK (btrim(referencia)<>''),
 detalhe text NOT NULL DEFAULT '',
 registrado_em timestamptz NOT NULL DEFAULT statement_timestamp(),
 UNIQUE (creator_id,marco,referencia)
);
CREATE INDEX jornada_creator_ocorrido ON interno.jornada(creator_id,ocorrido_em);
COMMENT ON TABLE interno.jornada IS 'Marcos da jornada de cada pessoa, um por linha, nunca alterados. Gravados por gatilho a partir das fichas e dos vínculos.';
ALTER TABLE interno.jornada ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_only ON interno.jornada TO service_role USING (true);
REVOKE ALL ON interno.jornada FROM PUBLIC, anon, authenticated;
GRANT SELECT ON interno.jornada TO service_role;

-- Só acrescenta. A exclusão só passa na remoção autorizada de uma pessoa (mesma marca dos eventos).
CREATE FUNCTION interno.jornada_proteger() RETURNS trigger LANGUAGE plpgsql SET search_path='' AS $proteger$
BEGIN
 IF TG_OP='DELETE' AND current_setting('app.v5_purge_creator',true)=OLD.creator_id::text THEN RETURN OLD; END IF;
 RAISE EXCEPTION 'jornada_so_acrescenta' USING ERRCODE='23514';
END;
$proteger$;
CREATE TRIGGER v5_10_so_acrescenta BEFORE UPDATE OR DELETE ON interno.jornada
 FOR EACH ROW EXECUTE FUNCTION interno.jornada_proteger();

CREATE FUNCTION interno.jornada_marcar(p_creator uuid, p_marco text, p_em timestamptz, p_fonte text,
 p_referencia text, p_detalhe text DEFAULT '') RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path='' AS $marcar$
 INSERT INTO interno.jornada(creator_id,marco,ocorrido_em,fonte,referencia,detalhe)
 SELECT p_creator,p_marco,p_em,p_fonte,p_referencia,coalesce(p_detalhe,'')
 WHERE p_creator IS NOT NULL AND p_em IS NOT NULL AND isfinite(p_em)
 ON CONFLICT (creator_id,marco,referencia) DO NOTHING;
$marcar$;
REVOKE ALL ON FUNCTION interno.jornada_marcar(uuid,text,timestamptz,text,text,text) FROM PUBLIC, anon, authenticated, service_role;

-- Uma falha aqui vira aviso no log: o histórico nunca bloqueia a gravação da ficha ou do vínculo.
CREATE FUNCTION interno.jornada_da_ficha() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $ficha$
DECLARE o interno.creators;
BEGIN
 IF TG_OP='UPDATE' THEN o:=OLD; END IF;
 BEGIN
  IF TG_OP='INSERT' THEN
   PERFORM interno.jornada_marcar(NEW.id,'primeiro_contato',
     least(NEW.primeira_mensagem_em,NEW.formulario_recebido_em,NEW.criado_em),NEW.canal_entrada,'ficha');
  END IF;
  IF NEW.validacao_confirmada_em IS DISTINCT FROM o.validacao_confirmada_em
    AND NEW.validacao_situacao IN ('elegivel','inelegivel') THEN
   PERFORM interno.jornada_marcar(NEW.id,'validacao_'||NEW.validacao_situacao,NEW.validacao_confirmada_em,
     'pre_validacao',NEW.validacao_confirmada_em::text,coalesce(NEW.validacao_motivo,''));
  END IF;
  IF NEW.convite_enviado_em IS DISTINCT FROM o.convite_enviado_em THEN
   PERFORM interno.jornada_marcar(NEW.id,'convite_enviado',NEW.convite_enviado_em,'convites',
     coalesce(NEW.convite_referencia,NEW.convite_enviado_em::text));
  END IF;
  IF NEW.convite_aceito_em IS DISTINCT FROM o.convite_aceito_em THEN
   PERFORM interno.jornada_marcar(NEW.id,'convite_aceito',NEW.convite_aceito_em,'agenciamento',
     coalesce(NEW.convite_referencia,NEW.convite_aceito_em::text));
  END IF;
  IF NEW.formulario_recebido_em IS DISTINCT FROM o.formulario_recebido_em THEN
   PERFORM interno.jornada_marcar(NEW.id,'cadastro_recebido',NEW.formulario_recebido_em,'formulario',
     coalesce(NEW.formulario_submissao_referencia,NEW.formulario_recebido_em::text),coalesce(NEW.formulario_versao,''));
  END IF;
  IF NEW.circle_acesso_criado_em IS DISTINCT FROM o.circle_acesso_criado_em THEN
   PERFORM interno.jornada_marcar(NEW.id,'acesso_liberado',NEW.circle_acesso_criado_em,'circle',
     coalesce(NEW.acesso_referencia,NEW.circle_acesso_criado_em::text));
  END IF;
  IF NEW.circle_categoria_entrada IS DISTINCT FROM o.circle_categoria_entrada AND NEW.circle_categoria_entrada IS NOT NULL THEN
   PERFORM interno.jornada_marcar(NEW.id,'categoria_definida',
     coalesce(NEW.circle_cargos_atribuidos_em,NEW.circle_acesso_criado_em,statement_timestamp()),'gmv_de_entrada',
     'categoria:'||NEW.circle_categoria_entrada,NEW.circle_categoria_entrada);
  END IF;
 EXCEPTION WHEN OTHERS THEN
  RAISE WARNING 'jornada_nao_registrada %', SQLSTATE;
 END;
 RETURN NULL;
END;
$ficha$;
CREATE TRIGGER v5_80_jornada AFTER INSERT OR UPDATE ON interno.creators
 FOR EACH ROW EXECUTE FUNCTION interno.jornada_da_ficha();

CREATE FUNCTION interno.jornada_do_vinculo() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $vinculo$
DECLARE o interno.agenciamentos;
BEGIN
 IF TG_OP='UPDATE' THEN o:=OLD; END IF;
 BEGIN
  PERFORM interno.jornada_marcar(NEW.creator_id,'agenciamento_iniciado',coalesce(NEW.inicio_em,NEW.confirmado_em),
    NEW.fonte,'agenciamento:'||NEW.id);
  IF NEW.fim_em IS NOT NULL AND NEW.fim_em IS DISTINCT FROM o.fim_em THEN
   PERFORM interno.jornada_marcar(NEW.creator_id,'agenciamento_encerrado',NEW.fim_em,NEW.fonte,
     'agenciamento:'||NEW.id,coalesce(NEW.motivo_saida,''));
  END IF;
  IF NEW.numero_renovacao>coalesce(o.numero_renovacao,0) THEN
   PERFORM interno.jornada_marcar(NEW.creator_id,'contrato_renovado',
     coalesce(NEW.contrato_ultima_renovacao_em,statement_timestamp()),NEW.fonte,
     'agenciamento:'||NEW.id||':'||NEW.numero_renovacao);
  END IF;
 EXCEPTION WHEN OTHERS THEN
  RAISE WARNING 'jornada_nao_registrada %', SQLSTATE;
 END;
 RETURN NULL;
END;
$vinculo$;
CREATE TRIGGER v5_80_jornada AFTER INSERT OR UPDATE ON interno.agenciamentos
 FOR EACH ROW EXECUTE FUNCTION interno.jornada_do_vinculo();

REVOKE ALL ON FUNCTION interno.jornada_proteger(), interno.jornada_da_ficha(), interno.jornada_do_vinculo()
 FROM PUBLIC, anon, authenticated, service_role;

-- Marcos que já aconteceram, a partir das datas guardadas.
SELECT interno.jornada_marcar(c.id,'primeiro_contato',least(c.primeira_mensagem_em,c.formulario_recebido_em,c.criado_em),
  c.canal_entrada,'ficha') FROM interno.creators c;
SELECT interno.jornada_marcar(c.id,'validacao_'||c.validacao_situacao,c.validacao_confirmada_em,'pre_validacao',
  c.validacao_confirmada_em::text,coalesce(c.validacao_motivo,''))
 FROM interno.creators c WHERE c.validacao_situacao IN ('elegivel','inelegivel');
SELECT interno.jornada_marcar(c.id,'convite_enviado',c.convite_enviado_em,'convites',
  coalesce(c.convite_referencia,c.convite_enviado_em::text)) FROM interno.creators c;
SELECT interno.jornada_marcar(c.id,'convite_aceito',c.convite_aceito_em,'agenciamento',
  coalesce(c.convite_referencia,c.convite_aceito_em::text)) FROM interno.creators c;
SELECT interno.jornada_marcar(c.id,'cadastro_recebido',c.formulario_recebido_em,'formulario',
  coalesce(c.formulario_submissao_referencia,c.formulario_recebido_em::text),coalesce(c.formulario_versao,''))
 FROM interno.creators c;
SELECT interno.jornada_marcar(c.id,'acesso_liberado',c.circle_acesso_criado_em,'circle',
  coalesce(c.acesso_referencia,c.circle_acesso_criado_em::text)) FROM interno.creators c;
SELECT interno.jornada_marcar(c.id,'categoria_definida',
  coalesce(c.circle_cargos_atribuidos_em,c.circle_acesso_criado_em,c.formulario_recebido_em),'gmv_de_entrada',
  'categoria:'||c.circle_categoria_entrada,c.circle_categoria_entrada)
 FROM interno.creators c WHERE c.circle_categoria_entrada IS NOT NULL;
SELECT interno.jornada_marcar(a.creator_id,'agenciamento_iniciado',coalesce(a.inicio_em,a.confirmado_em),a.fonte,
  'agenciamento:'||a.id) FROM interno.agenciamentos a;
SELECT interno.jornada_marcar(a.creator_id,'agenciamento_encerrado',a.fim_em,a.fonte,'agenciamento:'||a.id,
  coalesce(a.motivo_saida,'')) FROM interno.agenciamentos a WHERE a.fim_em IS NOT NULL;
SELECT interno.jornada_marcar(a.creator_id,'contrato_renovado',a.contrato_ultima_renovacao_em,a.fonte,
  'agenciamento:'||a.id||':'||a.numero_renovacao) FROM interno.agenciamentos a WHERE a.numero_renovacao>0;

-- 4. Formatação da planilha ---------------------------------------------------------------------
CREATE FUNCTION interno.planilha_sim_nao(p boolean) RETURNS text LANGUAGE sql IMMUTABLE SET search_path='' AS
$f$ SELECT CASE p WHEN true THEN 'Sim' WHEN false THEN 'Não' END $f$;

CREATE FUNCTION interno.planilha_data(p timestamptz) RETURNS text LANGUAGE sql STABLE SET search_path='' AS
$f$ SELECT to_char(p AT TIME ZONE 'America/Sao_Paulo','DD/MM/YYYY') $f$;

CREATE FUNCTION interno.planilha_data(p date) RETURNS text LANGUAGE sql IMMUTABLE SET search_path='' AS
$f$ SELECT to_char(p,'DD/MM/YYYY') $f$;

CREATE FUNCTION interno.planilha_numero(p numeric) RETURNS text LANGUAGE sql IMMUTABLE SET search_path='' AS
$f$ SELECT translate(to_char(p,'FM999,999,999,990.00'),',.','.,') $f$;

CREATE FUNCTION interno.planilha_lista(p text[]) RETURNS text LANGUAGE sql IMMUTABLE SET search_path='' AS
$f$ SELECT nullif(array_to_string(p,', '),'') $f$;

-- Primeira letra maiúscula ("liso" -> "Liso"); o resto fica como a pessoa escreveu.
CREATE FUNCTION interno.planilha_rotulo(p text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path='' AS
$f$ SELECT nullif(upper(left(btrim(p),1))||substr(btrim(p),2),'') $f$;

-- Nome de cidade: só corrige o que veio todo em maiúsculas ou todo em minúsculas.
CREATE FUNCTION interno.planilha_nome_proprio(p text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path='' AS $f$
 SELECT CASE WHEN nullif(btrim(p),'') IS NULL THEN NULL
  WHEN btrim(p)<>upper(btrim(p)) AND btrim(p)<>lower(btrim(p)) THEN regexp_replace(btrim(p),'\s+',' ','g')
  ELSE (SELECT string_agg(CASE WHEN w.n>1 AND w.p IN ('de','da','do','das','dos','e') THEN w.p
        ELSE upper(left(w.p,1))||substr(w.p,2) END,' ' ORDER BY w.n)
        FROM unnest(regexp_split_to_array(lower(regexp_replace(btrim(p),'\s+',' ','g')),' ')) WITH ORDINALITY w(p,n)) END
$f$;

-- Respostas que dizem "nada" viram "Nenhum".
CREATE FUNCTION interno.planilha_nenhum(p text) RETURNS text LANGUAGE sql IMMUTABLE SET search_path='' AS $f$
 SELECT CASE WHEN lower(regexp_replace(btrim(p),'[.!\s]+$','')) IN ('nenhum','nenhuma','nada','não','nao','n/a','na','-',
   'creio que não','creio que nao','acho que não','acho que nao','não tenho','nao tenho','não há','nao ha','sem')
  THEN 'Nenhum' ELSE nullif(btrim(p),'') END
$f$;

-- Campo condicional: o valor, "Não informado" se devia ter e não tem, "Não se aplica" se não se aplica.
CREATE FUNCTION interno.planilha_condicional(p text, p_aplica boolean) RETURNS text LANGUAGE sql IMMUTABLE SET search_path='' AS
$f$ SELECT coalesce(nullif(btrim(p),''),CASE WHEN p_aplica THEN 'Não informado' ELSE 'Não se aplica' END) $f$;

REVOKE ALL ON FUNCTION interno.planilha_sim_nao(boolean), interno.planilha_data(timestamptz), interno.planilha_data(date),
 interno.planilha_numero(numeric), interno.planilha_lista(text[]), interno.planilha_rotulo(text),
 interno.planilha_nome_proprio(text), interno.planilha_nenhum(text), interno.planilha_condicional(text,boolean)
 FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION interno.planilha_sim_nao(boolean), interno.planilha_data(timestamptz), interno.planilha_data(date),
 interno.planilha_numero(numeric), interno.planilha_lista(text[]), interno.planilha_rotulo(text),
 interno.planilha_nome_proprio(text), interno.planilha_nenhum(text), interno.planilha_condicional(text,boolean)
 TO service_role;

-- 5. A planilha -----------------------------------------------------------------------------------
CREATE VIEW interno.cadastro_planilha WITH (security_invoker=true) AS
SELECT
 c.id::text AS "ID",
 coalesce(nullif(btrim(c.nome),''),'Não informado') AS "Nome",
 coalesce('@'||nullif(ltrim(btrim(c.tiktok),'@'),''),'Não informado') AS "@ TikTok",
 coalesce('R$ '||interno.planilha_numero(g.valor),'Não informado') AS "GMV",
 CASE WHEN g.id IS NULL OR g.periodicidade='nao_informado' THEN 'Não informado no cadastro'
  ELSE interno.planilha_data(g.periodo_inicio)||' a '||interno.planilha_data(g.periodo_fim) END AS "Período do GMV",
 coalesce(c.circle_categoria_entrada,'Pendente') AS "Categoria",
 coalesce(nullif(btrim(c.whatsapp),''),nullif(btrim(c.telefone),''),'Não informado') AS "Contato",
 coalesce(nullif(btrim(c.email),''),'Não informado') AS "E-mail",
 coalesce(interno.planilha_nome_proprio(c.endereco_cidade),'Não informado') AS "Cidade",
 CASE WHEN nullif(btrim(c.endereco_estado),'') IS NOT NULL THEN 'Brasil' ELSE 'Não informado' END AS "País",
 interno.planilha_data(least(c.primeira_mensagem_em,c.formulario_recebido_em,c.criado_em)) AS "Data de entrada",
 CASE WHEN a.id IS NULL THEN 'Não' WHEN a.situacao='confirmado' AND a.fim_em IS NULL THEN 'Sim'
  ELSE 'Não (desvinculado em '||interno.planilha_data(a.fim_em)||')' END AS "Agenciado?",
 coalesce(interno.planilha_data(coalesce(a.inicio_em,a.confirmado_em)),'Pendente') AS "Data de agenciamento",
 coalesce(nullif(btrim(c.observacoes),''),'Sem observações') AS "Observações",
 coalesce(nullif(btrim(c.foto_perfil_referencia),''),'Não informado') AS "Foto de perfil (referência)",
 coalesce(nullif(btrim(c.mini_bio),''),'Não informado') AS "Apresentação do creator",
 coalesce(interno.planilha_data(c.data_nascimento),'Não informado') AS "Data de nascimento",
 coalesce(interno.planilha_rotulo(c.genero),'Não informado') AS "Gênero",
 coalesce(interno.planilha_rotulo(c.estado_civil),'Não informado') AS "Estado civil",
 coalesce(nullif(btrim(c.camiseta),''),'Não informado') AS "Tamanho da camiseta",
 interno.planilha_condicional(c.camiseta_outro,c.camiseta='Outro') AS "Outro tamanho de camiseta",
 coalesce(interno.planilha_lista(c.nichos),'Não informado') AS "Nichos de conteúdo",
 interno.planilha_condicional(c.nichos_outros,'Outros'=ANY(c.nichos)) AS "Outros nichos",
 coalesce(interno.planilha_rotulo(c.cabelo),'Não informado') AS "Tipo de cabelo",
 coalesce(trim_scale(c.calcado)::text,'Não informado') AS "Número do calçado",
 coalesce(interno.planilha_rotulo(c.cor_raca),'Não informado') AS "Cor ou raça autodeclarada",
 coalesce(nullif(btrim(c.origem_informada_formulario),''),'Não informado') AS "Como conheceu a Amplify",
 interno.planilha_condicional(c.origem_outro,c.origem_informada_formulario='Outro jeito') AS "Outra forma de conhecer a Amplify",
 coalesce(interno.planilha_nenhum(c.expectativas),'Não informado') AS "Apoio esperado da Amplify",
 coalesce('R$ '||interno.planilha_numero(c.meta_renda_mensal),'Não informado') AS "Meta de renda mensal (R$)",
 coalesce(interno.planilha_nenhum(c.contexto_adicional),'Nenhum') AS "Contexto adicional do cadastro",
 coalesce(interno.planilha_lista(c.plataformas),'Não informado') AS "Plataformas de atuação",
 interno.planilha_condicional(c.instagram,'Instagram'=ANY(c.plataformas)) AS "@ Instagram",
 interno.planilha_condicional(c.plataformas_outros,'Outros'=ANY(c.plataformas)) AS "Outras plataformas",
 coalesce(interno.planilha_rotulo(c.experiencia_live_shop),'Não informado') AS "Experiência com Live Shop",
 coalesce(interno.planilha_sim_nao(c.teve_agencia_anterior),'Não informado') AS "Já participou de outra agência?",
 interno.planilha_condicional(c.nome_agencia_anterior,c.teve_agencia_anterior) AS "Nome da agência anterior",
 interno.planilha_condicional(c.experiencia_agencia,c.teve_agencia_anterior) AS "Experiência com a agência anterior",
 coalesce(interno.planilha_nenhum(c.produtos_excluidos),'Nenhum') AS "Produtos com que não trabalha",
 coalesce(interno.planilha_data(c.inicio_amplify_informado),'Não informado') AS "Início na Amplify informado",
 coalesce(nullif(btrim(c.rotina),''),'Não informado') AS "Rotina de criação",
 interno.planilha_condicional(c.rotina_outro,c.rotina='Outro') AS "Outra rotina de criação",
 coalesce(interno.planilha_sim_nao(c.declarou_mais_2000_seguidores),'Não informado') AS "Mais de 2.000 seguidores no TikTok?",
 coalesce(nullif(btrim(g.comprovante_referencia),''),'Não informado') AS "Print do GMV (referência)",
 coalesce(nullif(btrim(c.endereco_estado),''),'Não informado') AS "Estado de residência",
 coalesce(nullif(btrim(c.endereco_logradouro),''),'Não informado') AS "Logradouro de entrega",
 coalesce(nullif(btrim(c.endereco_bairro),''),'Não informado') AS "Bairro de entrega",
 coalesce(nullif(btrim(c.endereco_numero),''),'Não informado') AS "Número do endereço",
 coalesce(interno.planilha_nenhum(c.endereco_complemento),'Sem complemento') AS "Complemento do endereço",
 coalesce(nullif(btrim(c.endereco_cep),''),'Não informado') AS "CEP de entrega",
 coalesce(nullif(btrim(c.cpf),''),'Não informado') AS "CPF",
 coalesce(nullif(btrim(c.pix_chave),''),'Não informado') AS "Chave PIX",
 coalesce(interno.planilha_sim_nao(c.possui_cnpj),'Não informado') AS "Possui CNPJ?",
 interno.planilha_condicional(c.cnpj,c.possui_cnpj) AS "CNPJ",
 coalesce(interno.planilha_sim_nao(c.tem_filhos),'Não informado') AS "Tem filhos?",
 coalesce(nullif(btrim(c.alimentacao),''),'Não informado') AS "Alimentação",
 interno.planilha_condicional(c.restricao_alimentar,c.alimentacao='Tenho restrições alimentares (especificar)')
   AS "Restrição alimentar informada",
 coalesce(interno.planilha_sim_nao(c.casa_praia_campo),'Não informado') AS "Tem casa de praia ou campo?",
 coalesce(interno.planilha_sim_nao(c.carro),'Não informado') AS "Tem carro?",
 coalesce(interno.planilha_sim_nao(c.moto),'Não informado') AS "Tem moto?",
 coalesce(nullif(btrim(c.celular),''),'Não informado') AS "Tipo de celular",
 coalesce(interno.planilha_sim_nao(c.computador),'Não informado') AS "Tem computador?",
 coalesce(interno.planilha_sim_nao(c.tripe),'Não informado') AS "Tem tripé?",
 coalesce(interno.planilha_sim_nao(c.microfone),'Não informado') AS "Tem microfone de lapela?",
 coalesce(interno.planilha_sim_nao(c.academia),'Não informado') AS "Tem acesso a academia?",
 coalesce(interno.planilha_sim_nao(c.tem_pet),'Não informado') AS "Tem pet?",
 interno.planilha_condicional(c.pets,c.tem_pet) AS "Quais pets?",
 coalesce(interno.planilha_sim_nao(c.outro_idioma),'Não informado') AS "Fala outro idioma?",
 interno.planilha_condicional(c.video_idioma,c.outro_idioma) AS "Vídeo em outro idioma (link)",
 interno.planilha_condicional(interno.planilha_lista(c.idiomas),c.outro_idioma) AS "Idiomas falados",
 interno.planilha_condicional(c.idiomas_outros,'Outros'=ANY(c.idiomas)) AS "Outros idiomas",
 -- Além das 71: origem real, campanha, consentimento e situação calculada pela jornada.
 CASE c.canal_entrada WHEN 'whatsapp' THEN 'WhatsApp' WHEN 'formulario_publico' THEN 'Formulário direto'
  ELSE coalesce(interno.planilha_rotulo(c.canal_entrada),'Não identificado') END AS "Canal de entrada (real)",
 'Não identificado'::text AS "Campanha / anúncio",
 coalesce(interno.planilha_data(c.consentimento_aceito_em)||' (versão '||c.consentimento_versao||')','Não informado')
   AS "Consentimento",
 CASE WHEN a.id IS NOT NULL AND a.situacao='confirmado' AND a.fim_em IS NULL AND a.numero_renovacao>0 THEN 'Agenciado (renovado)'
  WHEN a.id IS NOT NULL AND a.situacao='confirmado' AND a.fim_em IS NULL THEN 'Agenciado'
  WHEN a.id IS NOT NULL THEN 'Desvinculado'
  WHEN c.circle_acesso_criado_em IS NOT NULL THEN 'Com acesso, vínculo não comprovado'
  ELSE 'Cadastrado, vínculo não comprovado' END AS "Situação atual"
FROM interno.creators c
LEFT JOIN LATERAL (SELECT g.* FROM interno.gmv g WHERE g.creator_id=c.id AND g.finalidade='entrada'
  ORDER BY (g.id=c.gmv_entrada_id) DESC NULLS LAST, g.criado_em DESC, g.id DESC LIMIT 1) g ON true
LEFT JOIN LATERAL (SELECT a.* FROM interno.agenciamentos a WHERE a.creator_id=c.id
  ORDER BY (a.fim_em IS NULL) DESC, coalesce(a.inicio_em,a.confirmado_em) DESC, a.id DESC LIMIT 1) a ON true
WHERE c.cadastro_situacao='confirmado';
COMMENT ON VIEW interno.cadastro_planilha IS 'Planilha "Principal": uma linha por cadastro confirmado, 71 colunas na ordem + 4 de origem e situação. Só texto, nenhuma célula vazia.';
REVOKE ALL ON interno.cadastro_planilha FROM PUBLIC, anon, authenticated;
GRANT SELECT ON interno.cadastro_planilha TO service_role;

-- 6. Conferência: 75 colunas e nenhuma célula vazia ---------------------------------------------
DO $confere$
DECLARE v_colunas integer; v_vazias integer;
BEGIN
 SELECT count(*) INTO v_colunas FROM information_schema.columns
  WHERE table_schema='interno' AND table_name='cadastro_planilha';
 SELECT count(*) INTO v_vazias FROM interno.cadastro_planilha p, jsonb_each_text(to_jsonb(p)) e
  WHERE e.value IS NULL OR btrim(e.value)='';
 IF v_colunas<>75 OR v_vazias<>0 THEN
  RAISE EXCEPTION 'cadastro_publico_007_planilha_incompleta colunas=% vazias=%', v_colunas, v_vazias;
 END IF;
END;
$confere$;
COMMIT;
