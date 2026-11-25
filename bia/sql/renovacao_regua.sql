-- Renovação de contrato · Fase B (25/11/2026): a régua no banco, SEM ENVIAR NADA.
-- public.renovacao_regua: quem deve receber qual mensagem HOJE, com o motivo quando não pode.
-- interno.renovacao_envios: a fila; uma linha por contrato e etapa (nunca repete). Fica "previsto" até o envio ser ligado.
-- public.preparar_fila_renovacao_v5(): copia a régua de hoje para a fila. Não manda mensagem.
-- Depende de agenciados_partner_completo.sql (renovação do TikTok) e telefones (agenciados_ficha.telefone).
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS interno.renovacao_envios (
  id bigserial PRIMARY KEY,
  relation_id text NOT NULL,
  contrato_fim date NOT NULL,                -- o contrato a que a mensagem se refere
  etapa text NOT NULL CHECK (etapa IN ('semana', 'lembrete', 'hoje', 'confirmada')),
  template text,                             -- template aprovado da caixa 1 (null = falta template)
  parametros jsonb NOT NULL DEFAULT '[]',    -- valores do corpo ({{1}}...)
  telefone text,
  arroba text,
  nome text,
  situacao text NOT NULL DEFAULT 'previsto' CHECK (situacao IN ('previsto', 'enviado', 'falhou', 'cancelado')),
  motivo text,                               -- por que foi cancelado ou falhou
  previsto_em timestamptz NOT NULL DEFAULT now(),
  enviado_em timestamptz,
  chatwoot_conversa text,
  UNIQUE (relation_id, contrato_fim, etapa)  -- trava: a mesma etapa do mesmo contrato só uma vez
);
CREATE INDEX IF NOT EXISTS renovacao_envios_situacao ON interno.renovacao_envios (situacao, previsto_em);
ALTER TABLE interno.renovacao_envios ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON interno.renovacao_envios FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON interno.renovacao_envios TO service_role;
GRANT USAGE ON SEQUENCE interno.renovacao_envios_id_seq TO service_role;

-- A régua de hoje (horário de Brasília):
--   semana   : faltam 5 a 7 dias  -> primeiro_contato_contrato (UTILITY)
--   lembrete : faltam 1 a 3 dias  -> contrato_acompanhamento ({{1}} = dias; MARKETING, o único aprovado com dias)
--   hoje     : vence hoje         -> hoje_acompanhamento (UTILITY)
-- Só manda "já enviamos a solicitação, é só aceitar" quando o TikTok tem o pedido aguardando aceite.
CREATE OR REPLACE VIEW public.renovacao_regua AS
WITH base AS (
  SELECT f.relation_id, f.tiktok, f.nome, f.telefone, f.categoria, f.gmv_nivel, f.situacao, f.contrato_fim,
         f.dias_para_vencer AS dias, f.renovacao,
         CASE WHEN f.dias_para_vencer BETWEEN 5 AND 7 THEN 'semana'
              WHEN f.dias_para_vencer BETWEEN 1 AND 3 THEN 'lembrete'
              WHEN f.dias_para_vencer = 0 THEN 'hoje' END AS etapa
  FROM public.agenciados_ficha f
  WHERE f.situacao IN ('Ativo', 'Saindo') AND f.dias_para_vencer BETWEEN 0 AND 7
)
SELECT b.relation_id, b.tiktok, b.nome, b.telefone, b.categoria, b.gmv_nivel, b.contrato_fim, b.dias, b.renovacao, b.etapa,
       CASE b.etapa WHEN 'semana' THEN 'primeiro_contato_contrato' WHEN 'lembrete' THEN 'contrato_acompanhamento'
                    WHEN 'hoje' THEN 'hoje_acompanhamento' END AS template,
       CASE WHEN b.etapa = 'lembrete' THEN jsonb_build_array(b.dias::text) ELSE '[]'::jsonb END AS parametros,
       CASE
         WHEN b.etapa IS NULL THEN 'Fora da régua hoje (faltam 4 dias)'
         WHEN b.situacao = 'Saindo' THEN 'Pediu para sair'
         WHEN b.renovacao = 'Aceita' THEN 'Já renovou'
         WHEN b.renovacao = 'Não aceita' THEN 'TikTok: pedido não aceito (time decide)'
         WHEN b.renovacao = 'Sem pedido' OR b.renovacao IS NULL THEN 'TikTok ainda não enviou o pedido'
         WHEN b.telefone IS NULL THEN 'Sem telefone'
         WHEN EXISTS (SELECT 1 FROM interno.renovacao_envios e WHERE e.relation_id = b.relation_id
                        AND e.contrato_fim = b.contrato_fim AND e.etapa = b.etapa) THEN 'Já está na fila'
       END AS motivo
