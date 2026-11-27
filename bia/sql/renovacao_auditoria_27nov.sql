-- Renovação · correções da auditoria (27/11/2026).
-- 1) A fila cancela o que perdeu o sentido: contrato que já venceu (ou vence hoje), quem renovou, quem pediu para sair
--    e quem sumiu da ficha. Nada "previsto" de dias atrás sai com data passada quando o envio for ligado.
-- 2) As respostas só são registradas nas conversas que o serviço enviou (renovacao_envios.chatwoot_conversa) ou de
--    números de teste (p.teste = true). Conversas antigas com a mesma etiqueta (n8n) ficam de fora.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION public.preparar_fila_renovacao_v5()
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE n_novos integer; n_cancelados integer; hoje date := (now() AT TIME ZONE 'America/Sao_Paulo')::date;
BEGIN
  IF current_user NOT IN ('service_role', 'postgres') THEN
    RAISE EXCEPTION USING errcode = '42501', message = 'Só o sistema prepara a fila de renovação.';
  END IF;
  INSERT INTO interno.renovacao_envios (relation_id, contrato_fim, etapa, template, parametros, telefone, arroba, nome, tipo_contrato)
  SELECT r.relation_id, r.contrato_fim, r.etapa, r.template, r.parametros, r.telefone, ltrim(r.tiktok, '@'), r.nome, r.tipo_contrato
  FROM public.renovacao_regua r
  WHERE r.motivo IS NULL
  ON CONFLICT (relation_id, contrato_fim, etapa) DO NOTHING;
  GET DIAGNOSTICS n_novos = ROW_COUNT;
  UPDATE interno.renovacao_envios e SET situacao = 'cancelado',
         motivo = CASE WHEN a.relation_id IS NULL THEN 'Saiu da base antes do envio'
                       WHEN a.renovacao = 'Aceita' OR a.contrato_fim > e.contrato_fim THEN 'Renovou antes do envio'
                       WHEN a.situacao <> 'Ativo' THEN 'Pediu para sair antes do envio'
                       ELSE 'Contrato venceu antes do envio' END
  FROM interno.renovacao_envios e2
  LEFT JOIN public.agenciados_ficha a ON a.relation_id = e2.relation_id
  WHERE e2.id = e.id AND e.situacao = 'previsto'
    AND (a.relation_id IS NULL OR a.renovacao = 'Aceita' OR a.contrato_fim > e.contrato_fim OR a.situacao <> 'Ativo'
         OR e.contrato_fim <= hoje);
  GET DIAGNOSTICS n_cancelados = ROW_COUNT;
  RETURN jsonb_build_object('novos', n_novos, 'cancelados', n_cancelados,
    'previstos', (SELECT count(*) FROM interno.renovacao_envios WHERE situacao = 'previsto'));
END
$fn$;
REVOKE ALL ON FUNCTION public.preparar_fila_renovacao_v5() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.preparar_fila_renovacao_v5() TO service_role;

CREATE OR REPLACE FUNCTION public.registrar_resposta_renovacao_v5(p jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE e record; n integer;
BEGIN
  IF current_user NOT IN ('service_role', 'postgres') THEN
    RAISE EXCEPTION USING errcode = '42501', message = 'Só o sistema registra respostas.';
  END IF;
  IF (p ->> 'mensagem') !~ '^[0-9]{1,18}$' OR (p ->> 'conversa') !~ '^[0-9]{1,18}$'
     OR (p ->> 'resposta') NOT IN ('quero', 'nao_quero', 'duvida', 'motivo', 'outro') THEN
    RAISE EXCEPTION USING errcode = '23514', message = 'Resposta inválida.';
  END IF;
  SELECT r.id, r.relation_id, r.contrato_fim, a.renovacao, a.renovacao_expira_em, a.situacao
    INTO e
  FROM interno.renovacao_envios r
  LEFT JOIN public.agenciados_ficha a ON a.relation_id = r.relation_id
  WHERE r.chatwoot_conversa = p ->> 'conversa' AND r.situacao = 'enviado'
  ORDER BY r.enviado_em DESC NULLS LAST LIMIT 1;
  -- Conversa que o serviço não enviou (ex.: etiqueta antiga do n8n) e não é teste: não é nossa.
  IF e.id IS NULL AND coalesce((p ->> 'teste')::boolean, false) IS NOT TRUE THEN
    RETURN jsonb_build_object('status', 'fora', 'envio', NULL);
  END IF;
  INSERT INTO interno.renovacao_respostas (chatwoot_mensagem, chatwoot_conversa, envio_id, relation_id, telefone, resposta, motivo, texto)
  VALUES (p ->> 'mensagem', p ->> 'conversa', e.id, e.relation_id, left(regexp_replace(coalesce(p ->> 'telefone', ''), '\D', '', 'g'), 20),
          p ->> 'resposta', left(nullif(p ->> 'motivo', ''), 200), left(nullif(p ->> 'texto', ''), 500))
  ON CONFLICT (chatwoot_mensagem) DO NOTHING;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN jsonb_build_object('status', CASE WHEN n = 1 THEN 'registrada' ELSE 'repetida' END,
    'envio', CASE WHEN e.id IS NULL THEN NULL ELSE jsonb_build_object('id', e.id, 'relation_id', e.relation_id,
      'contrato_fim', to_char(e.contrato_fim, 'DD/MM'), 'renovacao', e.renovacao, 'situacao', e.situacao) END);
END
$fn$;
REVOKE ALL ON FUNCTION public.registrar_resposta_renovacao_v5(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.registrar_resposta_renovacao_v5(jsonb) TO service_role;
COMMIT;
