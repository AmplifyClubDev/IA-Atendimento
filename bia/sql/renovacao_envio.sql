-- Renovação · marcar o resultado de cada envio da fila (25/11/2026). Usado por renovacao/envio.mjs.
-- p = {"id", "situacao": "enviado"|"falhou"|"cancelado", "motivo"?, "chatwoot_conversa"?}. Só muda o que está "previsto".
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION public.marcar_envio_renovacao_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE n integer;
BEGIN
  IF current_user NOT IN ('service_role', 'postgres') THEN
    RAISE EXCEPTION USING errcode = '42501', message = 'Só o sistema marca envios.';
  END IF;
  IF (p ->> 'situacao') NOT IN ('enviado', 'falhou', 'cancelado') OR (p ->> 'id') !~ '^[0-9]{1,18}$' THEN
    RAISE EXCEPTION USING errcode = '23514', message = 'Envio inválido.';
  END IF;
  UPDATE interno.renovacao_envios SET
    situacao = p ->> 'situacao',
    motivo = left(nullif(p ->> 'motivo', ''), 200),
    chatwoot_conversa = CASE WHEN (p ->> 'chatwoot_conversa') ~ '^[0-9]{1,18}$' THEN p ->> 'chatwoot_conversa' END,
    enviado_em = CASE WHEN p ->> 'situacao' = 'enviado' THEN now() END
  WHERE id = (p ->> 'id')::bigint AND situacao = 'previsto';
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN jsonb_build_object('alterados', n);
END
$fn$;
REVOKE ALL ON FUNCTION public.marcar_envio_renovacao_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.marcar_envio_renovacao_v5(jsonb) TO service_role;
COMMIT;
