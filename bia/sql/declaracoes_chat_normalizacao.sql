BEGIN;
ALTER TABLE interno.declaracoes_chat ADD COLUMN criterio_normalizacao text NOT NULL DEFAULT 'valor_explicito' CHECK (criterio_normalizacao IN ('valor_explicito','sem_vendas','inicio_atividade','nao_sabe','aproximado','limite_inferior_faixa'));
COMMENT ON COLUMN interno.declaracoes_chat.criterio_normalizacao IS 'Regra de armazenamento aprovada por Bruno em 17/11/2026. nao_sabe/inicio_atividade armazenam zero por convenção, não confirmação de ausência de vendas.';
CREATE OR REPLACE FUNCTION interno.registrar_declaracoes_chat_v5(p_entrada jsonb, p_resultado jsonb, p_declaracoes jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,interno AS $fn$
DECLARE a interno.atendimentos%rowtype; d jsonb; anterior interno.declaracoes_chat%rowtype;
 v_valor bigint; v_data timestamptz;
BEGIN
 IF current_setting('role',true) IS DISTINCT FROM 'service_role' THEN
  RAISE EXCEPTION 'service_role_required' USING ERRCODE='42501';
 END IF;
 IF jsonb_typeof(p_declaracoes) IS DISTINCT FROM 'array' OR jsonb_array_length(p_declaracoes) NOT BETWEEN 1 AND 2 THEN
  RAISE EXCEPTION 'declaracoes_invalid' USING ERRCODE='22023';
 END IF;
 SELECT * INTO a FROM interno.atendimentos WHERE id=(p_resultado->>'atendimento_id')::uuid FOR UPDATE;
 IF NOT FOUND OR a.account_id<>'1' OR a.creator_id::text IS DISTINCT FROM p_resultado->>'creator_id'
  OR a.instancia IS DISTINCT FROM p_entrada->>'instancia'
  OR a.account_id IS DISTINCT FROM p_entrada->>'account_id'
  OR a.contact_id IS DISTINCT FROM p_entrada->>'contact_id'
  OR a.conversation_id IS DISTINCT FROM p_entrada->>'conversation_id'
  OR a.id::text IS DISTINCT FROM p_entrada->>'atendimento_id' THEN
  RAISE EXCEPTION 'declaracoes_identity_conflict' USING ERRCODE='23505';
 END IF;
 FOR d IN SELECT value FROM jsonb_array_elements(p_declaracoes) LOOP
  IF jsonb_typeof(d) IS DISTINCT FROM 'object'
    OR NOT d ?& ARRAY['campo','valor','moeda','periodo_dias','declarado_em','mensagem_id','evidencia']
    OR (SELECT count(*) FROM jsonb_object_keys(d)) NOT IN (7,8)
    OR EXISTS(SELECT 1 FROM jsonb_object_keys(d) k WHERE k NOT IN ('campo','valor','moeda','periodo_dias','declarado_em','mensagem_id','evidencia','criterio_normalizacao'))
    OR (d ? 'criterio_normalizacao' AND (jsonb_typeof(d->'criterio_normalizacao') IS DISTINCT FROM 'string' OR d->>'criterio_normalizacao' NOT IN ('valor_explicito','sem_vendas','inicio_atividade','nao_sabe','aproximado','limite_inferior_faixa')))
    OR (d->>'campo'='seguidores' AND coalesce(d->>'criterio_normalizacao','valor_explicito')<>'valor_explicito')
    OR d->>'campo' NOT IN ('gmv','seguidores') OR d->>'campo' IS NULL
    OR jsonb_typeof(d->'valor') IS DISTINCT FROM 'number'
    OR coalesce(d->>'valor','') !~ '^[0-9]{1,12}$'
    OR jsonb_typeof(d->'mensagem_id') IS DISTINCT FROM 'string'
    OR d->>'mensagem_id' IS DISTINCT FROM p_entrada->>'message_id'
    OR jsonb_typeof(d->'evidencia') IS DISTINCT FROM 'string'
    OR length(btrim(d->>'evidencia')) NOT BETWEEN 1 AND 4000
    OR jsonb_typeof(d->'declarado_em') IS DISTINCT FROM 'string'
    OR coalesce(d->>'declarado_em','') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T.*(Z|[+]00:00)$' THEN
   RAISE EXCEPTION 'declaracao_invalid' USING ERRCODE='22023';
  END IF;
  v_valor:=(d->>'valor')::bigint; v_data:=(d->>'declarado_em')::timestamptz;
  IF NOT isfinite(v_data) OR v_data>statement_timestamp()+interval '5 minutes'
    OR v_data IS DISTINCT FROM (p_entrada->>'observado_em')::timestamptz
    OR v_data<a.primeira_mensagem_em OR v_data>a.expires_at
    OR (d->>'campo'='gmv' AND (v_valor>100000000000 OR d->>'moeda' IS DISTINCT FROM 'BRL' OR d->'periodo_dias' IS DISTINCT FROM '30'::jsonb))
    OR (d->>'campo'='seguidores' AND (v_valor>1000000000 OR d->'moeda' IS DISTINCT FROM 'null'::jsonb OR d->'periodo_dias' IS DISTINCT FROM 'null'::jsonb)) THEN
   RAISE EXCEPTION 'declaracao_value_or_clock_invalid' USING ERRCODE='22023';
  END IF;
  INSERT INTO interno.declaracoes_chat(atendimento_id,creator_id,account_id,contact_id,conversation_id,inbox_id,
    campo,valor,moeda,periodo_dias,declarado_em,mensagem_id,pergunta_id,evidencia,lote,criterio_normalizacao)
   VALUES(a.id,a.creator_id,a.account_id,a.contact_id,a.conversation_id,'3',d->>'campo',v_valor,d->>'moeda',
    (d->>'periodo_dias')::integer,v_data,d->>'mensagem_id',NULL,d->>'evidencia','bia_automatico_v1',coalesce(d->>'criterio_normalizacao','valor_explicito'))
   ON CONFLICT(account_id,mensagem_id,campo) DO NOTHING;
  SELECT * INTO anterior FROM interno.declaracoes_chat
   WHERE account_id=a.account_id AND mensagem_id=d->>'mensagem_id' AND campo=d->>'campo';
  IF anterior.atendimento_id<>a.id OR anterior.creator_id<>a.creator_id OR anterior.valor<>v_valor
    OR anterior.declarado_em<>v_data OR anterior.evidencia IS DISTINCT FROM d->>'evidencia'
    OR anterior.moeda IS DISTINCT FROM d->>'moeda' OR anterior.periodo_dias IS DISTINCT FROM (d->>'periodo_dias')::integer THEN
   RAISE EXCEPTION 'declaracao_replay_conflict' USING ERRCODE='23505';
  END IF;
 END LOOP;
 -- Existing trigger projects the latest declarations without replacing other facts.
 UPDATE interno.atendimentos SET qualificacao=qualificacao WHERE id=a.id;
END;
$fn$;
REVOKE ALL ON FUNCTION interno.registrar_declaracoes_chat_v5(jsonb,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION interno.registrar_declaracoes_chat_v5(jsonb,jsonb,jsonb) TO service_role;

CREATE OR REPLACE FUNCTION interno.preservar_declaracoes_chat() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,interno AS $fn$
DECLARE dados jsonb;
BEGIN
 SELECT jsonb_object_agg(campo,jsonb_build_object(
  'valor',valor,'unidade',CASE WHEN campo='gmv' THEN 'centavos' ELSE 'seguidores' END,
  'moeda',moeda,'periodo_dias',periodo_dias,'criterio_normalizacao',criterio_normalizacao,'origem',origem,'declarado_em',declarado_em,
  'mensagem_id',mensagem_id,'pergunta_id',pergunta_id,'conversation_id',conversation_id))
 INTO dados FROM (
  SELECT DISTINCT ON (campo) campo,valor,moeda,periodo_dias,criterio_normalizacao,origem,declarado_em,mensagem_id,pergunta_id,conversation_id
  FROM interno.declaracoes_chat
  WHERE atendimento_id=NEW.id AND creator_id=NEW.creator_id
  ORDER BY campo,CASE WHEN criterio_normalizacao IN ('nao_sabe','inicio_atividade') THEN 1 ELSE 0 END,declarado_em DESC,id DESC
 ) ultima;
 IF dados IS NOT NULL THEN
  NEW.qualificacao=coalesce(NEW.qualificacao,'{}'::jsonb)||jsonb_build_object('declaracoes_chat',dados);
 END IF;
 RETURN NEW;
END;
$fn$;
CREATE OR REPLACE VIEW interno.qualificacao_chat_ultima WITH (security_invoker=true) AS
 SELECT DISTINCT ON (creator_id,campo) creator_id,atendimento_id,conversation_id,campo,valor,
 CASE WHEN campo='gmv' THEN 'centavos' ELSE 'seguidores' END AS unidade,
 moeda,periodo_dias,origem,declarado_em,mensagem_id,criterio_normalizacao
 FROM interno.declaracoes_chat ORDER BY creator_id,campo,
 CASE WHEN criterio_normalizacao IN ('nao_sabe','inicio_atividade') THEN 1 ELSE 0 END,declarado_em DESC,id DESC;
NOTIFY pgrst,'reload schema';
COMMIT;
