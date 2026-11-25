-- Renovação · template único (25/11/2026, decisão do Vitor): renovacao_contrato para os dois tipos de contrato,
-- sem nome; {{1}} = data do fim (dd/mm). O resto da conversa sai dentro das 24 h depois que a pessoa responde.
-- O tipo de contrato continua na régua (coluna tipo_contrato), só para informação.
BEGIN;
SET LOCAL lock_timeout = '5s';

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
       'renovacao_contrato'::text AS template,
       jsonb_build_array(to_char(b.contrato_fim, 'DD/MM')) AS parametros,
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

REVOKE ALL ON public.renovacao_regua FROM anon, authenticated;
GRANT SELECT ON public.renovacao_regua TO service_role;
COMMIT;
