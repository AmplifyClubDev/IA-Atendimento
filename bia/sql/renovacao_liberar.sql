-- Renovação · fim do ciclo (27/11/2026, item 15 da auditoria).
-- Quando o ciclo de uma conversa enviada pelo serviço acaba, a etiqueta "Renovacao de contrato" sai (a Bia volta a atender):
--   renovou  -> contrato estendido (fim > o do envio) ou TikTok mostra "Aceita"  (o serviço manda renovacao_confirmada)
--   saiu     -> não está mais ativo na base
--   venceu   -> o contrato do envio já terminou há 1 dia ou mais (sem renovar)
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE interno.renovacao_envios
  ADD COLUMN IF NOT EXISTS ciclo_fim text CHECK (ciclo_fim IN ('renovou', 'saiu', 'venceu')),
  ADD COLUMN IF NOT EXISTS ciclo_fechado_em timestamptz,
  ADD COLUMN IF NOT EXISTS confirmacao_enviada_em timestamptz;

CREATE OR REPLACE VIEW public.renovacao_para_liberar AS
SELECT e.id, e.chatwoot_conversa, e.telefone, e.relation_id,
       CASE WHEN a.relation_id IS NOT NULL AND (a.renovacao = 'Aceita' OR a.contrato_fim > e.contrato_fim) THEN 'renovou'
            WHEN a.relation_id IS NULL OR a.situacao = 'Saiu' THEN 'saiu'
            ELSE 'venceu' END AS ciclo_fim,
       to_char(coalesce(a.renovacao_novo_fim, a.contrato_fim), 'DD/MM/YYYY') AS novo_fim
FROM interno.renovacao_envios e
LEFT JOIN public.agenciados_ficha a ON a.relation_id = e.relation_id
WHERE e.situacao = 'enviado' AND e.chatwoot_conversa IS NOT NULL AND e.ciclo_fechado_em IS NULL
  AND (a.relation_id IS NULL OR a.situacao = 'Saiu' OR a.renovacao = 'Aceita' OR a.contrato_fim > e.contrato_fim
       OR e.contrato_fim < (now() AT TIME ZONE 'America/Sao_Paulo')::date);

-- p = {"id", "ciclo_fim", "confirmacao": true|false}. Fecha o ciclo uma vez só.
CREATE OR REPLACE FUNCTION public.fechar_ciclo_renovacao_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE n integer;
BEGIN
  IF current_user NOT IN ('service_role', 'postgres') THEN
    RAISE EXCEPTION USING errcode = '42501', message = 'Só o sistema fecha ciclos.';
  END IF;
  IF (p ->> 'id') !~ '^[0-9]{1,18}$' OR (p ->> 'ciclo_fim') NOT IN ('renovou', 'saiu', 'venceu') THEN
    RAISE EXCEPTION USING errcode = '23514', message = 'Ciclo inválido.';
  END IF;
  UPDATE interno.renovacao_envios SET ciclo_fim = p ->> 'ciclo_fim', ciclo_fechado_em = now(),
         confirmacao_enviada_em = CASE WHEN coalesce((p ->> 'confirmacao')::boolean, false) THEN now() END
  WHERE id = (p ->> 'id')::bigint AND ciclo_fechado_em IS NULL;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN jsonb_build_object('fechados', n);
END
$fn$;
REVOKE ALL ON FUNCTION public.fechar_ciclo_renovacao_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fechar_ciclo_renovacao_v5(jsonb) TO service_role;
REVOKE ALL ON public.renovacao_para_liberar FROM anon, authenticated;
GRANT SELECT ON public.renovacao_para_liberar TO service_role;
COMMIT;
