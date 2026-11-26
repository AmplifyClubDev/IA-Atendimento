-- Renovação · respostas aos botões (26/11/2026). Usado pelo serviço de renovação (renovacao/servico.mjs).
-- Cada mensagem recebida na conversa de renovação vira uma linha (uma vez por mensagem do Chatwoot).
-- resposta: quero | nao_quero | duvida | motivo | outro
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS interno.renovacao_respostas (
  id bigserial PRIMARY KEY,
  chatwoot_mensagem text NOT NULL UNIQUE,     -- trava: a mesma mensagem nunca é tratada 2 vezes
  chatwoot_conversa text NOT NULL,
  envio_id bigint REFERENCES interno.renovacao_envios(id),
  relation_id text,
  telefone text,
  resposta text NOT NULL CHECK (resposta IN ('quero', 'nao_quero', 'duvida', 'motivo', 'outro')),
  motivo text,
  texto text,                                 -- o que a pessoa escreveu/tocou (até 500 caracteres)
  recebido_em timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS renovacao_respostas_conversa ON interno.renovacao_respostas (chatwoot_conversa, recebido_em);
ALTER TABLE interno.renovacao_respostas ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON interno.renovacao_respostas FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON interno.renovacao_respostas TO service_role;
GRANT USAGE ON SEQUENCE interno.renovacao_respostas_id_seq TO service_role;

-- p = {"mensagem", "conversa", "telefone", "resposta", "motivo"?, "texto"?}. Liga ao envio pela conversa.
-- Devolve {"status": "registrada"|"repetida", "envio": {...} | null} com o contrato de quem respondeu.
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
  WHERE r.chatwoot_conversa = p ->> 'conversa'
  ORDER BY r.enviado_em DESC NULLS LAST LIMIT 1;
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

-- Para o Amplify OS e a retenção: quem respondeu o quê, com o contrato.
CREATE OR REPLACE VIEW public.renovacao_respostas AS
SELECT (r.recebido_em AT TIME ZONE 'America/Sao_Paulo') AS recebido_em, r.resposta, r.motivo, r.texto,
       a.tiktok, a.nome, a.categoria, a.gmv_nivel, a.contrato_fim, a.renovacao, r.telefone, r.chatwoot_conversa, r.relation_id
FROM interno.renovacao_respostas r
LEFT JOIN public.agenciados_ficha a ON a.relation_id = r.relation_id;
REVOKE ALL ON public.renovacao_respostas FROM anon, authenticated;
GRANT SELECT ON public.renovacao_respostas TO service_role;
COMMIT;
