-- Cadastro público v5, 006: leitura dos atendimentos da Bia parados em `blocked`.
--  * listar_atendimentos_parados_v5(p_minutos): atendimentos abertos em `blocked` há mais de
--    p_minutos (e há menos de 3 dias), para o alerta da equipe. Só leitura.
-- Não cria tabelas nem altera dados existentes.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='60s';
DO $guard$
BEGIN
 IF to_regclass('interno.atendimentos') IS NULL
   OR to_regprocedure('public.listar_atendimentos_parados_v5(integer)') IS NOT NULL
   THEN RAISE EXCEPTION 'cadastro_publico_006_estado_inesperado'; END IF;
END;
$guard$;

CREATE FUNCTION public.listar_atendimentos_parados_v5(p_minutos integer)
RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER SET search_path='' AS $listar$
 SELECT coalesce(jsonb_agg(jsonb_build_object('atendimento',a.id,'conversa',a.conversation_id,'etapa',a.etapa,
   'desde',a.atualizado_em,'tiktok',c.tiktok,'nome',c.nome) ORDER BY a.atualizado_em),'[]'::jsonb)
 FROM interno.atendimentos a LEFT JOIN interno.creators c ON c.id=a.creator_id
 WHERE a.situacao='aberto' AND a.etapa='blocked'
   AND a.atualizado_em<statement_timestamp()-make_interval(mins=>greatest(p_minutos,5))
   AND a.atualizado_em>statement_timestamp()-interval '3 days';
$listar$;

REVOKE ALL ON FUNCTION public.listar_atendimentos_parados_v5(integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.listar_atendimentos_parados_v5(integer) TO service_role;
COMMIT;
