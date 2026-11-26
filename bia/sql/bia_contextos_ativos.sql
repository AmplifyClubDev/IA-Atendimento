-- Cartões de contexto ativos da Bia (26/11/2026), para a "Bia dos agenciados" do serviço de renovação usar a mesma
-- personalidade, conhecimento e limites. Só leitura; só o sistema (service_role) lê.
BEGIN;
SET LOCAL lock_timeout = '5s';
CREATE OR REPLACE VIEW public.bia_contextos_ativos AS
SELECT tipo, titulo, conteudo, atualizado_em FROM interno.contextos_ia WHERE ativo;
REVOKE ALL ON public.bia_contextos_ativos FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.bia_contextos_ativos TO service_role;
COMMIT;
