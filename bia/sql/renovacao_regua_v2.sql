-- Renovação · régua nova (25/11/2026, decisão do Vitor): sem n8n e sem os templates antigos.
-- Uma mensagem só por contrato, quando faltam de 7 a 1 dias, perguntando se a pessoa quer renovar
-- (botão "Quero renovar" -> a ponte envia o pedido de renovação no Partner Center).
-- Template pelo tipo de contrato (medido em 25/11: todo convite é de 61 dias; renovação estende 1 ano):
--   contrato atual de até 90 dias -> renovacao_primeiro_contrato (fim dos 2 meses iniciais)
--   acima de 90 dias              -> renovacao_contrato_anual
-- Parâmetros: {{1}} primeiro nome, {{2}} data do fim (dd/mm). A fila antiga (templates do n8n) é cancelada.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE interno.renovacao_envios DROP CONSTRAINT IF EXISTS renovacao_envios_etapa_check;
ALTER TABLE interno.renovacao_envios ADD CONSTRAINT renovacao_envios_etapa_check
  CHECK (etapa IN ('semana', 'lembrete', 'hoje', 'confirmada', 'convite'));
ALTER TABLE interno.renovacao_envios ADD COLUMN IF NOT EXISTS tipo_contrato text;

-- Primeiro nome para a mensagem: o nome do formulário (quem passou pela Bia); senão o nome do TikTok; só letras.
CREATE OR REPLACE FUNCTION interno.primeiro_nome(nome text)
RETURNS text LANGUAGE sql IMMUTABLE SET search_path = '' AS $fn$
  -- Primeira palavra com 3+ letras que não seja título ou palavra de loja (Prof, Dra, Loja, Shop...).
  SELECT initcap(p) FROM unnest(string_to_array(btrim(regexp_replace(lower(coalesce(nome, '')), '[^[:alpha:] ]', ' ', 'g')), ' ')) WITH ORDINALITY AS w(p, i)
  WHERE length(p) >= 3 AND p NOT IN ('prof', 'profa', 'dra', 'sra', 'srta', 'tia', 'tio', 'loja', 'shop', 'store', 'oficial', 'the', 'canal',
    'sou', 'mae', 'mãe', 'dicas', 'achadinhos', 'achados', 'tiktok', 'creator', 'ugc', 'mundo', 'casa', 'blog', 'perfil')
  ORDER BY i LIMIT 1
$fn$;
GRANT EXECUTE ON FUNCTION interno.primeiro_nome(text) TO PUBLIC;

CREATE OR REPLACE VIEW public.renovacao_regua AS
WITH base AS (
  SELECT f.relation_id, f.tiktok, f.nome, f.telefone, f.categoria, f.gmv_nivel, f.situacao, f.contrato_fim,
         f.dias_para_vencer AS dias, f.renovacao, a.renovacao_pedidos_restantes AS pedidos_restantes,
         CASE WHEN (a.vigencia_fim::date - a.contrato_inicio::date) <= 90 THEN 'primeiro' ELSE 'anual' END AS tipo_contrato,
         CASE WHEN f.dias_para_vencer BETWEEN 1 AND 7 THEN 'convite' END AS etapa,
         coalesce(interno.primeiro_nome(c.nome), interno.primeiro_nome(f.nome), 'creator') AS primeiro_nome
  FROM public.agenciados_ficha f
  JOIN interno.agenciados_tiktok a ON a.relation_id = f.relation_id
  LEFT JOIN LATERAL (SELECT x.nome FROM public.creators x WHERE lower(btrim(ltrim(x.tiktok, '@'))) = ltrim(f.tiktok, '@') LIMIT 1) c ON true
  WHERE f.situacao IN ('Ativo', 'Saindo') AND f.dias_para_vencer BETWEEN 0 AND 7
)
SELECT b.relation_id, b.tiktok, b.nome, b.telefone, b.categoria, b.gmv_nivel, b.contrato_fim, b.dias, b.renovacao, b.etapa,
       CASE b.tipo_contrato WHEN 'primeiro' THEN 'renovacao_primeiro_contrato' ELSE 'renovacao_contrato_anual' END AS template,
       jsonb_build_array(b.primeiro_nome, to_char(b.contrato_fim, 'DD/MM')) AS parametros,
       CASE
         WHEN b.etapa IS NULL THEN 'Vence hoje (fora da régua de 7 a 1 dias)'
         WHEN b.situacao = 'Saindo' THEN 'Pediu para sair'
         WHEN b.renovacao = 'Aceita' THEN 'Já renovou'
         WHEN b.renovacao = 'Não aceita' AND coalesce(b.pedidos_restantes, 0) = 0 THEN 'TikTok: sem pedidos de renovação restantes (time decide)'
         WHEN b.telefone IS NULL THEN 'Sem telefone'
         WHEN EXISTS (SELECT 1 FROM interno.renovacao_envios e WHERE e.relation_id = b.relation_id
                        AND e.contrato_fim = b.contrato_fim AND e.etapa = b.etapa) THEN 'Já está na fila'
       END AS motivo,
       b.tipo_contrato, b.primeiro_nome
FROM base b;

-- A fila de antes usava os templates do n8n: cancelada (nada tinha sido enviado).
UPDATE interno.renovacao_envios SET situacao = 'cancelado', motivo = 'Régua trocada em 25/11 (templates novos)'
WHERE situacao = 'previsto' AND etapa IN ('semana', 'lembrete', 'hoje');

CREATE OR REPLACE FUNCTION public.preparar_fila_renovacao_v5()
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $fn$
DECLARE n_novos integer; n_cancelados integer;
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

REVOKE ALL ON public.renovacao_regua FROM anon, authenticated;
GRANT SELECT ON public.renovacao_regua TO service_role;
COMMIT;
