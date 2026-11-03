-- 005: o que a Bia apura na conversa passa a aparecer na ficha (interno.creators).
-- Hoje fica só dentro de interno.atendimentos (qualificacao/origem/marcos/resumo) e a ficha fica null.
-- Um gatilho em atendimentos projeta, a cada gravação, só campos que a conversa já confirmou:
--   origem_entrada/fonte/detalhe <- atendimentos.origem (declaração da pessoa)
--   interesse_agenciamento, quer_convite <- qualificacao (respostas dela)
--   validacao_situacao/confirmada_em <- verificacoes_tiktok.precheck (só resultado confirmado)
--   convite_situacao/enviado_em/referencia/aceito_em <- verificacoes_tiktok.invite / relationship
--   pendencia_atual, proxima_acao <- resumo / proximo_passo do atendimento mais recente
-- O @ declarado NÃO vai para creators.tiktok: lá só entra @ com vínculo confirmado (regra da Bia).
-- Não altera a função da Bia nem cria tabela. No fim, preenche as fichas existentes uma vez.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
DO $guard$
BEGIN
 IF to_regprocedure('interno.projetar_atendimento_na_ficha()') IS NOT NULL
   THEN RAISE EXCEPTION 'cadastro_publico_005_ja_instalada'; END IF;
END;
$guard$;

CREATE FUNCTION interno.projetar_atendimento_na_ficha()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $projetar$
DECLARE
 q jsonb := coalesce(NEW.qualificacao,'{}'::jsonb);
 v jsonb := coalesce(NEW.qualificacao->'verificacoes_tiktok','{}'::jsonb);
 v_pre jsonb := v->'precheck'; v_inv jsonb := v->'invite'; v_rel jsonb := v->'relationship';
 v_mais_recente boolean;
 v_previous text := coalesce(current_setting('app.v5_explicit_event',true),'off');
BEGIN
 v_mais_recente := NOT EXISTS(SELECT 1 FROM interno.atendimentos o WHERE o.creator_id=NEW.creator_id
   AND o.id<>NEW.id AND o.atualizado_em>NEW.atualizado_em);
 -- Projeção derivada: sem evento de auditoria por campo (o evento do atendimento já existe).
 PERFORM set_config('app.v5_explicit_event','on',true);
 UPDATE interno.creators c SET
   origem_entrada=coalesce(c.origem_entrada,NEW.origem->>'value'),
   origem_fonte=coalesce(c.origem_fonte,NEW.origem->>'source'),
   origem_detalhe=coalesce(c.origem_detalhe,NEW.origem->>'reference'),
   interesse_agenciamento=CASE WHEN jsonb_typeof(q->'interesse_agenciamento')='boolean'
     THEN (q->>'interesse_agenciamento')::boolean ELSE c.interesse_agenciamento END,
   quer_convite=CASE WHEN jsonb_typeof(q->'consentimento_convite')='boolean'
     THEN (q->>'consentimento_convite')::boolean ELSE c.quer_convite END,
   validacao_situacao=CASE WHEN v_pre->'confirmed'='true'::jsonb THEN
       CASE v_pre->>'status' WHEN 'eligible' THEN 'elegivel' WHEN 'ineligible' THEN 'inelegivel' ELSE v_pre->>'status' END
     WHEN v_pre IS NOT NULL AND c.validacao_situacao IS NULL THEN 'pendente' ELSE c.validacao_situacao END,
   validacao_confirmada_em=CASE WHEN v_pre->'confirmed'='true'::jsonb
     THEN coalesce(c.validacao_confirmada_em,(v_pre->>'observed_at')::timestamptz) ELSE c.validacao_confirmada_em END,
   convite_situacao=CASE
     WHEN v_rel->>'status'='linked' AND v_rel->'confirmed'='true'::jsonb THEN 'aceito'
     WHEN v_inv->>'status'='sent' AND v_inv->'confirmed'='true'::jsonb THEN coalesce(nullif(c.convite_situacao,'a_confirmar'),'enviado')
     WHEN v_inv IS NOT NULL AND c.convite_situacao IS NULL THEN 'a_confirmar'
     ELSE c.convite_situacao END,
   convite_enviado_em=CASE WHEN v_inv->>'status'='sent' AND v_inv->'confirmed'='true'::jsonb
     THEN coalesce(c.convite_enviado_em,(v_inv->>'observed_at')::timestamptz) ELSE c.convite_enviado_em END,
   convite_referencia=coalesce(c.convite_referencia,v_inv->'evidence'->>'relation_id'),
   convite_aceito_em=CASE WHEN v_rel->>'status'='linked' AND v_rel->'confirmed'='true'::jsonb
     THEN coalesce(c.convite_aceito_em,(v_rel->>'observed_at')::timestamptz) ELSE c.convite_aceito_em END,
   pendencia_atual=CASE WHEN v_mais_recente THEN NEW.resumo ELSE c.pendencia_atual END,
   proxima_acao=CASE WHEN v_mais_recente THEN NEW.proximo_passo ELSE c.proxima_acao END
 WHERE c.id=NEW.creator_id;
 PERFORM set_config('app.v5_explicit_event',v_previous,true);
 RETURN NULL;
END;
$projetar$;

CREATE TRIGGER v5_60_projetar_ficha AFTER INSERT OR UPDATE ON interno.atendimentos
 FOR EACH ROW EXECUTE FUNCTION interno.projetar_atendimento_na_ficha();
REVOKE ALL ON FUNCTION interno.projetar_atendimento_na_ficha() FROM PUBLIC, anon, authenticated;

-- Preenche as fichas que já existem, do atendimento mais antigo ao mais recente
-- (o mais recente prevalece). Toque neutro: regrava o mesmo valor só para disparar o gatilho.
DO $backfill$
DECLARE a record;
BEGIN
 FOR a IN SELECT id FROM interno.atendimentos ORDER BY atualizado_em LOOP
  UPDATE interno.atendimentos SET resumo=resumo WHERE id=a.id;
 END LOOP;
END;
$backfill$;
COMMIT;
