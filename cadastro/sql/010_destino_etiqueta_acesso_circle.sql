-- Projeção pontual do acesso na conversa exata, sem decidir envio de mensagens.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';

CREATE FUNCTION public.destino_etiqueta_acesso_circle_v5(p_evento uuid)
RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $destino$
 WITH matches AS (
   SELECT DISTINCT a.conversation_id, a.account_id
   FROM interno.eventos AS e
   JOIN interno.atendimentos AS a
     ON a.id = e.atendimento_id AND a.creator_id = e.creator_id
   WHERE current_user = 'service_role'
     AND e.referencia = p_evento::text
     AND e.tipo = 'acesso_entregue'
     AND e.instancia = 'formulario_publico'
     AND a.instancia = 'chatwoot-amplify-prod'
     AND a.conversation_id ~ '^[1-9][0-9]{0,17}$'
     AND a.account_id ~ '^[1-9][0-9]{0,17}$'
   LIMIT 2
 )
 SELECT CASE WHEN count(*) = 1 THEN
   jsonb_build_object('conversation_id', min(conversation_id), 'account_id', min(account_id))
   ELSE '{}'::jsonb END
 FROM matches
$destino$;

REVOKE ALL ON FUNCTION public.destino_etiqueta_acesso_circle_v5(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.destino_etiqueta_acesso_circle_v5(uuid) TO service_role;
COMMIT;