FROM base b;

-- Fila: o que já foi preparado (e, depois, enviado), com o estado de renovação de hoje.
CREATE OR REPLACE VIEW public.renovacao_fila AS
SELECT e.id, e.etapa, e.template, e.parametros, e.situacao, e.motivo, e.nome, '@' || e.arroba AS tiktok, e.telefone,
       e.contrato_fim, (e.previsto_em AT TIME ZONE 'America/Sao_Paulo') AS previsto_em,
       (e.enviado_em AT TIME ZONE 'America/Sao_Paulo') AS enviado_em, e.relation_id,
       a.renovacao AS renovacao_agora
FROM interno.renovacao_envios e
LEFT JOIN public.agenciados_ficha a ON a.relation_id = e.relation_id;

-- Prepara a fila de hoje (só grava "previsto"; não envia). Também cancela o que ficou sem sentido:
-- quem renovou ou pediu para sair antes do envio.
CREATE OR REPLACE FUNCTION public.preparar_fila_renovacao_v5()
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE n_novos integer; n_cancelados integer;
BEGIN
  IF current_user NOT IN ('service_role', 'postgres') THEN
    RAISE EXCEPTION USING errcode = '42501', message = 'Só o sistema prepara a fila de renovação.';
  END IF;
  INSERT INTO interno.renovacao_envios (relation_id, contrato_fim, etapa, template, parametros, telefone, arroba, nome)
  SELECT r.relation_id, r.contrato_fim, r.etapa, r.template, r.parametros, r.telefone, ltrim(r.tiktok, '@'), r.nome
  FROM public.renovacao_regua r
  WHERE r.motivo IS NULL
  ON CONFLICT (relation_id, contrato_fim, etapa) DO NOTHING;
  GET DIAGNOSTICS n_novos = ROW_COUNT;
  UPDATE interno.renovacao_envios e SET situacao = 'cancelado',
         motivo = CASE WHEN a.renovacao = 'Aceita' OR a.contrato_fim > e.contrato_fim THEN 'Renovou antes do envio'
                       ELSE 'Pediu para sair antes do envio' END
  FROM public.agenciados_ficha a
  WHERE a.relation_id = e.relation_id AND e.situacao = 'previsto'
    AND (a.renovacao = 'Aceita' OR a.contrato_fim > e.contrato_fim OR a.situacao <> 'Ativo');
  GET DIAGNOSTICS n_cancelados = ROW_COUNT;
  RETURN jsonb_build_object('novos', n_novos, 'cancelados', n_cancelados,
    'previstos', (SELECT count(*) FROM interno.renovacao_envios WHERE situacao = 'previsto'));
END
$fn$;
REVOKE ALL ON FUNCTION public.preparar_fila_renovacao_v5() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.preparar_fila_renovacao_v5() TO service_role;

REVOKE ALL ON public.renovacao_regua, public.renovacao_fila FROM anon, authenticated;
GRANT SELECT ON public.renovacao_regua, public.renovacao_fila TO service_role;
COMMIT;
