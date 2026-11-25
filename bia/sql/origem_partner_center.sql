-- Origem "Partner Center" (25/11/2026, tarefa Registrar Origem): quem chegou direto pelo Partner Center, sem passar
-- pela Bia, passa a ter origem "Partner Center" (eram 1.290 agenciados ativos sem origem). Quem passou pela Bia mantém a
-- origem da ficha (Anúncio, Indicação...). É regra das telas: vale sozinha para quem entrar depois e não cria leads falsos.
-- Telas: agenciados_ficha.origem e partner_center.origem_lead (coluna nova no fim).
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE OR REPLACE VIEW public.agenciados_ficha AS
SELECT '@' || a.arroba AS tiktok, a.nome_tiktok AS nome,
       CASE WHEN NOT a.ativo THEN 'Saiu' WHEN a.situacao_tiktok = 'desvinculando' THEN 'Saindo' ELSE 'Ativo' END
         AS situacao,
       (a.vinculado_em AT TIME ZONE 'America/Sao_Paulo') AS agenciado_em,
       (a.saiu_em AT TIME ZONE 'America/Sao_Paulo') AS saiu_em,
       (a.contrato_inicio AT TIME ZONE 'America/Sao_Paulo')::date AS contrato_inicio,
       (a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date AS contrato_fim,
       CASE WHEN a.ativo THEN (a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date
                              - (now() AT TIME ZONE 'America/Sao_Paulo')::date END AS dias_para_vencer,
       a.nivel, a.nivel_nome, a.gmv_nivel, a.gmv_meta, a.progresso_pct, a.nivel_proximo,
       a.seguidores, array_to_string(a.categorias, ', ') AS categorias, a.comissao_pct,
       t.telefone, t.fonte AS fonte_telefone,
       CASE WHEN f.id IS NOT NULL THEN 'Sim' ELSE 'Não' END AS passou_pela_bia,
       CASE WHEN f.id IS NOT NULL THEN f.origem ELSE 'Partner Center' END AS origem,
       (SELECT count(*) FROM interno.agenciados_eventos e WHERE e.relation_id = a.relation_id AND e.tipo = 'renovou')
         AS renovacoes,
       (a.ultima_coleta_em AT TIME ZONE 'America/Sao_Paulo') AS conferido_em,
       (a.detalhes_em AT TIME ZONE 'America/Sao_Paulo') AS detalhes_em,
       a.relation_id, a.creator_id,
       interno.categoria_amplify(a.gmv_nivel) AS categoria,
       interno.renovacao_rotulo(a.renovacao_status) AS renovacao,
       (a.renovacao_pedido_em AT TIME ZONE 'America/Sao_Paulo') AS renovacao_pedido_em,
       (a.renovacao_expira_em AT TIME ZONE 'America/Sao_Paulo') AS renovacao_expira_em,
       (a.renovacao_novo_fim AT TIME ZONE 'America/Sao_Paulo')::date AS renovacao_novo_fim,
       a.renovacao_pedidos_restantes,
       (a.desvinculo_pedido_em AT TIME ZONE 'America/Sao_Paulo') AS desvinculo_pedido_em,
       (a.desvinculo_conclui_em AT TIME ZONE 'America/Sao_Paulo') AS desvinculo_conclui_em
FROM interno.agenciados_tiktok a
LEFT JOIN LATERAL (
  SELECT c.telefone, c.fonte FROM interno.telefones_creators c WHERE c.arroba = a.arroba
  ORDER BY array_position(ARRAY['formulario', 'ficha_bia', 'chatwoot', 'base_amplify', 'notion'], c.fonte), c.visto_em DESC NULLS LAST
  LIMIT 1) t ON true
LEFT JOIN LATERAL (SELECT x.id, x.origem FROM public.creators x
                   WHERE lower(btrim(ltrim(x.tiktok, '@'))) = a.arroba LIMIT 1) f ON a.arroba IS NOT NULL;

CREATE OR REPLACE VIEW public.partner_center AS
-- Origem do lead: a da ficha da Bia (anúncio, indicação...) quando a pessoa passou por ela; senão "Partner Center".
WITH leads AS (SELECT DISTINCT ON (lower(btrim(ltrim(x.tiktok, '@')))) lower(btrim(ltrim(x.tiktok, '@'))) AS arroba, x.origem
               FROM public.creators x WHERE nullif(btrim(x.tiktok), '') IS NOT NULL
               ORDER BY lower(btrim(ltrim(x.tiktok, '@'))), x.criado_em)
-- 1) Agenciados (coleta de hora em hora): vinculado, saindo ou que saiu.
SELECT a.relation_id AS id_parceria, a.creator_id, '@' || a.arroba AS tiktok, a.nome_tiktok AS nome,
       CASE WHEN a.ativo AND a.situacao_tiktok = 'desvinculando' THEN 'Saindo'
            WHEN a.ativo THEN 'Vinculado'
            WHEN h.status_tiktok IN (6, 7, 9, 10) THEN interno.parceria_rotulo(h.status_tiktok)
            ELSE 'Saiu' END AS estado,
       (a.vinculado_em AT TIME ZONE 'America/Sao_Paulo') AS convidado_em,
       (a.contrato_inicio AT TIME ZONE 'America/Sao_Paulo')::date AS contrato_inicio,
       (a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date AS contrato_fim,
       CASE WHEN a.ativo THEN (a.vigencia_fim AT TIME ZONE 'America/Sao_Paulo')::date
                              - (now() AT TIME ZONE 'America/Sao_Paulo')::date END AS dias_para_vencer,
       CASE WHEN a.ativo THEN coalesce(interno.renovacao_rotulo(a.renovacao_status), 'Sem pedido') END AS renovacao,
       (a.renovacao_pedido_em AT TIME ZONE 'America/Sao_Paulo') AS renovacao_pedido_em,
       (a.renovacao_expira_em AT TIME ZONE 'America/Sao_Paulo') AS renovacao_expira_em,
       (a.renovacao_novo_fim AT TIME ZONE 'America/Sao_Paulo')::date AS renovacao_novo_fim,
       (a.desvinculo_pedido_em AT TIME ZONE 'America/Sao_Paulo') AS desvinculo_pedido_em,
       (a.desvinculo_conclui_em AT TIME ZONE 'America/Sao_Paulo') AS desvinculo_conclui_em,
       (a.saiu_em AT TIME ZONE 'America/Sao_Paulo') AS saiu_em,
       interno.categoria_amplify(a.gmv_nivel) AS categoria, a.gmv_nivel,
       'agenciados'::text AS origem,
       (a.ultima_coleta_em AT TIME ZONE 'America/Sao_Paulo') AS atualizado_em,
       coalesce(o.origem, 'Partner Center') AS origem_lead
FROM interno.agenciados_tiktok a
LEFT JOIN interno.parcerias_partner_center h ON h.relation_id = a.relation_id AND NOT a.ativo
LEFT JOIN leads o ON o.arroba = a.arroba
UNION ALL
-- 2) Convites (leads) que ainda não viraram agenciados.
SELECT v.relation_id, NULL, '@' || v.arroba, v.nome,
       CASE WHEN v.pendente THEN 'Convite pendente'
            WHEN h.status_tiktok IN (6, 7) THEN interno.parceria_rotulo(h.status_tiktok)
            ELSE 'Convite não aceito' END,
       (v.convidado_em AT TIME ZONE 'America/Sao_Paulo'), NULL, (v.contrato_fim_proposto AT TIME ZONE 'America/Sao_Paulo')::date,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       (v.resolvido_em AT TIME ZONE 'America/Sao_Paulo'), NULL, NULL,
       'convites', (v.ultima_vista_em AT TIME ZONE 'America/Sao_Paulo'), coalesce(o.origem, 'Partner Center')
FROM interno.agenciados_convites v
LEFT JOIN interno.parcerias_partner_center h ON h.relation_id = v.relation_id
LEFT JOIN leads o ON o.arroba = v.arroba
WHERE NOT EXISTS (SELECT 1 FROM interno.agenciados_tiktok a WHERE a.relation_id = v.relation_id)
UNION ALL
-- 3) O resto do histórico (recusas, convites expirados, saídas e contratos vencidos de antes).
SELECT r.relation_id, r.creator_id, '@' || r.arroba, r.nome,
       CASE WHEN r.status_tiktok IN (1, 2, 4) THEN 'Sem coleta recente' ELSE interno.parceria_rotulo(r.status_tiktok) END,
       (coalesce(r.vinculo_criado_em, r.criado_em) AT TIME ZONE 'America/Sao_Paulo'),
       (r.inicio_em AT TIME ZONE 'America/Sao_Paulo')::date, (r.fim_em AT TIME ZONE 'America/Sao_Paulo')::date,
       NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       CASE WHEN r.status_tiktok IN (9, 10) THEN (r.criado_em AT TIME ZONE 'America/Sao_Paulo') END, NULL, NULL,
       'historico', (r.ultima_vista_em AT TIME ZONE 'America/Sao_Paulo'), coalesce(o.origem, 'Partner Center')
FROM interno.parcerias_partner_center r
LEFT JOIN leads o ON o.arroba = r.arroba
WHERE NOT EXISTS (SELECT 1 FROM interno.agenciados_tiktok a WHERE a.relation_id = r.relation_id)
  AND NOT EXISTS (SELECT 1 FROM interno.agenciados_convites v WHERE v.relation_id = r.relation_id);

REVOKE ALL ON public.agenciados_ficha, public.partner_center FROM anon, authenticated;
GRANT SELECT ON public.agenciados_ficha, public.partner_center TO service_role;
COMMIT;
