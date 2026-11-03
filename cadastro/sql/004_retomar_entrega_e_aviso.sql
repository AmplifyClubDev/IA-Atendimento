-- 004: entrega do acesso que se recupera sozinha + dados para o aviso no WhatsApp.
--  * preparar_entrega_circle_v5 passa a permitir nova tentativa quando a anterior não
--    terminou (reinício do serviço, Circle lento): até 3 tentativas, 10 min entre elas.
--    Cada tentativa é um evento 'acesso_solicitado' próprio (revisão 2, 102, 103).
--    Devolve o que já foi feito (Circle / e-mail) para não repetir efeito externo, e a
--    conversa do Chatwoot do lead da Bia para o aviso "acesso liberado".
--  * listar_entregas_pendentes_v5: cadastros do formulário cuja entrega não terminou.
-- Não cria tabelas nem altera dados existentes.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
DO $guard$
BEGIN
 IF to_regprocedure('public.preparar_entrega_circle_v5(uuid)') IS NULL
   OR to_regprocedure('public.listar_entregas_pendentes_v5()') IS NOT NULL
   THEN RAISE EXCEPTION 'cadastro_publico_004_estado_inesperado'; END IF;
END;
$guard$;

CREATE OR REPLACE FUNCTION public.preparar_entrega_circle_v5(p_evento uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $preparar$
DECLARE e interno.eventos%rowtype; c interno.creators%rowtype; v_gmv numeric; v_declarado numeric;
 v_tentativas integer; v_ultima timestamptz; v_circle boolean; v_email boolean; v_member text; v_categoria text;
 v_conversa text; v_conta text; v_rev integer; v_lido numeric;
 v_previous text:=coalesce(current_setting('app.v5_explicit_event',true),'off');
BEGIN
 IF current_user<>'service_role' THEN RAISE EXCEPTION 'cadastro_publico_service_role_obrigatorio' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('v5:cadastro',0));
 SELECT * INTO e FROM interno.eventos WHERE submissao_id=p_evento AND tipo='cadastro_confirmado' AND instancia='formulario_publico';
 IF NOT FOUND THEN RETURN jsonb_build_object('ready',false,'reason','cadastro_nao_encontrado'); END IF;
 SELECT count(*), max(registrado_em) INTO v_tentativas, v_ultima FROM interno.eventos
   WHERE instancia='formulario_publico' AND referencia=p_evento::text AND tipo='acesso_solicitado';
 SELECT dados->>'circle_member_id', dados->>'categoria' INTO v_member, v_categoria FROM interno.eventos
   WHERE instancia='formulario_publico' AND referencia=p_evento::text AND tipo='acesso_entregue' LIMIT 1;
 v_circle := v_member IS NOT NULL;
 v_email := EXISTS(SELECT 1 FROM interno.eventos WHERE instancia='formulario_publico' AND referencia=p_evento::text
   AND tipo='email_aceito_provedor');
 IF v_circle AND v_email THEN RETURN jsonb_build_object('ready',false,'reason','entrega_concluida'); END IF;
 IF v_tentativas>=3 THEN RETURN jsonb_build_object('ready',false,'reason','tentativas_esgotadas'); END IF;
 IF v_tentativas>0 AND v_ultima>statement_timestamp()-interval '10 minutes' THEN
  RETURN jsonb_build_object('ready',false,'reason','entrega_ja_iniciada'); END IF;
 SELECT * INTO c FROM interno.creators WHERE id=e.creator_id FOR UPDATE;
 IF c.cadastro_situacao<>'confirmado' OR c.email IS NULL OR c.nome IS NULL THEN
  RETURN jsonb_build_object('ready',false,'reason','cadastro_incompleto'); END IF;
 SELECT valor INTO v_gmv FROM interno.gmv WHERE creator_id=c.id AND finalidade='entrada' AND natureza='verificado'
   AND situacao='registrado' AND valor IS NOT NULL;
 SELECT valor INTO v_declarado FROM interno.gmv WHERE creator_id=c.id AND finalidade='entrada' AND natureza='declarado'
   AND situacao='registrado' AND valor IS NOT NULL;
 -- Valor que o bot leu no print (categoria também numa nova tentativa).
 SELECT (dados->>'valor')::numeric INTO v_lido FROM interno.eventos WHERE instancia='formulario_publico'
   AND referencia=p_evento::text AND tipo='gmv_atualizado' AND dados->>'situacao'='lido' LIMIT 1;
 -- Conversa do Chatwoot do lead (atendimento mais recente da mesma ficha, aberto ou não).
 SELECT conversation_id, account_id INTO v_conversa, v_conta FROM interno.atendimentos
   WHERE creator_id=c.id ORDER BY atualizado_em DESC LIMIT 1;
 v_rev := CASE WHEN v_tentativas=0 THEN 2 ELSE 100+v_tentativas+1 END;
 PERFORM set_config('app.v5_explicit_event','on',true);
 INSERT INTO interno.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,dados)
 VALUES(c.id,e.atendimento_id,'acesso_solicitado','formulario_publico',p_evento::text,v_rev,statement_timestamp(),
   jsonb_build_object('origem','formulario_publico','tentativa',v_tentativas+1,'gmv_verificado',v_gmv,'gmv_declarado',v_declarado));
 UPDATE interno.creators SET circle_situacao='entrega_em_andamento' WHERE id=c.id AND NOT v_circle;
 PERFORM set_config('app.v5_explicit_event',v_previous,true);
 RETURN jsonb_build_object('ready',true,'creator_id',c.id,'name',c.nome,'email',c.email,'gmv_verificado',v_gmv,
   'gmv_declarado',v_declarado,'gmv_lido',v_lido,'tentativa',v_tentativas+1,'circle_feito',v_circle,'circle_member_id',v_member::bigint,
   'categoria_entregue',v_categoria,'email_feito',v_email,'conversation_id',v_conversa,'account_id',v_conta);
END;
$preparar$;

CREATE FUNCTION public.listar_entregas_pendentes_v5()
RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $listar$
 SELECT coalesce(jsonb_agg(jsonb_build_object('evento',e.submissao_id,'tentativas',
   (SELECT count(*) FROM interno.eventos s WHERE s.instancia='formulario_publico' AND s.referencia=e.referencia AND s.tipo='acesso_solicitado'))
   ORDER BY e.registrado_em),'[]'::jsonb)
 FROM interno.eventos e
 WHERE e.instancia='formulario_publico' AND e.tipo='cadastro_confirmado'
   AND e.registrado_em>statement_timestamp()-interval '7 days'
   AND NOT EXISTS(SELECT 1 FROM interno.eventos d WHERE d.instancia='formulario_publico' AND d.referencia=e.referencia
     AND d.tipo='email_aceito_provedor')
$listar$;

REVOKE ALL ON FUNCTION public.listar_entregas_pendentes_v5() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.listar_entregas_pendentes_v5() TO service_role;
COMMIT;
