-- Categoria do Circle na entrada: GMV verificado quando existir; senão o GMV que a pessoa
-- declarou no formulário (regra do processo antigo: CADASTRO_GMV_ORIGEM=formulario_declarado).
-- Só troca public.preparar_entrega_circle_v5 (mesma assinatura e permissões); não toca tabelas.
CREATE OR REPLACE FUNCTION public.preparar_entrega_circle_v5(p_evento uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $preparar$
DECLARE e interno.eventos%rowtype; c interno.creators%rowtype; v_gmv numeric; v_declarado numeric; v_previous text:=coalesce(current_setting('app.v5_explicit_event',true),'off');
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
 SELECT valor INTO v_gmv FROM interno.gmv WHERE creator_id=c.id AND finalidade='entrada' AND natureza='verificado'
   AND situacao='registrado' AND valor IS NOT NULL;
 SELECT valor INTO v_declarado FROM interno.gmv WHERE creator_id=c.id AND finalidade='entrada' AND natureza='declarado'
   AND situacao='registrado' AND valor IS NOT NULL;
 PERFORM set_config('app.v5_explicit_event','on',true);
 INSERT INTO interno.eventos(creator_id,atendimento_id,tipo,instancia,referencia,revisao,ocorrido_em,dados)
 VALUES(c.id,e.atendimento_id,'acesso_solicitado','formulario_publico',p_evento::text,2,statement_timestamp(),
   jsonb_build_object('origem','formulario_publico','gmv_verificado',v_gmv,'gmv_declarado',v_declarado));
 UPDATE interno.creators SET circle_situacao='entrega_em_andamento' WHERE id=c.id;
 PERFORM set_config('app.v5_explicit_event',v_previous,true);
 RETURN jsonb_build_object('ready',true,'creator_id',c.id,'name',c.nome,'email',c.email,'gmv_verificado',v_gmv,
   'gmv_declarado',v_declarado);
END;
$preparar$;
